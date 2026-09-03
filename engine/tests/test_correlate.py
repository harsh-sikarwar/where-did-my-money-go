"""Correlation tests — the differentiator.

The headline claim needs its own test matrix. Two things matter equally:
  * that it RESOLVES what it legitimately can (the gain)
  * that it REFUSES what it cannot (no false attribution)

The second is the harder discipline. A correlator that resolves everything is not
impressive, it is lying.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finctl.classify.classifier import Classification, Classifier
from finctl.config.loader import load_config
from finctl.correlate.correlator import Correlator, failure_bucket
from finctl.generate.generator import Generator
from finctl.generate.ground_truth import GroundTruth
from finctl.generate.writer import write_batch
from finctl.match.matcher import match
from finctl.schema import Source
from finctl.score import score
from finctl.stage.staging import StagedBatch, stage_from_dir


def scenario(payments=None, subscriptions=None, recon=None) -> StagedBatch:
    """One unmatched order, with whatever payment/subscription evidence is supplied."""
    b = StagedBatch(batch_id="t")
    b.add(Source.LEDGER, [{"order_id": "O1", "amount_paise": 100000,
                           "captured_at": None, "payment_method": "upi"}], "l")
    if payments:
        b.add(Source.PAYMENTS, payments, "p")
    if subscriptions:
        b.add(Source.SUBSCRIPTIONS, subscriptions, "s")
    if recon:
        b.add(Source.RECON, recon, "r")
    return b.seal()


def classify_and_correlate(batch: StagedBatch):
    cfg = load_config()
    return Correlator(batch).correlate(Classifier(cfg).classify(match(batch)))


class TestResolution:
    def test_a_halted_subscription_is_resolved(self) -> None:
        """The demo centrepiece: invoice generated, charge never attempted."""
        b = scenario(
            payments=[{"id": "pay_1", "order_id": "O1", "status": "failed",
                       "error_reason": "subscription_halted", "subscription_id": "sub_1",
                       "invoice_id": "inv_1"}],
            subscriptions=[{"id": "sub_1", "status": "halted", "auth_attempts": 3,
                            "remaining_count": 8, "customer_id": "cust_1"}],
        )
        f = classify_and_correlate(b).findings[0]
        assert f.classification is Classification.HALTED_SUBSCRIPTION
        c = f.proof["correlation"]
        assert c["subscription_status"] == "halted"
        assert c["invoice_id"] == "inv_1"          # the invoice DID get generated
        assert c["join_chain"]                     # and we say how we got there

    def test_a_failed_payment_is_resolved_with_its_reason(self) -> None:
        b = scenario(payments=[{"id": "pay_1", "order_id": "O1", "status": "failed",
                                "error_code": "GATEWAY_ERROR",
                                "error_reason": "insufficient_funds",
                                "error_description": "Card has insufficient funds",
                                "subscription_id": None}])
        f = classify_and_correlate(b).findings[0]
        assert f.classification is Classification.PAYMENT_FAILED
        assert f.proof["correlation"]["error_reason"] == "insufficient_funds"
        assert f.proof["correlation"]["failure_bucket"] == "retry_later"

    def test_the_before_after_number_moves(self) -> None:
        """The Day-1 checkpoint, in miniature."""
        b = scenario(payments=[{"id": "pay_1", "order_id": "O1", "status": "failed",
                                "error_reason": "insufficient_funds",
                                "subscription_id": None}])
        r = classify_and_correlate(b)
        assert r.unexplained_before_paise == 100000
        assert r.unexplained_after_paise == 0
        assert r.resolved_paise == 100000


class TestRefusals:
    """No inference from resemblance. The join lands, or the row stays unexplained."""

    def test_no_payment_record_stays_unresolved(self) -> None:
        r = classify_and_correlate(scenario())
        f = r.findings[0]
        assert f.classification is Classification.MISSING
        assert f.proof["correlation"]["outcome"].startswith("no payment record")
        assert r.unexplained_after_paise == 100000   # honestly still unexplained

    def test_an_active_subscription_is_not_claimed_as_halted(self) -> None:
        """THE false-attribution guard.

        A failed payment on an ACTIVE subscription is a normal retryable failure, not
        silent revenue death. Claiming otherwise would tell a merchant to chase a
        customer whose subscription is working fine.
        """
        b = scenario(
            payments=[{"id": "pay_1", "order_id": "O1", "status": "failed",
                       "error_reason": "insufficient_funds", "subscription_id": "sub_1"}],
            subscriptions=[{"id": "sub_1", "status": "active", "auth_attempts": 0}],
        )
        f = classify_and_correlate(b).findings[0]
        assert f.classification is Classification.PAYMENT_FAILED
        assert f.classification is not Classification.HALTED_SUBSCRIPTION

    def test_an_unresolvable_subscription_id_is_not_attributed_elsewhere(self) -> None:
        """A dangling reference must not borrow a different subscription's halted status."""
        b = scenario(
            payments=[{"id": "pay_1", "order_id": "O1", "status": "failed",
                       "error_reason": "x", "subscription_id": "sub_GONE"}],
            subscriptions=[{"id": "sub_OTHER", "status": "halted", "auth_attempts": 3}],
        )
        assert classify_and_correlate(b).findings[0].classification is (
            Classification.PAYMENT_FAILED
        )

    def test_a_successful_payment_does_not_explain_a_gap(self) -> None:
        """If the payment succeeded, the gap has some other cause. Say so."""
        b = scenario(payments=[{"id": "pay_1", "order_id": "O1", "status": "captured",
                                "subscription_id": None}])
        f = classify_and_correlate(b).findings[0]
        assert f.classification is Classification.MISSING
        assert "did not fail" in f.proof["correlation"]["outcome"]

    def test_correlation_never_overrides_arithmetic_proof(self) -> None:
        """A FEE finding is proven by arithmetic. Correlation must leave it alone."""
        b = StagedBatch(batch_id="t")
        b.add(Source.LEDGER, [{"order_id": "O1", "amount_paise": 1000000,
                               "captured_at": None, "payment_method": "card_credit"}], "l")
        b.add(Source.RECON, [{"entity_id": "pay_1", "type": "payment", "order_id": "O1",
                              "amount": 1000000, "credit": 972400, "debit": 0,
                              "fee": 27600, "tax": 3600, "settlement_id": "s1",
                              "settlement_utr": "U1", "settled_at": None,
                              "method": "card_credit"}], "r")
        b.add(Source.PAYMENTS, [{"id": "pay_1", "order_id": "O1", "status": "failed",
                                 "error_reason": "insufficient_funds",
                                 "subscription_id": None}], "p")
        classes = {f.classification for f in classify_and_correlate(b.seal()).findings}
        assert Classification.FEE in classes
        assert Classification.PAYMENT_FAILED not in classes


class TestFailureBuckets:
    @pytest.mark.parametrize(
        ("reason", "bucket"),
        [("insufficient_funds", "retry_later"), ("incorrect_otp", "retry_later"),
         ("gateway_timeout", "retry_soon"), ("payment_risk_check_failed", "never_retry"),
         ("fraud_suspected", "never_retry"), ("some_new_code_razorpay_added", "unknown"),
         (None, "unknown")],
    )
    def test_buckets(self, reason, bucket: str) -> None:
        assert failure_bucket(reason) == bucket

    def test_a_risk_block_is_never_recommended_for_retry(self) -> None:
        """Retrying a risk block is at best futile and at worst account-damaging."""
        assert failure_bucket("payment_risk_check_failed") == "never_retry"

    def test_unknown_codes_are_not_silently_sorted_into_retry(self) -> None:
        """An unrecognised decline getting sorted into 'retry' is confident bad advice."""
        assert failure_bucket("brand_new_code") == "unknown"


class TestGainMetric:
    def test_zero_before_reports_zero_gain_not_perfect(self) -> None:
        """Nothing to resolve is not a perfect score (same reasoning as ADR-016)."""
        from finctl.correlate.correlator import CorrelationResult
        assert CorrelationResult().gain_ratio == 0.0

    def test_gain_ratio_is_the_fraction_resolved(self) -> None:
        from finctl.correlate.correlator import CorrelationResult
        r = CorrelationResult(unexplained_before_paise=1000, unexplained_after_paise=250)
        assert r.gain_ratio == 0.75


class TestEndToEndAgainstGroundTruth:
    """The checkpoint itself, asserted."""

    @pytest.fixture
    def scored(self, tmp_path: Path):
        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        cfg = load_config()
        batch = stage_from_dir(tmp_path)
        matches = match(batch)
        correlated = Correlator(batch).correlate(Classifier(cfg).classify(matches))
        return score(GroundTruth.read(tmp_path / "ground_truth.json"),
                     correlated, matches, cfg), correlated

    def test_the_unexplained_number_moves(self, scored) -> None:
        """THE DAY-1 CHECKPOINT. If this fails, everything downstream is decoration."""
        _, correlated = scored
        assert correlated.unexplained_before_paise > 0
        assert correlated.unexplained_after_paise < correlated.unexplained_before_paise

    def test_no_false_positives(self, scored) -> None:
        """Worse than a miss: telling a merchant something untrue."""
        report, _ = scored
        assert report.false_positives == []

    def test_every_planted_defect_is_caught_or_honestly_below_tolerance(self, scored) -> None:
        report, _ = scored
        assert report.total_missed == 0, f"missed: {report.as_dict()['by_type']}"

    def test_all_six_halted_subscriptions_are_found(self, scored) -> None:
        report, _ = scored
        assert len(report.by_type["halted_subscription"].caught) == 6

    @pytest.mark.parametrize("archetype", ["saas_subscription", "d2c_ecommerce"])
    def test_holds_across_archetypes(self, tmp_path: Path, archetype: str) -> None:
        write_batch(Generator(load_config(), seed=7, volume=200, archetype=archetype,
                              defect_profile="demo").generate(), tmp_path)
        cfg = load_config()
        batch = stage_from_dir(tmp_path)
        matches = match(batch)
        correlated = Correlator(batch).correlate(Classifier(cfg).classify(matches))
        report = score(GroundTruth.read(tmp_path / "ground_truth.json"),
                       correlated, matches, cfg)
        assert report.total_missed == 0
        assert report.false_positives == []


class TestFalseAttributionAtBatchScale:
    """The decoy, scored. ADR-042.

    The unit tests above prove the engine declines a single hand-built decoy. This
    proves it at batch scale, through the real pipeline, with the decoys planted by the
    generator and scored by the scorer — which is what turns "0 false positives" from a
    statement about DATA (where every gap happened to have a real cause) into a
    statement about the ENGINE (which had a wrong cause dangled in front of it).
    """

    @staticmethod
    def _run(tmp_path, **kwargs):
        from finctl.config.loader import load_config
        from finctl.generate.generator import Generator
        from finctl.generate.writer import write_batch
        from finctl.pipeline import run

        params = dict(seed=20260902, volume=200, defect_profile="demo")
        params.update(kwargs)
        write_batch(Generator(load_config(), **params).generate(), tmp_path)
        return run(tmp_path)

    def test_the_demo_batch_plants_decoys_at_all(self, tmp_path) -> None:
        """A guard that is never exercised guards nothing."""
        r = self._run(tmp_path)
        assert r.scored.decoys_resisted or r.scored.decoys_claimed, (
            "no decoys were scored — the false-attribution guard is not being exercised"
        )

    def test_no_decoy_is_ever_claimed(self, tmp_path) -> None:
        """THE headline assertion.

        A claimed decoy means the engine told a merchant to chase a customer whose
        subscription is working fine. That is worse than a miss: a miss is a gap in
        coverage, a false attribution is the engine being confidently wrong.
        """
        r = self._run(tmp_path)
        assert r.scored.decoys_claimed == [], (
            f"false attribution: {r.scored.decoys_claimed}"
        )
        assert r.scored.false_attribution_rate == 0.0

    def test_the_decoy_gets_the_milder_correct_answer(self, tmp_path) -> None:
        """Resisting is not enough — the engine must still explain the gap.

        Declining to say HALTED_SUBSCRIPTION while saying nothing at all would resist
        the trap and fail the merchant. The right answer is PAYMENT_FAILED: the payment
        really did fail, it is simply retryable rather than terminal.
        """
        from finctl.classify.classifier import Classification
        from finctl.generate.ground_truth import GroundTruth

        r = self._run(tmp_path)
        gt = GroundTruth.read(tmp_path / "ground_truth.json")
        decoy_orders = {d.order_id for d in gt.decoys}
        assert decoy_orders
        by_order = {f.order_id: f.classification for f in r.correlated.findings}
        for oid in decoy_orders:
            assert by_order.get(oid) is Classification.PAYMENT_FAILED, (
                f"decoy {oid} got {by_order.get(oid)}, expected PAYMENT_FAILED"
            )

    def test_a_decoy_is_not_counted_as_a_false_positive(self, tmp_path) -> None:
        """The engine gave the RIGHT answer on a decoy. That must not score as a miss.

        A decoy order is planted, just not as a defect. Scoring the correct answer as a
        false positive would make planting decoys look like a regression and discourage
        ever adding one.
        """
        r = self._run(tmp_path)
        assert r.scored.false_positives == []

    @pytest.mark.parametrize("cycle", [1, 2, 7])
    def test_decoys_are_resisted_across_settlement_cycles(self, tmp_path, cycle) -> None:
        """The guard must not depend on the merchant's settlement terms."""
        r = self._run(tmp_path, settlement_cycle_days=cycle)
        assert r.scored.decoys_claimed == []


class TestWithholdingIsItsOwnMechanism:
    """Three joins, not one. ADR-049.

    The classifier reads `dispute_id` and `on_hold` (ADR-036, ADR-041) — but only on an
    order it MATCHED. An order the ledger has and the matcher could not pair arrives at
    correlation as MISSING, and those fields were never looked at. A disputed payment
    behind a missing order came out as a generic PAYMENT_FAILED, losing the deadline.
    """

    def test_a_dispute_beats_payment_failed(self) -> None:
        """"Retry the charge" is the wrong instruction for a chargeback."""
        b = scenario(payments=[{
            "id": "pay_1", "order_id": "O1", "status": "failed",
            "dispute_id": "disp_1", "dispute_reason": "chargeback",
        }])
        f = classify_and_correlate(b).findings[0]
        assert f.classification is Classification.DISPUTED
        assert f.proof["correlation"]["dispute_id"] == "disp_1"
        assert f.proof["correlation"]["dispute_reason"] == "chargeback"

    def test_a_hold_beats_payment_failed(self) -> None:
        b = scenario(payments=[{
            "id": "pay_1", "order_id": "O1", "status": "failed",
            "on_hold": True, "hold_reason": "kyc_pending",
        }])
        f = classify_and_correlate(b).findings[0]
        assert f.classification is Classification.ON_HOLD
        assert f.proof["correlation"]["hold_reason"] == "kyc_pending"

    def test_a_dispute_on_a_recon_row_is_found_too(self) -> None:
        """A real export carries dispute_id on the recon row; which file a merchant
        uploaded should not change the answer."""
        b = scenario(
            payments=[{"id": "pay_1", "order_id": "O1", "status": "failed"}],
            recon=[{"transaction_entity": "refund", "order_id": "O1",
                    "dispute_id": "disp_9", "dispute_reason": "fraud",
                    "amount": 0, "credit": 0, "debit": 0, "fee": 0, "tax": 0}],
        )
        f = classify_and_correlate(b).findings[0]
        assert f.classification is Classification.DISPUTED
        assert f.proof["correlation"]["dispute_id"] == "disp_9"

    def test_an_ordinary_failure_is_still_payment_failed(self) -> None:
        """The new mechanisms must not swallow the one that already worked."""
        b = scenario(payments=[{
            "id": "pay_1", "order_id": "O1", "status": "failed",
            "error_reason": "incorrect_otp",
        }])
        assert classify_and_correlate(b).findings[0].classification is (
            Classification.PAYMENT_FAILED
        )

    def test_a_halted_subscription_is_still_found(self) -> None:
        b = scenario(
            payments=[{"id": "pay_1", "order_id": "O1", "status": "failed",
                       "subscription_id": "sub_1"}],
            subscriptions=[{"id": "sub_1", "status": "halted", "auth_attempts": 3}],
        )
        assert classify_and_correlate(b).findings[0].classification is (
            Classification.HALTED_SUBSCRIPTION
        )

    def test_a_dispute_outranks_a_halted_subscription(self) -> None:
        """Both are true; only one has a deadline. Order of precedence is the claim."""
        b = scenario(
            payments=[{"id": "pay_1", "order_id": "O1", "status": "failed",
                       "subscription_id": "sub_1", "dispute_id": "disp_1"}],
            subscriptions=[{"id": "sub_1", "status": "halted", "auth_attempts": 3}],
        )
        assert classify_and_correlate(b).findings[0].classification is (
            Classification.DISPUTED
        )

    def test_no_dispute_and_no_hold_changes_nothing(self) -> None:
        """THE false-attribution guard for the new mechanisms.

        A payment record with neither field must not acquire one. Same discipline as
        the halted/active distinction: resemblance is not evidence.
        """
        b = scenario(payments=[{"id": "pay_1", "order_id": "O1", "status": "failed",
                                "dispute_id": None, "on_hold": False}])
        f = classify_and_correlate(b).findings[0]
        assert f.classification is Classification.PAYMENT_FAILED

    def test_the_action_list_gets_a_usable_reason(self) -> None:
        """A correlated cause with no `error_reason` leaves the action list blank."""
        b = scenario(payments=[{"id": "pay_1", "order_id": "O1", "status": "failed",
                                "dispute_id": "disp_1", "dispute_reason": "chargeback"}])
        from finctl.actions import build

        groups = build(classify_and_correlate(b).findings)
        assert groups[0].items[0].reason == "chargeback"

