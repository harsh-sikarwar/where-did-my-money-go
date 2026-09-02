"""The canonical schema, and the column mappings that reach it.

ADR-008: field names follow Razorpay's real response, including its oddities, so that
swapping seeded data for live API data is a SOURCE change rather than a SCHEMA change.
Every rename is a place the Day-2 swap can silently mismatch under a 2-hour timebox —
precisely when there is no time to debug it.

The alias tables below exist because a merchant's CSV export does not use our column
names. They are explicit and finite: normalize resolves through this table or raises.
It never guesses, and never falls back to column position.
"""

from __future__ import annotations

from enum import StrEnum


class Source(StrEnum):
    """Where a record came from. Side A vs Side B, in Cointab's terms."""

    LEDGER = "ledger"       # the merchant's record of what SHOULD have happened
    RECON = "recon"         # Razorpay's settlement recon report
    BANK = "bank"           # the bank statement — what ACTUALLY arrived
    PAYMENTS = "payments"   # payment records, including failures
    SUBSCRIPTIONS = "subscriptions"


class ReconType(StrEnum):
    """Razorpay's recon row discriminator (ADR-008).

    Refunds are ROWS with this set to `refund`, not a column on a payment row.
    """

    PAYMENT = "payment"
    REFUND = "refund"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"


class MatchStatus(StrEnum):
    """Adopted from Hyperswitch, not invented — see docs/PRIOR-ART.md.

    PARTIALLY_RECONCILED is deliberately absent from anything the engine can assign:
    a machine that can mark its own work partially done will use that state to hide
    uncertainty. It exists in the vocabulary for humans only.
    """

    PENDING = "Pending"
    RECONCILED = "Reconciled"
    EXCEPTION = "Exception"
    PARTIALLY_RECONCILED = "Partially Reconciled"   # humans only
    ARCHIVED = "Archived"
    VOID = "Void"


# Canonical columns per source. Order is the on-disk order; it carries no meaning,
# because nothing in this engine matches positionally.
LEDGER_COLUMNS = ("order_id", "amount_paise", "captured_at", "customer_id", "payment_method")
BANK_COLUMNS = ("utr", "credit_paise", "value_date")

# Column aliases. Keys are canonical names; values are the input spellings accepted.
# Matching is case-insensitive and ignores spaces, hyphens and underscores, so
# "Order ID", "order-id" and "ORDER_ID" all resolve without needing separate entries.
#
# Deliberately conservative. An alias that is merely PLAUSIBLE is worse than a missing
# one: a missing alias raises and gets fixed in seconds, while a wrong alias silently
# reconciles the wrong column and is found much later, if ever.
LEDGER_ALIASES: dict[str, tuple[str, ...]] = {
    "order_id": ("order_id", "orderid", "order", "order_ref", "order_reference",
                 "receipt", "reference", "ref"),
    "amount_paise": ("amount", "amount_paise", "order_amount", "value", "total",
                     "gross", "gross_amount", "sale_amount"),
    "captured_at": ("timestamp", "captured_at", "created_at", "date", "order_date",
                    "transaction_date", "datetime"),
    "customer_id": ("customer_id", "customerid", "customer", "cust_id", "buyer_id"),
    "payment_method": ("payment_method", "method", "mode", "payment_mode", "rail",
                       "instrument"),
}

BANK_ALIASES: dict[str, tuple[str, ...]] = {
    "utr": ("utr", "utr_number", "utr_no", "reference", "ref_no", "transaction_ref",
            "bank_reference", "rrn"),
    "credit_paise": ("credit_amount", "credit", "amount", "credit_paise", "deposit",
                     "amount_credited"),
    "value_date": ("value_date", "date", "txn_date", "transaction_date", "posting_date",
                   "credit_date"),
}

# Columns that must be present. A missing one raises rather than defaulting, because a
# defaulted identifier silently matches nothing and a defaulted amount silently
# reconciles to zero — both look like data problems rather than mapping problems.
LEDGER_REQUIRED = ("order_id", "amount_paise")
BANK_REQUIRED = ("utr", "credit_paise")


def normalise_key(name: str) -> str:
    """Fold a column name for alias comparison.

    "Order ID", "order-id", "ORDER_ID" and "order id" all fold to "orderid".
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())
