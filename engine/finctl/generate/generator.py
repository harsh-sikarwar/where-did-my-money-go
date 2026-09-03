"""Seeded synthetic data generator.

Emits Razorpay-shaped records for a given (seed, volume, archetype, payment mix,
settlement cycle, defect profile), plus a machine-readable ground truth (ADR-004).

Two design rules that matter more than they look:

1. **Field shapes follow Razorpay's real response, including its oddities** (ADR-008).
   Recon rows are type-discriminated; `payment_id` is null on payment rows and the id
   lives in `entity_id`; refunds are their own DEBIT rows rather than a column. Getting
   this right here is what makes the Day-2 live swap a source change, not a schema change.

2. **Fees are computed with the same code the engine uses to check them.** That sounds
   circular and is deliberate: the generator models a *correct* Razorpay, and defects are
   introduced by explicitly perturbing that correct baseline. A defect is then the
   difference between what the rate card says and what we deliberately wrote — which is
   exactly what the classifier must find. If instead the generator had its own fee logic,
   a shared misunderstanding would produce a batch that reconciles perfectly and proves
   nothing.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from finctl.calendar import WorkingCalendar
from finctl.config.loader import Config
from finctl.fees import expected_fee
from finctl.generate.ground_truth import DefectType, GroundTruth, PlantedDefect
from finctl.money import apply_bps

_ID_ALPHABET = string.ascii_letters + string.digits


@dataclass
class GeneratedBatch:
    """Everything one run produces.

    Held in memory as plain dicts rather than DataFrames: the writer decides the on-disk
    format, and the normalize stage must be exercised against real CSV text anyway.
    """

    ledger: list[dict[str, Any]] = field(default_factory=list)
    recon: list[dict[str, Any]] = field(default_factory=list)
    bank: list[dict[str, Any]] = field(default_factory=list)
    payments: list[dict[str, Any]] = field(default_factory=list)
    subscriptions: list[dict[str, Any]] = field(default_factory=list)
    ground_truth: GroundTruth | None = None


class Generator:
    """Deterministic given a seed. Two runs with the same parameters are identical."""

    def __init__(
        self,
        config: Config,
        *,
        seed: int = 20260902,
        archetype: str = "saas_subscription",
        payment_mix: str | None = None,
        volume: int = 200,
        settlement_cycle_days: int | None = None,
        defect_profile: str = "demo",
        start_date: date | None = None,
        fee_convention: str = "gst_inclusive",
    ) -> None:
        if volume < 1:
            raise ValueError(f"volume must be at least 1, got {volume}")
        if fee_convention not in ("gst_inclusive", "mdr_only"):
            raise ValueError(
                f"fee_convention must be 'gst_inclusive' or 'mdr_only', got {fee_convention!r}"
            )
        self.fee_convention = fee_convention

        self.config = config
        self.seed = seed
        self.rng = random.Random(seed)
        self.archetype = config.archetype(archetype)   # raises, listing valid names
        self.volume = volume
        self.defect_profile_name = defect_profile

        # An explicit payment mix overrides the archetype's own distribution, so the
        # payment-mix axis can be varied independently on test day.
        if payment_mix:
            self.mix = config.payment_mix(payment_mix).mix
            self.payment_mix_name = payment_mix
        else:
            self.mix = self.archetype.payment_mix
            self.payment_mix_name = f"{archetype}-default"

        self.cycle_days = (
            settlement_cycle_days
            if settlement_cycle_days is not None
            else config.tolerances.cycle_days
        )
        self.calendar = WorkingCalendar(
            config.tolerances.weekend_days, config.tolerances.holidays
        )
        self.start_date = start_date or date(2026, 8, 3)  # a Monday

        self.defects = self._load_defect_profile(defect_profile)

    # ---------------------------------------------------------------- config

    def _load_defect_profile(self, name: str) -> dict[str, dict[str, Any]]:
        import yaml

        from finctl.config.loader import DEFAULTS_DIR, ConfigError

        profiles = yaml.safe_load((DEFAULTS_DIR / "defects.yaml").read_text())
        if name not in profiles:
            raise ConfigError(f"unknown defect profile {name!r}. Known: {sorted(profiles)}")
        return {k: v for k, v in profiles[name].items() if k != "description"}

    def _defect_count(self, defect_type: str) -> int:
        """How many of this defect to plant. Absolute count or a rate of the batch."""
        spec = self.defects.get(defect_type)
        if not spec:
            return 0
        if "count" in spec:
            return min(spec["count"], self.volume)
        if "rate" in spec:
            return int(self.volume * spec["rate"])
        return 0

    # ---------------------------------------------------------------- ids

    def _rid(self, prefix: str, length: int = 14) -> str:
        """A Razorpay-shaped id. Drawn from the seeded RNG, so ids are reproducible."""
        return prefix + "".join(self.rng.choice(_ID_ALPHABET) for _ in range(length))

    @staticmethod
    def _ts(day: date, hour: int = 10, minute: int = 0) -> int:
        """Unix timestamp, UTC. Razorpay returns integer epoch seconds."""
        return int(datetime.combine(day, time(hour, minute), tzinfo=UTC).timestamp())

    # ---------------------------------------------------------------- pieces

    def _pick_method(self) -> str:
        methods = list(self.mix)
        weights = [self.mix[m] for m in methods]
        return self.rng.choices(methods, weights=weights, k=1)[0]

    def _pick_amount(self) -> int:
        """A ticket size in paise, rounded to whole rupees as a real price would be."""
        lo, hi = self.archetype.ticket_min_paise, self.archetype.ticket_max_paise
        return self.rng.randrange(lo // 100, hi // 100 + 1) * 100

    def _order_dates(self) -> list[date]:
        """Spread orders across working days, with Fridays deliberately over-weighted.

        The timing defect is 'Friday orders land Tuesday'. That story only exists if
        Fridays actually carry a disproportionate share of volume, which is also true of
        real consumer businesses.
        """
        days: list[date] = []
        cursor = self.start_date
        while len(days) < 30:
            if self.calendar.is_working_day(cursor):
                days.append(cursor)
            cursor += timedelta(days=1)

        weights = [3.0 if d.weekday() == 4 else 1.0 for d in days]
        return self.rng.choices(days, weights=weights, k=self.volume)

    # ---------------------------------------------------------------- main

    def generate(self) -> GeneratedBatch:
        batch = GeneratedBatch()
        gt = GroundTruth(
            seed=self.seed,
            archetype=self.archetype.name,
            payment_mix=self.payment_mix_name,
            volume=self.volume,
            settlement_cycle_days=self.cycle_days,
            defect_profile=self.defect_profile_name,
        )

        order_days = sorted(self._order_dates())

        # Decide up front which order indices carry which defect, so no order is given
        # two conflicting defects and the counts are exact rather than probabilistic.
        indices = list(range(self.volume))
        self.rng.shuffle(indices)
        # Each order carries at most one defect, so the demanded counts must fit inside
        # the batch. If they do not, the slices below run off the end and the LAST
        # defect types silently get nothing -- while ground truth still claims they were
        # planted. That produces a batch whose metrics are confidently wrong, which is
        # the one failure mode this project cannot tolerate. So: refuse, loudly, naming
        # the arithmetic. Found by a test at volume=40 (51 defects demanded), where it
        # had silently produced zero halted subscriptions.
        demanded = {dt: self._defect_count(dt) for dt in (
            DefectType.MISSING_ORDER,
            DefectType.WRONG_FEE_RATE,
            DefectType.ONE_SIDED_REFUND,
            DefectType.HALTED_SUBSCRIPTION,
            DefectType.TIMING_LAG,
            DefectType.SPLIT_SETTLEMENT,
            DefectType.EARLY_REFUND,
        )}
        total_demanded = sum(demanded.values())
        if total_demanded > self.volume:
            breakdown = ", ".join(f"{k}={v}" for k, v in demanded.items() if v)
            raise ValueError(
                f"defect profile {self.defect_profile_name!r} demands {total_demanded} "
                f"defects but the batch has only {self.volume} orders ({breakdown}). "
                "Each order carries at most one defect. Either raise --volume or use a "
                "rate-based profile such as 'scale'."
            )

        cursor = 0
        assigned: dict[str, set[int]] = {}
        for defect_type, n in demanded.items():
            assigned[defect_type] = set(indices[cursor : cursor + n])
            cursor += n

        settlement_groups: dict[date, list[dict[str, Any]]] = {}

        for i, order_day in enumerate(order_days):
            order_id = self._rid("order_")
            payment_id = self._rid("pay_")
            method = self._pick_method()
            amount = self._pick_amount()
            customer_id = self._rid("cust_", 10)

            is_subscription = self.rng.random() < self.archetype.subscription_share

            batch.ledger.append({
                "order_id": order_id,
                "amount": amount,
                "timestamp": self._ts(order_day, self.rng.randrange(9, 20)),
                "customer_id": customer_id,
                "payment_method": method,
            })

            gt.total_orders += 1
            gt.total_gross_paise += amount

            # ---- DEFECT: halted subscription ----------------------------------
            # Invoice generated, charge never attempted. The money never enters the
            # settlement stream at all, which is why it reads as a plain gap until
            # correlation looks up the subscription.
            if i in assigned[DefectType.HALTED_SUBSCRIPTION]:
                sub_id = self._rid("sub_")
                batch.subscriptions.append({
                    "id": sub_id,
                    "entity": "subscription",
                    "plan_id": self._rid("plan_"),
                    "customer_id": customer_id,
                    "status": "halted",
                    "auth_attempts": 3,
                    "paid_count": self.rng.randrange(2, 8),
                    "total_count": 12,
                    "remaining_count": self.rng.randrange(3, 9),
                    "current_start": self._ts(order_day),
                    "current_end": self._ts(order_day + timedelta(days=30)),
                    "charge_at": self._ts(order_day + timedelta(days=30)),
                    "created_at": self._ts(order_day - timedelta(days=90)),
                    "payment_method": method,
                    "notes": {"order_id": order_id},
                })
                # An invoice exists — this is the cruel part of the halted state.
                batch.payments.append({
                    "id": payment_id,
                    "entity": "payment",
                    "amount": amount,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": order_id,
                    "invoice_id": self._rid("inv_"),
                    "subscription_id": sub_id,
                    "method": method,
                    "captured": False,
                    "amount_refunded": 0,
                    "fee": None,
                    "tax": None,
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Subscription is halted; no charge was attempted",
                    "error_source": "internal",
                    "error_step": "payment_initiation",
                    "error_reason": "subscription_halted",
                    "created_at": self._ts(order_day),
                })
                gt.add(PlantedDefect(
                    defect_id=f"halted-{sub_id}",
                    defect_type=DefectType.HALTED_SUBSCRIPTION,
                    order_id=order_id,
                    impact_paise=amount,
                    expected_classification="HALTED_SUBSCRIPTION",
                    detail={"subscription_id": sub_id, "payment_id": payment_id,
                            "customer_id": customer_id},
                ))
                continue

            # ---- DEFECT: missing order ----------------------------------------
            # Payment failed, so it never reached settlement. Indistinguishable from
            # lost money until correlation reads error_reason.
            if i in assigned[DefectType.MISSING_ORDER]:
                reason, desc, source, step = self.rng.choice([
                    ("insufficient_funds", "Card has insufficient funds", "bank", "payment_authorization"),
                    ("incorrect_otp", "Payment failed because of incorrect OTP", "customer", "payment_authentication"),
                    ("payment_risk_check_failed", "Payment flagged as suspicious", "internal", "payment_initiation"),
                ])
                batch.payments.append({
                    "id": payment_id,
                    "entity": "payment",
                    "amount": amount,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": order_id,
                    "invoice_id": None,
                    "subscription_id": None,
                    "method": method,
                    "captured": False,
                    "amount_refunded": 0,
                    "fee": None,
                    "tax": None,
                    "error_code": "GATEWAY_ERROR" if source == "bank" else "BAD_REQUEST_ERROR",
                    "error_description": desc,
                    "error_source": source,
                    "error_step": step,
                    "error_reason": reason,
                    "created_at": self._ts(order_day),
                })
                gt.add(PlantedDefect(
                    defect_id=f"missing-{order_id}",
                    defect_type=DefectType.MISSING_ORDER,
                    order_id=order_id,
                    impact_paise=amount,
                    expected_classification="MISSING",
                    detail={"payment_id": payment_id, "error_reason": reason},
                ))
                continue

            # ---- the happy path: a captured payment that settles -----------------
            fee_breakdown = expected_fee(amount, method, self.config.rate_card)
            fee_paise = fee_breakdown.total_fee_paise
            tax_paise = fee_breakdown.gst_paise

            # ---- DEFECT: wrong fee rate ---------------------------------------
            # Razorpay charged more than the contract. The overcharge is the impact.
            if i in assigned[DefectType.WRONG_FEE_RATE]:
                extra_bps = self.defects[DefectType.WRONG_FEE_RATE].get("overcharge_bps", 25)
                overcharge = apply_bps(amount, extra_bps, self.config.rate_card.rounding_mode)
                fee_paise += overcharge
                gt.add(PlantedDefect(
                    defect_id=f"fee-{order_id}",
                    defect_type=DefectType.WRONG_FEE_RATE,
                    order_id=order_id,
                    impact_paise=overcharge,
                    expected_classification="FEE",
                    detail={"method": method, "contracted_bps": fee_breakdown.mdr_bps,
                            "overcharge_bps": extra_bps,
                            "expected_fee_paise": fee_breakdown.total_fee_paise,
                            "actual_fee_paise": fee_paise},
                ))

            gt.total_expected_fee_paise += fee_breakdown.total_fee_paise
            gt.total_expected_net_paise += fee_breakdown.net_paise

            batch.payments.append({
                "id": payment_id,
                "entity": "payment",
                "amount": amount,
                "currency": "INR",
                "status": "captured",
                "order_id": order_id,
                "invoice_id": self._rid("inv_") if is_subscription else None,
                "subscription_id": None,
                "method": method,
                "captured": True,
                "amount_refunded": 0,
                "fee": fee_paise,
                "tax": tax_paise,
                "error_code": None,
                "error_description": None,
                "error_source": None,
                "error_step": None,
                "error_reason": None,
                "created_at": self._ts(order_day),
            })

            # ---- settlement date, with the timing defect ------------------------
            settled_day = self.calendar.add_working_days(order_day, self.cycle_days)
            if i in assigned[DefectType.TIMING_LAG]:
                extra = self.rng.randrange(1, 3)
                late_day = self.calendar.add_working_days(settled_day, extra)
                gt.add(PlantedDefect(
                    defect_id=f"timing-{order_id}",
                    defect_type=DefectType.TIMING_LAG,
                    order_id=order_id,
                    impact_paise=amount - fee_paise,
                    expected_classification="TIMING",
                    detail={"expected_settled_on": settled_day.isoformat(),
                            "actual_settled_on": late_day.isoformat(),
                            "working_days_late": extra},
                ))
                settled_day = late_day

            # ADR-008: entity_id carries the payment id; payment_id is null here.
            # ADR-007: we do not know which convention Razorpay uses, so the generator
            # is explicit about which one it is EMITTING. `credit` is what actually
            # reached the bank, so it is derived from the convention rather than assumed:
            #   gst_inclusive -> `fee` already contains the GST, credit = amount - fee
            #   mdr_only      -> `fee` is MDR alone,      credit = amount - fee - tax
            # This lets us generate batches in either convention and prove the engine's
            # detector handles both, instead of only ever seeing the one we happened to
            # pick. See test_generate.py::TestFeeConvention.
            if self.fee_convention == "gst_inclusive":
                recon_fee, recon_credit = fee_paise, amount - fee_paise
            else:
                recon_fee, recon_credit = fee_paise - tax_paise, amount - fee_paise

            recon_row = {
                "entity_id": payment_id,
                "type": "payment",
                "debit": 0,
                "credit": recon_credit,
                "amount": amount,
                "currency": "INR",
                "fee": recon_fee,
                "tax": tax_paise,
                "on_hold": False,
                "settled": True,
                "created_at": self._ts(order_day),
                "settled_at": self._ts(settled_day, 18),
                "settlement_id": None,   # filled once settlements are grouped
                "posted_at": None,
                "credit_type": "default",
                "description": "Recurring Payment via Subscription" if is_subscription else "Order payment",
                "notes": None,
                "payment_id": None,
                "settlement_utr": None,  # filled once settlements are grouped
                "order_id": order_id,
                "order_receipt": None,
                "method": method,
                "card_network": "Visa" if method.startswith("card") else None,
                "card_issuer": "HDFC" if method.startswith("card") else None,
                "card_type": method.replace("card_", "") if method.startswith("card") else None,
                "dispute_id": None,
            }
            # ---- DEFECT: split settlement ---------------------------------------
            # One order paid across two settlements on different days. Legitimate
            # Razorpay behaviour, not an error — the engine must record both legs and
            # flag the split rather than treating either half as a shortfall.
            if i in assigned[DefectType.SPLIT_SETTLEMENT]:
                first_amount = amount // 2 // 100 * 100
                second_amount = amount - first_amount
                first_fee = round(fee_paise * first_amount / amount) if amount else 0
                second_fee = fee_paise - first_fee
                first_tax = round(tax_paise * first_amount / amount) if amount else 0
                second_tax = tax_paise - first_tax
                later_day = self.calendar.add_working_days(settled_day, 1)

                halves = [
                    (first_amount, first_fee, first_tax, settled_day, payment_id),
                    (second_amount, second_fee, second_tax, later_day, self._rid("pay_")),
                ]
                for half_amount, half_fee, half_tax, half_day, half_id in halves:
                    row = dict(recon_row)
                    row["entity_id"] = half_id
                    row["amount"] = half_amount
                    # Mirror the convention used on the main path (ADR-007/ADR-014):
                    # gst_inclusive -> `fee` contains the GST, credit = amount - fee
                    # mdr_only      -> `fee` is MDR alone,     credit = amount - fee - tax
                    # `half_fee` is the GST-inclusive total, so both branches subtract
                    # the same money and differ only in how it is reported.
                    if self.fee_convention == "gst_inclusive":
                        row["fee"] = half_fee
                    else:
                        row["fee"] = half_fee - half_tax
                    row["tax"] = half_tax
                    row["credit"] = half_amount - half_fee
                    row["settled_at"] = self._ts(half_day, 18)
                    settlement_groups.setdefault(half_day, []).append(row)
                    batch.recon.append(row)

                gt.add(PlantedDefect(
                    defect_id=f"split-{order_id}",
                    defect_type=DefectType.SPLIT_SETTLEMENT,
                    order_id=order_id,
                    # No money is lost. The impact is zero by design: this defect tests
                    # that the engine does NOT report a discrepancy, which is a harder
                    # thing to get right than reporting one.
                    impact_paise=0,
                    expected_classification="RECONCILED",
                    detail={"first_paise": first_amount, "second_paise": second_amount,
                            "first_settled_on": settled_day.isoformat(),
                            "second_settled_on": later_day.isoformat(),
                            "note": "one order across two settlements; totals must still reconcile"},
                ))
                continue

            settlement_groups.setdefault(settled_day, []).append(recon_row)
            batch.recon.append(recon_row)

            # ---- DEFECT: refund before the original settled ---------------------
            # A refund row dated BEFORE its payment settled. Real, and awkward: the
            # debit lands in an earlier settlement than the credit it reverses, so a
            # naive per-settlement view shows money leaving before it arrived.
            if i in assigned[DefectType.EARLY_REFUND]:
                refund_amount = amount // 3 // 100 * 100
                early_day = self.calendar.add_working_days(order_day, 1)
                refund_row = {
                    **recon_row,
                    "entity_id": self._rid("rfnd_"),
                    "type": "refund",
                    "debit": refund_amount,
                    "credit": 0,
                    "amount": refund_amount,
                    "fee": 0,
                    "tax": 0,
                    "payment_id": payment_id,   # refunds DO carry payment_id (ADR-008)
                    "settled_at": self._ts(early_day, 18),
                    "description": "Refund issued before the original settled",
                }
                settlement_groups.setdefault(early_day, []).append(refund_row)
                batch.recon.append(refund_row)

                gt.add(PlantedDefect(
                    defect_id=f"early-refund-{order_id}",
                    defect_type=DefectType.EARLY_REFUND,
                    order_id=order_id,
                    impact_paise=refund_amount,
                    expected_classification="REFUND",
                    detail={"refund_paise": refund_amount,
                            "refund_settled_on": early_day.isoformat(),
                            "payment_settled_on": settled_day.isoformat(),
                            "note": "refund settled BEFORE the payment it reverses"},
                ))

            # ---- DEFECT: one-sided refund --------------------------------------
            # A refund the merchant recorded but which never reached settlement.
            #
            # This MUST be visible in the data, not merely asserted in ground truth. The
            # first implementation recorded the defect and changed nothing, so the ledger
            # and settlement agreed exactly and the classifier correctly found nothing --
            # 0 of 8 detected. Ground truth claiming a defect the data does not contain is
            # the same failure as the under-planting bug: metrics that are confidently
            # wrong.
            #
            # Side A (ledger) says the order NETTED amount - refund, because the merchant
            # refunded part of it. Side B (settlement) never saw the refund and still shows
            # the full amount. The ledger row is written down accordingly, which is what
            # makes gap_paise non-zero and the divergence detectable.
            if i in assigned[DefectType.ONE_SIDED_REFUND]:
                refund_amount = amount // 2 // 100 * 100
                batch.ledger[-1]["amount"] = amount - refund_amount
                gt.total_gross_paise -= refund_amount
                gt.add(PlantedDefect(
                    defect_id=f"refund-{order_id}",
                    defect_type=DefectType.ONE_SIDED_REFUND,
                    order_id=order_id,
                    impact_paise=refund_amount,
                    expected_classification="REFUND",
                    detail={"refund_paise": refund_amount, "recorded_in": "ledger_only",
                            "ledger_amount_paise": amount - refund_amount,
                            "settled_gross_paise": amount,
                            "note": "merchant recorded a refund that never reached settlement"},
                ))

        # ---- group recon rows into settlements, then into bank credits ----------
        for settled_day, rows in sorted(settlement_groups.items()):
            settlement_id = self._rid("setl_")
            utr = f"{self._ts(settled_day)}{self._rid('', 6).lower()}"
            for row in rows:
                row["settlement_id"] = settlement_id
                row["settlement_utr"] = utr

            net = sum(r["credit"] - r["debit"] for r in rows)
            batch.bank.append({
                "utr": utr,
                "credit_amount": net,
                "value_date": settled_day.isoformat(),
            })

        batch.ground_truth = gt
        return batch
