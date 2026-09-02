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
    defect: PlantedDefect, config: Config, matches: MatchResult
) -> bool:
    """Is this planted defect one the config deliberately declines to flag?

    Only timing has a tolerance that can swallow a whole defect: `grace_days`. Fee and
    amount tolerances are one paise, far below any planted magnitude.
    """
    if defect.defect_type != DefectType.TIMING_LAG:
        return False

    tol = config.tolerances
    cal = WorkingCalendar(tol.weekend_days, tol.holidays)
    match = next((m for m in matches.order_matches if m.order_id == defect.order_id), None)
    if match is None or not match.recon_rows:
        return False

    captured = to_date(match.ledger_row.get("captured_at"))
    settled = [to_date(r["settled_at"]) for r in match.recon_rows if r.get("settled_at")]
    settled = [d for d in settled if d]
    if not captured or not settled:
        return False

    due = cal.add_working_days(captured, tol.cycle_days)
    return cal.working_days_between(due, max(settled)) <= tol.grace_days


def score(
    truth: GroundTruth,
    correlated: CorrelationResult,
    matches: MatchResult,
    config: Config,
) -> ScoreReport:
    """Compare what the engine found against what was actually planted."""
    report = ScoreReport(
        unexplained_before_paise=correlated.unexplained_before_paise,
        unexplained_after_paise=correlated.unexplained_after_paise,
    )

    # order_id -> the classifications the engine assigned to it
    found: dict[str, set[Classification]] = {}
    for f in correlated.findings:
        if f.order_id:
            found.setdefault(f.order_id, set()).add(f.classification)

    planted_orders: set[str] = set()

    for defect in truth.real_defects:
        s = report.by_type.setdefault(defect.defect_type, DefectScore())
        if defect.order_id:
            planted_orders.add(defect.order_id)

        acceptable = EXPECTED.get(defect.defect_type, frozenset())
        assigned = found.get(defect.order_id or "", set())

        if assigned & acceptable:
            s.caught.append(defect.defect_id)
        elif _is_below_tolerance(defect, config, matches):
            s.below_tolerance.append(defect.defect_id)
        else:
            s.missed.append(defect.defect_id)

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
