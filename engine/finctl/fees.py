"""Expected-fee arithmetic. Deterministic, no LLM, proof on every result.

This computes what the rate card SAYS the fee should be. Comparing that against what
Razorpay actually charged is the FEE / TAX_ON_FEE classification.

Distinguish two questions that are easy to conflate:

  1. "Was the fee what my contract says?"   <- this module, from the rate card
  2. "How is the fee encoded in the data?"  <- ADR-007, derived from the data

Question 2 must never be answered from the rate card. If we assumed a convention and
the data used the other one, every card transaction would be wrong by the GST amount,
silently absorbed into the residual. That is the exact failure this product exists to
detect, occurring inside the product.
"""

from __future__ import annotations

from dataclasses import dataclass

from finctl.config.loader import RateCard
from finctl.money import apply_bps


@dataclass(frozen=True)
class FeeBreakdown:
    """An expected fee, with the arithmetic that produced it.

    BEHAVIOR.md global invariant 3: every classification carries its proof, as data,
    not prose. This dataclass IS that proof — it goes into the audit log verbatim and
    is what the UI's [detail] view renders.
    """

    method: str
    amount_paise: int
    mdr_bps: int
    mdr_paise: int
    gst_rate_bps: int
    gst_paise: int
    fixed_fee_paise: int

    @property
    def total_fee_paise(self) -> int:
        """MDR + GST on MDR + any fixed fee. What Razorpay should keep."""
        return self.mdr_paise + self.gst_paise + self.fixed_fee_paise

    @property
    def net_paise(self) -> int:
        """What should reach the bank."""
        return self.amount_paise - self.total_fee_paise

    def explain(self) -> str:
        """One-line human-readable proof. Used in console output and audit entries."""
        from finctl.money import format_rupees

        return (
            f"{self.method}: {format_rupees(self.amount_paise)} "
            f"× {self.mdr_bps / 100:.2f}% MDR = {format_rupees(self.mdr_paise)}, "
            f"+ {self.gst_rate_bps / 100:.0f}% GST on MDR = {format_rupees(self.gst_paise)}"
            + (f", + fixed {format_rupees(self.fixed_fee_paise)}" if self.fixed_fee_paise else "")
            + f" → fee {format_rupees(self.total_fee_paise)}, "
            f"net {format_rupees(self.net_paise)}"
        )

    def as_dict(self) -> dict[str, int | str]:
        """Flat dict for the JSONL audit log."""
        return {
            "method": self.method,
            "amount_paise": self.amount_paise,
            "mdr_bps": self.mdr_bps,
            "mdr_paise": self.mdr_paise,
            "gst_rate_bps": self.gst_rate_bps,
            "gst_paise": self.gst_paise,
            "fixed_fee_paise": self.fixed_fee_paise,
            "total_fee_paise": self.total_fee_paise,
            "net_paise": self.net_paise,
        }


def expected_fee(amount_paise: int, method: str, rate_card: RateCard) -> FeeBreakdown:
    """Compute the contracted fee for one transaction.

    GST is levied on the MDR, never on the transaction amount. On a ₹10,000 card
    payment: MDR ₹200, GST on that ₹36, net ₹9,764 — not ₹10,000 × 18%.

    By default GST is computed on the ROUNDED MDR (rate_card.gst_on_rounded_mdr),
    so a merchant can verify the MDR line without reproducing our GST arithmetic.
    See ADR-009.

    Raises ConfigError for an unpriced method — never assumes a default rate.
    """
    rate = rate_card.rate_for(method)
    mode = rate_card.rounding_mode

    mdr_paise = apply_bps(amount_paise, rate.mdr_bps, mode)

    if rate_card.gst_on_rounded_mdr:
        # Default. GST is computed on the MDR the merchant can see and verify.
        gst_paise = apply_bps(mdr_paise, rate_card.gst_rate_bps, mode)
    else:
        # GST against the UNROUNDED MDR: fold both rates into a single basis-point
        # product and divide once, so only one rounding boundary exists. Staying in
        # integer bps means no float enters the calculation at any point.
        combined_bps = rate.mdr_bps * rate_card.gst_rate_bps  # bps squared
        gst_paise = apply_bps(amount_paise, combined_bps, mode) // 10_000

    return FeeBreakdown(
        method=method,
        amount_paise=amount_paise,
        mdr_bps=rate.mdr_bps,
        mdr_paise=mdr_paise,
        gst_rate_bps=rate_card.gst_rate_bps,
        gst_paise=gst_paise,
        fixed_fee_paise=rate_card.fixed_fee_paise,
    )
