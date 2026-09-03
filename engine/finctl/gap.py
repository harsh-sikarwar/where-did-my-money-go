"""Gap decomposition — the arithmetic that makes the verdict screen add up.

WHY THIS MODULE EXISTS. The first verdict screen was built by summing classification
findings, and the lines did not add up to the gap: ₹99,421 of lines against a ₹38,372
gap. The engine's numbers were right; the screen was assembling them wrongly.

The mistake was treating `Finding.amount_paise` as a contribution to the gap. It is not.
It means something different per classification:

    FEE                  the OVERCHARGE (delta from the rate card), not the fee itself
    TIMING               the whole order — which has usually already arrived
    REFUND               the magnitude of a difference whose SIGN is negative
    HALTED_SUBSCRIPTION  the whole order, which genuinely never arrived

Those are not commensurable, so adding them was never going to equal anything. A
discrepancy is not the same thing as a contribution to the gap, and the verdict screen
is about the gap.

So the decomposition is computed directly from the matched data, and every component is
signed. The identity below must hold exactly, and is asserted:

    gap = fees_kept + never_arrived + not_yet_settled - settled_above_ledger + residual

Findings still supply the count, the copy and the drill-down proof. They no longer
supply the amount.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from finctl.classify.classifier import Classification, Finding
from finctl.match.matcher import MatchResult, OrderMatch
from finctl.schema import ReconType


@dataclass
class GapComponent:
    """One signed contribution to the gap between expected and received."""

    classification: Classification
    amount_paise: int          # signed: positive widens the gap, negative narrows it
    count: int
    order_ids: list[str] = field(default_factory=list)


@dataclass
class GapDecomposition:
    """Every rupee of the gap, accounted for.

    `residual` is whatever the components do not explain. It should be zero, and the
    fact that it is *computed* rather than assumed is the point: if a future change
    breaks the identity, the residual becomes non-zero and says so on screen rather
    than silently rebalancing.
    """

    expected_paise: int
    received_paise: int
    components: list[GapComponent] = field(default_factory=list)

    @property
    def gap_paise(self) -> int:
        return self.expected_paise - self.received_paise

    @property
    def explained_paise(self) -> int:
        return sum(c.amount_paise for c in self.components)

    @property
    def residual_paise(self) -> int:
        return self.gap_paise - self.explained_paise

    def check(self) -> None:
        """Assert the identity holds. Called on every run.

        A silent failure here is exactly the bug this module was written to fix, so it
        raises rather than logging.
        """
        if self.residual_paise != 0:
            breakdown = ", ".join(
                f"{c.classification}={c.amount_paise}" for c in self.components
            )
            raise ArithmeticError(
                f"gap decomposition does not balance: gap={self.gap_paise}, "
                f"components sum to {self.explained_paise}, "
                f"residual={self.residual_paise}. Components: {breakdown}"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "expected_paise": self.expected_paise,
            "received_paise": self.received_paise,
            "gap_paise": self.gap_paise,
            "explained_paise": self.explained_paise,
            "residual_paise": self.residual_paise,
            "components": [
                {
                    "classification": str(c.classification),
                    "amount_paise": c.amount_paise,
                    "count": c.count,
                }
                for c in self.components
            ],
        }


def decompose(matches: MatchResult, findings: list[Finding]) -> GapDecomposition:
    """Split the gap into signed components that sum to it exactly.

    Every component is derived from the MATCHED DATA, not from finding amounts — that
    substitution is the whole fix.
    """
    d = GapDecomposition(
        expected_paise=matches.expected_paise,
        received_paise=matches.received_paise,
    )

    # Which orders correlation resolved, and how. Findings decide the LABEL a component
    # carries; the matched data decides its amount.
    resolution: dict[str, Classification] = {
        f.order_id: f.classification
        for f in findings
        if f.order_id and f.classification in (
            Classification.HALTED_SUBSCRIPTION,
            Classification.PAYMENT_FAILED,
            Classification.MISSING,
            Classification.UNEXPLAINED,
            Classification.NEEDS_REVIEW,
        )
    }

    # --- duplicated ledger rows -------------------------------------------------------
    # A duplicated order inflates `expected` with a sale that happened once. Razorpay
    # settled it once, so the extra copy is pure phantom expectation and belongs in the
    # gap under its own name.
    #
    # Every copy after the first is a duplicate. The FIRST copy is the real order and is
    # processed normally below; the rest are excluded from fee and settlement arithmetic
    # so their settlement is not counted once per copy.
    seen_orders: set[str] = set()
    duplicate_rows: list[OrderMatch] = []
    primary_rows: list[OrderMatch] = []
    for m in matches.order_matches:
        if m.order_id in seen_orders:
            duplicate_rows.append(m)
        else:
            seen_orders.add(m.order_id)
            primary_rows.append(m)

    if duplicate_rows:
        d.components.append(GapComponent(
            classification=Classification.DUPLICATE,
            amount_paise=sum(m.ledger_amount_paise for m in duplicate_rows),
            count=len(duplicate_rows),
            order_ids=[m.order_id for m in duplicate_rows],
        ))

    # --- money Razorpay kept as fees -------------------------------------------------
    # The gap includes the WHOLE fee, not just the overcharge. The overcharge is a
    # separate question (is the rate correct?) answered in the drill-down.
    fees = sum(m.fee_paise for m in primary_rows)
    if fees:
        d.components.append(GapComponent(
            classification=Classification.FEE,
            amount_paise=fees,
            count=sum(1 for m in primary_rows if m.fee_paise),
        ))

    # --- orders that never reached settlement ----------------------------------------
    # Grouped by how correlation explained them, so the verdict can say WHY the money is
    # absent rather than only that it is.
    by_cause: dict[Classification, list[tuple[str, int]]] = {}
    for m in primary_rows:
        if m.matched:
            continue
        cause = resolution.get(m.order_id, Classification.MISSING)
        by_cause.setdefault(cause, []).append((m.order_id, m.ledger_amount_paise))

    for cause, orders in by_cause.items():
        d.components.append(GapComponent(
            classification=cause,
            amount_paise=sum(a for _, a in orders),
            count=len(orders),
            order_ids=[o for o, _ in orders],
        ))

    # --- settled but not yet in the bank ---------------------------------------------
    # Genuinely still in flight: Razorpay has it, the bank does not. This is the only
    # TIMING that belongs in the gap. An order that settled late but HAS arrived is
    # already inside `received`, and counting it again was the original double-count.
    in_flight = sum(
        s.expected_credit_paise for s in matches.settlement_matches if not s.matched
    )
    if in_flight:
        d.components.append(GapComponent(
            classification=Classification.TIMING,
            amount_paise=in_flight,
            count=sum(1 for s in matches.settlement_matches if not s.matched),
        ))

    # --- settled for MORE than the ledger expected -----------------------------------
    # A one-sided refund: the merchant wrote their books down, Razorpay settled the full
    # amount. The bank received more than expected, so this NARROWS the gap. Negative.
    excess = 0
    excess_count = 0
    for m in primary_rows:
        if m.matched and m.settled_gross_paise > m.ledger_amount_paise:
            excess += m.settled_gross_paise - m.ledger_amount_paise
            excess_count += 1
    if excess:
        d.components.append(GapComponent(
            classification=Classification.REFUND,
            amount_paise=-excess,
            count=excess_count,
        ))

    # --- settled for LESS than the ledger expected -----------------------------------
    # A shortfall on an order that did settle. Widens the gap.
    shortfall = 0
    shortfall_count = 0
    for m in primary_rows:
        if m.matched and m.settled_gross_paise < m.ledger_amount_paise:
            shortfall += m.ledger_amount_paise - m.settled_gross_paise
            shortfall_count += 1
    if shortfall:
        d.components.append(GapComponent(
            classification=Classification.UNEXPLAINED,
            amount_paise=shortfall,
            count=shortfall_count,
        ))

    # --- refunds that Razorpay debited from a settlement ------------------------------
    # A refund row is a DEBIT: money leaves the settlement to go back to a customer.
    # It therefore reduces what the bank received and widens the gap.
    #
    # Pass-1 matching deliberately ignores refund rows (a refund is not evidence a sale
    # reached Razorpay), so these debits are invisible to every order-based component.
    # Without this, a refund settling against a matched order left its full value
    # unattributed — found by generating the "refund before the original settled" case,
    # which the invariant then caught as a ₹5,421 residual.
    refund_debits = sum(
        row.get("debit", 0)
        for sm in matches.settlement_matches
        for row in sm.recon_rows
        if row.get("type") == ReconType.REFUND
    )
    if refund_debits:
        d.components.append(GapComponent(
            classification=Classification.REFUND,
            amount_paise=refund_debits,
            count=sum(
                1 for sm in matches.settlement_matches
                for row in sm.recon_rows
                if row.get("type") == ReconType.REFUND
            ),
        ))

    # --- settlements for orders the ledger does not contain ---------------------------
    # Razorpay settled a sale the merchant has no record of. That money reached the bank
    # and is inside `received`, but nothing in `expected` claims it — so it NARROWS the
    # gap and must be subtracted.
    #
    # Found by a hand-edited blind test: deleting two ledger rows left ₹16,992.29
    # unaccounted for, exactly the net credit of the two orphaned settlements. The
    # matcher had detected them all along (`unmatched_recon_orders`); the decomposition
    # simply never consumed them. Every generated defect removes money or moves it, so
    # no synthetic case had ever produced settled money with no ledger row behind it.
    orphan_settlements = sum(
        row.get("credit", 0) - row.get("debit", 0)
        for row in matches.unmatched_recon_orders
    )
    if orphan_settlements:
        d.components.append(GapComponent(
            classification=Classification.UNEXPECTED_SETTLEMENT,
            amount_paise=-orphan_settlements,
            count=len({
                row.get("order_id") for row in matches.unmatched_recon_orders
                if row.get("order_id")
            }) or len(matches.unmatched_recon_orders),
            order_ids=sorted({
                row["order_id"] for row in matches.unmatched_recon_orders
                if row.get("order_id")
            }),
        ))

    # --- bank credits with no settlement behind them ---------------------------------
    # Already counted inside `received`, so they narrow the gap.
    orphan = sum(r["credit_paise"] for r in matches.unmatched_bank_rows)
    if orphan:
        d.components.append(GapComponent(
            classification=Classification.UNEXPECTED_SETTLEMENT,
            amount_paise=-orphan,
            count=len(matches.unmatched_bank_rows),
        ))

    # Two different mechanisms can produce the same classification -- a one-sided refund
    # (negative: the bank got more than the books expected) and a refund Razorpay
    # actually debited (positive: money went back to a customer). They are both REFUND
    # to a merchant, so they must appear as ONE line, and the ranker looks components up
    # by classification. Leaving two would silently drop one.
    merged: dict[Classification, GapComponent] = {}
    for component in d.components:
        existing = merged.get(component.classification)
        if existing is None:
            merged[component.classification] = component
        else:
            existing.amount_paise += component.amount_paise
            existing.count += component.count
            existing.order_ids.extend(component.order_ids)
    d.components = list(merged.values())

    return d
