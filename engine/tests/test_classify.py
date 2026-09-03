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
        # ₹1,000 UPI: 2% platform fee = ₹20 MDR, 18% GST on it = ₹3.60 (ADR-030).
        "amount": 100000, "credit": 97640, "debit": 0, "fee": 2360, "tax": 360,
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

    def test_upi_charged_the_platform_fee_is_not_flagged(self, classifier) -> None:
        """UPI is zero-MDR but not zero-fee: ~2% platform fee + 18% GST is correct.

        Regression test for ADR-030. This case previously asserted the opposite —
        that any UPI fee was a discrepancy — which would flag every real UPI row.
        On ₹1,000: 2% = ₹20 MDR, 18% GST on that = ₹3.60, total ₹23.60.
        """
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            [recon_row(fee=2360, credit=97640)],
        )
        assert not [x for x in classifier.classify(match(b)).findings
                    if x.classification is Classification.FEE]

    def test_upi_charged_no_fee_at_all_is_flagged(self, classifier) -> None:
        """The inverse: a zero fee on UPI is now the anomaly, not the expectation."""
        b = one_order_batch(
            {"order_id": "O1", "amount_paise": 100000, "captured_at": ts(2026, 9, 1),
             "payment_method": "upi"},
            [recon_row(fee=0, credit=100000)],
        )
        f = next(x for x in classifier.classify(match(b)).findings
                 if x.classification is Classification.FEE)
        assert f.proof["expected_fee_paise"] == 2360
        assert f.proof["actual_fee_paise"] == 0


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
            [recon_row(amount=100001, credit=97641)],
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


class TestUnrecordedRefund:
    """The reverse refund: money Razorpay returned that the merchant never recorded.

    ADR-039. Built from row 10 of `sample-settlements-recon-report.xlsx`, which carries
    `transaction_entity: refund` with a `settlement_id` and a BLANK `order_id`.
    Before this rule that row was dropped by the matcher and produced no finding at all.
    """

    @staticmethod
    def _batch(refund_row: dict) -> tuple:
        b = StagedBatch(batch_id="rev")
        b.add(Source.LEDGER, [{"order_id": "order_A", "amount_paise": 100000,
                               "captured_at": "2022-07-01", "_row": 2}], "t")
        b.add(Source.RECON, [
            {"transaction_entity": "payment", "order_id": "order_A", "amount": 100000,
             "credit": 97640, "debit": 0, "fee": 2360, "tax": 0,
             "settlement_id": "setl_1", "settled_at": "2022-07-04",
             "payment_method": "card_credit"},
            refund_row,
        ], "t")
        b.seal()
        result = match(b)
        return result, Classifier(load_config()).classify(result)

    def test_a_refund_with_no_order_id_is_reported(self) -> None:
        """THE regression. This row previously produced silence."""
        _, c = self._batch({
            "transaction_entity": "refund", "entity_id": "rfnd_Jt7Bq2djxtuWo5",
            "amount": 100000, "credit": 0, "debit": 100000, "fee": 0, "tax": 0,
            "settlement_id": "setl_JtAs2E7Uf55JMV", "settled_at": "2022-07-14",
        })
        found = c.by_class(Classification.UNRECORDED_REFUND)
        assert len(found) == 1
        assert found[0].amount_paise == 100000
        assert found[0].proof["entity_id"] == "rfnd_Jt7Bq2djxtuWo5"

    def test_a_refund_for_an_order_the_ledger_lacks_is_reported(self) -> None:
        """The other shape: an order_id is present but names nothing in the ledger."""
        _, c = self._batch({
            "transaction_entity": "refund", "entity_id": "rfnd_Y",
            "order_id": "order_NOT_IN_LEDGER", "amount": 5000, "credit": 0,
            "debit": 5000, "fee": 0, "tax": 0, "settlement_id": "setl_1",
            "settled_at": "2022-07-14",
        })
        found = c.by_class(Classification.UNRECORDED_REFUND)
        assert len(found) == 1
        assert found[0].order_id == "order_NOT_IN_LEDGER"
        assert "does not contain" in found[0].proof["reason"]

    def test_it_is_not_benign(self) -> None:
        """Money left the account and the books do not know. That needs a human."""
        assert Classification.UNRECORDED_REFUND not in BENIGN

    def test_a_refund_the_ledger_does_claim_is_not_unrecorded(self) -> None:
        """A refund both sides know about is REFUND, not UNRECORDED_REFUND."""
        _, c = self._batch({
            "transaction_entity": "refund", "entity_id": "rfnd_Z",
            "order_id": "order_A", "amount": 5000, "credit": 0, "debit": 5000,
            "fee": 0, "tax": 0, "settlement_id": "setl_1", "settled_at": "2022-07-14",
        })
        assert c.by_class(Classification.UNRECORDED_REFUND) == []

    def test_the_proof_carries_the_reason_the_merchant_needs(self) -> None:
        """A refund reason sitting in the row must reach the merchant, not be dropped."""
        _, c = self._batch({
            "transaction_entity": "refund", "entity_id": "rfnd_W", "amount": 100,
            "credit": 0, "debit": 100, "fee": 0, "tax": 0, "settlement_id": "setl_1",
            "settled_at": "2022-07-14", "arn": "219510147152",
            "refund_notes": '{"refund_reason":"Virtual Account is closed"}',
        })
        proof = c.by_class(Classification.UNRECORDED_REFUND)[0].proof
        assert proof["arn"] == "219510147152"
        assert "Virtual Account is closed" in proof["refund_notes"]

    def test_the_gap_still_balances(self) -> None:
        """A new money-claiming label must not double-count the debit.

        The refund debit is already booked by the REFUND component in Pass 2, which is
        keyed on settlement_id and therefore sees rows with no order_id. This rule adds
        a LABEL, not a second claim on the same rupees.
        """
        from finctl.gap import decompose

        result, c = self._batch({
            "transaction_entity": "refund", "entity_id": "rfnd_X", "amount": 100000,
            "credit": 0, "debit": 100000, "fee": 0, "tax": 0,
            "settlement_id": "setl_1", "settled_at": "2022-07-14",
        })
        assert decompose(result, c.findings).residual_paise == 0

    def test_it_gets_its_own_gap_component_not_the_refund_line(self) -> None:
        """The bug this guards: money hidden inside a benign line.

        REFUND and UNRECORDED_REFUND are debits of identical size and sign, so the
        arithmetic balances either way. But the verdict screen is built from gap
        components, and REFUND is a line a merchant reads and moves past. Folding the
        two together meant an actionable finding never reached the actionable list.
        """
        from finctl.gap import decompose

        result, c = self._batch({
            "transaction_entity": "refund", "entity_id": "rfnd_X", "amount": 100000,
            "credit": 0, "debit": 100000, "fee": 0, "tax": 0,
            "settlement_id": "setl_1", "settled_at": "2022-07-14",
        })
        by_class = {comp.classification: comp for comp in decompose(result, c.findings).components}
        assert Classification.UNRECORDED_REFUND in by_class
        assert by_class[Classification.UNRECORDED_REFUND].amount_paise == 100000
        # And it must NOT also be counted under REFUND.
        assert Classification.REFUND not in by_class


class TestDisputed:
    """A chargeback is neither late nor missing. ADR-041.

    `dispute_id`, `dispute_created_at` and `dispute_reason` are three real columns in
    `sample-settlements-recon-report.xlsx` — the schema is Razorpay's, not invented.
    """

    @staticmethod
    def _classify(recon_extra: dict):
        b = StagedBatch(batch_id="disp")
        b.add(Source.LEDGER, [{"order_id": "order_A", "amount_paise": 100000,
                               "captured_at": "2022-07-01", "_row": 2}], "t")
        b.add(Source.RECON, [{
            "transaction_entity": "payment", "order_id": "order_A", "amount": 100000,
            "credit": 97640, "debit": 0, "fee": 2360, "tax": 0,
            "payment_method": "card_credit", **recon_extra,
        }], "t")
        b.seal()
        return Classifier(load_config()).classify(match(b))

    def test_a_dispute_is_classified_as_disputed(self) -> None:
        c = self._classify({"dispute_id": "disp_X", "dispute_reason": "chargeback",
                            "settled_at": None})
        found = c.by_class(Classification.DISPUTED)
        assert len(found) == 1
        assert found[0].proof["dispute_ids"] == ["disp_X"]
        assert found[0].proof["dispute_reasons"] == ["chargeback"]

    def test_it_beats_timing(self) -> None:
        """THE ordering guarantee.

        A disputed payment also looks late once the cycle elapses. Reporting TIMING —
        'it arrives on its own' — is the most damaging thing the engine could say about
        a chargeback, because waiting is exactly how a merchant loses one.
        """
        c = self._classify({
            "dispute_id": "disp_X", "dispute_reason": "chargeback",
            "settled_at": "2023-01-01",   # long past any cycle
        })
        assert c.by_class(Classification.DISPUTED)
        assert not c.by_class(Classification.TIMING)

    def test_it_is_not_benign(self) -> None:
        """There is a response deadline. Doing nothing forfeits the money."""
        assert Classification.DISPUTED not in BENIGN

    def test_an_undisputed_row_is_not_disputed(self) -> None:
        c = self._classify({"settled_at": "2022-07-04"})
        assert not c.by_class(Classification.DISPUTED)

    def test_the_merchant_gets_the_reason_and_the_date(self) -> None:
        """Both are in the row. A merchant needs them to find it in the dashboard."""
        c = self._classify({"dispute_id": "disp_X", "dispute_reason": "fraud",
                            "dispute_created_at": "2022-07-05", "settled_at": None})
        proof = c.by_class(Classification.DISPUTED)[0].proof
        assert proof["dispute_reasons"] == ["fraud"]
        assert proof["dispute_raised_at"] == ["2022-07-05"]


class TestWithheldMoneyIsNeverAlsoLate:
    """ADR-036 claimed this for ON_HOLD and never enforced it. ADR-041 found that out.

    Rule ORDER was supposed to protect it, but TIMING is emitted from the `independent`
    set, which bypasses the money-rule contest entirely — so a withheld payment came out
    as BOTH withheld and "on its way, it arrives on its own". The second is false, and
    for a chargeback it is actively harmful: waiting is how a merchant loses one.
    """

    @staticmethod
    def _classify(extra: dict):
        b = StagedBatch(batch_id="w")
        b.add(Source.LEDGER, [{"order_id": "order_A", "amount_paise": 100000,
                               "captured_at": "2022-07-01", "_row": 2}], "t")
        b.add(Source.RECON, [{
            "transaction_entity": "payment", "order_id": "order_A", "amount": 100000,
            "credit": 97640, "debit": 0, "fee": 2360, "tax": 0,
            "payment_method": "card_credit", **extra,
        }], "t")
        b.seal()
        return Classifier(load_config()).classify(match(b))

    @pytest.mark.parametrize(
        ("label", "extra"),
        [
            ("on_hold", {"on_hold": True, "hold_reason": "risk_review"}),
            ("disputed", {"dispute_id": "disp_X", "dispute_reason": "chargeback"}),
        ],
    )
    def test_withheld_money_is_never_reported_as_timing(
        self, label: str, extra: dict
    ) -> None:
        # settled_at far past any cycle, so _check_timing would certainly fire.
        c = self._classify({**extra, "settled_at": "2023-01-01"})
        assert not c.by_class(Classification.TIMING), (
            f"{label} was also reported as TIMING — 'it arrives on its own' is false "
            "for money the PSP is withholding"
        )

    def test_a_genuinely_late_payment_is_still_timing(self) -> None:
        """The suppression must not swallow real timing findings."""
        c = self._classify({"settled_at": "2023-01-01"})
        assert c.by_class(Classification.TIMING)

