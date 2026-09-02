"""Gap decomposition tests.

Written because the verdict screen showed ₹99,421.65 of lines against a ₹38,372.30 gap.
Every individual number was correct; the screen was assembling them wrongly, and nothing
asserted that the lines add up to the thing they claim to explain.

The identity these tests defend:

    gap = fees_kept + never_arrived + in_flight - settled_above_ledger + residual
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finctl.classify.classifier import Classification, Classifier
from finctl.config.loader import load_config
from finctl.correlate.correlator import Correlator
from finctl.gap import GapComponent, GapDecomposition, decompose
from finctl.generate.generator import Generator
from finctl.generate.writer import write_batch
from finctl.match.matcher import match
from finctl.stage.staging import stage_from_dir


def decomposition_for(path: Path) -> GapDecomposition:
    cfg = load_config()
    batch = stage_from_dir(path)
    matches = match(batch)
    correlated = Correlator(batch).correlate(Classifier(cfg).classify(matches))
    return decompose(matches, correlated.findings)


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    write_batch(Generator(load_config(), seed=20260902, volume=200,
                          defect_profile="demo").generate(), tmp_path)
    return tmp_path


class TestTheIdentity:
    def test_components_sum_to_the_gap_exactly(self, demo: Path) -> None:
        d = decomposition_for(demo)
        assert d.residual_paise == 0
        assert d.explained_paise == d.gap_paise

    def test_check_raises_when_it_does_not_balance(self) -> None:
        """A silent failure here is precisely the original bug, so it must raise."""
        d = GapDecomposition(expected_paise=100000, received_paise=50000)
        d.components.append(GapComponent(Classification.FEE, 1000, 1))
        with pytest.raises(ArithmeticError, match="does not balance"):
            d.check()

    def test_the_error_names_the_numbers(self) -> None:
        d = GapDecomposition(expected_paise=100000, received_paise=50000)
        d.components.append(GapComponent(Classification.FEE, 1000, 1))
        with pytest.raises(ArithmeticError) as exc:
            d.check()
        assert "gap=50000" in str(exc.value)
        assert "residual=49000" in str(exc.value)


class TestTheThreeOriginalBugs:
    """One test per bug, so a regression names which one came back."""

    def test_bug_1_arrived_money_is_not_counted_as_a_gap(self, demo: Path) -> None:
        """TIMING counted orders that settled late but HAD arrived.

        That money is already inside `received`, so counting it again inflated the
        screen by ₹30,501.15. Only genuinely in-flight settlements belong.
        """
        cfg = load_config()
        batch = stage_from_dir(demo)
        matches = match(batch)
        correlated = Correlator(batch).correlate(Classifier(cfg).classify(matches))
        d = decompose(matches, correlated.findings)

        timing = next(
            (c for c in d.components if c.classification is Classification.TIMING), None
        )
        in_flight = sum(
            s.expected_credit_paise for s in matches.settlement_matches if not s.matched
        )
        assert (timing.amount_paise if timing else 0) == in_flight

    def test_bug_2_over_settled_refunds_are_negative(self, demo: Path) -> None:
        """A one-sided refund means the bank received MORE than the books expected.

        It narrows the gap. Reporting its magnitude as positive added ₹23,628 that
        should have been subtracted — a ₹47,256 error in a ₹38,372 gap.
        """
        d = decomposition_for(demo)
        refund = next(
            (c for c in d.components if c.classification is Classification.REFUND), None
        )
        assert refund is not None
        assert refund.amount_paise < 0

    def test_bug_3_fees_are_the_whole_fee_not_the_overcharge(self, demo: Path) -> None:
        """The gap includes every rupee Razorpay kept.

        Reporting only the rate-card overcharge showed ₹603.50 where ₹17,311.30 of real
        money had left the merchant's pocket.
        """
        cfg = load_config()
        batch = stage_from_dir(demo)
        matches = match(batch)
        correlated = Correlator(batch).correlate(Classifier(cfg).classify(matches))
        d = decompose(matches, correlated.findings)

        fee = next(c for c in d.components if c.classification is Classification.FEE)
        assert fee.amount_paise == sum(m.fee_paise for m in matches.order_matches)
        assert fee.amount_paise > 1_000_000   # far more than the overcharge alone


class TestSigns:
    def test_money_that_never_arrived_widens_the_gap(self, demo: Path) -> None:
        d = decomposition_for(demo)
        for cls in (Classification.HALTED_SUBSCRIPTION, Classification.PAYMENT_FAILED,
                    Classification.MISSING):
            c = next((x for x in d.components if x.classification is cls), None)
            if c:
                assert c.amount_paise > 0, f"{cls} should widen the gap"

    def test_fees_widen_the_gap(self, demo: Path) -> None:
        d = decomposition_for(demo)
        fee = next(c for c in d.components if c.classification is Classification.FEE)
        assert fee.amount_paise > 0


class TestAcrossConfigurations:
    """The identity must hold everywhere, not only on the demo batch."""

    @pytest.mark.parametrize("profile", ["demo", "clean", "chaos", "scale"])
    def test_every_defect_profile_balances(self, tmp_path: Path, profile: str) -> None:
        write_batch(Generator(load_config(), seed=11, volume=200,
                              defect_profile=profile).generate(), tmp_path)
        decomposition_for(tmp_path).check()

    @pytest.mark.parametrize("archetype", ["saas_subscription", "d2c_ecommerce"])
    def test_every_archetype_balances(self, tmp_path: Path, archetype: str) -> None:
        write_batch(Generator(load_config(), seed=11, volume=200, archetype=archetype,
                              defect_profile="demo").generate(), tmp_path)
        decomposition_for(tmp_path).check()

    @pytest.mark.parametrize("mix", ["upi_heavy", "card_heavy", "even"])
    def test_every_payment_mix_balances(self, tmp_path: Path, mix: str) -> None:
        """UPI is zero-MDR, so the FEE component vanishes entirely. Still must balance."""
        write_batch(Generator(load_config(), seed=11, volume=200, payment_mix=mix,
                              defect_profile="demo").generate(), tmp_path)
        decomposition_for(tmp_path).check()

    @pytest.mark.parametrize("cycle", [1, 2, 7])
    def test_every_settlement_cycle_balances(self, tmp_path: Path, cycle: int) -> None:
        write_batch(Generator(load_config(), seed=11, volume=200,
                              settlement_cycle_days=cycle,
                              defect_profile="demo").generate(), tmp_path)
        decomposition_for(tmp_path).check()

    @pytest.mark.parametrize("volume", [60, 200, 1000])
    def test_every_volume_balances(self, tmp_path: Path, volume: int) -> None:
        write_batch(Generator(load_config(), seed=11, volume=volume,
                              defect_profile="scale").generate(), tmp_path)
        decomposition_for(tmp_path).check()

    def test_a_batch_with_no_bank_file_balances(self, demo: Path) -> None:
        """Two-way reconciliation: everything settled is 'in flight' by definition."""
        (demo / "bank.csv").unlink()
        decomposition_for(demo).check()
