"""Composition audit: is the OUTPUT true, not just are the parts correct?

Written after the verdict screen showed ₹99,421.65 of lines against a ₹38,372.30 gap.
That bug survived 345 tests because every individual number was correct and
independently tested — nothing asserted the relationship BETWEEN correct numbers.

So these tests deliberately do NOT reuse the engine's own aggregation helpers. They
recompute each displayed figure from the rawest available source — the staged rows, the
generator's ground truth — and compare. Agreement then means something, because the two
paths do not share code. Reusing `matches.expected_paise` to check
`matches.expected_paise` would prove only that a property is deterministic.

Every number the UI renders should appear here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finctl.config.loader import load_config
from finctl.generate.generator import Generator
from finctl.generate.writer import write_batch
from finctl.pipeline import run
from finctl.schema import Source

CONFIGURATIONS = [
    ("demo", "saas_subscription", None, 200),
    ("demo", "d2c_ecommerce", None, 200),
    ("demo", "saas_subscription", "upi_heavy", 200),
    ("demo", "saas_subscription", "card_heavy", 200),
    ("scale", "saas_subscription", "even", 500),
    ("clean", "d2c_ecommerce", None, 120),
]


def build(tmp_path: Path, profile: str, archetype: str, mix: str | None, volume: int):
    write_batch(
        Generator(load_config(), seed=20260902, volume=volume, archetype=archetype,
                  payment_mix=mix, defect_profile=profile).generate(),
        tmp_path,
    )
    return run(tmp_path)


@pytest.fixture(params=CONFIGURATIONS, ids=lambda c: f"{c[0]}-{c[1][:4]}-{c[2] or 'default'}-{c[3]}")
def scenario(request, tmp_path: Path):
    return build(tmp_path, *request.param), tmp_path


# ---------------------------------------------------------------- raw recomputation


def raw_expected_paise(batch_dir: Path) -> int:
    """Sum the ledger CSV directly, parsing rupee strings by hand.

    Deliberately does not use `parse_money` or the normalizer: if both the engine and
    the check share a parser, a parser bug agrees with itself.
    """
    total = 0
    lines = (batch_dir / "ledger.csv").read_text().strip().splitlines()
    header = lines[0].split(",")
    amount_col = header.index("amount")
    for row in lines[1:]:
        rupees = row.split(",")[amount_col].strip().strip('"').replace(",", "")
        whole, _, frac = rupees.partition(".")
        total += int(whole) * 100 + int((frac + "00")[:2])
    return total


def raw_received_paise(batch_dir: Path) -> int:
    """Sum the bank CSV directly."""
    total = 0
    lines = (batch_dir / "bank.csv").read_text().strip().splitlines()
    if len(lines) < 2:
        return 0
    header = lines[0].split(",")
    col = header.index("credit_amount")
    for row in lines[1:]:
        rupees = row.split(",")[col].strip().strip('"').replace(",", "")
        neg = rupees.startswith("-")
        rupees = rupees.lstrip("-")
        whole, _, frac = rupees.partition(".")
        value = int(whole) * 100 + int((frac + "00")[:2])
        total += -value if neg else value
    return total


def raw_recon(batch_dir: Path) -> list[dict]:
    return json.loads((batch_dir / "settlement_recon.json").read_text())["items"]


# ---------------------------------------------------------------- the audit


class TestHeadlineFigures:
    """The three numbers at the top of the screen."""

    def test_expected_matches_the_ledger_file(self, scenario) -> None:
        result, batch_dir = scenario
        assert result.verdict.expected_paise == raw_expected_paise(batch_dir)

    def test_received_matches_the_bank_file(self, scenario) -> None:
        result, batch_dir = scenario
        assert result.verdict.received_paise == raw_received_paise(batch_dir)

    def test_gap_is_the_difference(self, scenario) -> None:
        result, _ = scenario
        v = result.verdict
        assert v.gap_paise == v.expected_paise - v.received_paise


class TestTheLinesAddUp:
    """The bug that started this file."""

    def test_lines_plus_residual_equal_the_gap(self, scenario) -> None:
        result, _ = scenario
        v = result.verdict
        total = sum(line.amount_paise for line in v.lines)
        assert total + v.residual_paise == v.gap_paise, (
            f"lines sum to {total} + residual {v.residual_paise}, "
            f"but the gap is {v.gap_paise}"
        )

    def test_unexplained_is_the_correlation_residual_not_the_decomposition_one(
        self, scenario
    ) -> None:
        """The row a merchant reads must be capable of being non-zero.

        It used to show `GapDecomposition.residual_paise`, which is structurally always
        zero — the components are built to close the gap, and `check()` raises if they
        do not. So the screen said "Unexplained: nothing in the data accounts for this,
        ₹0.00" on every run ever made, while the correlation section on the same page
        named real money still outstanding.
        """
        result, _ = scenario
        v = result.verdict
        c = result.correlated

        assert v.unexplained_paise == sum(f.amount_paise for f in c.still_unexplained)
        assert v.unexplained_count == len(c.still_unexplained)
        # And the integrity check it used to be conflated with still holds separately.
        assert v.residual_paise == 0

    def test_actionable_plus_benign_equals_the_lines(self, scenario) -> None:
        """Both totals are displayed. They must partition the same set."""
        result, _ = scenario
        v = result.verdict
        assert v.actionable_paise + v.benign_paise == sum(
            line.amount_paise for line in v.lines
        )

    def test_fee_line_equals_the_fees_in_the_recon_file(self, scenario) -> None:
        """Recomputed from the raw JSON, not from the matcher."""
        result, batch_dir = scenario
        from finctl.classify.classifier import Classification

        fee_line = next(
            (line for line in result.verdict.lines
             if line.classification is Classification.FEE), None
        )
        # Only fees on rows the LEDGER knows about count — a settlement for an order the
        # merchant never recorded is a different line entirely.
        ledger_orders = {r["order_id"] for r in result.batch.get(Source.LEDGER)}
        raw_fees = sum(
            r["fee"] for r in raw_recon(batch_dir)
            if r["type"] == "payment" and r.get("order_id") in ledger_orders
        )
        assert (fee_line.amount_paise if fee_line else 0) == raw_fees


class TestCounts:
    """Counts are displayed next to every amount. A wrong count is a wrong claim."""

    def test_line_counts_match_the_findings_behind_them(self, scenario) -> None:
        """A count and the amount beside it must describe the same rows.

        FEE is the exception that proves the rule, and it is excluded here because it
        is asserted properly below instead. Every order that pays a fee produces no
        finding — a correct fee is not a discrepancy — so for FEE the finding count is
        the OVERCHARGED orders while the amount is the whole fee. Requiring them to be
        equal is what drove the fee line to display one population's count over
        another's money.
        """
        from finctl.classify.classifier import Classification

        result, _ = scenario
        for line in result.verdict.lines:
            if line.classification is Classification.FEE:
                continue
            behind = [
                f for f in result.correlated.findings
                if f.classification is line.classification
            ]
            if behind:
                assert line.count == len(behind), (
                    f"{line.classification}: screen says {line.count}, "
                    f"{len(behind)} findings exist"
                )

    def test_fee_line_and_its_note_each_count_their_own_population(
        self, scenario
    ) -> None:
        """The fee line counts fee-payers; its note counts the overcharged.

        The regression this pins: the line once took its count from the findings and
        its amount from the gap component, so it read "40 orders, ₹37,023.69" beside a
        drill-down of "40 orders, ₹227.90" — 162x apart under one label.
        """
        from finctl.classify.classifier import Classification

        result, _ = scenario
        fee = next(
            (line for line in result.verdict.lines
             if line.classification is Classification.FEE), None
        )
        if fee is None:
            return

        over = [
            f for f in result.correlated.findings
            if f.classification is Classification.FEE
        ]

        # The line counts orders that paid a fee, which is at least the number
        # overcharged and generally many more.
        assert fee.count >= len(over)

        if over:
            assert fee.note is not None, "overcharges exist but the line does not say so"
            assert fee.note.count == len(over)
            assert fee.note.amount_paise == sum(f.amount_paise for f in over)
            # The overcharge is part of the fee already shown, never additional to it.
            assert abs(fee.note.amount_paise) <= abs(fee.amount_paise)
        else:
            assert fee.note is None

    def test_halted_count_matches_the_subscriptions_file(self, scenario) -> None:
        """'Six customers' must be six actual halted subscriptions."""
        result, batch_dir = scenario
        from finctl.classify.classifier import Classification

        halted_line = next(
            (line for line in result.verdict.lines
             if line.classification is Classification.HALTED_SUBSCRIPTION), None
        )
        if halted_line is None:
            return
        subs = json.loads((batch_dir / "subscriptions.json").read_text())["items"]
        assert halted_line.count == sum(1 for s in subs if s["status"] == "halted")

    def test_match_rates_are_consistent_with_their_counts(self, scenario) -> None:
        """The footer shows '191/200' and the rate. They must agree."""
        result, _ = scenario
        s = result.matches.summary()
        for key in ("pass1", "pass2"):
            p = s[key]
            assert p["matched"] + p["unmatched"] == p["total"]
            if p["total"]:
                assert abs(p["match_rate"] - p["matched"] / p["total"]) < 1e-9


class TestCorrelationScreen:
    def test_before_minus_after_equals_resolved(self, scenario) -> None:
        result, _ = scenario
        c = result.correlated
        assert c.unexplained_before_paise - c.unexplained_after_paise == c.resolved_paise

    def test_after_equals_the_rows_still_unexplained(self, scenario) -> None:
        result, _ = scenario
        c = result.correlated
        assert c.unexplained_after_paise == sum(
            f.amount_paise for f in c.still_unexplained
        )

    def test_resolved_by_class_sums_to_resolved(self, scenario) -> None:
        """The breakdown under the bars must equal the bar it breaks down."""
        result, _ = scenario
        c = result.correlated
        by_class = sum(v["paise"] for v in c.summary()["resolved_by_class"].values())
        assert by_class == sum(f.amount_paise for f in c.resolved)

    def test_resolved_and_unexplained_partition_the_correlatable_rows(
        self, scenario
    ) -> None:
        """No row may be counted in both, or in neither."""
        result, _ = scenario
        c = result.correlated
        resolved_ids = {id(f) for f in c.resolved}
        unexplained_ids = {id(f) for f in c.still_unexplained}
        assert not (resolved_ids & unexplained_ids)
        assert len(c.resolved) + len(c.still_unexplained) == len(
            [f for f in c.findings if id(f) in resolved_ids | unexplained_ids]
        )

    def test_gain_ratio_matches_its_own_numbers(self, scenario) -> None:
        result, _ = scenario
        c = result.correlated
        if c.unexplained_before_paise:
            expected = c.resolved_paise / c.unexplained_before_paise
            assert abs(c.gain_ratio - expected) < 1e-9


class TestScoreReport:
    def test_recall_matches_its_own_caught_and_missed(self, scenario) -> None:
        result, _ = scenario
        if result.scored is None:
            return
        r = result.scored
        scoreable = r.total_caught + r.total_missed
        if scoreable:
            assert abs(r.recall - r.total_caught / scoreable) < 1e-9

    def test_every_planted_defect_is_in_exactly_one_bucket(self, scenario) -> None:
        """caught / missed / below_tolerance must partition the planted defects."""
        result, batch_dir = scenario
        if result.scored is None:
            return
        from finctl.generate.ground_truth import GroundTruth

        truth = GroundTruth.read(batch_dir / "ground_truth.json")
        bucketed = (
            result.scored.total_caught
            + result.scored.total_missed
            + result.scored.total_below_tolerance
        )
        assert bucketed == len(truth.real_defects)


class TestAuditReconstructibility:
    def test_verdict_lines_are_recomputable_from_the_log(self, scenario) -> None:
        result, _ = scenario
        from_log = {
            e["detail"]["classification"]: e["detail"]["amount_paise"]
            for e in result.audit.events if e["event"] == "verdict_line"
        }
        from_screen = {
            str(line.classification): line.amount_paise for line in result.verdict.lines
        }
        assert from_log == from_screen

    def test_ingest_row_counts_match_the_staged_sources(self, scenario) -> None:
        result, _ = scenario
        for e in result.audit.events:
            if e["event"] != "source_staged":
                continue
            source = Source(e["detail"]["source"])
            assert e["detail"]["rows"] == len(result.batch.get(source))


class TestNoDoubleCounting:
    """The specific failure mode behind the original bug."""

    def test_money_in_the_bank_is_not_also_in_the_gap(self, scenario) -> None:
        """An order that settled AND arrived contributes nothing to the gap.

        This is the invariant the TIMING bug violated.
        """
        result, _ = scenario
        arrived_utrs = {
            s.utr for s in result.matches.settlement_matches if s.matched
        }
        for m in result.matches.order_matches:
            if not m.matched:
                continue
            if all(r.get("settlement_utr") in arrived_utrs for r in m.recon_rows):
                # Its money is inside `received`; only a ledger/settlement disagreement
                # may contribute, never the order amount itself.
                contribution = m.ledger_amount_paise - m.settled_gross_paise + m.fee_paise
                assert abs(contribution) <= m.ledger_amount_paise

    def test_no_order_appears_in_two_gap_components(self, scenario) -> None:
        result, _ = scenario
        from finctl.gap import decompose

        d = decompose(result.matches, result.correlated.findings)
        seen: set[str] = set()
        for component in d.components:
            for order_id in component.order_ids:
                assert order_id not in seen, f"{order_id} counted twice"
                seen.add(order_id)


class TestAdversarialInputsStillBalance:
    """The invariant must hold on malformed input too, not just on clean batches.

    Both bugs below were found by running these cases, not by reasoning about them.
    """

    @pytest.fixture
    def batch_dir(self, tmp_path: Path) -> Path:
        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        return tmp_path

    def test_duplicated_ledger_rows_balance(self, batch_dir: Path) -> None:
        """A real bug the invariant caught: ₹7,305.71 of unattributed residual.

        A duplicated ledger row inflates `expected` with a sale that happened once.
        Razorpay settled it once, so its settlement and fee were being counted per copy
        while only one sale existed. The extra copies are now their own DUPLICATE
        component: phantom expectation, named as such.
        """
        p = batch_dir / "ledger.csv"
        lines = p.read_text().splitlines()
        p.write_text("\n".join(lines + lines[1:6]) + "\n")

        v = run(batch_dir).verdict
        assert sum(line.amount_paise for line in v.lines) + v.residual_paise == v.gap_paise

        from finctl.classify.classifier import Classification
        dup = next(
            line for line in v.lines
            if line.classification is Classification.DUPLICATE
        )
        assert dup.amount_paise > 0   # phantom expectation widens the gap

    def test_a_duplicated_orders_settlement_is_counted_once(self, batch_dir: Path) -> None:
        """The specific double-count: fee charged once, not once per ledger copy."""
        p = batch_dir / "ledger.csv"
        lines = p.read_text().splitlines()
        clean_fees = run(batch_dir).verdict
        from finctl.classify.classifier import Classification
        before = next(
            line.amount_paise for line in clean_fees.lines
            if line.classification is Classification.FEE
        )

        p.write_text("\n".join(lines + lines[1:6]) + "\n")
        after = next(
            line.amount_paise for line in run(batch_dir).verdict.lines
            if line.classification is Classification.FEE
        )
        assert after == before, "duplicating a ledger row must not duplicate its fee"

    def test_an_empty_batch_answers_nothing_to_reconcile(self, batch_dir: Path) -> None:
        """A real bug: two empty CSVs hash identically, so duplicate detection fired.

        BEHAVIOR.md requires "nothing to reconcile" to be a valid answer that survives
        to the verdict stage — not an exception.
        """
        for name in ("ledger.csv", "bank.csv"):
            p = batch_dir / name
            p.write_text(p.read_text().splitlines()[0] + "\n")
        for name in ("settlement_recon.json", "payments.json", "subscriptions.json"):
            (batch_dir / name).write_text('{"entity":"collection","count":0,"items":[]}')

        result = run(batch_dir)
        assert result.verdict.gap_paise == 0
        assert result.verdict.lines == []
        assert result.verdict.headline() == "Nothing needs you this week."
        # And it must not claim a perfect match rate on nothing (ADR-016).
        assert result.matches.pass1_match_rate == 0.0

    def test_a_half_arrived_bank_file_balances(self, batch_dir: Path) -> None:
        """Adversarial: the bank statement arrives late and incomplete."""
        import csv as _csv
        p = batch_dir / "bank.csv"
        rows = list(_csv.DictReader(p.open()))
        with p.open("w", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows[: len(rows) // 2])

        v = run(batch_dir).verdict
        assert sum(line.amount_paise for line in v.lines) + v.residual_paise == v.gap_paise

    def test_renamed_columns_produce_the_same_answer(self, batch_dir: Path) -> None:
        """Mapping must be by name, and must not change any number."""
        import csv as _csv
        before = run(batch_dir).verdict.gap_paise

        p = batch_dir / "ledger.csv"
        rows = list(_csv.DictReader(p.open()))
        with p.open("w", newline="") as fh:
            w = _csv.DictWriter(
                fh, fieldnames=["Order ID", "Gross", "Txn Date", "Buyer ID", "Mode"]
            )
            w.writeheader()
            for r in rows:
                w.writerow({
                    "Order ID": r["order_id"], "Gross": r["amount"],
                    "Txn Date": r["timestamp"], "Buyer ID": r["customer_id"],
                    "Mode": r["payment_method"],
                })
        assert run(batch_dir).verdict.gap_paise == before

    def test_comma_formatted_amounts_produce_the_same_answer(
        self, batch_dir: Path
    ) -> None:
        """Adversarial: amounts as "1,234.50" strings."""
        import csv as _csv
        before = run(batch_dir).verdict.gap_paise

        p = batch_dir / "ledger.csv"
        rows = list(_csv.DictReader(p.open()))
        with p.open("w", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            for r in rows:
                r["amount"] = f"{float(r['amount']):,.2f}"
                w.writerow(r)
        assert run(batch_dir).verdict.gap_paise == before

    def test_a_batch_with_no_bank_file_balances(self, batch_dir: Path) -> None:
        """Two-way reconciliation: everything settled is in-flight by definition."""
        (batch_dir / "bank.csv").unlink()
        v = run(batch_dir).verdict
        assert sum(line.amount_paise for line in v.lines) + v.residual_paise == v.gap_paise


class TestSplitSettlementsAndEarlyRefunds:
    """The two adversarial cases from build-spec 6e that were unverified until now.

    Generating them immediately found a real bug: refund rows DEBIT a settlement, so
    they reduce what the bank received — but pass-1 matching deliberately ignores refund
    rows, so no order-based component could see them. ₹5,421 left the bank unattributed
    and the balance invariant caught it.
    """

    @pytest.fixture
    def result(self, tmp_path: Path):
        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        return run(tmp_path), tmp_path

    def test_a_split_settlement_reports_no_discrepancy(self, result) -> None:
        """Legitimate Razorpay behaviour. Reporting it would be a false positive.

        Getting this right is harder than reporting a problem: the engine must see two
        settlement rows for one order and conclude nothing is wrong.
        """
        pipeline, batch_dir = result
        from finctl.generate.ground_truth import DefectType, GroundTruth

        truth = GroundTruth.read(batch_dir / "ground_truth.json")
        splits = {d.order_id for d in truth.by_type(DefectType.SPLIT_SETTLEMENT)}
        assert splits, "the demo profile must plant split settlements"

        by_order = {m.order_id: m for m in pipeline.matches.order_matches}
        for order_id in splits:
            m = by_order[order_id]
            assert len(m.recon_rows) == 2, "both legs must be recorded"
            assert m.is_split
            assert m.gap_paise == 0, "the two legs must sum to the ledger amount"

    def test_split_settlements_produce_no_false_positive(self, result) -> None:
        pipeline, batch_dir = result
        from finctl.classify.classifier import Classification
        from finctl.generate.ground_truth import DefectType, GroundTruth

        truth = GroundTruth.read(batch_dir / "ground_truth.json")
        splits = {d.order_id for d in truth.by_type(DefectType.SPLIT_SETTLEMENT)}
        for f in pipeline.correlated.findings:
            if f.order_id in splits:
                assert f.classification is Classification.RECONCILED

    def test_a_refund_that_settled_early_is_still_reported(self, result) -> None:
        """A refund dated BEFORE the payment it reverses.

        The debit lands in an earlier settlement than the credit, so a naive
        per-settlement view shows money leaving before it arrived. It must still be
        classified REFUND rather than silently netted away.
        """
        pipeline, batch_dir = result
        from finctl.classify.classifier import Classification
        from finctl.generate.ground_truth import DefectType, GroundTruth

        truth = GroundTruth.read(batch_dir / "ground_truth.json")
        early = {d.order_id for d in truth.by_type(DefectType.EARLY_REFUND)}
        assert early

        found = {
            f.order_id for f in pipeline.correlated.findings
            if f.classification is Classification.REFUND
        }
        assert early <= found, f"early refunds not reported: {early - found}"

    def test_the_early_refund_proof_names_the_inversion(self, result) -> None:
        """The merchant should be told WHY this one looks strange."""
        pipeline, batch_dir = result
        from finctl.classify.classifier import Classification
        from finctl.generate.ground_truth import DefectType, GroundTruth

        truth = GroundTruth.read(batch_dir / "ground_truth.json")
        early = {d.order_id for d in truth.by_type(DefectType.EARLY_REFUND)}
        proofs = [
            f.proof for f in pipeline.correlated.findings
            if f.order_id in early and f.classification is Classification.REFUND
        ]
        assert proofs
        assert any(p.get("settled_before_the_payment") for p in proofs)

    def test_refund_debits_are_accounted_for_in_the_gap(self, result) -> None:
        """The bug the invariant caught: money debited from a settlement is money that
        left the bank, and something must account for it."""
        pipeline, _ = result
        v = pipeline.verdict
        assert sum(line.amount_paise for line in v.lines) + v.residual_paise == v.gap_paise

    def test_both_refund_mechanisms_merge_into_one_line(self, result) -> None:
        """A one-sided refund (negative) and a settled refund (positive) are both
        REFUND to a merchant. Two components with one classification would silently
        drop one when the ranker looks them up by name."""
        pipeline, _ = result
        from finctl.classify.classifier import Classification
        refund_lines = [
            line for line in pipeline.verdict.lines
            if line.classification is Classification.REFUND
        ]
        assert len(refund_lines) <= 1


class TestHandEditedLedger:
    """Defects a human introduced by editing the CSV, not ones a generator planted.

    Found a real bug on first contact: deleting two ledger rows left ₹16,992.29
    unaccounted for. The matcher had detected the orphaned settlements all along
    (`unmatched_recon_orders`); the decomposition simply never consumed them.

    No generated defect had ever produced this shape. Every planted defect removes money
    or moves it — none had ever left money SETTLED with no ledger row behind it, because
    the generator writes the ledger first and derives everything else from it. That is
    the structural blind spot hand-editing exists to find.
    """

    @pytest.fixture
    def batch_dir(self, tmp_path: Path) -> Path:
        write_batch(Generator(load_config(), seed=20260902, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        return tmp_path

    def _delete_ledger_rows(self, batch_dir: Path, data_rows: list[int]) -> list[str]:
        """Delete 1-indexed DATA rows (header excluded). Returns the deleted order ids."""
        p = batch_dir / "ledger.csv"
        lines = p.read_text().splitlines()
        deleted = []
        for n in sorted(data_rows, reverse=True):   # descending keeps indices valid
            deleted.append(lines[n].split(",")[0])
            del lines[n]
        p.write_text("\n".join(lines) + "\n")
        return deleted

    def test_deleting_ledger_rows_still_balances(self, batch_dir: Path) -> None:
        self._delete_ledger_rows(batch_dir, [10, 19])
        v = run(batch_dir).verdict
        assert sum(line.amount_paise for line in v.lines) + v.residual_paise == v.gap_paise

    def test_a_deleted_order_becomes_an_unexpected_settlement(
        self, batch_dir: Path
    ) -> None:
        """Razorpay settled a sale the merchant has no record of. That is an exception
        in its own right — money arriving unexplained is as notable as money missing."""
        from finctl.classify.classifier import Classification

        deleted = set(self._delete_ledger_rows(batch_dir, [10, 19]))
        v = run(batch_dir).verdict
        line = next(
            line for line in v.lines
            if line.classification is Classification.UNEXPECTED_SETTLEMENT
        )
        assert line.count == len(deleted)

    def test_an_unexpected_settlement_narrows_the_gap(self, batch_dir: Path) -> None:
        """The money reached the bank and is inside `received`, but nothing in
        `expected` claims it. So it must be NEGATIVE."""
        from finctl.classify.classifier import Classification

        self._delete_ledger_rows(batch_dir, [10, 19])
        v = run(batch_dir).verdict
        line = next(
            line for line in v.lines
            if line.classification is Classification.UNEXPECTED_SETTLEMENT
        )
        assert line.amount_paise < 0

    def test_the_orphan_amount_equals_what_was_actually_settled(
        self, batch_dir: Path
    ) -> None:
        """Exact, not approximate: the net credit of the orphaned settlement rows.

        Disputed rows are excluded from the expectation, because their credit never
        reached the bank — Razorpay withholds it pending the outcome. Counting it as
        money that arrived would narrow the gap by an amount the merchant never got.
        One of the deleted rows here happens to be a disputed order, which is how that
        distinction was found. See ADR-041.
        """
        from finctl.classify.classifier import Classification

        self._delete_ledger_rows(batch_dir, [10, 19])
        result = run(batch_dir)
        expected = sum(
            row.get("credit", 0) - row.get("debit", 0)
            for row in result.matches.unmatched_recon_orders
            if not row.get("dispute_id")
        )
        line = next(
            line for line in result.verdict.lines
            if line.classification is Classification.UNEXPECTED_SETTLEMENT
        )
        assert line.amount_paise == -expected

    def test_inflating_a_ledger_amount_is_unexplained_not_a_refund(
        self, batch_dir: Path
    ) -> None:
        """The ledger claims more than Razorpay settled: a shortfall.

        This is the sign trap from ADR-024 in the opposite direction. A refund means the
        bank got MORE than the books expected; a shortfall means money never arrived.
        Labelling it REFUND would tell a merchant they refunded a customer they did not.
        """
        from finctl.classify.classifier import Classification

        # Pick a row the generator left CLEAN. Inflating one that already carries a
        # one-sided refund only shrinks that existing negative gap, so it stays REFUND —
        # correctly. My first attempt at this test picked such a row and blamed the
        # engine for being right.
        baseline = run(batch_dir)
        clean = {
            f.order_id for f in baseline.correlated.findings
            if f.classification is Classification.RECONCILED
        }

        p = batch_dir / "ledger.csv"
        lines = p.read_text().splitlines()
        target = next(
            i for i, line in enumerate(lines[1:], start=1)
            if line.split(",")[0] in clean
        )
        parts = lines[target].split(",")
        order_id, original = parts[0], float(parts[1])
        parts[1] = f"{original + 1149:.2f}"
        lines[target] = ",".join(parts)
        p.write_text("\n".join(lines) + "\n")

        result = run(batch_dir)
        finding = next(
            f for f in result.correlated.findings if f.order_id == order_id
        )
        assert finding.classification is Classification.UNEXPLAINED
        assert finding.amount_paise == 114900

    def test_several_hand_edits_at_once_still_balance(self, batch_dir: Path) -> None:
        """The combination, as a human would actually make it."""
        p = batch_dir / "ledger.csv"
        lines = p.read_text().splitlines()
        parts = lines[15].split(",")
        parts[1] = "3456.00"
        lines[15] = ",".join(parts)
        del lines[19]
        del lines[10]
        p.write_text("\n".join(lines) + "\n")

        v = run(batch_dir).verdict
        assert sum(line.amount_paise for line in v.lines) + v.residual_paise == v.gap_paise


class TestMoreHandEdits:
    """A second round of human edits: a renamed header, a duplicated row, a zeroed
    amount. Each probes a different structural assumption.

    The zeroed amount found a real misclassification: a ledger amount of 0 was reported
    as a REFUND, telling a merchant they had refunded a customer they never refunded.
    """

    @pytest.fixture
    def batch_dir(self, tmp_path: Path) -> Path:
        write_batch(Generator(load_config(), seed=4242, volume=200,
                              defect_profile="demo").generate(), tmp_path)
        return tmp_path

    def test_a_renamed_header_changes_no_number(self, batch_dir: Path) -> None:
        """ADR-015: mapping is by name, never positional. So a rename that resolves
        through the alias table must be completely invisible in the output."""
        before = run(batch_dir).verdict.gap_paise

        p = batch_dir / "ledger.csv"
        lines = p.read_text().splitlines()
        lines[0] = lines[0].replace("payment_method", "Mode")
        p.write_text("\n".join(lines) + "\n")

        after = run(batch_dir)
        assert after.verdict.gap_paise == before
        # And the audit trail must record which column was actually read, so a merchant
        # disputing a number can see it.
        mapping = after.batch.manifest()["sources"]["ledger"]["column_mapping"]
        assert "'Mode'->payment_method" in mapping

    def test_an_unmappable_header_raises_rather_than_guessing(
        self, batch_dir: Path
    ) -> None:
        """The other half of the same rule: a rename we cannot resolve must fail loudly."""
        from finctl.normalize.normalizer import NormalizationError

        p = batch_dir / "ledger.csv"
        lines = p.read_text().splitlines()
        lines[0] = lines[0].replace("order_id", "widget_code")
        p.write_text("\n".join(lines) + "\n")

        with pytest.raises(NormalizationError, match="Refusing to guess"):
            run(batch_dir)

    def test_a_duplicated_row_is_phantom_expectation(self, batch_dir: Path) -> None:
        """The sale happened once; the books claim it twice. The extra copy widens the
        gap and is named, rather than being netted away (ADR-025)."""
        from finctl.classify.classifier import Classification

        p = batch_dir / "ledger.csv"
        lines = p.read_text().splitlines()
        duplicated = lines[67]
        order_id, amount = duplicated.split(",")[0], duplicated.split(",")[1]
        lines.insert(68, duplicated)
        p.write_text("\n".join(lines) + "\n")

        v = run(batch_dir).verdict
        line = next(
            line for line in v.lines
            if line.classification is Classification.DUPLICATE
        )
        assert line.amount_paise == round(float(amount) * 100)
        assert line.amount_paise > 0
        assert sum(x.amount_paise for x in v.lines) + v.residual_paise == v.gap_paise
        assert order_id  # the duplicated order is identifiable

    def test_a_zero_ledger_amount_is_not_called_a_refund(self, batch_dir: Path) -> None:
        """THE bug this round found.

        A ledger amount of 0 against a real settlement is a data-entry error, not a
        partial refund. Reporting it as REFUND tells a merchant they refunded a customer
        they never refunded — a false statement, which is worse than an unexplained one.

        The generator never produces a zero-value order, so no synthetic case could
        reach this branch.
        """
        from finctl.classify.classifier import Classification

        p = batch_dir / "ledger.csv"
        lines = p.read_text().splitlines()
        parts = lines[69].split(",")
        order_id = parts[0]
        parts[1] = "0.00"
        lines[69] = ",".join(parts)
        p.write_text("\n".join(lines) + "\n")

        result = run(batch_dir)
        finding = next(f for f in result.correlated.findings if f.order_id == order_id)
        assert finding.classification is Classification.UNEXPLAINED
        assert "data-entry error" in finding.proof["interpretation"]

    def test_a_genuine_partial_refund_is_still_a_refund(self, batch_dir: Path) -> None:
        """Guard the fix from over-reaching: a normal one-sided refund must be unaffected."""
        from finctl.classify.classifier import Classification

        result = run(batch_dir)
        refunds = [
            f for f in result.correlated.findings
            if f.classification is Classification.REFUND
        ]
        assert refunds, "the demo profile plants one-sided refunds"

    def test_all_three_edits_together_still_balance(self, batch_dir: Path) -> None:
        p = batch_dir / "ledger.csv"
        lines = p.read_text().splitlines()
        lines[0] = lines[0].replace("payment_method", "Mode")
        parts = lines[69].split(",")
        parts[1] = "0.00"
        lines[69] = ",".join(parts)
        lines.insert(68, lines[67])
        p.write_text("\n".join(lines) + "\n")

        v = run(batch_dir).verdict
        assert sum(line.amount_paise for line in v.lines) + v.residual_paise == v.gap_paise
