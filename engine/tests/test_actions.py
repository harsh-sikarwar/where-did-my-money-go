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
        """A finding the engine made and the list drops is money silently lost.

        "Actionable" is the VERDICT's judgement, not `not in BENIGN`. The two are
        different rules and this test used to assert the coarser one: `tolerances.yaml`
        also marks REFUND and DUPLICATE `always_benign` ("a bookkeeping divergence to
        reconcile, not a this-week action"), and materiality can demote a finding
        besides. Asserting the coarse rule required the action list to carry rows the
        verdict called benign, so the two screens disagreed about whether ₹2,244 of
        DUPLICATE needed the merchant this week — the exact class of disagreement
        ADR-053 exists to prevent. ADR-054.

        What must hold is that nothing the verdict counts as work is dropped here.
        """
        actionable = {
            line.classification for line in result.verdict.lines if line.actionable
        }
        expected = [f for f in result.correlated.findings
                    if f.classification in actionable]
        listed = sum(len(g.items) for g in result.actions)
        assert listed == len(expected)
        # ...and nothing the verdict calls benign is presented as work.
        assert all(g.classification in actionable for g in result.actions)

    def test_the_totals_match_the_verdict(self, result) -> None:
        """A projection that disagrees with the verdict is worse than no projection.

        This test previously asserted the totals matched `sum(finding.amount_paise)`,
        which is the quantity `gap.py` exists to say is meaningless — it means a fee
        delta for FEE, a whole order for HALTED_SUBSCRIPTION, and a magnitude whose sign
        is negative for REFUND. So the test passed while the action list and the verdict
        screen showed different numbers for the same batch. The test was enforcing the
        bug. See ADR-053.
        """
        verdict_by_class = {
            line.classification: line.amount_paise for line in result.verdict.lines
        }
        for group in result.actions:
            assert group.classification in verdict_by_class, (
                f"{group.classification} is on the action list but not the verdict"
            )
            assert group.total_paise == verdict_by_class[group.classification], (
                f"{group.classification}: action list says {group.total_paise}, "
                f"verdict says {verdict_by_class[group.classification]}"
            )

    def test_the_actionable_total_matches_the_verdict(self, result) -> None:
        """The headline number a merchant acts on, from both screens.

        The docstring on `actions.py` claims this module "cannot disagree with the
        verdict it accompanies". Until ADR-053 that was aspirational. This is the
        assertion that makes it true.
        """
        actionable = {
            line.classification for line in result.verdict.lines if line.actionable
        }
        listed = sum(
            g.total_paise for g in result.actions if g.classification in actionable
        )
        assert listed == result.verdict.actionable_paise

    def test_items_sum_to_their_group(self, result) -> None:
        """The parts must sum to the whole, in every group without exception."""
        for group in result.actions:
            assert sum(i.amount_paise for i in group.items) == group.total_paise, (
                f"{group.classification}: items do not sum to the group total"
            )

    def test_no_actionable_row_reads_zero(self, result) -> None:
        """A row a merchant is told to act on must say what is at stake.

        The ₹0.00 chargeback is the worst single output this product can produce: a
        DISPUTED row carries a statutory response deadline, and a merchant shown ₹0.00
        closes the tab. It came from summing a netted credit; the refund groups then
        reproduced it one component further down, where the gap decomposition tracked
        the money in aggregate and named no orders. Both are ADR-053.
        """
        for group in result.actions:
            for item in group.items:
                assert item.amount_paise != 0, (
                    f"{group.classification} row {item.order_id} reads zero"
                )

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


class TestFormulaInjection:
    """A merchant-supplied string must not execute when the CSV is opened.

    `to_csv`'s whole argument is that the file gets opened in a spreadsheet. That makes
    `reason`, `email` and `customer_id` — all merchant- or PSP-supplied — an injection
    path: Excel, LibreOffice and Sheets treat a leading =, +, - or @ as a formula.
    """

    def _row(self, reason: str) -> dict[str, str]:
        groups = build([
            Finding(
                order_id="ORD-1",
                classification=Classification.DISPUTED,
                amount_paise=100_000,
                proof={"dispute_reason": reason},
            )
        ])
        return next(iter(csv.DictReader(io.StringIO(to_csv(groups)))))

    @pytest.mark.parametrize(
        "payload",
        [
            "=cmd|'/c calc'!A1",
            "+1+1",
            "-2+3",
            "@SUM(A1)",
            "\t=SUM(A1)",
            " =HYPERLINK('http://evil','click')",
        ],
    )
    def test_a_formula_is_neutralised(self, payload: str) -> None:
        value = self._row(payload)["reason"]
        assert not value.lstrip("\t\r\n ").startswith(("=", "+", "-", "@"))
        assert value.startswith("'")

    @pytest.mark.parametrize(
        "benign",
        ["card_declined", "a@b.com", "ORD-123", "Refund - duplicate", "insufficient funds"],
    )
    def test_ordinary_values_are_left_alone(self, benign: str) -> None:
        """Quoting everything would be safe and unreadable. Only formulas get quoted."""
        assert self._row(benign)["reason"] == benign

    def test_the_payload_is_preserved_not_stripped(self) -> None:
        """Defusing must not edit the merchant's own data — only prefix it."""
        payload = "=1+1"
        assert self._row(payload)["reason"] == "'" + payload


class TestTheMerchantCanActuallyContactThem:
    """"Email these customers a new payment link" must come with an email. ADR-052.

    The verdict's whole promise is "here are the six customers to chase". Until this,
    the list named them with `cust_…` ids and no address, so the single most important
    instruction in the product was not executable — a list rather than a tool.
    """

    def test_every_chaseable_row_has_a_way_to_reach_the_customer(self, result) -> None:
        """The classifications whose next step is to contact a person."""
        chaseable = {
            Classification.HALTED_SUBSCRIPTION,
            Classification.PAYMENT_FAILED,
        }
        rows = [
            item
            for group in result.actions if group.classification in chaseable
            for item in group.items
        ]
        assert rows, "the demo batch must produce chaseable rows"
        for item in rows:
            assert item.email, f"{item.order_id} has no email to write to"
            assert item.contact, f"{item.order_id} has no phone number"

    def test_the_halted_customers_are_reachable(self, result) -> None:
        """THE headline: "those 6 customers" must be six people you can email."""
        halted = next(
            g for g in result.actions
            if g.classification is Classification.HALTED_SUBSCRIPTION
        )
        assert len(halted.items) == 6
        assert all("@" in (i.email or "") for i in halted.items)

    def test_contact_details_reach_the_csv(self, result) -> None:
        """The export is where the work leaves the screen; empty columns defeat it."""
        rows = list(csv.DictReader(io.StringIO(to_csv(result.actions))))
        chaseable = [
            r for r in rows
            if r["what"] in ("HALTED_SUBSCRIPTION", "PAYMENT_FAILED")
        ]
        assert chaseable
        assert all(r["email"] and r["contact"] for r in chaseable)

    def test_one_customer_has_one_address_across_every_source(self, result) -> None:
        """A customer whose email differed per source would make a right join look wrong.

        The address is derived from `customer_id`, so the ledger, the payments feed and
        the subscriptions feed necessarily agree. Asserted rather than assumed: it is the
        property that makes the join trustworthy.
        """
        by_customer: dict[str, set[str]] = {}
        for group in result.actions:
            for item in group.items:
                if item.customer_id and item.email:
                    by_customer.setdefault(item.customer_id, set()).add(item.email)
        assert by_customer
        for customer, emails in by_customer.items():
            assert len(emails) == 1, f"{customer} has {len(emails)} different emails"

    def test_synthetic_addresses_can_never_route(self, result) -> None:
        """`.invalid` is reserved by RFC 2606.

        Demo data that could reach a real inbox is one accidental send away from a
        problem, and this file gets handed to people.
        """
        for group in result.actions:
            for item in group.items:
                if item.email:
                    assert item.email.endswith("@example.invalid")

    def test_a_ledger_without_contact_columns_still_reconciles(self, tmp_path) -> None:
        """Email and contact are OPTIONAL, and a real merchant export may lack them.

        Making them required would turn a nice-to-have into a reason a merchant cannot
        use the tool at all.
        """
        out = tmp_path / "bare"
        write_batch(
            Generator(load_config(), seed=20260902, volume=200,
                      defect_profile="demo").generate(),
            out,
        )
        ledger = out / "ledger.csv"
        rows = list(csv.DictReader(ledger.read_text().splitlines()))
        kept = [
            {k: v for k, v in row.items() if k not in ("email", "contact")}
            for row in rows
        ]
        with ledger.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(kept[0]))
            writer.writeheader()
            writer.writerows(kept)

        result = run(out)
        assert result.verdict.gap_paise != 0
        halted = next(
            g for g in result.actions
            if g.classification is Classification.HALTED_SUBSCRIPTION
        )
        # The customer is still named through the subscription join; only the address
        # is gone, which is exactly the pre-ADR-052 behaviour rather than a failure.
        assert all(i.customer_id for i in halted.items)
        assert all(i.email is None for i in halted.items)
