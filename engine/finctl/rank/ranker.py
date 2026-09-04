"""Materiality ranking: benign vs actionable.

BEHAVIOR.md, stage `rank`:
  Promises  — split resolved exceptions into benign (explained, no action) and
              actionable (needs a human this week). Success is a SHORT actionable list.
  Refuses   — to rank by rupee value alone. A ₹31,000 timing lag that resolves itself on
              Tuesday is benign; ₹3,800 of dead subscriptions is not.

Materiality is about **recoverability**, not size. Size only orders the list once
recoverability has decided what belongs on it.

This is the stage that makes the product a two-minute Monday read rather than a
dashboard. Getting it wrong in the permissive direction produces a long list nobody
reads, which is indistinguishable from having no tool at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from finctl.classify.classifier import Classification, Finding
from finctl.config.loader import Tolerances
from finctl.gap import decompose
from finctl.match.matcher import MatchResult

# The verdict screen's line ordering and human copy. Deliberately data rather than
# code: the phrasing is product copy and belongs somewhere a non-programmer can edit.
#
# Every finance term is explained inline or absent — a merchant who does not know what
# MDR means must still understand the line. The exact numbers live one click down.
LINE_COPY: dict[Classification, tuple[str, str]] = {
    Classification.TIMING: (
        "on its way — settled, not yet in your bank",
        "Razorpay has released this money but it has not landed in your account yet. "
        "It arrives on its own.",
    ),
    Classification.ON_HOLD: (
        "held by Razorpay — not on its way",
        "Razorpay is deliberately holding this money rather than settling it. This is "
        "not a delay that clears on its own: it usually means pending KYC, a risk "
        "review, or a dispute. Check your Razorpay dashboard — waiting will not "
        "release it.",
    ),
    Classification.FEE: (
        "Razorpay's cut + tax on it",
        "The processing fee Razorpay kept, plus the 18% GST charged on that fee — "
        "not on your sale.",
    ),
    Classification.TAX_ON_FEE: (
        "tax on Razorpay's cut",
        "GST is charged on the processing fee, not on the transaction amount.",
    ),
    Classification.REFUND: (
        "refunds you recorded but Razorpay still paid out",
        "You wrote these down as refunded, so you expected less. Razorpay settled the "
        "full amount anyway — your bank got MORE than your books expected, which is why "
        "this line is negative. Worth reconciling: either the refund never went through, "
        "or it was recorded twice.",
    ),
    Classification.ROUNDING: (
        "rounding differences",
        "Sub-rupee arithmetic differences, within tolerance.",
    ),
    Classification.HALTED_SUBSCRIPTION: (
        "subscriptions died silently — recoverable",
        "Razorpay stopped attempting charges but kept generating invoices. "
        "Nobody was told. This money is recoverable if you act.",
    ),
    Classification.PAYMENT_FAILED: (
        "payments that failed",
        "The customer's payment did not go through. Some are worth retrying.",
    ),
    Classification.MISSING: (
        "no record at Razorpay at all",
        "The order is in your books but Razorpay has no matching payment.",
    ),
    Classification.DUPLICATE: (
        "the same order recorded twice",
        "One order id appears more than once in your ledger.",
    ),
    Classification.NEEDS_REVIEW: (
        "more than one explanation fits",
        "We found several possible causes and will not guess between them.",
    ),
    Classification.UNEXPLAINED: (
        "we can't explain",
        "No rule and no correlation accounts for this. It is reported rather than hidden.",
    ),
    Classification.UNEXPECTED_SETTLEMENT: (
        "money in for an order you don't have",
        "Razorpay settled an order that is not in your ledger.",
    ),
    Classification.DISPUTED: (
        "disputed by the customer — you have a deadline",
        "A customer has formally contested these payments with their bank. Razorpay is "
        "holding the money, or has already taken it back. Unlike a delay, this does not "
        "resolve on its own: you have a limited window to submit evidence through the "
        "Razorpay dashboard, and missing it forfeits the money.",
    ),
    Classification.UNRECORDED_REFUND: (
        "refunds Razorpay paid out that you never recorded",
        "Razorpay returned this money to customers, but there is no refund in your "
        "books. Your records therefore show more money than you actually have. Check "
        "whether these were issued from the Razorpay dashboard without being written "
        "down — nothing in your own books would ever reveal them.",
    ),
}

# Display order for the verdict. Benign lines first, largest-first within each group,
# so the eye lands on "this is mostly fine" before "this needs you".
_DISPLAY_ORDER = (
    Classification.TIMING,
    Classification.FEE,
    Classification.TAX_ON_FEE,
    Classification.REFUND,
    Classification.ROUNDING,
    Classification.DUPLICATE,
    Classification.UNEXPECTED_SETTLEMENT,
    Classification.UNRECORDED_REFUND,
    Classification.DISPUTED,
    Classification.HALTED_SUBSCRIPTION,
    Classification.PAYMENT_FAILED,
    Classification.MISSING,
    Classification.NEEDS_REVIEW,
)


@dataclass
class LineNote:
    """A figure that qualifies a verdict line without entering the gap sum.

    Kept structurally separate from `amount_paise` so it cannot be mistaken for a
    contribution: nothing sums notes, and `GapDecomposition.check()` never sees them.
    """

    label: str
    count: int
    amount_paise: int
    actionable: bool
    explanation: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "count": self.count,
            "amount_paise": self.amount_paise,
            "actionable": self.actionable,
            "explanation": self.explanation,
        }


@dataclass
class VerdictLine:
    """One line of the verdict screen.

    `count` and `amount_paise` must describe the SAME population. That sounds too
    obvious to state, which is exactly why it went wrong: the fee line took its count
    from the findings (orders charged the wrong rate) and its amount from the gap
    component (the whole fee, across every order that paid one), and rendered them
    side by side as though they were one fact. On one QA run that read "40 orders ·
    ₹37,023.69" while its own drill-down showed "40 orders · ₹227.90" — the same label
    over two populations, 162x apart.
    """

    classification: Classification
    label: str
    explanation: str
    count: int
    amount_paise: int
    actionable: bool
    findings: list[Finding] = field(default_factory=list)
    # A second figure ABOUT this line rather than a second contribution to the gap.
    # The fee overcharge lives here: it is a subset of money already counted in
    # `amount_paise`, so it can never be added to the decomposition without
    # double-counting — but it is the only fee number a merchant can dispute, and
    # until now it appeared nowhere in the product.
    note: LineNote | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification": str(self.classification),
            "label": self.label,
            "explanation": self.explanation,
            "count": self.count,
            "amount_paise": self.amount_paise,
            "actionable": self.actionable,
            "note": self.note.as_dict() if self.note else None,
        }


@dataclass
class LatePayouts:
    """Settlements that arrived, but later than the cycle promised.

    Deliberately NOT a verdict line. Money that settled late but HAS arrived is already
    inside `received`, so its contribution to the gap is zero — counting it again was
    the original double-count that `gap.py` exists to prevent, and it is why this has
    no line despite the engine detecting 213 of them on a 2,500-order run.

    Zero gap impact is not zero information. A merchant with 213 late payouts has a
    working-capital problem worth naming, and the engine already knows the count, the
    value and how late each one was. So it is reported beside the waterfall rather than
    inside it: no rupee is double-counted and nothing is silently discarded.
    """

    count: int = 0
    value_paise: int = 0
    median_days_late: int = 0
    max_days_late: int = 0
    cycle_days: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "value_paise": self.value_paise,
            "median_days_late": self.median_days_late,
            "max_days_late": self.max_days_late,
            "cycle_days": self.cycle_days,
        }


@dataclass
class Verdict:
    """The whole four-lines-and-a-verdict output."""

    expected_paise: int
    received_paise: int
    gap_paise: int
    lines: list[VerdictLine] = field(default_factory=list)
    # Money no rule could account for, from the CORRELATION pass — the honest residual,
    # and the only one worth showing a merchant.
    #
    # This used to be the decomposition's residual, which is a different thing entirely
    # and is now `residual_paise` below. The components are constructed so as to close
    # the gap, so that number is structurally incapable of being non-zero: it read
    # "Unexplained — nothing in the data accounts for this — ₹0.00" on every run,
    # including 2,500 orders with 849 defects, on a page whose whole promise is that
    # every rupee is accounted for. Worse, the correlation section further down the
    # SAME page named ₹2,480.00 still unexplained, and the order it belonged to.
    #
    # A check that cannot fail proves nothing. This one can.
    unexplained_paise: int = 0
    # How many orders that residual spans, so the row can say "one order" rather than
    # leaving a bare figure to be taken on faith.
    unexplained_count: int = 0
    # The decomposition's own residual: gap minus the sum of the components. It MUST be
    # zero and `GapDecomposition.check()` raises when it is not, so it is kept as an
    # integrity signal rather than displayed as a finding.
    residual_paise: int = 0
    # Detected late settlements, summarised. Gap-neutral, so it sits beside the
    # waterfall rather than in it — see LatePayouts.
    late: LatePayouts | None = None

    @property
    def actionable_lines(self) -> list[VerdictLine]:
        return [line for line in self.lines if line.actionable]

    @property
    def actionable_paise(self) -> int:
        return sum(line.amount_paise for line in self.actionable_lines)

    @property
    def benign_paise(self) -> int:
        return sum(line.amount_paise for line in self.lines if not line.actionable)

    def headline(self) -> str:
        """The single sentence a merchant reads on Monday.

        Named the 'one thing' deliberately: if everything is urgent, nothing is. The
        headline reports the LARGEST actionable line, not a list of them.
        """
        actionable = self.actionable_lines
        if not actionable:
            return "Nothing needs you this week."

        top = max(actionable, key=lambda line: line.amount_paise)
        if top.classification is Classification.HALTED_SUBSCRIPTION:
            return f"One thing needs you this week: those {top.count} customers."
        return f"One thing needs you this week: {top.count} {top.label}."

    def as_dict(self) -> dict[str, Any]:
        return {
            "expected_paise": self.expected_paise,
            "received_paise": self.received_paise,
            "gap_paise": self.gap_paise,
            "unexplained_paise": self.unexplained_paise,
            "unexplained_count": self.unexplained_count,
            "residual_paise": self.residual_paise,
            "late": self.late.as_dict() if self.late else None,
            "actionable_paise": self.actionable_paise,
            "benign_paise": self.benign_paise,
            "headline": self.headline(),
            "lines": [line.as_dict() for line in self.lines],
        }


class Ranker:
    """Decides what needs a human.

    Every threshold comes from config. A magic number here would be a bug: test day
    varies materiality deliberately.
    """

    def __init__(self, tolerances: Tolerances) -> None:
        self.tol = tolerances

    def is_actionable(self, classification: Classification, amount_paise: int) -> bool:
        """Recoverability first, size second.

        `always_benign` and `always_actionable` come from tolerances.yaml and are
        checked before any amount comparison — that ordering IS the policy. A large
        timing lag stays benign; a small halted subscription stays actionable.
        """
        name = str(classification)
        if name in self.tol.always_benign:
            return False
        if name in self.tol.always_actionable:
            return True
        return abs(amount_paise) >= self.tol.actionable_above_paise

    def _line(
        self,
        classification: Classification,
        label: str,
        explanation: str,
        component: Any,
        counts: dict[Classification, int],
        findings: list[Finding],
    ) -> VerdictLine:
        """One verdict line, with its count and its amount describing the same rows.

        The count used to prefer the finding count for every classification, on the
        reasoning that "6 subscriptions" is a human fact while a component count is an
        accounting artefact. That is true where the two populations coincide. For FEE
        they are different sets — every order that paid a fee, versus the orders
        charged the wrong one — and pairing one's count with the other's amount is
        what produced a line contradicting its own drill-down.

        So: the count comes from the component whenever it is the component's money
        being shown, and the finding count is used only where a finding IS the unit of
        the amount.
        """
        mine = [f for f in findings if f.classification is classification]

        if classification is Classification.FEE:
            # Two questions, two lines' worth of fact, one of which is not a gap
            # contribution at all. `amount_paise` stays the whole fee (that is what
            # left the merchant's money), counted over the orders that actually paid
            # one. The overcharge rides along as a note.
            over_paise = sum(f.amount_paise for f in mine)
            # NOT `is_actionable(FEE, ...)`. FEE sits in `always_benign`, and that
            # entry means the fee itself — the contracted cost of taking payments —
            # is never something to chase. An overcharge is the opposite: money
            # charged above the rate card, which is the one fee figure a merchant can
            # dispute. So it is judged on materiality alone.
            note = LineNote(
                label="charged above your contracted rate",
                count=len(mine),
                amount_paise=over_paise,
                actionable=over_paise >= self.tol.actionable_above_paise,
                explanation=(
                    "The part of that fee which exceeds the rate card — the only "
                    "portion you could dispute. It is already included in the figure "
                    "above, not additional to it."
                ),
            ) if mine else None
            return VerdictLine(
                classification=classification,
                label=label,
                explanation=explanation,
                count=component.count,
                amount_paise=component.amount_paise,
                # The whole fee is the contracted cost of taking payments; it is not
                # something to chase. Only the overcharge can be actionable, and it
                # says so on the note.
                actionable=False,
                findings=mine,
                note=note,
            )

        return VerdictLine(
            classification=classification,
            label=label,
            explanation=explanation,
            count=counts.get(classification, component.count),
            amount_paise=component.amount_paise,
            actionable=self.is_actionable(classification, component.amount_paise),
            findings=mine,
        )

    def _late_payouts(self, findings: list[Finding]) -> LatePayouts | None:
        """Summarise the TIMING findings the waterfall cannot carry.

        Every figure here comes from proof the classifier already wrote — the delay is
        not recomputed, only aggregated, for the same reason the fee overcharge is not
        recomputed downstream.
        """
        late = [f for f in findings if f.classification is Classification.TIMING]
        if not late:
            return None

        days = sorted(
            int(f.proof.get("working_days_late", 0) or 0) for f in late
        )
        return LatePayouts(
            count=len(late),
            value_paise=sum(f.amount_paise for f in late),
            median_days_late=days[len(days) // 2],
            max_days_late=days[-1],
            # The cycle the delay was measured against, so the panel can say "T+2"
            # rather than leaving "late" undefined. Taken from the findings themselves
            # because the cycle may have been OBSERVED from the data rather than
            # configured, and the two can differ.
            cycle_days=int(late[0].proof.get("cycle_days", 0) or 0),
        )

    def rank(
        self,
        findings: list[Finding],
        matches: MatchResult,
        still_unexplained: list[Finding] | None = None,
    ) -> Verdict:
        """Build the verdict from the GAP DECOMPOSITION, not from finding amounts.

        This is the fix for the bug where the lines summed to ₹99,421 against a ₹38,372
        gap. A finding's `amount_paise` is not a contribution to the gap — it means
        something different per classification (a fee delta, a whole order, a refund
        magnitude), so summing them could never equal anything.

        Findings still supply counts, copy and drill-down proof. The decomposition
        supplies the amounts, and it is asserted to balance.
        """
        d = decompose(matches, findings)
        d.check()   # the identity must hold; a silent failure here is the original bug

        counts: dict[Classification, int] = {}
        for f in findings:
            if f.classification is Classification.RECONCILED:
                continue
            counts[f.classification] = counts.get(f.classification, 0) + 1

        by_class = {c.classification: c for c in d.components}

        lines: list[VerdictLine] = []
        for classification in _DISPLAY_ORDER:
            component = by_class.get(classification)
            if component is None:
                continue
            label, explanation = LINE_COPY.get(
                classification, (str(classification).lower(), "")
            )
            lines.append(self._line(
                classification, label, explanation, component, counts, findings,
            ))

        for classification, component in by_class.items():
            if classification in _DISPLAY_ORDER:
                continue
            label, explanation = LINE_COPY.get(
                classification, (str(classification).lower(), "")
            )
            lines.append(self._line(
                classification, label, explanation, component, counts, findings,
            ))

        # The residual a merchant is shown comes from the CORRELATION pass: money no
        # rule could account for, after the payments and subscriptions files were
        # brought in. `d.residual_paise` is a different quantity — an integrity check
        # on the decomposition that must be zero — and showing it as though it were
        # this one meant the row could never say anything.
        outstanding = list(still_unexplained or [])
        return Verdict(
            expected_paise=d.expected_paise,
            received_paise=d.received_paise,
            gap_paise=d.gap_paise,
            lines=lines,
            unexplained_paise=sum(f.amount_paise for f in outstanding),
            unexplained_count=len(outstanding),
            residual_paise=d.residual_paise,
            late=self._late_payouts(findings),
        )
