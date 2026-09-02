"""Two-pass matcher tests.

The value of two passes is that the output names WHICH LEG broke. A single
ledger-to-bank join can say money is missing; it cannot say whether the sale never
reached Razorpay or Razorpay never paid out. Those have different causes and fixes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finctl.config.loader import load_config
from finctl.generate.generator import Generator
from finctl.generate.ground_truth import DefectType, GroundTruth
from finctl.generate.writer import write_batch
from finctl.match.matcher import match
from finctl.schema import Source
from finctl.stage.staging import StagedBatch, stage_from_dir


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    batch = Generator(load_config(), seed=20260902, volume=200,
                      defect_profile="demo").generate()
    write_batch(batch, tmp_path)
    return tmp_path


@pytest.fixture
def result(demo_dir: Path):
    return match(stage_from_dir(demo_dir))


@pytest.fixture
def truth(demo_dir: Path) -> GroundTruth:
    return GroundTruth.read(demo_dir / "ground_truth.json")


class TestAgainstGroundTruth:
    """The matcher must find exactly what was planted. Not approximately."""

    def test_unmatched_orders_are_exactly_the_planted_gaps(self, result, truth) -> None:
        found = {m.order_id for m in result.unmatched_orders()}
        expected = {
            d.order_id for d in truth.real_defects
            if d.defect_type in (DefectType.MISSING_ORDER, DefectType.HALTED_SUBSCRIPTION)
        }
        assert found == expected, "matcher must find exactly the planted gaps, no others"

    def test_no_false_positives(self, result, truth) -> None:
        """An order the matcher calls missing that WAS settled is a lie to the merchant."""
        planted = {
            d.order_id for d in truth.real_defects
            if d.defect_type in (DefectType.MISSING_ORDER, DefectType.HALTED_SUBSCRIPTION)
        }
        for m in result.unmatched_orders():
            assert m.order_id in planted

    def test_the_gap_decomposes_completely(self, result) -> None:
        """expected - received == fees + missing, with nothing left over.

        A residual here would mean money the matcher cannot account for at all, which
        would silently pollute the 'we can't explain' bucket downstream.
        """
        fees = sum(m.fee_paise for m in result.order_matches)
        missing = sum(m.ledger_amount_paise for m in result.order_matches if not m.matched)
        assert result.gap_paise - fees - missing == 0


class TestTwoPassesNameTheLeg:
    def test_a_broken_order_leg_shows_in_pass1_not_pass2(self, result) -> None:
        """The whole point of two passes."""
        assert result.pass1_match_rate < 1.0     # sales did not all reach Razorpay
        assert result.pass2_match_rate == 1.0    # but every payout reached the bank

    def test_a_broken_bank_leg_shows_in_pass2_not_pass1(self, demo_dir: Path) -> None:
        """Delete a bank credit: pass 1 must stay perfect, pass 2 must drop."""
        import csv
        path = demo_dir / "bank.csv"
        rows = list(csv.DictReader(path.open()))
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows[:-1])          # drop one settlement credit

        r = match(stage_from_dir(demo_dir))
        assert r.pass2_match_rate < 1.0
        assert r.unmatched_bank_rows == []  # the settlement lost its credit, not vice versa

    def test_each_pass_states_its_question(self, result) -> None:
        s = result.summary()
        assert s["pass1"]["question"] == "did each sale reach Razorpay?"
        assert s["pass2"]["question"] == "did Razorpay's payout reach the bank?"


class TestRefusals:
    def test_matching_is_identifier_based_not_amount_based(self) -> None:
        """An amount-based near-match is a guess wearing a confidence score.

        Same amount, same day, different order id -> must NOT match.
        """
        b = StagedBatch(batch_id="t")
        b.add(Source.LEDGER, [{"order_id": "O_REAL", "amount_paise": 100000,
                               "captured_at": None, "payment_method": "upi"}], "l")
        b.add(Source.RECON, [{
            "entity_id": "pay_1", "type": "payment", "order_id": "O_DIFFERENT",
            "amount": 100000, "credit": 100000, "debit": 0, "fee": 0, "tax": 0,
            "settlement_id": "setl_1", "settlement_utr": "U1", "settled_at": 0,
        }], "r")
        r = match(b.seal())
        assert r.pass1_matched == 0
        assert len(r.unmatched_recon_orders) == 1

    def test_empty_batch_reports_zero_not_one_hundred_percent(self) -> None:
        """An empty batch has nothing to say. Claiming 100% would read well and lie."""
        r = match(StagedBatch(batch_id="empty").seal())
        assert r.pass1_match_rate == 0.0
        assert r.pass2_match_rate == 0.0
        assert r.gap_paise == 0

    def test_nothing_matching_reports_zero_percent_loudly(self) -> None:
        """It must never produce a plausible summary from an empty match set."""
        b = StagedBatch(batch_id="t")
        b.add(Source.LEDGER, [
            {"order_id": f"O{i}", "amount_paise": 1000, "captured_at": None,
             "payment_method": "upi"} for i in range(10)
        ], "l")
        r = match(b.seal())
        assert r.pass1_match_rate == 0.0
        assert r.pass1_total == 10
        assert len(r.unmatched_orders()) == 10


class TestAnomalies:
    def test_duplicate_order_ids_are_flagged_not_deduplicated(self) -> None:
        """Silently deduplicating would hide a real double-entry in the merchant's books."""
        b = StagedBatch(batch_id="t")
        b.add(Source.LEDGER, [
            {"order_id": "O1", "amount_paise": 1000, "captured_at": None, "payment_method": "upi"},
            {"order_id": "O1", "amount_paise": 1000, "captured_at": None, "payment_method": "upi"},
        ], "l")
        r = match(b.seal())
        assert r.duplicate_order_ids == {"O1": 2}
        assert r.pass1_total == 2                       # both rows survive
        assert all(m.is_duplicate_order_id for m in r.order_matches)

    def test_split_settlement_is_recorded_not_treated_as_an_error(self) -> None:
        """Adversarial case: one order paid across two settlements."""
        b = StagedBatch(batch_id="t")
        b.add(Source.LEDGER, [{"order_id": "O1", "amount_paise": 200000,
                               "captured_at": None, "payment_method": "card_credit"}], "l")
        b.add(Source.RECON, [
            {"entity_id": "pay_1", "type": "payment", "order_id": "O1", "amount": 100000,
             "credit": 97640, "debit": 0, "fee": 2360, "tax": 360,
             "settlement_id": "setl_1", "settlement_utr": "U1", "settled_at": 0},
            {"entity_id": "pay_2", "type": "payment", "order_id": "O1", "amount": 100000,
             "credit": 97640, "debit": 0, "fee": 2360, "tax": 360,
             "settlement_id": "setl_2", "settlement_utr": "U2", "settled_at": 0},
        ], "r")
        r = match(b.seal())
        m = r.order_matches[0]
        assert m.matched
        assert m.is_split
        assert m.settled_gross_paise == 200000     # both legs counted
        assert m.gap_paise == 0                    # and they add up

    def test_settlement_for_an_unknown_order_is_surfaced(self) -> None:
        """Money arriving for a sale the merchant has no record of is also an exception."""
        b = StagedBatch(batch_id="t")
        b.add(Source.LEDGER, [{"order_id": "O1", "amount_paise": 1000,
                               "captured_at": None, "payment_method": "upi"}], "l")
        b.add(Source.RECON, [{
            "entity_id": "pay_x", "type": "payment", "order_id": "O_GHOST",
            "amount": 5000, "credit": 5000, "debit": 0, "fee": 0, "tax": 0,
            "settlement_id": "setl_1", "settlement_utr": "U1", "settled_at": 0,
        }], "r")
        r = match(b.seal())
        assert len(r.unmatched_recon_orders) == 1

    def test_bank_credit_with_no_settlement_is_surfaced(self) -> None:
        b = StagedBatch(batch_id="t")
        b.add(Source.BANK, [{"utr": "U_MYSTERY", "credit_paise": 50000,
                             "value_date": None}], "b")
        r = match(b.seal())
        assert len(r.unmatched_bank_rows) == 1
        assert r.received_paise == 50000    # still counted as money received


class TestReconRowTypes:
    def test_refund_rows_do_not_count_as_a_successful_match(self) -> None:
        """ADR-008: a refund is not evidence that a sale reached Razorpay.

        Counting it would let a refunded-but-never-settled order look matched.
        """
        b = StagedBatch(batch_id="t")
        b.add(Source.LEDGER, [{"order_id": "O1", "amount_paise": 100000,
                               "captured_at": None, "payment_method": "card_credit"}], "l")
        b.add(Source.RECON, [{
            "entity_id": "rfnd_1", "type": "refund", "order_id": "O1",
            "amount": 100000, "credit": 0, "debit": 100000, "fee": 0, "tax": 0,
            "settlement_id": "setl_1", "settlement_utr": "U1", "settled_at": 0,
        }], "r")
        r = match(b.seal())
        assert not r.order_matches[0].matched

    def test_payment_rows_join_on_entity_id_not_payment_id(self, result) -> None:
        """ADR-008. Joining on payment_id would match nothing."""
        for m in result.order_matches:
            for row in m.recon_rows:
                assert row["payment_id"] is None
                assert row["entity_id"].startswith("pay_")


class TestDeterminism:
    def test_matching_is_pure_and_repeatable(self, demo_dir: Path) -> None:
        """Re-running must not mutate the batch or change the answer."""
        b = stage_from_dir(demo_dir)
        first = match(b).summary()
        second = match(b).summary()
        assert first == second

    def test_restaging_gives_the_same_answer(self, demo_dir: Path) -> None:
        assert match(stage_from_dir(demo_dir)).summary() == match(
            stage_from_dir(demo_dir)
        ).summary()


class TestScale:
    def test_five_thousand_orders_match(self, tmp_path: Path) -> None:
        batch = Generator(load_config(), seed=9, volume=5000,
                          defect_profile="scale").generate()
        write_batch(batch, tmp_path)
        r = match(stage_from_dir(tmp_path))
        assert r.pass1_total == 5000
        assert 0.0 < r.pass1_match_rate < 1.0
