"""The action list. ADR-048.

The verdict says "those 6 customers" and, until this module, could not name them. That
is the gap between an insight and a tool.

Nothing here is computed — every field is lifted from a finding's proof — so the tests
that matter are about whether the list can DISAGREE with the verdict, and whether a
merchant is handed enough to act.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from finctl.actions import CSV_COLUMNS, NEXT_STEP, build, to_csv
from finctl.classify.classifier import BENIGN, Classification, Finding
from finctl.config.loader import load_config
from finctl.generate.generator import Generator
from finctl.generate.writer import write_batch
from finctl.pipeline import run


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    write_batch(Generator(load_config(), seed=20260902, volume=200,
                          defect_profile="demo").generate(), out)
    return run(out)


class TestItNamesWhatTheVerdictCounts:
    def test_the_headline_customers_are_actually_listed(self, result) -> None:
        """THE point. "those 6 customers" must become six named rows."""
        halted = [g for g in result.actions
                  if g.classification is Classification.HALTED_SUBSCRIPTION]
        assert halted, "the demo batch must produce halted subscriptions"
        items = halted[0].items
        assert len(items) == 6
        assert all(i.customer_id for i in items)
        assert all(i.subscription_id for i in items)

    def test_every_actionable_finding_reaches_the_list(self, result) -> None:
        """A finding the engine made and the list drops is money silently lost."""
        actionable = [f for f in result.correlated.findings
                      if f.classification not in BENIGN]
        listed = sum(len(g.items) for g in result.actions)
        assert listed == len(actionable)

    def test_the_totals_match_the_findings(self, result) -> None:
        """A projection that disagrees with its source is worse than no projection."""
        expected = sum(f.amount_paise for f in result.correlated.findings
                       if f.classification not in BENIGN)
        assert sum(g.total_paise for g in result.actions) == expected

    def test_benign_lines_are_absent(self, result) -> None:
        """A merchant asking "what needs me?" is not asking about the fee they agreed to."""
        assert all(g.classification not in BENIGN for g in result.actions)

    def test_groups_are_largest_first(self, result) -> None:
        totals = [g.total_paise for g in result.actions]
        assert totals == sorted(totals, reverse=True)

    def test_items_within_a_group_are_largest_first(self, result) -> None:
        """If a merchant only does some of this, they should do the expensive ones."""
        for group in result.actions:
            amounts = [i.amount_paise for i in group.items]
            assert amounts == sorted(amounts, reverse=True)

    def test_every_order_backed_row_names_a_customer(self, result) -> None:
        """The ledger names the buyer on every row; only correlation was surfacing it.

        Without the ledger fallback the list could name the customer behind a halted
        subscription and not the one behind a failed payment — precisely backwards,
        since the failed payment is the one you email today.

        Scoped to rows that HAVE an order: a settlement-side refund carries no order_id
        by definition (ADR-039), so there is no buyer to name and claiming one would be
        an invention. Those rows lead with their `rfnd_…` id instead.
        """
        for group in result.actions:
            for item in group.items:
                if item.order_id:
                    assert item.customer_id, f"{item.order_id} has no customer"

    def test_a_row_with_no_order_still_identifies_itself(self, result) -> None:
        """An action a merchant cannot locate is not an action."""
        for group in result.actions:
            for item in group.items:
                assert item.order_id or item.payment_id or item.subscription_id or (
                    item.classification is Classification.UNRECORDED_REFUND
                ), f"{item.classification} row identifies nothing"


class TestEveryCauseTellsYouWhatToDo:
    def test_each_group_carries_an_instruction(self, result) -> None:
        for group in result.actions:
            assert group.next_step
            assert group.next_step != "Needs a look.", (
                f"{group.classification} has no specific next step"
            )

    @pytest.mark.parametrize("classification", sorted(
        set(Classification) - BENIGN - {Classification.RECONCILED},
        key=str,
    ))
    def test_every_actionable_classification_has_a_next_step(
        self, classification: Classification
    ) -> None:
        """A cause the engine can report and cannot advise on is a dead end."""
        assert classification in NEXT_STEP, f"{classification} has no next step"

    def test_the_instruction_is_imperative_not_a_category(self) -> None:
        """"Email these customers" is an instruction; "review subscriptions" is a label."""
        step = NEXT_STEP[Classification.HALTED_SUBSCRIPTION]
        assert step.startswith("Email")
        assert "will not restart on its own" in step


class TestCsv:
    def test_it_parses_as_csv_with_the_promised_columns(self, result) -> None:
        rows = list(csv.DictReader(io.StringIO(to_csv(result.actions))))
        assert rows
        assert tuple(rows[0]) == CSV_COLUMNS

    def test_it_has_one_row_per_item(self, result) -> None:
        rows = list(csv.DictReader(io.StringIO(to_csv(result.actions))))
        assert len(rows) == sum(len(g.items) for g in result.actions)

    def test_amounts_are_rupees_not_paise(self, result) -> None:
        """`87600` under a column headed "amount" invites a very expensive misread."""
        rows = list(csv.DictReader(io.StringIO(to_csv(result.actions))))
        items = [i for g in result.actions for i in g.items]
        # Row order is preserved by to_csv, so zip rather than keying on order_id —
        # a settlement-side refund has none (ADR-039).
        assert len(rows) == len(items)
        for row, item in zip(rows, items, strict=True):
            assert float(row["amount_rupees"]) == pytest.approx(item.amount_paise / 100)

    def test_every_row_carries_its_instruction(self, result) -> None:
        """The file must be useful to someone who never saw the screen."""
        rows = list(csv.DictReader(io.StringIO(to_csv(result.actions))))
        assert all(row["next_step"] for row in rows)

    def test_an_empty_list_still_produces_a_header(self) -> None:
        """A clean batch yields a valid empty file, not a blank one."""
        body = to_csv([])
        assert body.strip() == ",".join(CSV_COLUMNS)


class TestEdges:
    def test_a_clean_batch_has_nothing_to_do(self, tmp_path: Path) -> None:
        write_batch(Generator(load_config(), seed=5, volume=100,
                              defect_profile="clean").generate(), tmp_path)
        assert run(tmp_path).actions == []

    def test_a_finding_with_no_order_id_still_appears(self) -> None:
        """UNRECORDED_REFUND has no order_id by definition (ADR-039)."""
        groups = build([Finding(
            order_id=None,
            classification=Classification.UNRECORDED_REFUND,
            amount_paise=100_000,
            proof={"entity_id": "rfnd_X"},
        )])
        assert len(groups) == 1
        assert groups[0].items[0].order_id is None
        assert groups[0].items[0].amount_paise == 100_000

    def test_the_ledger_never_overrides_a_correlated_customer(self) -> None:
        """Correlation resolved a customer through the subscription join. It is better."""
        groups = build(
            [Finding(order_id="O1", classification=Classification.HALTED_SUBSCRIPTION,
                     amount_paise=100,
                     proof={"correlation": {"customer_id": "cust_from_correlation"}})],
            [{"order_id": "O1", "customer_id": "cust_from_ledger"}],
        )
        assert groups[0].items[0].customer_id == "cust_from_correlation"

    def test_razorpays_own_contact_fields_are_used_when_present(self) -> None:
        """Our generator has no email; Razorpay's real payments export does."""
        groups = build([Finding(
            order_id="O1", classification=Classification.PAYMENT_FAILED,
            amount_paise=100,
            proof={"correlation": {"email": "gaurav.kumar@example.com",
                                   "contact": "919900990099"}},
        )])
        item = groups[0].items[0]
        assert item.email == "gaurav.kumar@example.com"
        assert item.contact == "919900990099"
