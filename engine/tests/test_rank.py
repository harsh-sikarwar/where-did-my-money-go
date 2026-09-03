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


class TestVerdictBalances:
    """THE test this file was missing, and the bug it would have caught.

    The verdict screen showed ₹99,421.65 of lines against a ₹38,372.30 gap. Every
    individual number was right; the screen was assembling them wrongly. Nothing
    asserted that the lines add up to the thing they claim to explain, so nothing
    failed.
    """

    @pytest.fixture
    def verdict(self, tmp_path: Path):
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run
        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        return run(tmp_path).verdict

    def test_the_lines_sum_to_the_gap(self, verdict: Verdict) -> None:
        total = sum(line.amount_paise for line in verdict.lines)
        assert total + verdict.unexplained_paise == verdict.gap_paise, (
            f"lines sum to {total}, gap is {verdict.gap_paise} — "
            "the verdict screen does not add up"
        )

    def test_gap_is_expected_minus_received(self, verdict: Verdict) -> None:
        assert verdict.gap_paise == verdict.expected_paise - verdict.received_paise

    def test_refunds_that_over_settled_narrow_the_gap(self, verdict: Verdict) -> None:
        """A one-sided refund means the bank got MORE than the books expected.

        It must therefore be NEGATIVE. Reporting its magnitude as a positive
        contribution was one of the three bugs.
        """
        refund = next(
            (line for line in verdict.lines if line.classification is Classification.REFUND), None
        )
        if refund is not None:
            assert refund.amount_paise < 0

    def test_fees_report_the_whole_fee_not_the_overcharge(self, tmp_path: Path) -> None:
        """The gap includes every rupee Razorpay kept, not just the excess.

        Reporting only the overcharge understated this line by ~₹17,000.
        """
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run
        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        result = run(tmp_path)
        fee_line = next(
            line for line in result.verdict.lines if line.classification is Classification.FEE
        )
        total_fees = sum(m.fee_paise for m in result.matches.order_matches)
        assert fee_line.amount_paise == total_fees

    def test_money_that_already_arrived_is_not_in_the_gap(self, tmp_path: Path) -> None:
        """The original TIMING bug: orders that settled late but HAVE arrived are
        already inside `received`, so counting them again double-counts by ₹30,501."""
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run
        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        result = run(tmp_path)
        timing = next(
            (line for line in result.verdict.lines
             if line.classification is Classification.TIMING), None
        )
        in_flight = sum(
            s.expected_credit_paise
            for s in result.matches.settlement_matches if not s.matched
        )
        assert (timing.amount_paise if timing else 0) == in_flight

    def test_reconciled_rows_do_not_appear(self, verdict: Verdict) -> None:
        """Money that arrived correctly is not news."""
        assert all(
            line.classification is not Classification.RECONCILED for line in verdict.lines
        )

    @pytest.mark.parametrize("profile", ["demo", "clean", "scale"])
    def test_it_balances_across_defect_profiles(
        self, tmp_path: Path, profile: str
    ) -> None:
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run
        write_batch(Generator(load_config(), seed=7, volume=200,
                              defect_profile=profile).generate(), tmp_path)
        v = run(tmp_path).verdict
        assert sum(line.amount_paise for line in v.lines) + v.unexplained_paise == v.gap_paise

    @pytest.mark.parametrize("archetype", ["saas_subscription", "d2c_ecommerce"])
    def test_it_balances_across_archetypes(
        self, tmp_path: Path, archetype: str
    ) -> None:
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run
        write_batch(Generator(load_config(), seed=7, volume=200, archetype=archetype,
                              defect_profile="demo").generate(), tmp_path)
        v = run(tmp_path).verdict
        assert sum(line.amount_paise for line in v.lines) + v.unexplained_paise == v.gap_paise

    @pytest.mark.parametrize("mix", ["upi_heavy", "card_heavy", "even"])
    def test_it_balances_across_payment_mixes(self, tmp_path: Path, mix: str) -> None:
        """UPI is zero-MDR, so the FEE component vanishes. It must still balance."""
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run
        write_batch(Generator(load_config(), seed=7, volume=200, payment_mix=mix,
                              defect_profile="demo").generate(), tmp_path)
        v = run(tmp_path).verdict
        assert sum(line.amount_paise for line in v.lines) + v.unexplained_paise == v.gap_paise


class TestHeadline:
    @pytest.fixture
    def verdict(self, tmp_path: Path):
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run
        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        return run(tmp_path).verdict

    def test_it_names_one_thing_not_a_list(self, verdict: Verdict) -> None:
        """If everything is urgent, nothing is."""
        assert verdict.headline().startswith("One thing needs you this week")

    def test_halted_subscriptions_are_described_as_customers(
        self, verdict: Verdict
    ) -> None:
        """'Six customers' is a human fact; 'six halted subscriptions' is jargon."""
        assert "customers" in verdict.headline()

    def test_a_clean_batch_says_nothing_needs_you(self, tmp_path: Path) -> None:
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run
        write_batch(Generator(load_config(), seed=5, volume=100,
                              defect_profile="clean").generate(), tmp_path)
        v = run(tmp_path).verdict
        assert v.headline() == "Nothing needs you this week."
        assert v.actionable_lines == []


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

    def test_the_refund_copy_explains_why_it_is_negative(self) -> None:
        """A negative line on a money screen needs saying, not just showing."""
        _, explanation = LINE_COPY[Classification.REFUND]
        assert "negative" in explanation.lower() or "more" in explanation.lower()


class TestAgainstRealBatch:
    def test_demo_batch_produces_a_short_actionable_list(self, tmp_path: Path) -> None:
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run

        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        v: Verdict = run(tmp_path).verdict

        # The cap is a product promise: a merchant reads this list on a Monday morning
        # and it must fit in one glance. It is NOT a fixed number — it grew from 3 to 5
        # as the engine learned to name causes it previously left in UNEXPLAINED
        # (ON_HOLD, ADR-036; UNRECORDED_REFUND, ADR-039). Each addition moves money OUT
        # of a silent bucket and onto a line with an owner, which is the point. What
        # must not happen is the list becoming a dashboard.
        assert len(v.actionable_lines) <= 5, "the actionable list must stay short"
        # Actionable lines must stay a MINORITY of the verdict: most of a merchant's
        # money is always fine, and a screen where everything is urgent says nothing.
        assert len(v.actionable_lines) < len(v.lines)
        assert "customers" in v.headline()
