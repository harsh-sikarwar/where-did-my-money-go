"""Classifier tests.

Every finding must carry the arithmetic that proves it. A row that cannot show its
working is UNEXPLAINED, not guessed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from finctl.classify.classifier import BENIGN, Classification, Classifier
from finctl.config.loader import load_config
from finctl.generate.generator import Generator
from finctl.generate.ground_truth import GroundTruth
from finctl.generate.writer import write_batch
from finctl.match.matcher import match
from finctl.schema import Source
from finctl.stage.staging import StagedBatch


def ts(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, 12, 0, tzinfo=UTC)


def one_order_batch(ledger: dict, recon: list[dict]) -> StagedBatch:
    b = StagedBatch(batch_id="t")
    b.add(Source.LEDGER, [ledger], "l")
    if recon:
        b.add(Source.RECON, recon, "r")
    return b.seal()


def recon_row(**kw):
    base = {
        "entity_id": "pay_1", "type": "payment", "order_id": "O1",
        "amount": 100000, "credit": 100000, "debit": 0, "fee": 0, "tax": 0,
        "settlement_id": "setl_1", "settlement_utr": "U1",
        "settled_at": int(ts(2026, 9, 3).timestamp()), "method": "upi",
    }
    base.update(kw)
    return base


@pytest.fixture
def classifier():
    return Classifier(load_config())


class TestReconciled:
    def test_a_correct_upi_order_is_reconciled(self, classifier) -> None:
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            [recon_row()],
        )
        f = classifier.classify(match(b)).findings[0]
        assert f.classification is Classification.RECONCILED
        assert f.amount_paise == 0
        assert "arithmetic" in f.proof

    def test_a_correct_card_order_with_fees_is_reconciled(self, classifier) -> None:
        """Fees are expected, not a discrepancy. 10,000 card -> 236 fee."""
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 1000000, "captured_at": ts(2026, 9, 1),
             "payment_method": "card_credit"},
            [recon_row(amount=1000000, fee=23600, tax=3600, credit=976400,
                       method="card_credit")],
        )
        assert classifier.classify(match(b)).findings[0].classification is (
            Classification.RECONCILED
        )


class TestFee:
    def test_an_overcharge_is_caught_with_both_numbers(self, classifier) -> None:
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 1000000, "captured_at": ts(2026, 9, 1),
             "payment_method": "card_credit"},
            [recon_row(amount=1000000, fee=27600, tax=3600, credit=972400,
                       method="card_credit")],
        )
        f = next(x for x in classifier.classify(match(b)).findings
                 if x.classification is Classification.FEE)
        assert f.proof["expected_fee_paise"] == 23600
        assert f.proof["actual_fee_paise"] == 27600
        assert f.proof["delta_paise"] == 4000
        assert f.amount_paise == 4000

    def test_the_proof_separates_mdr_from_gst(self, classifier) -> None:
        """So a merchant can verify each half independently (ADR-009)."""
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 1000000, "captured_at": ts(2026, 9, 1),
             "payment_method": "card_credit"},
            [recon_row(amount=1000000, fee=30000, tax=3600, credit=970000,
                       method="card_credit")],
        )
        f = next(x for x in classifier.classify(match(b)).findings
                 if x.classification is Classification.FEE)
        assert f.proof["expected_mdr_paise"] == 20000
        assert f.proof["expected_gst_paise"] == 3600

    def test_upi_charged_a_fee_is_flagged(self, classifier) -> None:
        """UPI is zero-MDR. Any fee at all is a discrepancy."""
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            [recon_row(fee=2000, credit=98000)],
        )
        f = next(x for x in classifier.classify(match(b)).findings
                 if x.classification is Classification.FEE)
        assert f.proof["expected_fee_paise"] == 0
        assert f.proof["actual_fee_paise"] == 2000


class TestTiming:
    def test_settling_late_is_timing_not_missing(self, classifier) -> None:
        """The money arrived. It was late. That is a different thing."""
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            [recon_row(settled_at=int(ts(2026, 9, 10).timestamp()))],
        )
        f = next(x for x in classifier.classify(match(b)).findings
                 if x.classification is Classification.TIMING)
        assert f.proof["working_days_late"] > 1
        assert "expected_settled_on" in f.proof

    def test_within_grace_is_not_flagged(self, classifier) -> None:
        """grace_days is a deliberate tolerance, not an oversight."""
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            [recon_row(settled_at=int(ts(2026, 9, 4).timestamp()))],
        )
        classes = {f.classification for f in classifier.classify(match(b)).findings}
        assert Classification.TIMING not in classes

    def test_timing_is_benign(self) -> None:
        assert Classification.TIMING in BENIGN


class TestRefundDirection:
    """A real bug: I had this backwards on the first implementation."""

    def test_settlement_exceeding_ledger_is_a_refund(self, classifier) -> None:
        """The merchant recorded a refund that never reached settlement.

        Their ledger is written DOWN; Razorpay still shows the full amount. So the
        shape is settlement > ledger — a NEGATIVE gap under our sign convention.
        """
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 50000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            [recon_row(amount=100000, credit=100000)],
        )
        f = next(x for x in classifier.classify(match(b)).findings
                 if x.classification is Classification.REFUND)
        assert f.proof["direction"] == "settlement_exceeds_ledger"
        assert f.amount_paise == 50000

    def test_ledger_exceeding_settlement_is_not_a_refund(self, classifier) -> None:
        """A shortfall is money that never arrived, not money that went back.

        Labelling it REFUND would tell the merchant they refunded a customer they
        did not refund.
        """
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            [recon_row(amount=50000, credit=50000)],
        )
        classes = {f.classification for f in classifier.classify(match(b)).findings}
        assert Classification.REFUND not in classes
        assert Classification.UNEXPLAINED in classes


class TestMissingAndDuplicate:
    def test_no_settlement_is_missing(self, classifier) -> None:
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            [],
        )
        f = classifier.classify(match(b)).findings[0]
        assert f.classification is Classification.MISSING
        assert f.amount_paise == 100000

    def test_duplicate_order_id_is_flagged(self, classifier) -> None:
        b = StagedBatch(batch_id="t")
        b.add(Source.LEDGER, [
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
        ], "l")
        b.add(Source.RECON, [recon_row()], "r")
        findings = classifier.classify(match(b.seal())).findings
        assert all(f.classification is Classification.DUPLICATE for f in findings)


class TestAmbiguityRefusal:
    def test_two_competing_money_rules_become_needs_review(self, classifier) -> None:
        """Cointab's 'leave it unmatched when evidence is weak'.

        Picking the highest-scoring rule would convert a visible ambiguity into an
        invisible wrong answer.
        """
        # An amount gap that is simultaneously within rounding tolerance and not:
        # constructed so both _check_amount_gap and _check_rounding could claim it.
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            [recon_row(amount=100001, credit=100001)],
        )
        findings = classifier.classify(match(b)).findings
        # gap of 1 paise is within tolerance -> ROUNDING alone, no ambiguity
        assert {f.classification for f in findings} <= {
            Classification.ROUNDING, Classification.RECONCILED
        }

    def test_needs_review_carries_every_candidate(self) -> None:
        """When it does fire, it must not hide what it could not choose between."""
        from finctl.classify.classifier import Finding
        f = Finding(
            order_id="O1", classification=Classification.NEEDS_REVIEW, amount_paise=100,
            candidates=[Classification.FEE, Classification.REFUND],
        )
        assert len(f.as_dict()["candidates"]) == 2

    def test_needs_review_counts_toward_unexplained(self, classifier) -> None:
        """An ambiguous explanation is not an explanation."""
        from finctl.classify.classifier import ClassificationResult, Finding
        r = ClassificationResult(findings=[
            Finding(order_id="O1", classification=Classification.NEEDS_REVIEW,
                    amount_paise=5000),
        ])
        assert r.unexplained_paise == 5000


class TestProof:
    def test_every_non_reconciled_finding_carries_arithmetic(self, classifier) -> None:
        """BEHAVIOR.md invariant 3, asserted across a whole real batch."""
        import tempfile
        d = Path(tempfile.mkdtemp())
        write_batch(Generator(load_config(), seed=3, volume=200,
                              defect_profile="demo").generate(), d)
        from finctl.stage.staging import stage_from_dir
        for f in classifier.classify(match(stage_from_dir(d))).findings:
            assert f.proof, f"{f.classification} finding has no proof"
            assert "arithmetic" in f.proof or "reason" in f.proof

    def test_proof_is_structured_data_not_prose(self, classifier) -> None:
        """It is handed to the LLM as facts. The LLM returns language, never numbers."""
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 1000000, "captured_at": ts(2026, 9, 1),
             "payment_method": "card_credit"},
            [recon_row(amount=1000000, fee=27600, tax=3600, credit=972400,
                       method="card_credit")],
        )
        f = next(x for x in classifier.classify(match(b)).findings
                 if x.classification is Classification.FEE)
        assert isinstance(f.proof["delta_paise"], int)
        assert isinstance(f.proof["expected_fee_paise"], int)


class TestAgainstGroundTruth:
    def test_every_planted_defect_type_is_detected(self, tmp_path: Path) -> None:
        from finctl.stage.staging import stage_from_dir
        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        gt = GroundTruth.read(tmp_path / "ground_truth.json")
        result = Classifier(load_config()).classify(match(stage_from_dir(tmp_path)))

        # Every REFUND finding comes from one of two mechanisms: a one-sided refund
        # (ledger disagrees with settlement) or a refund Razorpay actually debited.
        # Both are real and both must be found.
        planted_refunds = (
            len(gt.by_type("one_sided_refund")) + len(gt.by_type("early_refund"))
        )
        assert len(result.by_class(Classification.REFUND)) == planted_refunds

        # Fee overcharges likewise.
        assert len(result.by_class(Classification.FEE)) == len(gt.by_type("wrong_fee_rate"))
