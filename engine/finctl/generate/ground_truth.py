"""Ground truth — the record of what we deliberately broke.

ADR-004. Without a machine-readable ground truth, "seeded defects caught / missed" is
something a human eyeballs. Across the test-day matrix (volume x archetype x mix x
cycle) that is not merely slow, it is unreliable — and an unreliable accuracy number is
worse than none, because it is the one thing a judge can check.

With this file, "94% of seeded defects caught, here are the 3 missed" becomes an
assertion the test suite makes, not a claim someone remembers to verify.

The rule from BEHAVIOR.md: the generator may not plant a defect it cannot describe
here. If it cannot be scored, it does not get planted.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class DefectType:
    """The defects the generator can plant.

    String constants rather than an enum so they serialise to readable JSON without a
    custom encoder — the ground-truth file is meant to be opened and read by a human at
    11pm.
    """

    MISSING_ORDER = "missing_order"
    WRONG_FEE_RATE = "wrong_fee_rate"
    ONE_SIDED_REFUND = "one_sided_refund"
    TIMING_LAG = "timing_lag"
    HALTED_SUBSCRIPTION = "halted_subscription"

    # Added during the composition audit: both are listed in build-spec.md 6e as
    # adversarial cases, and neither was generated, so engine behaviour on them was
    # unverified rather than known-good.
    SPLIT_SETTLEMENT = "split_settlement"
    EARLY_REFUND = "early_refund"

    # Razorpay's recon schema carries `on_hold`; a held payment is neither late nor
    # missing, and without generating one the engine's handling of it was unverified.
    # See ADR-036.
    PAYMENT_ON_HOLD = "payment_on_hold"

    # The MIRROR of ONE_SIDED_REFUND. That one is a refund the merchant recorded which
    # never reached settlement. This is the reverse: Razorpay settled a refund the
    # merchant never wrote down. Razorpay's own sample recon export contains one of
    # these (a `refund` row with a settlement_id and a blank order_id), and it is the
    # shape a real merchant is more likely to have. See ADR-039.
    UNRECORDED_REFUND = "unrecorded_refund"

    # Razorpay's recon export carries dispute_id / dispute_created_at / dispute_reason.
    # A chargeback is money the PSP is withholding or has clawed back, with a response
    # deadline attached. See ADR-041.
    DISPUTED = "disputed"

    # ORDER IS LOAD-BEARING. The generator slices a shuffled index range across these
    # in sequence, so changing the order changes WHICH orders receive WHICH defect —
    # every golden file shifts, for no real reason. This tuple therefore preserves the
    # historical assignment order, and new types are appended at the END, never
    # inserted. Reordering it is a deliberate act that invalidates the golden files.
    ALL = (
        MISSING_ORDER, WRONG_FEE_RATE, ONE_SIDED_REFUND, HALTED_SUBSCRIPTION,
        TIMING_LAG, SPLIT_SETTLEMENT, EARLY_REFUND, PAYMENT_ON_HOLD,
        UNRECORDED_REFUND, DISPUTED,
    )


@dataclass
class PlantedDefect:
    """One deliberately introduced anomaly, with everything needed to score it.

    `impact_paise` is the money the engine should attribute to this defect. It is
    recorded at planting time from the values actually used, never recomputed
    afterwards — a reconstruction could inherit the same bug as the generator and then
    agree with it.
    """

    defect_id: str
    defect_type: str
    order_id: str | None
    impact_paise: int
    expected_classification: str
    detail: dict[str, Any] = field(default_factory=dict)

    # Set to False for a decoy: something that RESEMBLES a defect but is not one.
    # The false-attribution test (Day 3) plants a gap that looks like a halted
    # subscription but isn't; if the engine claims it, that is a real finding.
    is_real_defect: bool = True

    def __post_init__(self) -> None:
        if self.defect_type not in DefectType.ALL:
            raise ValueError(
                f"unknown defect type {self.defect_type!r}; expected one of {DefectType.ALL}"
            )
        if not isinstance(self.impact_paise, int) or isinstance(self.impact_paise, bool):
            raise TypeError(f"impact_paise must be int paise, got {type(self.impact_paise).__name__}")


@dataclass
class GroundTruth:
    """Everything known about how a batch was constructed.

    The parameters are recorded alongside the defects so a result can be traced back to
    the exact run that produced it — on test day there will be dozens of batches and
    "which run was that?" must be answerable from the file itself.
    """

    seed: int
    archetype: str
    payment_mix: str
    volume: int
    settlement_cycle_days: int
    defect_profile: str
    defects: list[PlantedDefect] = field(default_factory=list)

    # Totals recorded at generation time, so the engine's arithmetic can be checked
    # against an independent source rather than against itself.
    total_orders: int = 0
    total_gross_paise: int = 0
    total_expected_fee_paise: int = 0
    total_expected_net_paise: int = 0

    def add(self, defect: PlantedDefect) -> None:
        self.defects.append(defect)

    @property
    def real_defects(self) -> list[PlantedDefect]:
        return [d for d in self.defects if d.is_real_defect]

    @property
    def decoys(self) -> list[PlantedDefect]:
        """Things that resemble defects but are not. Used by the false-attribution test."""
        return [d for d in self.defects if not d.is_real_defect]

    def by_type(self, defect_type: str) -> list[PlantedDefect]:
        return [d for d in self.defects if d.defect_type == defect_type]

    def impact_by_type(self) -> dict[str, int]:
        """Total paise impact per defect type. The 'how much did we break' summary."""
        out: dict[str, int] = {}
        for d in self.real_defects:
            out[d.defect_type] = out.get(d.defect_type, 0) + d.impact_paise
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "archetype": self.archetype,
            "payment_mix": self.payment_mix,
            "volume": self.volume,
            "settlement_cycle_days": self.settlement_cycle_days,
            "defect_profile": self.defect_profile,
            "total_orders": self.total_orders,
            "total_gross_paise": self.total_gross_paise,
            "total_expected_fee_paise": self.total_expected_fee_paise,
            "total_expected_net_paise": self.total_expected_net_paise,
            "defect_count": len(self.real_defects),
            "decoy_count": len(self.decoys),
            "impact_by_type": self.impact_by_type(),
            "defects": [asdict(d) for d in self.defects],
        }

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=False))

    @classmethod
    def read(cls, path: Path) -> GroundTruth:
        data = json.loads(path.read_text())
        gt = cls(
            seed=data["seed"],
            archetype=data["archetype"],
            payment_mix=data["payment_mix"],
            volume=data["volume"],
            settlement_cycle_days=data["settlement_cycle_days"],
            defect_profile=data["defect_profile"],
            total_orders=data.get("total_orders", 0),
            total_gross_paise=data.get("total_gross_paise", 0),
            total_expected_fee_paise=data.get("total_expected_fee_paise", 0),
            total_expected_net_paise=data.get("total_expected_net_paise", 0),
        )
        gt.defects = [PlantedDefect(**d) for d in data["defects"]]
        return gt
