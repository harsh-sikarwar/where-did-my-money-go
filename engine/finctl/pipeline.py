"""The pipeline, end to end, in one place.

ADR-001 says the web API is a thin wrapper over the engine. This module is what makes
that literally true: the CLI and the API both call `run()` and neither reimplements the
stage order. Two callers with two copies of the sequence is how a UI ends up showing a
number the CLI never produced.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finctl.actions import ActionGroup
from finctl.actions import build as build_actions
from finctl.audit.log import AuditLog
from finctl.classify.classifier import Classification, ClassificationResult, Classifier
from finctl.config.loader import Config, load_config
from finctl.correlate.correlator import CorrelationResult, Correlator
from finctl.cycle import CycleObservation
from finctl.gap import decompose
from finctl.generate.ground_truth import GroundTruth
from finctl.match.matcher import MatchResult, match
from finctl.rank.ranker import Ranker, Verdict
from finctl.schema import Source
from finctl.score import ScoreReport, score
from finctl.stage.staging import StagedBatch, stage_from_dir
from finctl.timeline import Timeline, build_timeline


@dataclass
class PipelineResult:
    """Everything one reconciliation run produced, at every stage.

    Intermediate results are kept rather than discarded: the audit trail and the
    drill-down views need the working, not just the answer.
    """

    batch: StagedBatch
    matches: MatchResult
    classified: ClassificationResult
    correlated: CorrelationResult
    verdict: Verdict
    scored: ScoreReport | None
    audit: AuditLog
    cycle: CycleObservation | None
    elapsed_seconds: float
    rows_processed: int

    @property
    def throughput(self) -> float:
        return self.rows_processed / self.elapsed_seconds if self.elapsed_seconds else 0.0

    @property
    def actions(self) -> list[ActionGroup]:
        """Who to chase, for how much, and why.

        A property rather than a stored field because it is a pure projection of
        `correlated.findings` — computing it at run time and storing it would create a
        second copy that could disagree with the verdict it accompanies. See ADR-048.

        The amounts come from the same gap decomposition the verdict is built from. A
        property alone was never enough to guarantee agreement: this list summed
        `finding.amount_paise` and disagreed with the verdict for every batch until
        ADR-053. Being computed in one place does not make two computations equal.
        """
        return build_actions(
            self.correlated.findings,
            list(self.batch.get(Source.LEDGER)),
            decomposition=decompose(self.matches, self.correlated.findings),
            # The verdict has already applied the materiality policy from
            # `tolerances.yaml`; handing its answer over is what keeps the two screens
            # from disagreeing about whether a line needs the merchant this week.
            # ADR-054.
            actionable=frozenset(
                line.classification for line in self.verdict.actionable_lines
            ),
        )

    @property
    def timeline(self) -> Timeline:
        """The gap spread over the days it happened on.

        A property, and built from `decompose(...)` like `actions` above, for the same
        reason: a stored second copy is a copy that can disagree. The chart on screen
        and the total above it are then the same arithmetic, not two that happen to
        match today.
        """
        return build_timeline(
            self.matches,
            decompose(self.matches, self.correlated.findings),
            # The same materiality answer the verdict reached, handed over rather than
            # recomputed — for the reason ADR-054 gives about the action list.
            actionable=frozenset(
                line.classification for line in self.verdict.actionable_lines
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "batch": self.batch.manifest(),
            "match": self.matches.summary(),
            "classification": self.classified.summary(),
            "correlation": self.correlated.summary(),
            "verdict": self.verdict.as_dict(),
            "performance": {
                "elapsed_seconds": round(self.elapsed_seconds, 4),
                "rows_processed": self.rows_processed,
                "rows_per_second": round(self.throughput),
            },
            "audit": {"events": len(self.audit), "by_stage": self.audit.by_stage()},
            "settlement_cycle": self.cycle.as_dict() if self.cycle else None,
        }
        if self.scored is not None:
            out["score"] = self.scored.as_dict()
        return out


def run(
    data_dir: Path,
    config: Config | None = None,
    mappings: Any | None = None,
) -> PipelineResult:
    """Ingest, match, classify, correlate, rank — and score if ground truth exists.

    Scoring is optional because real merchant data has no ground truth. Its absence is
    not an error; it just means the accuracy columns are unavailable, which is honest.

    `mappings` is an optional MappingStore of column mappings a human confirmed earlier
    (ADR-045). Absent, the engine behaves exactly as before: alias table or refuse.
    """
    cfg = config or load_config()
    started = time.perf_counter()

    batch = stage_from_dir(data_dir, mappings=mappings)
    log = AuditLog(batch.batch_id)

    # INGEST: what was read, from where, with which columns mapped to what. The answer
    # to "which column did you read as the amount?" when a number is disputed.
    for source, staged in sorted(batch.sources.items()):
        log.record("ingest", "source_staged", {
            "source": str(source),
            "origin": staged.origin,
            "rows": staged.row_count,
            "sha256": staged.content_sha256,
            "column_mapping": staged.column_mapping,
        })

    matches = match(batch)
    log.record("match", "pass_1_order_to_psp", matches.summary()["pass1"])
    log.record("match", "pass_2_psp_to_bank", matches.summary()["pass2"])
    for order_id, count in matches.duplicate_order_ids.items():
        log.record("match", "duplicate_order_id", {"occurrences": count},
                   order_id=order_id)

    classifier = Classifier(cfg)
    classified = classifier.classify(matches)

    # The settlement cycle the batch was actually settled on, versus the one configured.
    # Logged always, not only on disagreement, so the audit trail records which baseline
    # every timing judgement was made against.
    if classifier.cycle is not None:
        log.record("classify", "settlement_cycle", classifier.cycle.as_dict())
        if not classifier.cycle.agrees_with_config:
            log.record("classify", "settlement_cycle_disagrees_with_config", {
                "configured_days": classifier.cycle.configured_days,
                "observed_days": classifier.cycle.observed_days,
                "judged_against": classifier.cycle.effective_days,
                "note": (
                    "The data settles on a different cycle than tolerances.yaml states. "
                    "Timing was judged against the OBSERVED cycle, because 'late' is only "
                    "meaningful relative to what actually happens. Worth checking whether "
                    "the contract changed."
                ),
            })
    # One event per non-reconciled finding, carrying the arithmetic that produced it.
    # RECONCILED rows are summarised rather than enumerated: at 50k rows they would be
    # 95% of the log and none of the interest, and the count is what makes the totals
    # reconstructible anyway.
    reconciled = 0
    for f in classified.findings:
        if f.classification is Classification.RECONCILED:
            reconciled += 1
            continue
        log.record("classify", str(f.classification), {
            "amount_paise": f.amount_paise,
            "proof": f.proof,
            "candidates": [str(c) for c in f.candidates],
        }, order_id=f.order_id, settlement_id=f.settlement_id)
    log.record("classify", "reconciled_summary", {"count": reconciled})

    correlated = Correlator(batch).correlate(classified)
    for f in correlated.resolved:
        log.record("correlate", f"resolved_as_{f.classification}", {
            "amount_paise": f.amount_paise,
            "correlation": f.proof.get("correlation", {}),
        }, order_id=f.order_id)
    for f in correlated.still_unexplained:
        # Logged as prominently as the resolutions. The residual is the honesty metric,
        # so burying it would defeat the point of having one.
        log.record("correlate", "still_unexplained", {
            "amount_paise": f.amount_paise,
            "outcome": f.proof.get("correlation", {}).get("outcome", "not attempted"),
        }, order_id=f.order_id)
    log.record("correlate", "before_after", correlated.summary())

    verdict = Ranker(cfg.tolerances).rank(correlated.findings, matches)
    for line in verdict.lines:
        log.record("rank", "verdict_line", {
            "classification": str(line.classification),
            "count": line.count,
            "amount_paise": line.amount_paise,
            "actionable": line.actionable,
            "policy": "always_actionable/always_benign from tolerances.yaml",
        })
    log.record("rank", "headline", {"text": verdict.headline()})

    elapsed = time.perf_counter() - started

    scored: ScoreReport | None = None
    gt_path = data_dir / "ground_truth.json"
    if gt_path.exists():
        # The OBSERVED cycle, not the configured one. The classifier judged this batch
        # against `classifier.cycle_days`; handing the scorer `cfg` alone graded the
        # engine against a baseline it never used, and on a T+3-or-slower batch turned
        # correctly-reconciled orders into reported misses. See ADR-051.
        scored = score(
            GroundTruth.read(gt_path), correlated, matches, cfg,
            cycle_days=classifier.cycle_days,
        )

    return PipelineResult(
        batch=batch,
        matches=matches,
        classified=classified,
        correlated=correlated,
        verdict=verdict,
        scored=scored,
        audit=log,
        cycle=classifier.cycle,
        elapsed_seconds=elapsed,
        rows_processed=sum(s.row_count for s in batch.sources.values()),
    )
