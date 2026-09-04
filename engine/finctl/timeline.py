"""The gap, spread over the days the orders were captured on.

The verdict answers "how big is the gap and what explains it". This answers "when did
it happen" — which is the question a merchant asks next, and the one that turns a
number into something they can go and look at. A single bad day is a different problem
from a steady leak of the same size.

Two rules make this honest rather than decorative:

1. It attributes, it never re-derives. Every paisa here comes from a `GapComponent`'s
   `per_order`, recorded where the amount was originally computed. Re-deriving per-order
   amounts from findings is how a summary line and its own drill-down end up describing
   two different populations.

2. What cannot be dated is declared, not spread. In-flight settlements and orphan bank
   credits have no ledger order behind them and therefore no capture date. They are
   reported as `undated_paise` rather than smeared across the days they might have
   belonged to. `sum(days) + undated == gap` is asserted on every build.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from finctl.classify.classifier import Classification
from finctl.gap import GapDecomposition
from finctl.match.matcher import MatchResult
from finctl.normalize.normalizer import to_date


@dataclass
class TimelineDay:
    """One calendar day's signed contribution to the gap."""

    day: date
    paise: int
    order_count: int
    # What the ledger says this day's orders should have brought in. Bucketed by the
    # order's capture date, which is the only date every order has.
    expected_paise: int = 0
    # How much of the day is money that needs a decision, under the same materiality
    # policy the verdict applied. The chart colours bars from this rather than from
    # magnitude: in this product an amber bar means "act", never "big". A tall grey
    # bar is a busy day, not a problem.
    actionable_paise: int = 0

    @property
    def received_paise(self) -> int:
        """What actually arrived for this day's orders.

        Defined as `expected - gap` rather than summed from the bank side, because the
        bank credits arrive on settlement dates that belong to other days. Deriving it
        keeps the two lines on the chart exactly one gap apart — which is the claim the
        chart is making, so it should not be possible to draw it any other way.
        """
        return self.expected_paise - self.paise


@dataclass
class Timeline:
    days: list[TimelineDay] = field(default_factory=list)
    undated_paise: int = 0
    gap_paise: int = 0

    @property
    def dated_paise(self) -> int:
        return sum(d.paise for d in self.days)

    @property
    def peak(self) -> TimelineDay | None:
        """The worst day for money that needs a decision.

        Ranked by actionable money first, total second, so the readout names the day
        worth opening rather than merely the busiest one. Ties break to the earlier
        day — the older problem is the more urgent one.
        """
        widening = [d for d in self.days if d.paise > 0]
        return max(
            widening,
            key=lambda d: (d.actionable_paise, d.paise, -d.day.toordinal()),
            default=None,
        )

    def check(self) -> None:
        """The same discipline the decomposition holds itself to.

        If a future change starts dropping orders on the floor, this raises rather than
        quietly drawing a chart that no longer adds up to the number above it.
        """
        total = self.dated_paise + self.undated_paise
        if total != self.gap_paise:
            raise ArithmeticError(
                f"timeline does not balance: gap={self.gap_paise}, "
                f"dated={self.dated_paise}, undated={self.undated_paise}, "
                f"sum={total}"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "days": [
                {
                    "day": d.day.isoformat(),
                    "paise": d.paise,
                    "orders": d.order_count,
                    "actionable_paise": d.actionable_paise,
                    "expected_paise": d.expected_paise,
                    "received_paise": d.received_paise,
                }
                for d in self.days
            ],
            "undated_paise": self.undated_paise,
            "dated_paise": self.dated_paise,
            "gap_paise": self.gap_paise,
        }


def build_timeline(
    matches: MatchResult,
    decomposition: GapDecomposition,
    actionable: frozenset[Classification] = frozenset(),
) -> Timeline:
    """Bucket every attributable component amount by its order's capture date.

    Days with no gap contribution are still emitted, with zero. A chart that silently
    omits the quiet days compresses the time axis and makes a steady leak look like a
    spike.
    """
    captured: dict[str, date] = {}
    expected_by_day: dict[date, int] = {}
    for m in matches.order_matches:
        day = to_date(m.ledger_row.get("captured_at"))
        if day is None:
            continue
        # Every row counts toward `expected`, including the second copy of a duplicated
        # order — `MatchResult.expected_paise` sums them the same way, and the DUPLICATE
        # component is what accounts for the difference.
        expected_by_day[day] = expected_by_day.get(day, 0) + m.ledger_amount_paise
        captured.setdefault(m.order_id, day)

    by_day: dict[date, int] = {}
    actionable_by_day: dict[date, int] = {}
    orders_by_day: dict[date, set[str]] = {}
    attributed = 0

    for component in decomposition.components:
        needs_decision = component.classification in actionable
        for order_id, paise in component.per_order:
            day = captured.get(order_id)
            if day is None:
                # Attributable to an order, but that order carries no usable capture
                # date — an unrecorded refund keyed by entity id, or a settlement for
                # an order the ledger never mentioned.
                continue
            by_day[day] = by_day.get(day, 0) + paise
            if needs_decision:
                actionable_by_day[day] = actionable_by_day.get(day, 0) + paise
            orders_by_day.setdefault(day, set()).add(order_id)
            attributed += paise

    timeline = Timeline(
        gap_paise=decomposition.gap_paise,
        # Everything the components could not pin to a dated order. Computed as the
        # remainder so it can never silently disagree with the gap.
        undated_paise=decomposition.gap_paise - attributed,
    )

    # The axis spans every day the ledger touched, not only the days with a gap. A
    # chart that starts at the first bad day hides how much of the month was clean.
    dated = set(by_day) | set(expected_by_day)
    if dated:
        start, end = min(dated), max(dated)
        span = (end - start).days
        for offset in range(span + 1):
            day = start + timedelta(days=offset)
            timeline.days.append(TimelineDay(
                day=day,
                paise=by_day.get(day, 0),
                order_count=len(orders_by_day.get(day, ())),
                actionable_paise=actionable_by_day.get(day, 0),
                expected_paise=expected_by_day.get(day, 0),
            ))

    timeline.check()
    return timeline
