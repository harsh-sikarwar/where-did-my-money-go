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
from finctl.match.matcher import MatchResult


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

    # --- money Razorpay kept as fees -------------------------------------------------
    # The gap includes the WHOLE fee, not just the overcharge. The overcharge is a
    # separate question (is the rate correct?) answered in the drill-down.
    fees = sum(m.fee_paise for m in matches.order_matches)
    if fees:
        d.components.append(GapComponent(
            classification=Classification.FEE,
            amount_paise=fees,
            count=sum(1 for m in matches.order_matches if m.fee_paise),
        ))

    # --- orders that never reached settlement ----------------------------------------
    # Grouped by how correlation explained them, so the verdict can say WHY the money is
    # absent rather than only that it is.
    by_cause: dict[Classification, list[tuple[str, int]]] = {}
    for m in matches.order_matches:
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
    for m in matches.order_matches:
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
    for m in matches.order_matches:
        if m.matched and m.settled_gross_paise < m.ledger_amount_paise:
            shortfall += m.ledger_amount_paise - m.settled_gross_paise
            shortfall_count += 1
    if shortfall:
        d.components.append(GapComponent(
            classification=Classification.UNEXPLAINED,
            amount_paise=shortfall,
            count=shortfall_count,
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

    return d
