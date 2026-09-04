"""Correlation — the differentiator.

BEHAVIOR.md, stage `correlate`:
  Promises  — for every UNEXPLAINED row, look up the payment record and the subscription
              record. Report unexplained rupees BEFORE vs AFTER. That delta is the
              headline metric.
  Refuses   — to infer a cause from resemblance. Correlation follows the identifier join
              chain and nothing else. If the join does not land, the row stays
              UNEXPLAINED.
  Bad input — a gap that LOOKS like a halted subscription but has no subscription record
              must remain UNEXPLAINED. If the engine claims it, that is a real finding.

The thesis, in one paragraph: existing tools are architecturally siloed. Recovery,
reconciliation and cost are separate products, so an anomaly spanning two of them has no
owner and reaches the merchant as "unexplained". This stage crosses that boundary — it
takes reconciliation's residual and resolves it with recovery's data.

It is a JOIN, not a judgment. That is the point, and it is why no LLM is involved:

    ledger.order_id -> payment.order_id -> payment.subscription_id -> subscription.status

Every step is an identifier equality. Either it lands or it does not.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from finctl.classify.classifier import Classification, ClassificationResult, Finding
from finctl.schema import Source
from finctl.stage.staging import StagedBatch

# Failure buckets. Retry advice differs fundamentally, and a risk block must NEVER be
# recommended for retry — retrying it is at best futile and at worst account-damaging.
RETRY_LATER = frozenset({
    "insufficient_funds", "incorrect_otp", "card_expired", "invalid_cvv",
    "payment_failed_due_to_customer_cancellation",
})
RETRY_SOON = frozenset({
    "gateway_timeout", "gateway_error", "issuer_down", "network_error", "server_error",
})
NEVER_RETRY = frozenset({
    "payment_risk_check_failed", "fraud_suspected", "card_blocked", "account_blocked",
})


def failure_bucket(error_reason: str | None) -> str:
    """Which of the three failure buckets a decline falls into.

    Unknown reasons return 'unknown' rather than a guess. An unrecognised decline code
    getting silently sorted into 'retry' would produce confident bad advice.
    """
    if not error_reason:
        return "unknown"
    if error_reason in NEVER_RETRY:
        return "never_retry"
    if error_reason in RETRY_LATER:
        return "retry_later"
    if error_reason in RETRY_SOON:
        return "retry_soon"
    return "unknown"


@dataclass
class CorrelationResult:
    """Before/after, plus what changed and why.

    `unexplained_before` and `unexplained_after` are the headline. The delta between them
    is the entire claim of this project, measured rather than asserted.
    """

    unexplained_before_paise: int = 0
    unexplained_after_paise: int = 0
    resolved: list[Finding] = field(default_factory=list)
    still_unexplained: list[Finding] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def resolved_paise(self) -> int:
        return self.unexplained_before_paise - self.unexplained_after_paise

    @property
    def gain_ratio(self) -> float:
        """Fraction of the unexplained residual that correlation resolved.

        Zero-before returns 0.0, not 1.0 — nothing to resolve is not a perfect score
        (same reasoning as ADR-016).
        """
        if self.unexplained_before_paise == 0:
            return 0.0
        return self.resolved_paise / self.unexplained_before_paise

    def by_class(self, classification: Classification) -> list[Finding]:
        return [f for f in self.findings if f.classification == classification]

    def summary(self) -> dict[str, Any]:
        return {
            "unexplained_before_paise": self.unexplained_before_paise,
            "unexplained_after_paise": self.unexplained_after_paise,
            "resolved_paise": self.resolved_paise,
            "gain_ratio": round(self.gain_ratio, 4),
            "resolved_count": len(self.resolved),
            "still_unexplained_count": len(self.still_unexplained),
            "resolved_by_class": {
                str(c): {
                    "count": len([f for f in self.resolved if f.classification == c]),
                    "paise": sum(f.amount_paise for f in self.resolved if f.classification == c),
                }
                for c in (Classification.HALTED_SUBSCRIPTION, Classification.PAYMENT_FAILED)
                if any(f.classification == c for f in self.resolved)
            },
        }


class Correlator:
    """Resolves the unexplained residual using payment and subscription data."""

    # Classifications correlation is allowed to work on. Anything already explained by
    # arithmetic is left alone — correlation adds evidence, it never overrides proof.
    CORRELATABLE = frozenset({
        Classification.MISSING,
        Classification.UNEXPLAINED,
        Classification.NEEDS_REVIEW,
    })

    def __init__(self, batch: StagedBatch) -> None:
        payments = batch.get(Source.PAYMENTS)
        subscriptions = batch.get(Source.SUBSCRIPTIONS)
        recon = batch.get(Source.RECON)

        self.payments_by_order = {p["order_id"]: p for p in payments if p.get("order_id")}
        self.subscriptions_by_id = {s["id"]: s for s in subscriptions if s.get("id")}

        # Recon rows indexed by order, for the withholding joins. The CLASSIFIER already
        # reads `dispute_id` and `on_hold` (ADR-036, ADR-041) — but only on an order it
        # MATCHED. An order the ledger has and the matcher could not pair reaches
        # correlation as MISSING, and those two fields never get looked at. So a
        # disputed payment behind a missing order came out as a generic PAYMENT_FAILED,
        # losing the fact that there is a deadline attached. See ADR-049.
        self.recon_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in recon:
            if row.get("order_id"):
                self.recon_by_order[row["order_id"]].append(row)

    def correlate(self, classified: ClassificationResult) -> CorrelationResult:
        out = CorrelationResult()
        out.unexplained_before_paise = classified.unexplained_paise

        for finding in classified.findings:
            if finding.classification not in self.CORRELATABLE:
                out.findings.append(finding)
                continue

            resolved = self._resolve(finding)
            out.findings.append(resolved)

            if resolved.classification in self.CORRELATABLE:
                out.still_unexplained.append(resolved)
            else:
                out.resolved.append(resolved)

        out.unexplained_after_paise = sum(f.amount_paise for f in out.still_unexplained)
        return out

    def _withholding(self, finding: Finding) -> Finding | None:
        """Is the PSP holding this money, rather than the payment having failed?

        Two mechanisms, both reading fields Razorpay's own recon export carries:

          `dispute_id`  a customer charged back. There is a response deadline.
          `on_hold`     Razorpay is withholding on purpose, pending KYC or a review.

        Both are checked on the recon rows for the order AND on the payment record,
        because a real export puts `dispute_id` in both places and the one we have
        depends on which files a merchant uploaded.

        Returns None when neither applies, so the payment-failure path runs unchanged.
        """
        rows = self.recon_by_order.get(finding.order_id or "", [])
        payment = self.payments_by_order.get(finding.order_id) if finding.order_id else None
        sources = [*rows, payment] if payment else list(rows)

        disputed = next((r for r in sources if r.get("dispute_id")), None)
        if disputed is not None:
            return Finding(
                order_id=finding.order_id,
                classification=Classification.DISPUTED,
                amount_paise=finding.amount_paise,
                proof={
                    **finding.proof,
                    "correlation": {
                        "attempted": True,
                        "outcome": "resolved: the customer disputed this payment",
                        "join_chain": "order_id -> recon.dispute_id / payment.dispute_id",
                        "dispute_id": disputed.get("dispute_id"),
                        "dispute_reason": disputed.get("dispute_reason"),
                        "dispute_created_at": disputed.get("dispute_created_at"),
                        "payment_id": (payment or {}).get("id") or disputed.get("entity_id"),
                        "error_reason": disputed.get("dispute_reason") or "disputed",
                        "explanation": (
                            "A customer has contested this payment with their bank. "
                            "Razorpay is holding the money or has taken it back. Unlike "
                            "a delay this does not resolve itself: there is a window to "
                            "submit evidence, and missing it forfeits the money."
                        ),
                    },
                },
                settlement_id=finding.settlement_id,
            )

        held = next((r for r in sources if r.get("on_hold")), None)
        if held is not None:
            return Finding(
                order_id=finding.order_id,
                classification=Classification.ON_HOLD,
                amount_paise=finding.amount_paise,
                proof={
                    **finding.proof,
                    "correlation": {
                        "attempted": True,
                        "outcome": "resolved: Razorpay is withholding this settlement",
                        "join_chain": "order_id -> recon.on_hold",
                        "hold_reason": held.get("hold_reason"),
                        "error_reason": held.get("hold_reason") or "on_hold",
                        "settled": held.get("settled"),
                        "payment_id": (payment or {}).get("id") or held.get("entity_id"),
                        "explanation": (
                            "Razorpay is deliberately holding this money rather than "
                            "settling it — usually pending KYC, a risk review, or a "
                            "dispute. Waiting will not release it."
                        ),
                    },
                },
                settlement_id=finding.settlement_id,
            )

        return None

    def _resolve(self, finding: Finding) -> Finding:
        """Follow the identifier chain. No inference, no resemblance."""
        # Withholding first. A dispute or a hold is a fact about the SETTLEMENT and
        # outranks anything the payment record says: money Razorpay is keeping has a
        # deadline or a dashboard action attached, and "the payment failed" would send a
        # merchant to retry a charge instead. See ADR-049.
        withheld = self._withholding(finding)
        if withheld is not None:
            return withheld

        payment = self.payments_by_order.get(finding.order_id) if finding.order_id else None

        if payment is None:
            # No payment record at all. There is genuinely nothing to correlate with,
            # and saying so is the honest answer.
            finding.proof["correlation"] = {
                "attempted": True,
                "outcome": "no payment record found for this order_id",
            }
            return finding

        if payment.get("status") != "failed":
            finding.proof["correlation"] = {
                "attempted": True,
                "payment_id": payment.get("id"),
                "payment_status": payment.get("status"),
                "outcome": "payment exists and did not fail; the gap is not a payment failure",
            }
            return finding

        # --- the payment failed. Is a halted subscription the cause? ---
        subscription_id = payment.get("subscription_id")
        subscription = self.subscriptions_by_id.get(subscription_id) if subscription_id else None

        if subscription is not None and subscription.get("status") == "halted":
            # Both conditions must hold: the payment references a subscription AND that
            # subscription is actually halted. Resemblance is not enough — a failed
            # subscription payment on an ACTIVE subscription is a normal retryable
            # failure, not silent revenue death.
            return Finding(
                order_id=finding.order_id,
                classification=Classification.HALTED_SUBSCRIPTION,
                amount_paise=finding.amount_paise,
                proof={
                    **finding.proof,
                    "correlation": {
                        "attempted": True,
                        "outcome": "resolved: subscription is halted",
                        "join_chain": "order_id -> payment.subscription_id -> subscription.status",
                        "payment_id": payment.get("id"),
                        "subscription_id": subscription_id,
                        "subscription_status": subscription.get("status"),
                        "invoice_id": payment.get("invoice_id"),
                        "auth_attempts": subscription.get("auth_attempts"),
                        "remaining_count": subscription.get("remaining_count"),
                        "customer_id": subscription.get("customer_id"),
                        "error_reason": payment.get("error_reason"),
                        "explanation": (
                            "Razorpay continues generating invoices for a halted "
                            "subscription but does not attempt charges. Invoices keep "
                            "appearing; no money is ever collected."
                        ),
                    },
                },
                settlement_id=finding.settlement_id,
            )

        # --- failed payment, no halted subscription behind it ---
        reason = payment.get("error_reason")
        return Finding(
            order_id=finding.order_id,
            classification=Classification.PAYMENT_FAILED,
            amount_paise=finding.amount_paise,
            proof={
                **finding.proof,
                "correlation": {
                    "attempted": True,
                    "outcome": "resolved: payment failed",
                    "join_chain": "order_id -> payment.status",
                    "payment_id": payment.get("id"),
                    "error_code": payment.get("error_code"),
                    "error_reason": reason,
                    "error_description": payment.get("error_description"),
                    "error_source": payment.get("error_source"),
                    "error_step": payment.get("error_step"),
                    "failure_bucket": failure_bucket(reason),
                    "subscription_id": subscription_id,
                    "subscription_status": (
                        subscription.get("status") if subscription else None
                    ),
                },
            },
            settlement_id=finding.settlement_id,
        )
