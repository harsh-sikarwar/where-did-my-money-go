"""Infer the settlement cycle a batch was actually settled on.

WHY THIS EXISTS. The classifier judged every batch against `tolerances.cycle_days` from
config — a fixed T+2 — regardless of what the batch in front of it actually did. On a
T+1 merchant it computed due dates a day late and flagged NOTHING; on a T+7 merchant it
flagged nearly every settled order as late. Both are silent: one under-reports, the
other would bury a merchant in false positives.

Found by a blind test on a T+1 batch. The matrix had run T+1 twenty-two times and
reported 100% recall each time, because recall only counts defects the generator planted
and the scorer correctly treated the unflagged ones as within tolerance. Nobody noticed
that one whole axis caught zero.

The settlement cycle is a property of the MERCHANT'S CONTRACT, so config remains the
source of truth. But the data can disagree with the contract — a merchant may have been
moved from T+2 to T+1 without telling us, or the config may simply be wrong — and an
engine that silently judges against the wrong baseline is worse than one that says so.

So: infer from the data, compare against config, and report the disagreement rather than
picking a winner. Same instinct as ADR-007's fee convention.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

from finctl.calendar import WorkingCalendar
from finctl.match.matcher import MatchResult
from finctl.normalize.normalizer import to_date


@dataclass
class CycleObservation:
    """What the data says about how long settlement actually took."""

    configured_days: int
    observed_days: int | None
    distribution: dict[int, int]
    sample_size: int

    @property
    def agrees_with_config(self) -> bool:
        return self.observed_days is None or self.observed_days == self.configured_days

    @property
    def effective_days(self) -> int:
        """The cycle the classifier should judge against.

        The OBSERVED value wins when the two disagree. Config describes the contract;
        the data describes what happened, and 'late' is only meaningful relative to what
        actually happens. Judging a T+7 merchant against a contracted T+2 would flag
        nearly every order as late — technically true against the contract, useless as
        advice, and indistinguishable from a broken engine.

        The disagreement is reported separately so it is never silent.
        """
        return self.observed_days if self.observed_days is not None else self.configured_days

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured_days": self.configured_days,
            "observed_days": self.observed_days,
            "effective_days": self.effective_days,
            "agrees_with_config": self.agrees_with_config,
            "sample_size": self.sample_size,
            "distribution": dict(sorted(self.distribution.items())),
        }


def observe_cycle(
    matches: MatchResult,
    calendar: WorkingCalendar,
    configured_days: int,
) -> CycleObservation:
    """Measure the typical capture-to-settlement time, in working days.

    Uses the MODE rather than the mean or median. The distribution is deliberately
    skewed — planted lags and genuinely late settlements sit in the right tail — and a
    mean would drift toward them, which is precisely backwards: the baseline should be
    what NORMALLY happens, so that abnormal settlements stand out against it.
    """
    gaps: list[int] = []
    for m in matches.order_matches:
        if not m.matched:
            continue
        captured = to_date(m.ledger_row.get("captured_at"))
        if not captured:
            continue
        settled = [to_date(r["settled_at"]) for r in m.recon_rows if r.get("settled_at")]
        settled = [d for d in settled if d]
        if not settled:
            continue
        # The EARLIEST leg: a split settlement's second half is by nature later, and
        # counting it would inflate the apparent cycle for merchants who split.
        gaps.append(calendar.working_days_between(captured, min(settled)))

    if not gaps:
        return CycleObservation(configured_days, None, {}, 0)

    distribution = Counter(gaps)

    # Too few samples to infer anything. Fall back to config rather than guessing from
    # three orders — a wrong inference here silently rebases every timing judgement.
    if len(gaps) < 20:
        return CycleObservation(configured_days, None, dict(distribution), len(gaps))

    observed = statistics.mode(gaps)
    return CycleObservation(configured_days, observed, dict(distribution), len(gaps))
