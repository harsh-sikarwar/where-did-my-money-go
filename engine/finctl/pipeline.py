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

from finctl.classify.classifier import ClassificationResult, Classifier
from finctl.config.loader import Config, load_config
from finctl.correlate.correlator import CorrelationResult, Correlator
from finctl.generate.ground_truth import GroundTruth
from finctl.match.matcher import MatchResult, match
from finctl.rank.ranker import Ranker, Verdict
from finctl.score import ScoreReport, score
from finctl.stage.staging import StagedBatch, stage_from_dir


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
    elapsed_seconds: float
    rows_processed: int

    @property
    def throughput(self) -> float:
        return self.rows_processed / self.elapsed_seconds if self.elapsed_seconds else 0.0

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
        }
        if self.scored is not None:
            out["score"] = self.scored.as_dict()
        return out


def run(data_dir: Path, config: Config | None = None) -> PipelineResult:
    """Ingest, match, classify, correlate, rank — and score if ground truth exists.

    Scoring is optional because real merchant data has no ground truth. Its absence is
    not an error; it just means the accuracy columns are unavailable, which is honest.
    """
    cfg = config or load_config()
    started = time.perf_counter()

    batch = stage_from_dir(data_dir)
    matches = match(batch)
    classified = Classifier(cfg).classify(matches)
    correlated = Correlator(batch).correlate(classified)
    verdict = Ranker(cfg.tolerances).rank(
        correlated.findings,
        expected_paise=matches.expected_paise,
        received_paise=matches.received_paise,
    )

    elapsed = time.perf_counter() - started

    scored: ScoreReport | None = None
    gt_path = data_dir / "ground_truth.json"
    if gt_path.exists():
        scored = score(GroundTruth.read(gt_path), correlated, matches, cfg)

    return PipelineResult(
        batch=batch,
        matches=matches,
        classified=classified,
        correlated=correlated,
        verdict=verdict,
        scored=scored,
        elapsed_seconds=elapsed,
        rows_processed=sum(s.row_count for s in batch.sources.values()),
    )
