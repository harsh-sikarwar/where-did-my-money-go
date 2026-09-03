"""The merchant's own contracted rates. ADR-046.

The shipped card answers "was this the standard rate?". Merchants negotiate away from
standard pricing and enterprise rates are common, so for a real merchant that is a
different — and much less useful — question than "was this MY contracted rate?".
"""

from __future__ import annotations

import pytest

from finctl.config.loader import ConfigError, load_config


@pytest.fixture
def base():
    return load_config().rate_card


class TestLayering:
    def test_a_merchant_rate_replaces_the_standard_one(self, base) -> None:
        card = base.with_merchant_rates({"methods": {"upi": 175}}, "acme.yaml")
        assert card.rate_for("upi").mdr_bps == 175

    def test_methods_not_mentioned_keep_the_standard_rate(self, base) -> None:
        """A contract renegotiating UPI alone must not require restating everything.

        Every restatement is a chance to get one wrong, and no merchant would notice.
        """
        card = base.with_merchant_rates({"methods": {"upi": 175}}, "acme.yaml")
        assert card.rate_for("netbanking").mdr_bps == base.rate_for("netbanking").mdr_bps

    def test_a_method_the_standard_card_lacks_can_be_added(self, base) -> None:
        """A merchant may genuinely be billed for a rail we did not ship."""
        card = base.with_merchant_rates({"methods": {"bank_transfer": 90}}, "acme.yaml")
        assert card.rate_for("bank_transfer").mdr_bps == 90

    def test_an_unpriced_method_still_raises(self, base) -> None:
        """The refusal to invent a rate survives. That is the point of the config layer."""
        card = base.with_merchant_rates({"methods": {"upi": 175}}, "acme.yaml")
        with pytest.raises(ConfigError, match="no rate card entry"):
            card.rate_for("crypto")

    def test_the_long_form_carries_a_note(self, base) -> None:
        card = base.with_merchant_rates(
            {"methods": {"upi": {"mdr_bps": 175, "note": "volume tier 3"}}}, "acme.yaml"
        )
        assert card.rate_for("upi").note == "volume tier 3"

    def test_gst_and_fixed_fee_can_be_overridden(self, base) -> None:
        card = base.with_merchant_rates(
            {"gst_rate_bps": 500, "fixed_fee_paise": 200}, "acme.yaml"
        )
        assert card.gst_rate_bps == 500
        assert card.fixed_fee_paise == 200

    def test_the_card_says_it_is_the_merchants(self, base) -> None:
        """A merchant reading 'you were overcharged' deserves to know whose number."""
        assert "merchant" in base.with_merchant_rates({"methods": {"upi": 1}}, "x").name


class TestRefusals:
    """A bad rate card must fail at load time, not silently flag every row."""

    def test_a_percentage_where_basis_points_were_meant_is_refused(self, base) -> None:
        """The unit error that would otherwise flag every single row.

        Someone typing "2" for 2% gets 0.02%, and every transaction then looks
        overcharged. The absurd END of that mistake is refused; 2 bps itself is a legal
        (if tiny) rate and cannot be distinguished from intent.
        """
        with pytest.raises(ConfigError, match="BASIS POINTS"):
            base.with_merchant_rates({"methods": {"upi": 20_000}}, "acme.yaml")

    def test_a_negative_rate_is_refused(self, base) -> None:
        with pytest.raises(ConfigError, match="negative rate"):
            base.with_merchant_rates({"methods": {"upi": -5}}, "acme.yaml")

    def test_a_non_numeric_rate_is_refused(self, base) -> None:
        with pytest.raises(ConfigError, match="must be a number"):
            base.with_merchant_rates({"methods": {"upi": "cheap"}}, "acme.yaml")

    def test_a_mapping_without_mdr_bps_is_refused(self, base) -> None:
        with pytest.raises(ConfigError, match="mdr_bps"):
            base.with_merchant_rates({"methods": {"upi": {"note": "hi"}}}, "acme.yaml")

    def test_a_rupee_value_for_a_paise_field_is_refused(self, base) -> None:
        """2.00 meaning ₹2 is not 200 paise, and accepting it would understate fees."""
        with pytest.raises(ConfigError, match="integer number of paise"):
            base.with_merchant_rates({"fixed_fee_paise": 2.00}, "acme.yaml")

    def test_methods_must_be_a_mapping(self, base) -> None:
        with pytest.raises(ConfigError, match="must be a mapping"):
            base.with_merchant_rates({"methods": ["upi"]}, "acme.yaml")


class TestItChangesTheAnswer:
    """The whole reason this exists: it must change what the engine reports."""

    def test_a_lower_contracted_rate_finds_more_overcharge(self, tmp_path) -> None:
        from finctl.classify.classifier import Classification
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run

        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)

        standard = run(tmp_path, load_config())
        merchant = run(tmp_path, load_config(merchant_rate_card={
            "methods": {m: 175 for m in
                        ("upi", "card_credit", "card_debit", "netbanking", "wallet")}
        }))

        def overcharge(result) -> int:
            return sum(f.amount_paise
                       for f in result.classified.by_class(Classification.FEE))

        assert overcharge(merchant) > overcharge(standard)

    def test_the_proof_compares_against_the_merchants_number(self, tmp_path) -> None:
        """'You were charged this, your contract says that' — with their number."""
        from finctl.classify.classifier import Classification
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run

        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        result = run(tmp_path, load_config(
            merchant_rate_card={"methods": {"card_credit": 100}}))

        findings = [f for f in result.classified.by_class(Classification.FEE)
                    if f.proof.get("method") == "card_credit"]
        assert findings
        proof = findings[0].proof
        # 1.00% + 18% GST on it = 118 bps of the amount, well under the ~236 charged.
        assert proof["expected_fee_paise"] < proof["actual_fee_paise"]
        assert proof["delta_paise"] > 0

    def test_the_gap_still_balances_under_a_merchant_card(self, tmp_path) -> None:
        """Changing the contracted rate must not break the balance identity."""
        from finctl.gap import decompose
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run

        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        result = run(tmp_path, load_config(
            merchant_rate_card={"methods": {"upi": 175, "card_credit": 190}}))
        assert decompose(result.matches, result.correlated.findings).residual_paise == 0
