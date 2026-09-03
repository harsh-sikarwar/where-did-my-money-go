"""Deterministic classification, with proof on every row.

BEHAVIOR.md, stage `classify`:
  Promises  — exactly one label per discrepancy, with the arithmetic attached.
  Refuses   — to pick a winner when more than one rule fits. Multiple matches become
              NEEDS_REVIEW carrying every candidate.
  Bad input — a discrepancy no rule explains is UNEXPLAINED. That is a correct outcome,
              not a failure: the residual IS the honesty metric.

No LLM touches this stage. Arithmetic resolves what arithmetic can prove, and everything
else is admitted rather than guessed.

The refusal to break ties is Cointab's "leave it unmatched when evidence is weak"
(docs/PRIOR-ART.md). Picking the highest-scoring rule would convert a visible ambiguity
into an invisible wrong answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from finctl.calendar import WorkingCalendar
from finctl.config.loader import Config
from finctl.cycle import CycleObservation, observe_cycle
from finctl.fees import expected_fee
from finctl.match.matcher import MatchResult, OrderMatch
from finctl.normalize.normalizer import to_date


class Classification(StrEnum):
    """What explains a discrepancy.

    HALTED_SUBSCRIPTION and PAYMENT_FAILED are assigned by `correlate`, not here — the
    classifier cannot see payment or subscription data by design. They live in this enum
    so there is one vocabulary across both stages.
    """

    RECONCILED = "RECONCILED"                    # no discrepancy at all
    FEE = "FEE"                                  # Razorpay's cut
    TAX_ON_FEE = "TAX_ON_FEE"                    # GST on that cut
    TIMING = "TIMING"                            # not missing, just late
    REFUND = "REFUND"                            # money went back to a customer
    ROUNDING = "ROUNDING"                        # sub-tolerance arithmetic noise
    DUPLICATE = "DUPLICATE"                      # the same order recorded twice
    MISSING = "MISSING"                          # no PSP record at all
    UNEXPLAINED = "UNEXPLAINED"                  # honest residual
    NEEDS_REVIEW = "NEEDS_REVIEW"                # more than one rule fits
    # Assigned by correlate:
    PAYMENT_FAILED = "PAYMENT_FAILED"
    HALTED_SUBSCRIPTION = "HALTED_SUBSCRIPTION"
    UNEXPECTED_SETTLEMENT = "UNEXPECTED_SETTLEMENT"   # money in for an unknown order


# Classifications that mean "this is fine, no action needed". Used by ranking and by
# the verdict screen to separate the benign majority from the short actionable list.
BENIGN = frozenset({
    Classification.RECONCILED,
    Classification.FEE,
    Classification.TAX_ON_FEE,
    Classification.TIMING,
    Classification.ROUNDING,
})


@dataclass
class Finding:
    """One classified discrepancy, carrying the arithmetic that proves it.

    `proof` is structured data, never prose. It goes into the audit log verbatim, is what
    the UI `[detail]` view renders, and is what the LLM is handed to explain — the LLM
    receives facts and returns language, never the reverse.
    """

    order_id: str | None
    classification: Classification
    amount_paise: int
    proof: dict[str, Any] = field(default_factory=dict)
    candidates: list[Classification] = field(default_factory=list)
    settlement_id: str | None = None

    @property
    def is_benign(self) -> bool:
        return self.classification in BENIGN

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "order_id": self.order_id,
            "classification": str(self.classification),
            "amount_paise": self.amount_paise,
            "proof": self.proof,
        }
        if self.candidates:
            out["candidates"] = [str(c) for c in self.candidates]
        if self.settlement_id:
            out["settlement_id"] = self.settlement_id
        return out


@dataclass
class ClassificationResult:
    findings: list[Finding] = field(default_factory=list)

    def by_class(self, classification: Classification) -> list[Finding]:
        return [f for f in self.findings if f.classification == classification]

    def total_paise(self, classification: Classification) -> int:
        return sum(f.amount_paise for f in self.by_class(classification))

    @property
    def unexplained_paise(self) -> int:
        """The honest residual: what arithmetic could not account for.

        This is the number `correlate` is measured against. NEEDS_REVIEW counts toward
        it because an ambiguous explanation is not an explanation.
        """
        return (
            self.total_paise(Classification.UNEXPLAINED)
            + self.total_paise(Classification.MISSING)
            + self.total_paise(Classification.NEEDS_REVIEW)
        )

    def summary(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for f in self.findings:
            entry = out.setdefault(str(f.classification), {"count": 0, "paise": 0})
            entry["count"] += 1
            entry["paise"] += f.amount_paise
        return dict(sorted(out.items(), key=lambda kv: -kv[1]["paise"]))


class Classifier:
    """Applies deterministic rules to matched orders.

    Every rule is a function of the data plus config — never of a threshold hardcoded
    here. Test day varies tolerances and settlement cycles deliberately.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.tol = config.tolerances
        self.calendar = WorkingCalendar(self.tol.weekend_days, self.tol.holidays)
        # Set by classify() from the batch itself. Until then, fall back to config.
        # This exists because the classifier used to judge EVERY batch against the
        # configured T+2 regardless of what the batch actually did — see finctl/cycle.py.
        self.cycle: CycleObservation | None = None

    @property
    def cycle_days(self) -> int:
        """The cycle to judge against: observed where available, configured otherwise."""
        return self.cycle.effective_days if self.cycle else self.tol.cycle_days

    # ------------------------------------------------------------------ rules

    def _check_fee(self, m: OrderMatch) -> tuple[Classification, dict[str, Any]] | None:
        """Does the fee charged match the contracted rate card?

        Two separate labels: FEE for the MDR component, TAX_ON_FEE for the GST on it.
        Splitting them is what lets the verdict screen show 'Razorpay's cut + tax on it'
        as one line while the detail view proves each half independently (ADR-009).
        """
        if not m.recon_rows:
            return None

        method = m.ledger_row.get("payment_method") or m.recon_rows[0].get("method")
        if not method:
            return None

        expected_total = 0
        expected_mdr = 0
        expected_gst = 0
        for row in m.recon_rows:
            fee = expected_fee(row["amount"], row.get("method") or method, self.config.rate_card)
            expected_total += fee.total_fee_paise
            expected_mdr += fee.mdr_paise
            expected_gst += fee.gst_paise

        actual_total = m.fee_paise
        delta = actual_total - expected_total

        proof = {
            "method": method,
            "expected_fee_paise": expected_total,
            "expected_mdr_paise": expected_mdr,
            "expected_gst_paise": expected_gst,
            "actual_fee_paise": actual_total,
            "actual_tax_paise": m.tax_paise,
            "delta_paise": delta,
            "arithmetic": (
                f"charged {actual_total} vs contracted {expected_total} "
                f"(MDR {expected_mdr} + GST on MDR {expected_gst})"
            ),
        }

        # Rounding tolerance scales with the number of settlement legs. Splitting an
        # order across two settlements means the fee is computed and rounded on each
        # HALF, and two roundings of a half can differ from one rounding of the whole by
        # up to one paise per leg. Found on test day: a ₹4,008 order split into two
        # ₹2,004 legs came out ₹0.02 under contract and was flagged as a fee
        # discrepancy. The engine was right that the numbers differed; the tolerance was
        # wrong to assume a single rounding boundary.
        #
        # This is NOT a blanket loosening. It is exactly one paise per rounding boundary
        # the counterparty actually crossed, so a real fee error of even one paise more
        # than that still surfaces.
        allowed = self.tol.rounding_paise * max(len(m.recon_rows), 1)
        if abs(delta) <= allowed:
            return None   # fee is correct; the fee itself is reported separately

        proof["rounding_tolerance_paise"] = allowed
        proof["settlement_legs"] = len(m.recon_rows)
        return Classification.FEE, proof

    def _check_timing(self, m: OrderMatch) -> tuple[Classification, dict[str, Any]] | None:
        """Did it settle later than the cycle allows?

        Not missing, just late — and usually the largest line in the gap, which is the
        point: the biggest number is the one that needs no action.
        """
        captured = to_date(m.ledger_row.get("captured_at"))
        if not captured or not m.recon_rows:
            return None

        settled_dates = [to_date(r["settled_at"]) for r in m.recon_rows if r.get("settled_at")]
        settled_dates = [d for d in settled_dates if d]
        if not settled_dates:
            return None

        actual = max(settled_dates)
        expected: date = self.calendar.add_working_days(captured, self.cycle_days)
        days_late = self.calendar.working_days_between(expected, actual)

        if days_late <= self.tol.grace_days:
            return None

        return Classification.TIMING, {
            "captured_on": captured.isoformat(),
            "expected_settled_on": expected.isoformat(),
            "actual_settled_on": actual.isoformat(),
            "working_days_late": days_late,
            "grace_days": self.tol.grace_days,
            "cycle_days": self.cycle_days,
            "cycle_source": "observed" if self.cycle and self.cycle.observed_days is not None else "configured",
            "arithmetic": (
                f"captured {captured}, T+{self.cycle_days} due {expected}, "
                f"settled {actual} — {days_late} working days late"
            ),
        }

    def _check_amount_gap(self, m: OrderMatch) -> tuple[Classification, dict[str, Any]] | None:
        """Does the ledger's amount match what Razorpay recorded as gross?

        A gap here is NOT a fee question — fees are the difference between gross and net.
        This is the sale itself disagreeing, which usually means a refund recorded on one
        side only, or an amount entered wrongly.
        """
        gap = m.gap_paise
        if abs(gap) <= self.tol.rounding_paise:
            return None

        proof = {
            "ledger_amount_paise": m.ledger_amount_paise,
            "settled_gross_paise": m.settled_gross_paise,
            "gap_paise": gap,
            "arithmetic": (
                f"ledger says {m.ledger_amount_paise}, Razorpay recorded gross "
                f"{m.settled_gross_paise}, difference {gap}"
            ),
        }

        # Direction matters, and it is easy to get backwards — I did, first time.
        #
        # A one-sided refund is a refund the MERCHANT recorded that never reached
        # settlement. Their ledger is therefore written DOWN by the refund while
        # Razorpay still shows the full original amount. So the shape is
        # settlement > ledger, i.e. a NEGATIVE gap under our sign convention
        # (gap = ledger - settled_gross).
        #
        # The opposite sign is a different problem: the ledger expected more than
        # Razorpay ever recorded, which is money that never arrived rather than money
        # that went back. That is not a refund and must not be labelled as one.
        if gap < 0:
            proof["direction"] = "settlement_exceeds_ledger"

            # A ledger amount of ZERO is not a partial refund — it is a sale the
            # merchant recorded as worth nothing while Razorpay settled real money for
            # it. That is a data-entry error, and calling it a refund would tell a
            # merchant they refunded a customer they never refunded.
            #
            # Found by a hand-edited blind test that set one ledger amount to 0. The
            # generator never produces a zero-value order, so no synthetic case could
            # have reached this branch.
            if m.ledger_amount_paise == 0:
                proof["interpretation"] = (
                    "the ledger records this sale as worth nothing, but Razorpay settled "
                    f"{m.settled_gross_paise} for it — a data-entry error rather than a refund"
                )
                return Classification.UNEXPLAINED, proof

            proof["interpretation"] = (
                "merchant's ledger is lower than the settled amount — consistent with a "
                "refund recorded on the merchant side that never reached settlement"
            )
            return Classification.REFUND, proof

        proof["direction"] = "ledger_exceeds_settlement"
        proof["interpretation"] = (
            "ledger expected more than Razorpay recorded; this is a shortfall, not a refund"
        )
        return Classification.UNEXPLAINED, proof

    def _check_settled_refund(
        self, m: OrderMatch
    ) -> tuple[Classification, dict[str, Any]] | None:
        """Did Razorpay debit a settlement to return money to a customer?

        Distinct from the one-sided refund in `_check_amount_gap`, which is a
        DISAGREEMENT between the ledger and the settlement. This is a refund both sides
        agree on: the money genuinely left, so it must be reported rather than netted
        into silence.

        The awkward case this exists for is a refund that settles BEFORE the payment it
        reverses — the debit lands in an earlier settlement than the credit, so a naive
        per-settlement view shows money leaving before it arrived.
        """
        if not m.refund_rows:
            return None

        refunded = m.refunded_paise
        if refunded <= 0:
            return None

        settled_dates = [to_date(r["settled_at"]) for r in m.recon_rows if r.get("settled_at")]
        refund_dates = [to_date(r["settled_at"]) for r in m.refund_rows if r.get("settled_at")]
        settled_dates = [d for d in settled_dates if d]
        refund_dates = [d for d in refund_dates if d]

        early = bool(settled_dates and refund_dates and min(refund_dates) < min(settled_dates))

        return Classification.REFUND, {
            "refunded_paise": refunded,
            "refund_count": len(m.refund_rows),
            "refund_ids": [r.get("entity_id") for r in m.refund_rows],
            "refund_settled_on": min(refund_dates).isoformat() if refund_dates else None,
            "payment_settled_on": min(settled_dates).isoformat() if settled_dates else None,
            "settled_before_the_payment": early,
            "arithmetic": (
                f"{refunded} returned to the customer across {len(m.refund_rows)} "
                f"refund row(s)"
                + (
                    " — settled BEFORE the payment it reverses"
                    if early else ""
                )
            ),
        }

    def _check_rounding(self, m: OrderMatch) -> tuple[Classification, dict[str, Any]] | None:
        """Sub-tolerance arithmetic noise. Reported, not hidden.

        Our own rounding is bounded at one paise per line (ADR-009), so anything here is
        the counterparty's, not ours.
        """
        gap = m.gap_paise
        if gap == 0 or abs(gap) > self.tol.rounding_paise:
            return None
        return Classification.ROUNDING, {
            "gap_paise": gap,
            "tolerance_paise": self.tol.rounding_paise,
            "arithmetic": f"difference of {gap} paise is within the {self.tol.rounding_paise} paise tolerance",
        }

    # ------------------------------------------------------------------ driver

    def classify(self, result: MatchResult) -> ClassificationResult:
        # Establish the settlement cycle from the batch BEFORE judging anything against
        # it. Doing this per-batch rather than from config is the whole point.
        self.cycle = observe_cycle(result, self.calendar, self.tol.cycle_days)

        out = ClassificationResult()

        for m in result.order_matches:
            # Unmatched: no PSP record at all. Correlation gets these next.
            if not m.matched:
                out.findings.append(Finding(
                    order_id=m.order_id,
                    classification=Classification.MISSING,
                    amount_paise=m.ledger_amount_paise,
                    proof={
                        "ledger_amount_paise": m.ledger_amount_paise,
                        "reason": "order present in ledger, absent from settlement recon",
                        "arithmetic": f"expected {m.ledger_amount_paise}, settled 0",
                    },
                ))
                continue

            if m.is_duplicate_order_id:
                out.findings.append(Finding(
                    order_id=m.order_id,
                    classification=Classification.DUPLICATE,
                    amount_paise=m.ledger_amount_paise,
                    proof={
                        "order_id": m.order_id,
                        "occurrences": result.duplicate_order_ids.get(m.order_id, 2),
                        "arithmetic": "same order_id appears more than once in the ledger",
                    },
                ))
                continue

            # Collect every rule that fires. The count decides what happens next.
            hits: list[tuple[Classification, dict[str, Any]]] = []
            for rule in (self._check_fee, self._check_timing,
                         self._check_settled_refund,
                         self._check_amount_gap, self._check_rounding):
                hit = rule(m)
                if hit:
                    hits.append(hit)

            settlement_id = m.recon_rows[0].get("settlement_id") if m.recon_rows else None

            if not hits:
                out.findings.append(Finding(
                    order_id=m.order_id,
                    classification=Classification.RECONCILED,
                    amount_paise=0,
                    proof={
                        "ledger_amount_paise": m.ledger_amount_paise,
                        "settled_net_paise": m.settled_net_paise,
                        "fee_paise": m.fee_paise,
                        "arithmetic": (
                            f"{m.ledger_amount_paise} - {m.fee_paise} fee = "
                            f"{m.settled_net_paise} settled"
                        ),
                    },
                    settlement_id=settlement_id,
                ))
                continue

            # FEE and TIMING are orthogonal: a late settlement charged the wrong fee is
            # two independent facts, not an ambiguity. Emit both.
            # FEE, TIMING and a settled REFUND are orthogonal facts, not competing
            # explanations: an order can be charged the wrong fee, settle late AND have
            # money refunded. Only rules claiming the SAME rupees compete.
            independent = {Classification.FEE, Classification.TIMING}
            money_rules = [h for h in hits if h[0] not in independent]

            for classification, proof in [h for h in hits if h[0] in independent]:
                amount = (
                    abs(proof["delta_paise"]) if classification is Classification.FEE
                    else m.settled_net_paise
                )
                out.findings.append(Finding(
                    order_id=m.order_id, classification=classification,
                    amount_paise=amount, proof=proof, settlement_id=settlement_id,
                ))

            if len(money_rules) > 1:
                # More than one rule claims the SAME rupees. Refuse to pick.
                out.findings.append(Finding(
                    order_id=m.order_id,
                    classification=Classification.NEEDS_REVIEW,
                    amount_paise=abs(m.gap_paise),
                    proof={
                        "reason": "more than one rule explains the same difference",
                        "candidates": {str(c): p for c, p in money_rules},
                        "arithmetic": (
                            "refusing to choose between competing explanations — "
                            "see docs/BEHAVIOR.md, stage `classify`"
                        ),
                    },
                    candidates=[c for c, _ in money_rules],
                    settlement_id=settlement_id,
                ))
            elif money_rules:
                classification, proof = money_rules[0]
                out.findings.append(Finding(
                    order_id=m.order_id, classification=classification,
                    amount_paise=abs(proof.get("gap_paise", m.gap_paise)),
                    proof=proof, settlement_id=settlement_id,
                ))

        # Settlements for orders the ledger never mentioned.
        for row in result.unmatched_recon_orders:
            out.findings.append(Finding(
                order_id=row.get("order_id"),
                classification=Classification.UNEXPECTED_SETTLEMENT,
                amount_paise=row.get("credit", 0) - row.get("debit", 0),
                proof={
                    "entity_id": row.get("entity_id"),
                    "reason": "settlement recorded for an order absent from the ledger",
                    "arithmetic": f"credited {row.get('credit', 0)} for an unknown order",
                },
                settlement_id=row.get("settlement_id"),
            ))

        return out
