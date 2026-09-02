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
        assert total + v.unexplained_paise == v.gap_paise, (
            f"lines sum to {total} + residual {v.unexplained_paise}, "
            f"but the gap is {v.gap_paise}"
        )

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
        result, _ = scenario
        for line in result.verdict.lines:
            behind = [
                f for f in result.correlated.findings
                if f.classification is line.classification
            ]
            if behind:
                assert line.count == len(behind), (
                    f"{line.classification}: screen says {line.count}, "
                    f"{len(behind)} findings exist"
                )

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
        assert sum(line.amount_paise for line in v.lines) + v.unexplained_paise == v.gap_paise

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
        assert sum(line.amount_paise for line in v.lines) + v.unexplained_paise == v.gap_paise

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
        assert sum(line.amount_paise for line in v.lines) + v.unexplained_paise == v.gap_paise
