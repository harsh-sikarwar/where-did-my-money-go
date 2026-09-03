"""Two-pass matcher.

  Pass 1  Order -> PSP   "did each sale reach Razorpay?"
  Pass 2  PSP -> Bank    "did Razorpay's payout reach the bank?"

Two passes rather than one join, because the answer a merchant needs is not "there is a
gap" but "the gap is on THIS leg". A single ledger-to-bank join can tell you the money
is missing; it cannot tell you whether the sale never reached Razorpay or Razorpay never
paid out. Those have different causes and different fixes.

BEHAVIOR.md, stage `match`:
  Refuses   — to fuzzy-match on amount or timestamp proximity. Matching is on
              IDENTIFIERS. An amount-based near-match is a guess wearing a confidence
              score, and it is how reconciliation tools produce confident nonsense.
  Bad input — split settlements are recorded and flagged, not treated as errors;
              duplicate order ids are flagged rather than silently deduplicated;
              a 0% match rate is reported loudly rather than summarised into plausibility.

ADR-008 governs the join keys. On recon rows of type "payment" the payment id lives in
`entity_id` and `payment_id` is NULL — joining on `payment_id` would match nothing and
report every order as missing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from finctl.normalize.normalizer import to_date
from finctl.schema import ReconType, Source
from finctl.stage.staging import StagedBatch


@dataclass
class OrderMatch:
    """One ledger order and everything found for it on the PSP side.

    `recon_rows` is a list because a single order can legitimately settle across two
    settlements (partial settlement, an adversarial case from build-spec 6e).
    """

    order_id: str
    ledger_row: dict[str, Any]
    recon_rows: list[dict[str, Any]] = field(default_factory=list)
    # Refund rows are kept SEPARATE from recon_rows, not merged into them. Pass-1
    # matching must not treat a refund as evidence a sale reached Razorpay, but the
    # classifier does need to see that money went back out — those are different
    # questions and were conflated until the "refund before the original settled"
    # case was generated.
    refund_rows: list[dict[str, Any]] = field(default_factory=list)
    payment_row: dict[str, Any] | None = None
    is_duplicate_order_id: bool = False

    @property
    def ledger_amount_paise(self) -> int:
        return self.ledger_row["amount_paise"]

    @property
    def settled_gross_paise(self) -> int:
        """Gross amount Razorpay recorded, summed across any split settlements."""
        return sum(r["amount"] for r in self.recon_rows)

    @property
    def settled_net_paise(self) -> int:
        """Net credited, after fees. Debits (refunds) subtract."""
        return sum(r["credit"] - r["debit"] for r in self.recon_rows)

    @property
    def refunded_paise(self) -> int:
        """Money Razorpay debited from a settlement to return to a customer."""
        return sum(r.get("debit", 0) for r in self.refund_rows)

    @property
    def fee_paise(self) -> int:
        return sum(r["fee"] for r in self.recon_rows)

    @property
    def tax_paise(self) -> int:
        return sum(r["tax"] for r in self.recon_rows)

    @property
    def matched(self) -> bool:
        return bool(self.recon_rows)

    @property
    def is_split(self) -> bool:
        """Settled across more than one settlement. Legitimate, but worth naming."""
        return len({r["settlement_id"] for r in self.recon_rows}) > 1

    @property
    def gap_paise(self) -> int:
        """Ledger expectation minus what Razorpay recorded as gross.

        Non-zero means the sale and the PSP disagree about the amount itself, which is
        a different problem from fees — fees are a difference between gross and net.
        """
        return self.ledger_amount_paise - self.settled_gross_paise


@dataclass
class SettlementMatch:
    """One settlement and the bank credit that should correspond to it."""

    settlement_id: str
    utr: str
    recon_rows: list[dict[str, Any]] = field(default_factory=list)
    bank_row: dict[str, Any] | None = None

    @property
    def expected_credit_paise(self) -> int:
        return sum(r["credit"] - r["debit"] for r in self.recon_rows)

    @property
    def actual_credit_paise(self) -> int:
        return self.bank_row["credit_paise"] if self.bank_row else 0

    @property
    def matched(self) -> bool:
        return self.bank_row is not None

    @property
    def gap_paise(self) -> int:
        return self.expected_credit_paise - self.actual_credit_paise


@dataclass
class MatchResult:
    """Both passes, plus the leftovers each one could not account for."""

    order_matches: list[OrderMatch] = field(default_factory=list)
    settlement_matches: list[SettlementMatch] = field(default_factory=list)

    # Rows present on one side with no counterpart on the other. Kept rather than
    # dropped: an unexpected settlement is as interesting as a missing one.
    unmatched_recon_orders: list[dict[str, Any]] = field(default_factory=list)
    unmatched_bank_rows: list[dict[str, Any]] = field(default_factory=list)
    duplicate_order_ids: dict[str, int] = field(default_factory=dict)

    # ---- Pass 1 metrics ----
    @property
    def pass1_total(self) -> int:
        return len(self.order_matches)

    @property
    def pass1_matched(self) -> int:
        return sum(1 for m in self.order_matches if m.matched)

    @property
    def pass1_match_rate(self) -> float:
        """Fraction of ledger orders found on the PSP side.

        Zero orders returns 0.0, not 1.0. An empty batch has not achieved a perfect
        match rate; it has nothing to say, and claiming 100% would be a lie of the kind
        that reads well on a slide.
        """
        return self.pass1_matched / self.pass1_total if self.pass1_total else 0.0

    # ---- Pass 2 metrics ----
    @property
    def pass2_total(self) -> int:
        return len(self.settlement_matches)

    @property
    def pass2_matched(self) -> int:
        return sum(1 for m in self.settlement_matches if m.matched)

    @property
    def pass2_match_rate(self) -> float:
        return self.pass2_matched / self.pass2_total if self.pass2_total else 0.0

    # ---- money ----
    @property
    def expected_paise(self) -> int:
        """What the merchant's ledger says they sold."""
        return sum(m.ledger_amount_paise for m in self.order_matches)

    @property
    def received_paise(self) -> int:
        """What the bank statement says actually arrived."""
        return sum(m.actual_credit_paise for m in self.settlement_matches) + sum(
            r["credit_paise"] for r in self.unmatched_bank_rows
        )

    @property
    def gap_paise(self) -> int:
        """The headline number: expected minus received."""
        return self.expected_paise - self.received_paise

    def unmatched_orders(self) -> list[OrderMatch]:
        """Orders with no PSP record. The input to classification and correlation."""
        return [m for m in self.order_matches if not m.matched]

    def summary(self) -> dict[str, Any]:
        return {
            "pass1": {
                "leg": "Order -> PSP",
                "question": "did each sale reach Razorpay?",
                "total": self.pass1_total,
                "matched": self.pass1_matched,
                "unmatched": self.pass1_total - self.pass1_matched,
                "match_rate": round(self.pass1_match_rate, 4),
            },
            "pass2": {
                "leg": "PSP -> Bank",
                "question": "did Razorpay's payout reach the bank?",
                "total": self.pass2_total,
                "matched": self.pass2_matched,
                "unmatched": self.pass2_total - self.pass2_matched,
                "match_rate": round(self.pass2_match_rate, 4),
            },
            "money": {
                "expected_paise": self.expected_paise,
                "received_paise": self.received_paise,
                "gap_paise": self.gap_paise,
            },
            "anomalies": {
                "duplicate_order_ids": self.duplicate_order_ids,
                "split_settlements": sum(1 for m in self.order_matches if m.is_split),
                "unmatched_recon_orders": len(self.unmatched_recon_orders),
                "unmatched_bank_rows": len(self.unmatched_bank_rows),
            },
        }


def match(batch: StagedBatch) -> MatchResult:
    """Run both passes over a staged batch.

    Pure: reads the batch, mutates nothing, returns a result. Re-running produces an
    identical result, which is what makes staging entries worth having.
    """
    result = MatchResult()

    ledger = batch.get(Source.LEDGER)
    recon = batch.get(Source.RECON)
    bank = batch.get(Source.BANK)
    payments = batch.get(Source.PAYMENTS)

    # ---------------------------------------------------------------- Pass 1
    # Index recon PAYMENT rows by order_id. Refunds, transfers and adjustments are
    # deliberately excluded here: a refund is not evidence that a sale reached Razorpay,
    # and treating it as one would let a refunded order look successfully matched.
    recon_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    refunds_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in recon:
        if not row.get("order_id"):
            continue
        if row.get("type") == ReconType.PAYMENT:
            recon_by_order[row["order_id"]].append(row)
        elif row.get("type") == ReconType.REFUND:
            refunds_by_order[row["order_id"]].append(row)

    payments_by_order = {p["order_id"]: p for p in payments if p.get("order_id")}

    seen_order_ids: dict[str, int] = defaultdict(int)
    for row in ledger:
        seen_order_ids[row["order_id"]] += 1

    result.duplicate_order_ids = {k: v for k, v in seen_order_ids.items() if v > 1}

    consumed_orders: set[str] = set()
    for row in ledger:
        order_id = row["order_id"]
        m = OrderMatch(
            order_id=order_id,
            ledger_row=row,
            recon_rows=list(recon_by_order.get(order_id, ())),
            refund_rows=list(refunds_by_order.get(order_id, ())),
            payment_row=payments_by_order.get(order_id),
            is_duplicate_order_id=seen_order_ids[order_id] > 1,
        )
        result.order_matches.append(m)
        if m.matched:
            consumed_orders.add(order_id)

    # Recon rows for orders the ledger never mentioned. Money arriving for a sale the
    # merchant has no record of is as much an exception as money not arriving.
    for order_id, rows in recon_by_order.items():
        if order_id not in seen_order_ids:
            result.unmatched_recon_orders.extend(rows)

    # ---------------------------------------------------------------- Pass 2
    settlements: dict[str, SettlementMatch] = {}
    for row in recon:
        sid = row.get("settlement_id")
        if not sid:
            continue
        if sid not in settlements:
            settlements[sid] = SettlementMatch(
                settlement_id=sid, utr=row.get("settlement_utr") or ""
            )
        settlements[sid].recon_rows.append(row)

    bank_by_utr: dict[str, dict[str, Any]] = {}
    for row in bank:
        utr = row.get("utr")
        if utr:
            bank_by_utr[utr] = row

    consumed_utrs: set[str] = set()
    for sm in settlements.values():
        if sm.utr and sm.utr in bank_by_utr:
            sm.bank_row = bank_by_utr[sm.utr]
            consumed_utrs.add(sm.utr)
        result.settlement_matches.append(sm)

    # Bank credits with no settlement. Unexplained money in is still unexplained.
    result.unmatched_bank_rows = [r for utr, r in bank_by_utr.items() if utr not in consumed_utrs]

    result.settlement_matches.sort(key=lambda s: s.settlement_id)
    return result


def settlement_dates(m: OrderMatch) -> list[Any]:
    """Settlement dates for an order, for the timing classifier."""
    return [to_date(r["settled_at"]) for r in m.recon_rows if r.get("settled_at")]
