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
    Classification.HALTED_SUBSCRIPTION,
    Classification.PAYMENT_FAILED,
    Classification.MISSING,
    Classification.NEEDS_REVIEW,
)


@dataclass
class VerdictLine:
    """One line of the verdict screen."""

    classification: Classification
    label: str
    explanation: str
    count: int
    amount_paise: int
    actionable: bool
    findings: list[Finding] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification": str(self.classification),
            "label": self.label,
            "explanation": self.explanation,
            "count": self.count,
            "amount_paise": self.amount_paise,
            "actionable": self.actionable,
        }


@dataclass
class Verdict:
    """The whole four-lines-and-a-verdict output."""

    expected_paise: int
    received_paise: int
    gap_paise: int
    lines: list[VerdictLine] = field(default_factory=list)
    unexplained_paise: int = 0

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

    def rank(
        self,
        findings: list[Finding],
        matches: MatchResult,
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
            lines.append(VerdictLine(
                classification=classification,
                label=label,
                explanation=explanation,
                # Prefer the finding count where one exists: "6 subscriptions" is a
                # human fact, while the component count is an accounting artefact
                # (FEE spans every order that paid one).
                count=counts.get(classification, component.count),
                amount_paise=component.amount_paise,
                actionable=self.is_actionable(classification, component.amount_paise),
                findings=[f for f in findings if f.classification is classification],
            ))

        for classification, component in by_class.items():
            if classification in _DISPLAY_ORDER:
                continue
            label, explanation = LINE_COPY.get(
                classification, (str(classification).lower(), "")
            )
            lines.append(VerdictLine(
                classification=classification, label=label, explanation=explanation,
                count=counts.get(classification, component.count),
                amount_paise=component.amount_paise,
                actionable=self.is_actionable(classification, component.amount_paise),
                findings=[f for f in findings if f.classification is classification],
            ))

        return Verdict(
            expected_paise=d.expected_paise,
            received_paise=d.received_paise,
            gap_paise=d.gap_paise,
            lines=lines,
            unexplained_paise=d.residual_paise,
        )
