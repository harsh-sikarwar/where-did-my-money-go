"""The action list: who to chase, for how much, and why.

The verdict ends with *"One thing needs you this week: those 6 customers"* and, until
this module, could not name them. That is the gap between an insight and a tool, and the
README argues against dashboards precisely because a merchant should be handed the work
rather than a chart of it.

Nothing here is computed. Every field is lifted from a finding's proof — the correlation
stage already resolved `customer_id`, `subscription_id` and `error_reason` on the way to
labelling the gap. This module is a projection, not an analysis, which is why it cannot
disagree with the verdict it accompanies.

THAT CLAIM WAS FALSE UNTIL ADR-049. This module summed `finding.amount_paise`, which is
precisely the mistake `gap.py` exists to prevent: that field is not a contribution to
the gap, it means something different per classification. So the action list and the
verdict screen reported different totals for the same batch — DISPUTED at ₹8,693.87 on
one screen and ₹0.00 on the other. The lesson was learned in `gap.py` and not carried
here, because this module was written later.

The amounts now come from the same `GapDecomposition` the verdict is built from, and
`test_actions.py` asserts the two agree. A docstring claiming a property is not the same
as a test enforcing one.

ADR-048, ADR-049.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from finctl.classify.classifier import BENIGN, Classification, Finding
from finctl.gap import GapDecomposition
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
    # The component total from the gap decomposition. Authoritative: a component may
    # carry no per-order detail (TIMING, the REFUND excess), in which case re-summing
    # `items` would report zero for money the verdict is reporting. None only when no
    # decomposition was supplied.
    component_total_paise: int | None = None

    @property
    def total_paise(self) -> int:
        if self.component_total_paise is not None:
            return self.component_total_paise
        return sum(i.amount_paise for i in self.items)

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification": str(self.classification),
            "next_step": self.next_step,
            "count": len(self.items),
            "total": {"paise": self.total_paise, "display": format_rupees(self.total_paise)},
            "items": [i.as_dict() for i in self.items],
        }


# Excel, LibreOffice and Sheets treat a leading =, +, - or @ as the start of a formula,
# so a `reason` of `=cmd|'/c calc'!A1` becomes executable the moment a merchant opens
# this file. That is not hypothetical here: `reason` and `email` are merchant-supplied
# strings that pass through untouched, and this docstring's whole argument is that the
# file gets opened in a spreadsheet.
#
# Prefixing with a single quote is the standard mitigation: the cell renders as its
# literal text and the leading quote is not part of the value. A tab or CR first is the
# same attack, since the parser strips leading whitespace before looking at the sigil.
_FORMULA_SIGILS = ("=", "+", "-", "@")


def _defuse(value: str) -> str:
    """Neutralise a spreadsheet formula hiding in a merchant-supplied string."""
    if not value:
        return value
    # Leading whitespace is itself part of the attack — Excel skips it before reading
    # the sigil, so " =HYPERLINK(...)" and "\t=..." are live. Check the stripped form
    # for a sigil, but quote the ORIGINAL, since stripping would edit the merchant's
    # own data to defuse it.
    if value.lstrip("\t\r\n ").startswith(_FORMULA_SIGILS):
        return "'" + value
    return value


CSV_COLUMNS = (
    "order_id", "what", "amount_rupees", "customer_id", "email", "contact",
    "subscription_id", "payment_id", "reason", "next_step",
)


def _amounts_from_decomposition(
    decomposition: GapDecomposition | None,
) -> tuple[dict[Classification, dict[str, int]], dict[Classification, int]]:
    """Per-order amounts and per-class totals, taken from the gap decomposition.

    Returns `(per_order, totals)`. `per_order[cls][order_id]` is what that order
    contributes to the gap under that classification; `totals[cls]` is the component
    total, which is authoritative even where per-order detail is unavailable.

    Components are signed and some carry no `order_ids` at all (TIMING and the REFUND
    excess are computed in aggregate). Both facts matter: the group total must come from
    the component, not from re-summing items, or a component without order detail would
    silently report zero.
    """
    per_order: dict[Classification, dict[str, int]] = {}
    totals: dict[Classification, int] = {}
    if decomposition is None:
        return per_order, totals

    for component in decomposition.components:
        totals[component.classification] = (
            totals.get(component.classification, 0) + component.amount_paise
        )
        if not component.order_ids:
            continue
        # Split the component evenly only when it cannot be attributed per order; the
        # decomposition books most components as a sum over named orders, so the even
        # split is a last resort rather than the norm. The remainder goes to the first
        # order so the parts still sum to the component exactly — dropping it would
        # reintroduce the very disagreement this function exists to prevent.
        share, remainder = divmod(component.amount_paise, len(component.order_ids))
        bucket = per_order.setdefault(component.classification, {})
        for index, order_id in enumerate(component.order_ids):
            bucket[order_id] = bucket.get(order_id, 0) + share + (remainder if index == 0 else 0)

    return per_order, totals


def build(
    findings: list[Finding],
    ledger_rows: list[dict[str, Any]] | None = None,
    decomposition: GapDecomposition | None = None,
    actionable: frozenset[Classification] | None = None,
) -> list[ActionGroup]:
    """Group the actionable findings into work, largest group first.

    Only actionable classifications appear. A merchant asking "what needs me?" is not
    asking to be shown the fee they agreed to pay, and including benign rows would
    recreate the dashboard this product exists not to be.

    `actionable` is the set the VERDICT ranked as needing a human, and it is the
    authority on that question when supplied. Filtering on `BENIGN` alone is a coarser
    rule than the one the verdict applies: `tolerances.yaml` also lists REFUND and
    DUPLICATE as `always_benign` ("a bookkeeping divergence to reconcile, not a
    this-week action"), and materiality thresholds can demote a small finding besides.
    With only the `BENIGN` check, this list showed DUPLICATE as work to chase on a
    batch where the verdict called it benign — the two screens disagreed about whether
    ₹2,244 needed the merchant this week. Policy lives in config, so this module has to
    read the same answer rather than a second approximation of it.

    `ledger_rows` supplies the customer for orders that correlation never touched. The
    merchant's own ledger already names the buyer on every row; only the subscription
    join was putting `customer_id` into a proof, so without this the action list could
    name the customer behind a halted subscription and not the one behind a failed
    payment — which is precisely backwards, since the failed payment is the one you
    email today.

    `decomposition` supplies the amounts. Without it this function falls back to
    `finding.amount_paise` and the resulting totals WILL disagree with the verdict —
    that is the ADR-049 bug, kept reachable only so unit tests can construct a group
    from bare findings. Every production caller passes one.
    """
    by_order: dict[str, dict[str, Any]] = {
        row["order_id"]: row
        for row in (ledger_rows or ())
        if row.get("order_id")
    }

    per_order, totals = _amounts_from_decomposition(decomposition)

    groups: dict[Classification, ActionGroup] = {}

    for finding in findings:
        if finding.classification in BENIGN:
            continue
        if actionable is not None and finding.classification not in actionable:
            continue
        # RECONCILED is benign; anything else without a next step is still surfaced,
        # because silence about a finding we HAVE is worse than a generic instruction.
        step = NEXT_STEP.get(finding.classification, "Needs a look.")
        proof = finding.proof or {}
        group = groups.setdefault(
            finding.classification,
            ActionGroup(classification=finding.classification, next_step=step),
        )
        # The proof first — correlation resolved a customer through the subscription
        # join and that is the more specific answer — then the ledger row.
        ledger = by_order.get(finding.order_id or "", {})
        # The amount comes from the gap decomposition where it has one. Falling back to
        # `finding.amount_paise` is what made this list disagree with the verdict, so it
        # applies only when no decomposition was supplied at all (a direct unit-test
        # call); with one supplied, an order the decomposition does not name contributes
        # nothing to the gap and must read zero rather than a number of its own.
        if decomposition is None:
            amount = finding.amount_paise
        else:
            # Keyed by order, or by the refund entity where there is no order — an
            # unrecorded refund has no order_id on either side by definition.
            key = finding.order_id or proof.get("entity_id") or ""
            amount = per_order.get(finding.classification, {}).get(key, 0)
        group.items.append(ActionItem(
            order_id=finding.order_id,
            classification=finding.classification,
            amount_paise=amount,
            customer_id=_dig(proof, _LOOKUPS["customer_id"]) or ledger.get("customer_id"),
            email=_dig(proof, _LOOKUPS["email"]) or ledger.get("email"),
            contact=_dig(proof, _LOOKUPS["contact"]) or ledger.get("contact"),
            subscription_id=_dig(proof, _LOOKUPS["subscription_id"]),
            payment_id=_dig(proof, _LOOKUPS["payment_id"]),
            reason=_dig(proof, _LOOKUPS["reason"]),
            detail=_dig(proof, _LOOKUPS["detail"]),
        ))

    for group in groups.values():
        if decomposition is not None:
            group.component_total_paise = totals.get(group.classification, 0)
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
                "order_id": _defuse(item.order_id or ""),
                "what": str(item.classification),
                # Rupees, not paise: this file is for a human and a spreadsheet, and
                # `87600` in a column headed "amount" invites a very expensive misread.
                "amount_rupees": f"{item.amount_paise / 100:.2f}",
                "customer_id": _defuse(item.customer_id or ""),
                "email": _defuse(item.email or ""),
                "contact": _defuse(item.contact or ""),
                "subscription_id": _defuse(item.subscription_id or ""),
                "payment_id": _defuse(item.payment_id or ""),
                "reason": _defuse(item.reason or ""),
                "next_step": group.next_step,
            })
    return buffer.getvalue()
