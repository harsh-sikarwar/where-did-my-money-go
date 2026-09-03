"""Test-day matrix runner.

From the build plan: *"Treat test day as a build day whose output is evidence."* The
track bar asks for throughput plus measured accuracy plus an honest exception list —
*"one cherry-picked match proves nothing."*

This runs the full pipeline across volume x archetype x payment mix x settlement cycle,
scores every run against its own ground truth, and emits a table. Every number in the
submission's metrics section comes from here, so it is reproducible by re-running one
command rather than reconstructed from notes.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from finctl.config.loader import Config, load_config
from finctl.generate.generator import Generator
from finctl.generate.writer import write_batch
from finctl.pipeline import run


@dataclass
class RunResult:
    """One cell of the matrix. Mirrors the report format from build-spec 6g."""

    volume: int
    archetype: str
    payment_mix: str
    cycle_days: int
    defect_profile: str

    # accuracy
    match_rate_pass1: float
    match_rate_pass2: float
    recall: float
    defects_caught: int
    defects_missed: int
    defects_below_tolerance: int
    false_positives: int
    missed_ids: list[str] = field(default_factory=list)

    # money
    expected_paise: int = 0
    received_paise: int = 0
    gap_paise: int = 0
    unexplained_before_paise: int = 0
    unexplained_after_paise: int = 0
    correlation_gain: float = 0.0
    actionable_paise: int = 0
    benign_paise: int = 0

    # throughput
    rows: int = 0
    seconds: float = 0.0
    rows_per_second: float = 0.0

    # invariants — a run that does not balance is not a data point, it is a bug
    balances: bool = True
    error: str | None = None

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


def run_cell(
    tmp_root: Path,
    config: Config,
    *,
    volume: int,
    archetype: str,
    payment_mix: str,
    cycle_days: int,
    defect_profile: str,
    seed: int = 20260902,
) -> RunResult:
    """Generate one batch, reconcile it, and score it.

    Generation time is deliberately excluded from the throughput figure: it measures the
    engine, not the test harness. Reporting a number that includes our own data
    generation would understate real throughput and be dishonest in our favour.
    """
    out = tmp_root / f"{archetype}_{payment_mix}_{volume}_t{cycle_days}_{defect_profile}"

    try:
        batch = Generator(
            config, seed=seed, archetype=archetype, payment_mix=payment_mix,
            volume=volume, settlement_cycle_days=cycle_days,
            defect_profile=defect_profile,
        ).generate()
        write_batch(batch, out)
    except ValueError as exc:
        # A profile can legitimately demand more defects than a small batch has orders.
        # That is a configuration limit, not an engine failure, and it is recorded
        # rather than silently skipped.
        return RunResult(
            volume=volume, archetype=archetype, payment_mix=payment_mix,
            cycle_days=cycle_days, defect_profile=defect_profile,
            match_rate_pass1=0.0, match_rate_pass2=0.0, recall=0.0,
            defects_caught=0, defects_missed=0, defects_below_tolerance=0,
            false_positives=0, error=str(exc)[:120],
        )

    started = time.perf_counter()
    result = run(out, config)
    elapsed = time.perf_counter() - started

    v = result.verdict
    c = result.correlated
    s = result.scored

    balances = (
        sum(line.amount_paise for line in v.lines) + v.unexplained_paise == v.gap_paise
    )

    return RunResult(
        volume=volume, archetype=archetype, payment_mix=payment_mix,
        cycle_days=cycle_days, defect_profile=defect_profile,
        match_rate_pass1=round(result.matches.pass1_match_rate, 4),
        match_rate_pass2=round(result.matches.pass2_match_rate, 4),
        recall=round(s.recall, 4) if s else 0.0,
        defects_caught=s.total_caught if s else 0,
        defects_missed=s.total_missed if s else 0,
        defects_below_tolerance=s.total_below_tolerance if s else 0,
        false_positives=len(s.false_positives) if s else 0,
        missed_ids=[
            i for entry in (s.as_dict()["by_type"].values() if s else [])
            for i in entry["missed_ids"]
        ][:10],
        expected_paise=v.expected_paise,
        received_paise=v.received_paise,
        gap_paise=v.gap_paise,
        unexplained_before_paise=c.unexplained_before_paise,
        unexplained_after_paise=c.unexplained_after_paise,
        correlation_gain=round(c.gain_ratio, 4),
        actionable_paise=v.actionable_paise,
        benign_paise=v.benign_paise,
        rows=result.rows_processed,
        seconds=round(elapsed, 4),
        rows_per_second=round(result.rows_processed / elapsed) if elapsed else 0,
        balances=balances,
    )


def default_matrix() -> list[dict[str, Any]]:
    """The axes from build-plan-3.5-days.md, Day 3 morning.

    Volume is crossed fully against archetype at the demo scale, and the large tiers are
    run on a narrower slice — 50k across every mix would take minutes for information the
    500-row runs already give. What the large tiers exist to answer is "where does it
    degrade", which one archetype answers.
    """
    cells: list[dict[str, Any]] = []

    for archetype in ("saas_subscription", "d2c_ecommerce"):
        for mix in ("upi_heavy", "card_heavy", "even"):
            for cycle in (1, 2):
                cells.append({
                    "volume": 200, "archetype": archetype, "payment_mix": mix,
                    "cycle_days": cycle, "defect_profile": "demo",
                })

    for volume in (50, 500, 5_000, 50_000):
        for archetype in ("saas_subscription", "d2c_ecommerce"):
            cells.append({
                "volume": volume, "archetype": archetype, "payment_mix": "even",
                "cycle_days": 2, "defect_profile": "scale",
            })

    # Edge profiles: does it correctly say "nothing to do", and stay honest under chaos?
    for profile in ("clean", "chaos"):
        cells.append({
            "volume": 200, "archetype": "saas_subscription", "payment_mix": "even",
            "cycle_days": 2, "defect_profile": profile,
        })

    return cells


def run_matrix(
    tmp_root: Path,
    cells: list[dict[str, Any]] | None = None,
    config: Config | None = None,
    on_result=None,
) -> list[RunResult]:
    cfg = config or load_config()
    results = []
    for cell in cells or default_matrix():
        result = run_cell(tmp_root, cfg, **cell)
        results.append(result)
        if on_result:
            on_result(result)
    return results


def write_results(results: list[RunResult], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.as_row() for r in results], indent=2))
    return path
