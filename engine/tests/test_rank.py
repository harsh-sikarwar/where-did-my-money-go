"""Materiality ranking tests.

'Success is a SHORT list, not a long one.' Getting this wrong in the permissive
direction produces a list nobody reads, which is indistinguishable from having no tool.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finctl.classify.classifier import Classification, Finding
from finctl.config.loader import load_config
from finctl.rank.ranker import LINE_COPY, Ranker, Verdict


@pytest.fixture
def ranker() -> Ranker:
    return Ranker(load_config().tolerances)


def finding(classification: Classification, paise: int, order_id: str = "O1") -> Finding:
    return Finding(order_id=order_id, classification=classification, amount_paise=paise)


class TestRecoverabilityBeatsSize:
    """The central ranking claim, asserted directly."""

    def test_a_huge_timing_lag_is_benign(self, ranker: Ranker) -> None:
        """₹31,000 that resolves itself on Tuesday needs nobody."""
        assert not ranker.is_actionable(Classification.TIMING, 3_100_000)

    def test_a_tiny_halted_subscription_is_actionable(self, ranker: Ranker) -> None:
        """₹1 of silently dying revenue still needs a human."""
        assert ranker.is_actionable(Classification.HALTED_SUBSCRIPTION, 100)

    def test_size_does_not_override_policy_in_either_direction(self, ranker: Ranker) -> None:
        big_benign = ranker.is_actionable(Classification.TIMING, 100_000_000)
        small_actionable = ranker.is_actionable(Classification.HALTED_SUBSCRIPTION, 1)
        assert not big_benign
        assert small_actionable

    def test_correct_fees_are_never_actionable(self, ranker: Ranker) -> None:
        """A fee matching the contract is correct, not a problem."""
        assert not ranker.is_actionable(Classification.FEE, 10_000_000)


class TestPolicyIsConfigNotCode:
    def test_benign_and_actionable_come_from_config(self) -> None:
        tol = load_config().tolerances
        assert "TIMING" in tol.always_benign
        assert "HALTED_SUBSCRIPTION" in tol.always_actionable

    def test_unlisted_classifications_fall_through_to_the_threshold(
        self, ranker: Ranker
    ) -> None:
        tol = load_config().tolerances
        unlisted = Classification.TAX_ON_FEE
        if str(unlisted) in tol.always_benign or str(unlisted) in tol.always_actionable:
            pytest.skip("this classification is explicitly listed")
        assert ranker.is_actionable(unlisted, tol.actionable_above_paise + 1)

    def test_a_typo_in_the_config_is_rejected_at_load(self) -> None:
        """Otherwise the name silently fails to match and the class falls through."""
        from finctl.config.loader import ConfigError, Tolerances
        bad = {
            "settlement": {"cycle_days": 2, "grace_days": 1}, "calendar": {},
            "amount": {"rounding_paise": 1, "material_paise": 10000},
            "materiality": {"always_benign": ["TIMNIG"], "always_actionable": [],
                            "actionable_above_paise": 1},
        }
        with pytest.raises(ConfigError, match="unknown classification"):
            Tolerances.from_dict(bad, "t")


class TestVerdict:
    def test_reconciled_rows_do_not_appear(self, ranker: Ranker) -> None:
        """Money that arrived correctly is not news."""
        v = ranker.rank(
            [finding(Classification.RECONCILED, 0), finding(Classification.TIMING, 5000)],
            expected_paise=100000, received_paise=95000,
        )
        assert [line.classification for line in v.lines] == [Classification.TIMING]

    def test_benign_lines_come_before_actionable_ones(self, ranker: Ranker) -> None:
        """The eye should land on 'mostly fine' before 'this needs you'."""
        v = ranker.rank(
            [finding(Classification.HALTED_SUBSCRIPTION, 5000),
             finding(Classification.TIMING, 90000)],
            expected_paise=100000, received_paise=5000,
        )
        assert v.lines[0].classification is Classification.TIMING
        assert v.lines[-1].classification is Classification.HALTED_SUBSCRIPTION

    def test_gap_is_expected_minus_received(self, ranker: Ranker) -> None:
        v = ranker.rank([], expected_paise=100000, received_paise=70000)
        assert v.gap_paise == 30000

    def test_unknown_classifications_are_still_reported(self, ranker: Ranker) -> None:
        """Silently dropping an unrecognised label would hide the thing worth seeing."""
        v = ranker.rank(
            [finding(Classification.UNEXPECTED_SETTLEMENT, 5000)],
            expected_paise=0, received_paise=5000,
        )
        assert len(v.lines) == 1


class TestHeadline:
    def test_it_names_one_thing_not_a_list(self, ranker: Ranker) -> None:
        """If everything is urgent, nothing is."""
        v = ranker.rank(
            [finding(Classification.HALTED_SUBSCRIPTION, 380000),
             finding(Classification.MISSING, 100000)],
            expected_paise=1000000, received_paise=520000,
        )
        assert v.headline().startswith("One thing needs you this week")

    def test_halted_subscriptions_are_described_as_customers(self, ranker: Ranker) -> None:
        """'Six customers' is a human fact; 'six halted subscriptions' is jargon."""
        v = ranker.rank(
            [finding(Classification.HALTED_SUBSCRIPTION, 380000, f"O{i}") for i in range(6)],
            expected_paise=1000000, received_paise=620000,
        )
        assert "6 customers" in v.headline()

    def test_a_clean_batch_says_nothing_needs_you(self, ranker: Ranker) -> None:
        v = ranker.rank(
            [finding(Classification.TIMING, 5000)], expected_paise=100000,
            received_paise=95000,
        )
        assert v.headline() == "Nothing needs you this week."

    def test_the_headline_picks_the_largest_actionable_line(self, ranker: Ranker) -> None:
        v = ranker.rank(
            [finding(Classification.MISSING, 900000),
             finding(Classification.HALTED_SUBSCRIPTION, 100)],
            expected_paise=1000000, received_paise=0,
        )
        assert "customers" not in v.headline()   # MISSING is bigger, so it wins


class TestCopy:
    def test_every_classification_has_human_copy(self) -> None:
        """Every finance term explained inline or absent — no exceptions."""
        engine_assigned = set(Classification) - {Classification.RECONCILED}
        assert engine_assigned <= set(LINE_COPY)

    def test_copy_avoids_unexplained_jargon(self) -> None:
        """'MDR' must never reach the merchant without explanation."""
        for label, explanation in LINE_COPY.values():
            assert "MDR" not in label
            if "GST" in explanation:
                assert "fee" in explanation.lower()

    def test_the_halted_copy_says_it_is_recoverable(self) -> None:
        label, explanation = LINE_COPY[Classification.HALTED_SUBSCRIPTION]
        assert "recoverable" in (label + explanation).lower()


class TestAgainstRealBatch:
    def test_demo_batch_produces_a_short_actionable_list(self, tmp_path: Path) -> None:
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run

        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        v: Verdict = run(tmp_path).verdict

        assert len(v.actionable_lines) <= 3, "the actionable list must stay short"
        assert v.benign_paise > 0
        assert "customers" in v.headline()
