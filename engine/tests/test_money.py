"""Money arithmetic tests.

ADR-003. These exist because the engine has a ROUNDING classification: if float drift
can manufacture a rounding "defect", the engine cannot tell its own numerical noise
from a real merchant discrepancy.
"""

from __future__ import annotations

import pytest

from finctl.money import MoneyError, apply_bps, format_rupees, parse_money


class TestApplyBps:
    def test_canonical_card_case(self) -> None:
        """The example from the brief: ₹10,000 card txn, 2% MDR = ₹200."""
        assert apply_bps(1_000_000, 200) == 20_000

    def test_a_zero_rate_is_genuinely_zero(self) -> None:
        """A zero rate yields zero at any magnitude — no float drift, no rounding up.

        This is arithmetic about bps, not a claim about UPI: UPI's *MDR* is zero
        but its platform fee is not, so UPI does not use a zero rate. See ADR-030.
        """
        assert apply_bps(1_000_000, 0) == 0
        assert apply_bps(999_999_999, 0) == 0

    def test_gst_on_mdr_not_on_amount(self) -> None:
        """₹10,000 → MDR ₹200 → GST ₹36. NOT 18% of ₹10,000 (₹1,800)."""
        mdr = apply_bps(1_000_000, 200)
        gst = apply_bps(mdr, 1800)
        assert gst == 3_600
        assert gst != apply_bps(1_000_000, 1800)

    @pytest.mark.parametrize(
        ("amount", "bps", "mode", "expected"),
        [
            (33_300, 200, "half_up", 666),      # 6.66 exactly
            (33_350, 200, "half_up", 667),      # 6.67 exactly
            (100, 250, "half_up", 3),           # 2.5 -> 3 (half up)
            (100, 250, "half_even", 2),         # 2.5 -> 2 (banker's, ties to even)
            (100, 250, "floor", 2),
            (100, 250, "ceil", 3),
        ],
    )
    def test_rounding_modes_differ_where_it_matters(
        self, amount: int, bps: int, mode: str, expected: int
    ) -> None:
        """A tie must resolve per the configured policy, not per float luck."""
        assert apply_bps(amount, bps, mode) == expected

    def test_no_float_drift_on_repeated_application(self) -> None:
        """The failure this module exists to prevent.

        Naive float arithmetic accumulates error over many transactions. Integer paise
        cannot: the sum of exact integers is exact.
        """
        total = sum(apply_bps(10_007, 200) for _ in range(10_000))
        assert total == 200 * 10_000
        assert isinstance(total, int)

    def test_rejects_float_amount(self) -> None:
        with pytest.raises(MoneyError, match="int paise"):
            apply_bps(100.5, 200)  # type: ignore[arg-type]

    def test_rejects_bool(self) -> None:
        """bool is an int subclass in Python. Guarded explicitly."""
        with pytest.raises(MoneyError):
            apply_bps(True, 200)  # type: ignore[arg-type]

    def test_rejects_negative_rate(self) -> None:
        with pytest.raises(MoneyError, match="non-negative"):
            apply_bps(1000, -200)

    def test_rejects_unknown_rounding_mode(self) -> None:
        with pytest.raises(MoneyError, match="unknown rounding mode"):
            apply_bps(1000, 200, "nearest_vibe")


class TestParseMoney:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1,234.50", 123_450),
            ("₹1234.50", 123_450),
            ("₹1,234.50", 123_450),
            ("1234.5", 123_450),
            ("1234", 123_400),
            (" 1,234.50 ", 123_450),
            ("0", 0),
            ("0.01", 1),
            (1234, 123_400),
            (1234.5, 123_450),
        ],
    )
    def test_parses_the_messy_forms_a_csv_actually_contains(self, raw, expected: int) -> None:
        """Adversarial case from build-spec 6e: amounts as "1,234.50" strings."""
        assert parse_money(raw) == expected

    def test_float_does_not_inherit_binary_representation_error(self) -> None:
        """Decimal(0.1) is 0.1000000000000000055...; Decimal(str(0.1)) is 0.1."""
        assert parse_money(0.1) == 10
        assert parse_money(1234.56) == 123_456

    def test_refuses_sub_paise_precision_rather_than_rounding_silently(self) -> None:
        """BEHAVIOR.md: fail loudly, never guess.

        Silently rounding ₹0.005 away would be a tiny error that compounds invisibly.
        """
        with pytest.raises(MoneyError, match="sub-paise"):
            parse_money("1234.567")

    def test_negative_requires_opt_in(self) -> None:
        with pytest.raises(MoneyError, match="negative"):
            parse_money("-100")
        assert parse_money("-100", allow_negative=True) == -10_000

    @pytest.mark.parametrize("bad", ["", "   ", "abc", "₹", "1,2,3.4.5", None, []])
    def test_rejects_garbage(self, bad) -> None:
        with pytest.raises(MoneyError):
            parse_money(bad)

    def test_rejects_bool(self) -> None:
        with pytest.raises(MoneyError, match="bool"):
            parse_money(True)


class TestFormatRupees:
    @pytest.mark.parametrize(
        ("paise", "expected"),
        [
            (84_000_000, "₹8,40,000.00"),    # Indian grouping: lakhs, from the brief
            (78_800_000, "₹7,88,000.00"),
            (5_200_000, "₹52,000.00"),
            (123_450, "₹1,234.50"),
            (100, "₹1.00"),
            (1, "₹0.01"),
            (0, "₹0.00"),
            (-123_450, "-₹1,234.50"),
            (1_000_000_000, "₹1,00,00,000.00"),  # one crore
        ],
    )
    def test_indian_digit_grouping(self, paise: int, expected: str) -> None:
        assert format_rupees(paise) == expected

    def test_symbol_optional(self) -> None:
        assert format_rupees(123_450, symbol=False) == "1,234.50"

    def test_rejects_non_int(self) -> None:
        with pytest.raises(MoneyError):
            format_rupees(1234.5)  # type: ignore[arg-type]
