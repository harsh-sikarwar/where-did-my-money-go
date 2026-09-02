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

        self.payments_by_order = {p["order_id"]: p for p in payments if p.get("order_id")}
        self.subscriptions_by_id = {s["id"]: s for s in subscriptions if s.get("id")}

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

    def _resolve(self, finding: Finding) -> Finding:
        """Follow the identifier chain. No inference, no resemblance."""
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
