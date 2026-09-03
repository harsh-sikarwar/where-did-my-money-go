"""The action list: who to chase, for how much, and why.

The verdict ends with *"One thing needs you this week: those 6 customers"* and, until
this module, could not name them. That is the gap between an insight and a tool, and the
README argues against dashboards precisely because a merchant should be handed the work
rather than a chart of it.

Nothing here is computed. Every field is lifted from a finding's proof — the correlation
stage already resolved `customer_id`, `subscription_id` and `error_reason` on the way to
labelling the gap. This module is a projection, not an analysis, which is why it cannot
disagree with the verdict it accompanies.

ADR-048.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from finctl.classify.classifier import BENIGN, Classification, Finding
from finctl.money import format_rupees

# What to tell a merchant to DO, per cause. Deliberately imperative and specific: "email
# these customers a new payment link" is an instruction, "review halted subscriptions" is
# a category name wearing a verb.
NEXT_STEP: dict[Classification, str] = {
    Classification.HALTED_SUBSCRIPTION: (
        "Email these customers a new payment link. Razorpay stopped attempting charges "
        "and will not restart on its own."
    ),
    Classification.PAYMENT_FAILED: (
        "Retry or ask for another payment method. Most of these are recoverable."
    ),
    Classification.ON_HOLD: (
        "Open your Razorpay dashboard and clear the hold. Waiting will not release it."
    ),
    Classification.DISPUTED: (
        "Submit evidence in the Razorpay dashboard before the deadline. "
        "Doing nothing forfeits the money."
    ),
    Classification.REFUND: (
        "Check these against your own refund records. Either the refund never went "
        "through, or it was recorded twice."
    ),
    Classification.UNRECORDED_REFUND: (
        "Check whether these refunds were issued from the dashboard without being "
        "written down, and correct your books."
    ),
    Classification.MISSING: (
        "No record at Razorpay at all. Check whether the sale actually completed."
    ),
    Classification.UNEXPECTED_SETTLEMENT: (
        "Razorpay settled an order your ledger does not contain. Find out what it was."
    ),
    Classification.NEEDS_REVIEW: (
        "More than one explanation fits. A human needs to decide which."
    ),
    Classification.UNEXPLAINED: (
        "The engine could not account for this. It is not hiding it."
    ),
    Classification.DUPLICATE: (
        "The same order appears twice in your ledger. Remove one."
    ),
}

# Where each fact lives in a finding's proof. Correlation writes into `proof.correlation`;
# the classifier writes at the top level. Looked up in order, first hit wins.
_LOOKUPS: dict[str, tuple[str, ...]] = {
    "customer_id": ("customer_id",),
    "email": ("email", "customer_email"),
    "contact": ("contact", "customer_contact"),
    "subscription_id": ("subscription_id",),
    "payment_id": ("payment_id",),
    "reason": ("error_reason", "hold_reason", "dispute_reason"),
    "detail": ("error_description", "explanation", "outcome"),
}


def _dig(proof: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Find a value at the top level of a proof or inside its `correlation` block."""
    correlation = proof.get("correlation") or {}
    for key in keys:
        for source in (proof, correlation):
            value = source.get(key) if isinstance(source, dict) else None
            if value not in (None, "", []):
                return value
    return None


@dataclass
class ActionItem:
    """One thing a merchant should do, about one order."""

    order_id: str | None
    classification: Classification
    amount_paise: int
    customer_id: str | None = None
    email: str | None = None
    contact: str | None = None
    subscription_id: str | None = None
    payment_id: str | None = None
    reason: str | None = None
    detail: str | None = None

    @property
    def amount_display(self) -> str:
        return format_rupees(self.amount_paise)

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "classification": str(self.classification),
            "amount": {"paise": self.amount_paise, "display": self.amount_display},
            "customer_id": self.customer_id,
            "email": self.email,
            "contact": self.contact,
            "subscription_id": self.subscription_id,
            "payment_id": self.payment_id,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class ActionGroup:
    """Everything that needs the same action, largest first."""

    classification: Classification
    next_step: str
    items: list[ActionItem] = field(default_factory=list)

    @property
    def total_paise(self) -> int:
        return sum(i.amount_paise for i in self.items)

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification": str(self.classification),
            "next_step": self.next_step,
            "count": len(self.items),
            "total": {"paise": self.total_paise, "display": format_rupees(self.total_paise)},
            "items": [i.as_dict() for i in self.items],
        }


CSV_COLUMNS = (
    "order_id", "what", "amount_rupees", "customer_id", "email", "contact",
    "subscription_id", "payment_id", "reason", "next_step",
)


def build(
    findings: list[Finding],
    ledger_rows: list[dict[str, Any]] | None = None,
) -> list[ActionGroup]:
    """Group the actionable findings into work, largest group first.

    Only actionable classifications appear. A merchant asking "what needs me?" is not
    asking to be shown the fee they agreed to pay, and including benign rows would
    recreate the dashboard this product exists not to be.

    `ledger_rows` supplies the customer for orders that correlation never touched. The
    merchant's own ledger already names the buyer on every row; only the subscription
    join was putting `customer_id` into a proof, so without this the action list could
    name the customer behind a halted subscription and not the one behind a failed
    payment — which is precisely backwards, since the failed payment is the one you
    email today.
    """
    by_order: dict[str, dict[str, Any]] = {
        row["order_id"]: row
        for row in (ledger_rows or ())
        if row.get("order_id")
    }

    groups: dict[Classification, ActionGroup] = {}

    for finding in findings:
        if finding.classification in BENIGN:
            continue
        # RECONCILED is benign; anything else without a next step is still surfaced,
        # because silence about a finding we HAVE is worse than a generic instruction.
        step = NEXT_STEP.get(finding.classification, "Needs a look.")
        group = groups.setdefault(
            finding.classification,
            ActionGroup(classification=finding.classification, next_step=step),
        )
        proof = finding.proof or {}
        # The proof first — correlation resolved a customer through the subscription
        # join and that is the more specific answer — then the ledger row.
        ledger = by_order.get(finding.order_id or "", {})
        group.items.append(ActionItem(
            order_id=finding.order_id,
            classification=finding.classification,
            amount_paise=finding.amount_paise,
            customer_id=_dig(proof, _LOOKUPS["customer_id"]) or ledger.get("customer_id"),
            email=_dig(proof, _LOOKUPS["email"]) or ledger.get("email"),
            contact=_dig(proof, _LOOKUPS["contact"]) or ledger.get("contact"),
            subscription_id=_dig(proof, _LOOKUPS["subscription_id"]),
            payment_id=_dig(proof, _LOOKUPS["payment_id"]),
            reason=_dig(proof, _LOOKUPS["reason"]),
            detail=_dig(proof, _LOOKUPS["detail"]),
        ))

    for group in groups.values():
        # Largest first within a group: if a merchant only does some of this, they
        # should do the expensive ones.
        group.items.sort(key=lambda i: -i.amount_paise)

    return sorted(groups.values(), key=lambda g: -g.total_paise)


def to_csv(groups: list[ActionGroup]) -> str:
    """The list as a CSV a merchant can open, sort, or hand to someone else.

    A copy-pasteable artefact is the point: the difference between a dashboard and a
    tool is whether the work leaves the screen.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for group in groups:
        for item in group.items:
            writer.writerow({
                "order_id": item.order_id or "",
                "what": str(item.classification),
                # Rupees, not paise: this file is for a human and a spreadsheet, and
                # `87600` in a column headed "amount" invites a very expensive misread.
                "amount_rupees": f"{item.amount_paise / 100:.2f}",
                "customer_id": item.customer_id or "",
                "email": item.email or "",
                "contact": item.contact or "",
                "subscription_id": item.subscription_id or "",
                "payment_id": item.payment_id or "",
                "reason": item.reason or "",
                "next_step": group.next_step,
            })
    return buffer.getvalue()
