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

# The verdict screen's line ordering and human copy. Deliberately data rather than
# code: the phrasing is product copy and belongs somewhere a non-programmer can edit.
#
# Every finance term is explained inline or absent — a merchant who does not know what
# MDR means must still understand the line. The exact numbers live one click down.
LINE_COPY: dict[Classification, tuple[str, str]] = {
    Classification.TIMING: (
        "not missing, just late",
        "Money captured before the settlement cycle completed. It arrives on its own.",
    ),
    Classification.FEE: (
        "Razorpay's cut + tax on it",
        "The processing fee, plus the 18% GST charged on that fee — not on your sale.",
    ),
    Classification.TAX_ON_FEE: (
        "tax on Razorpay's cut",
        "GST is charged on the processing fee, not on the transaction amount.",
    ),
    Classification.REFUND: (
        "refunds recorded on one side only",
        "You recorded a refund that never reached the settlement, or the reverse.",
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
        *,
        expected_paise: int,
        received_paise: int,
    ) -> Verdict:
        grouped: dict[Classification, list[Finding]] = {}
        for f in findings:
            if f.classification is Classification.RECONCILED:
                continue   # nothing to report about money that arrived correctly
            grouped.setdefault(f.classification, []).append(f)

        lines: list[VerdictLine] = []
        for classification in _DISPLAY_ORDER:
            group = grouped.get(classification)
            if not group:
                continue
            total = sum(f.amount_paise for f in group)
            label, explanation = LINE_COPY.get(
                classification, (str(classification).lower(), "")
            )
            lines.append(VerdictLine(
                classification=classification,
                label=label,
                explanation=explanation,
                count=len(group),
                amount_paise=total,
                actionable=self.is_actionable(classification, total),
                findings=group,
            ))

        # Any classification not in the display order still gets reported. Silently
        # dropping an unknown label would hide exactly the thing worth seeing.
        for classification, group in grouped.items():
            if classification in _DISPLAY_ORDER:
                continue
            total = sum(f.amount_paise for f in group)
            label, explanation = LINE_COPY.get(
                classification, (str(classification).lower(), "")
            )
            lines.append(VerdictLine(
                classification=classification, label=label, explanation=explanation,
                count=len(group), amount_paise=total,
                actionable=self.is_actionable(classification, total), findings=group,
            ))

        unexplained = sum(
            f.amount_paise for f in findings
            if f.classification in (Classification.UNEXPLAINED, Classification.NEEDS_REVIEW)
        )

        return Verdict(
            expected_paise=expected_paise,
            received_paise=received_paise,
            gap_paise=expected_paise - received_paise,
            lines=lines,
            unexplained_paise=unexplained,
        )
