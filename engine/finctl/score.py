"""Score engine output against ground truth.

ADR-004 exists for this function. Across the test-day matrix there will be dozens of
runs, and "seeded defects caught / missed" verified by eye is not merely slow — it is
unreliable, and an unreliable accuracy number is worse than none because it is the one
thing a judge can check.

This turns the headline metric into an assertion the test suite makes.

One honest complication, discovered rather than anticipated: the engine and ground truth
can legitimately disagree about what counts as a defect. The generator plants timing lags
of 1-2 working days; `grace_days: 1` means a 1-day lag is WITHIN tolerance and is
deliberately not flagged. Those are not misses — they are the tolerance working. So the
score distinguishes:

    caught             detected, as expected
    missed             planted, not detected, and it SHOULD have been
    below_tolerance    planted, not detected, because config says it is not a defect

Collapsing the third category into "missed" would understate accuracy and misrepresent
the engine. Collapsing it into "caught" would overstate it. It gets its own row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from finctl.calendar import WorkingCalendar
from finctl.classify.classifier import Classification
from finctl.config.loader import Config
from finctl.correlate.correlator import CorrelationResult
from finctl.generate.ground_truth import DefectType, GroundTruth, PlantedDefect
from finctl.match.matcher import MatchResult
from finctl.normalize.normalizer import to_date

# Which engine classification satisfies which planted defect.
EXPECTED: dict[str, frozenset[Classification]] = {
    DefectType.MISSING_ORDER: frozenset({
        Classification.MISSING, Classification.PAYMENT_FAILED,
    }),
    DefectType.HALTED_SUBSCRIPTION: frozenset({Classification.HALTED_SUBSCRIPTION}),
    DefectType.WRONG_FEE_RATE: frozenset({Classification.FEE, Classification.TAX_ON_FEE}),
    DefectType.ONE_SIDED_REFUND: frozenset({Classification.REFUND}),
    DefectType.TIMING_LAG: frozenset({Classification.TIMING}),
    # A split settlement is legitimate Razorpay behaviour, not a defect. "Caught" here
    # means the engine correctly reported NO discrepancy -- which is a harder property
    # to get right than reporting one, and the reason this case is planted at all.
    DefectType.SPLIT_SETTLEMENT: frozenset({Classification.RECONCILED}),
    DefectType.EARLY_REFUND: frozenset({Classification.REFUND}),
    DefectType.PAYMENT_ON_HOLD: frozenset({Classification.ON_HOLD}),
    DefectType.UNRECORDED_REFUND: frozenset({Classification.UNRECORDED_REFUND}),
    DefectType.DISPUTED: frozenset({Classification.DISPUTED}),
}


@dataclass
class DefectScore:
    caught: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    below_tolerance: list[str] = field(default_factory=list)

    @property
    def scoreable(self) -> int:
        """Defects the engine was actually expected to find."""
        return len(self.caught) + len(self.missed)

    @property
    def recall(self) -> float:
        return len(self.caught) / self.scoreable if self.scoreable else 1.0


@dataclass
class ScoreReport:
    by_type: dict[str, DefectScore] = field(default_factory=dict)
    false_positives: list[str] = field(default_factory=list)
    unexplained_before_paise: int = 0
    unexplained_after_paise: int = 0

    # Decoys: planted things that RESEMBLE a defect but are not one. A decoy the engine
    # claims is a false attribution — the failure this project's headline number exists
    # to rule out. Tracked separately from `false_positives` because a decoy is a
    # DELIBERATE trap with a known answer, while a false positive is any unplanted order
    # the engine flagged. See ADR-042.
    decoys_resisted: list[str] = field(default_factory=list)
    decoys_claimed: list[str] = field(default_factory=list)

    @property
    def false_attribution_rate(self) -> float:
        """Fraction of deliberate traps the engine walked into. Must be 0.0."""
        total = len(self.decoys_resisted) + len(self.decoys_claimed)
        return len(self.decoys_claimed) / total if total else 0.0

    @property
    def total_caught(self) -> int:
        return sum(len(s.caught) for s in self.by_type.values())

    @property
    def total_missed(self) -> int:
        return sum(len(s.missed) for s in self.by_type.values())

    @property
    def total_below_tolerance(self) -> int:
        return sum(len(s.below_tolerance) for s in self.by_type.values())

    @property
    def recall(self) -> float:
        scoreable = self.total_caught + self.total_missed
        return self.total_caught / scoreable if scoreable else 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "recall": round(self.recall, 4),
            "caught": self.total_caught,
            "missed": self.total_missed,
            "below_tolerance": self.total_below_tolerance,
            "false_positives": len(self.false_positives),
            "decoys_resisted": len(self.decoys_resisted),
            "decoys_claimed": len(self.decoys_claimed),
            "false_attribution_rate": round(self.false_attribution_rate, 4),
            "decoys_claimed_ids": self.decoys_claimed[:10],
            "unexplained_before_paise": self.unexplained_before_paise,
            "unexplained_after_paise": self.unexplained_after_paise,
            "by_type": {
                name: {
                    "caught": len(s.caught),
                    "missed": len(s.missed),
                    "below_tolerance": len(s.below_tolerance),
                    "recall": round(s.recall, 4),
                    "missed_ids": s.missed[:10],   # the honest list, capped for display
                }
                for name, s in sorted(self.by_type.items())
            },
        }


def _is_below_tolerance(
    defect: PlantedDefect,
    config: Config,
    matches: MatchResult,
    index: dict[str, Any] | None = None,
    cycle_days: int | None = None,
) -> bool:
    """Is this planted defect one the config deliberately declines to flag?

    Only timing has a tolerance that can swallow a whole defect: `grace_days`. Fee and
    amount tolerances are one paise, far below any planted magnitude.

    `cycle_days` is the cycle the ENGINE judged against — observed where the data
    disagreed with config. It must be the same number, or the scorer grades the engine
    against a baseline the engine never used. See `score`.
    """
    if defect.defect_type != DefectType.TIMING_LAG:
        return False

    tol = config.tolerances
    cal = WorkingCalendar(tol.weekend_days, tol.holidays)
    effective_cycle = tol.cycle_days if cycle_days is None else cycle_days

    # Indexed lookup, not a scan. This was the engine's worst hot spot at 50k rows:
    # a linear scan through every order match, once per planted timing defect, is
    # O(defects × orders) — 3.0s of a 7.7s run, and the only super-linear term measured
    # anywhere in the pipeline. Found by profiling the 50k tier rather than by guessing.
    if index is not None:
        match = index.get(defect.order_id or "")
    else:
        match = next(
            (m for m in matches.order_matches if m.order_id == defect.order_id), None
        )
    if match is None or not match.recon_rows:
        return False

    captured = to_date(match.ledger_row.get("captured_at"))
    settled = [to_date(r["settled_at"]) for r in match.recon_rows if r.get("settled_at")]
    settled = [d for d in settled if d]
    if not captured or not settled:
        return False

    due = cal.add_working_days(captured, effective_cycle)
    return cal.working_days_between(due, max(settled)) <= tol.grace_days


def score(
    truth: GroundTruth,
    correlated: CorrelationResult,
    matches: MatchResult,
    config: Config,
    cycle_days: int | None = None,
) -> ScoreReport:
    """Compare what the engine found against what was actually planted.

    `cycle_days` is the settlement cycle the CLASSIFIER judged against — the observed
    one where the data disagreed with config (`CycleObservation.effective_days`). Pass it
    or the scorer grades the engine against a baseline the engine never used.

    This was wrong until ADR-051. `cycle.py` exists because the classifier once judged
    every batch against a configured T+2 regardless of what the batch actually did; that
    fix gave the classifier an observed cycle and never gave one to the scorer. On a
    T+3-or-slower batch the engine correctly classified late-but-within-cycle orders as
    RECONCILED, and the scorecard counted each one as a MISS — reporting 0.600 recall for
    work that was 1.000 correct. The engine was right and its own report card understated
    it, which is the rarer and more embarrassing direction for a measurement bug.

    Defaults to the configured value so a caller without an observation still works.
    """
    report = ScoreReport(
        unexplained_before_paise=correlated.unexplained_before_paise,
        unexplained_after_paise=correlated.unexplained_after_paise,
    )

    # order_id -> the classifications the engine assigned to it
    found: dict[str, set[Classification]] = {}
    for f in correlated.findings:
        if f.order_id:
            found.setdefault(f.order_id, set()).add(f.classification)

    # entity_id -> classifications, for defects that have no order_id to be keyed by.
    # A settlement-side refund is identified only by its `rfnd_…` entity_id — Razorpay's
    # real export leaves order_id blank on those rows (ADR-039). Scoring purely by
    # order_id marked every such defect MISSED no matter what the engine reported,
    # because the join key did not exist. See ADR-040.
    found_by_entity: dict[str, set[Classification]] = {}
    for f in correlated.findings:
        entity_id = f.proof.get("entity_id") if f.proof else None
        if entity_id:
            found_by_entity.setdefault(str(entity_id), set()).add(f.classification)

    planted_orders: set[str] = set()

    # Built once and reused, rather than rebuilt per defect.
    order_index = {m.order_id: m for m in matches.order_matches}

    for defect in truth.real_defects:
        s = report.by_type.setdefault(defect.defect_type, DefectScore())
        if defect.order_id:
            planted_orders.add(defect.order_id)

        acceptable = EXPECTED.get(defect.defect_type, frozenset())
        assigned = found.get(defect.order_id or "", set())

        # Fall back to the entity key when the defect has no order_id. Ground truth
        # records the entity_id in `detail` for exactly this purpose.
        if not assigned:
            entity_id = defect.detail.get("entity_id") if defect.detail else None
            if entity_id:
                assigned = found_by_entity.get(str(entity_id), set())

        if assigned & acceptable:
            s.caught.append(defect.defect_id)
        elif _is_below_tolerance(defect, config, matches, order_index, cycle_days):
            s.below_tolerance.append(defect.defect_id)
        else:
            s.missed.append(defect.defect_id)

    # --- decoys: the false-attribution guard ------------------------------------------
    # A decoy is planted to LOOK like a defect while not being one — a failed payment
    # against a healthy subscription, say. The engine must decline to claim it.
    #
    # This is scored separately from `false_positives` because the two answer different
    # questions. A false positive is "did the engine flag something unplanted?", which
    # a batch where every gap has a real cause can only ever answer trivially. A decoy
    # asks "does the engine claim a cause that is NOT there when one is dangled in front
    # of it?" — which is the question the headline number needs. See ADR-042.
    #
    # `claimed` is deliberately narrow: only the classifications that assert a SPECIFIC
    # cause with an owner. Reporting a decoy as UNEXPLAINED is not a false attribution —
    # it is the engine correctly declining to explain something, which is the behaviour
    # BEHAVIOR.md asks for.
    for decoy in truth.decoys:
        assigned = found.get(decoy.order_id or "", set())
        if not assigned and decoy.detail.get("entity_id"):
            assigned = found_by_entity.get(str(decoy.detail["entity_id"]), set())

        forbidden = {
            Classification[c] for c in decoy.detail.get("must_not_claim", ())
            if c in Classification.__members__
        } or set(EXPECTED.get(decoy.defect_type, frozenset()))

        if assigned & forbidden:
            report.decoys_claimed.append(decoy.defect_id)
        else:
            report.decoys_resisted.append(decoy.defect_id)

        # A decoy order is PLANTED, even though it is not a real defect. Without this
        # the false-positive check below sees a flagged order it has no record of and
        # reports it as a false positive — which would be wrong twice over: the engine
        # gave the correct answer (PAYMENT_FAILED; the payment really did fail), and
        # the decoy's whole purpose is to be flagged as something MILDER than the trap.
        # Scoring the right answer as a false positive would make planting decoys look
        # like a regression and discourage ever adding one.
        if decoy.order_id:
            planted_orders.add(decoy.order_id)

    # A false positive is an order the engine flagged as a problem that was never
    # planted as one. These matter more than misses: a miss is a gap in coverage, a
    # false positive is the engine telling a merchant something untrue.
    problem_classes = {
        Classification.MISSING, Classification.HALTED_SUBSCRIPTION,
        Classification.PAYMENT_FAILED, Classification.REFUND,
        Classification.UNEXPLAINED, Classification.NEEDS_REVIEW,
    }
    for order_id, classes in found.items():
        if (classes & problem_classes) and order_id not in planted_orders:
            report.false_positives.append(order_id)

    return report
