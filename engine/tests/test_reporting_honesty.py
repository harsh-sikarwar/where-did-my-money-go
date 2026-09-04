"""Numbers the product shows about ITSELF.

Every test here pins a case where the engine was right and its own reporting layer
said something else — a figure that could not move, a detection that was never
displayed, a score that forgave what it did not mention, an answer key that disagreed
with a correct analysis. The arithmetic was never the problem; the claims about the
arithmetic were. See ADR-059.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from finctl.classify.classifier import Classification
from finctl.config.loader import load_config
from finctl.generate.generator import Generator
from finctl.generate.ground_truth import GroundTruth
from finctl.generate.writer import write_batch
from finctl.pipeline import run


def _batch(tmp_path: Path, *, profile: str = "demo", volume: int = 200) -> Path:
    write_batch(
        Generator(load_config(), seed=20260902, volume=volume,
                  defect_profile=profile).generate(),
        tmp_path,
    )
    return tmp_path


class TestLatePayoutsAreReported:
    """F4 — 213 late settlements detected on a 2,500-order run, zero mentioned."""

    def test_detected_late_payouts_reach_the_verdict(self, tmp_path: Path) -> None:
        r = run(_batch(tmp_path))
        timing = [
            f for f in r.correlated.findings
            if f.classification is Classification.TIMING
        ]
        if not timing:
            pytest.skip("this profile planted no timing lag")

        late = r.verdict.late
        assert late is not None, "TIMING findings exist but the verdict reports none"
        assert late.count == len(timing)
        assert late.value_paise == sum(f.amount_paise for f in timing)

    def test_late_payouts_are_not_a_gap_line(self, tmp_path: Path) -> None:
        """The money arrived. Counting it in the gap is the original double-count.

        `gap.py` books only settlements still in flight; an order that settled late but
        HAS arrived is already inside `received`. The panel exists precisely so that
        fact can be stated without a line implying otherwise.
        """
        r = run(_batch(tmp_path))
        v = r.verdict
        assert sum(line.amount_paise for line in v.lines) + v.residual_paise == v.gap_paise

    def test_the_delay_is_not_recomputed(self, tmp_path: Path) -> None:
        """Every figure comes from proof the classifier already wrote."""
        r = run(_batch(tmp_path))
        late = r.verdict.late
        if late is None:
            pytest.skip("no late payouts in this batch")

        days = sorted(
            int(f.proof.get("working_days_late", 0) or 0)
            for f in r.correlated.findings
            if f.classification is Classification.TIMING
        )
        assert late.max_days_late == days[-1]
        assert late.median_days_late == days[len(days) // 2]


class TestRecallDoesNotForgiveSilently:
    """F5 — 1.00 reported on a run that found 612 of 849 planted defects."""

    def test_strict_recall_counts_everything_planted(self, tmp_path: Path) -> None:
        r = run(_batch(tmp_path))
        assert r.scored is not None
        s = r.scored
        assert s.total_planted == s.total_caught + s.total_missed + s.total_below_tolerance
        assert s.recall_strict == pytest.approx(s.total_caught / s.total_planted)

    def test_strict_is_never_flattered_by_tolerance(self, tmp_path: Path) -> None:
        """The lenient figure drops below_tolerance from its denominator; strict cannot.

        Where nothing was forgiven the two agree — that is the point. Where something
        was, strict is the smaller number and the honest one.
        """
        r = run(_batch(tmp_path))
        s = r.scored
        assert s is not None
        assert s.recall_strict <= s.recall
        if s.total_below_tolerance:
            assert s.recall_strict < s.recall

    def test_the_tolerance_window_is_stated(self, tmp_path: Path) -> None:
        """A recall figure without its threshold cannot be argued with."""
        r = run(_batch(tmp_path))
        assert r.scored is not None
        assert r.scored.as_dict()["tolerance_grace_days"] == (
            load_config().tolerances.grace_days
        )


class TestDecoysAppearInTheAnswerKey:
    """F6 — the key listed nothing for a decoy the engine correctly reported."""

    def test_decoys_declare_the_findings_they_should_produce(
        self, tmp_path: Path
    ) -> None:
        """A healthy subscription with a retryable failure IS a failed payment.

        The engine saying PAYMENT_FAILED about it is correct. The trap is claiming
        HALTED_SUBSCRIPTION, which `must_not_claim` pins separately.
        """
        write_batch(
            Generator(load_config(), seed=20260902, volume=300,
                      defect_profile={"healthy_subscription_decoy": {"count": 20}}).generate(),
            tmp_path,
        )
        gt = GroundTruth.read(tmp_path / "ground_truth.json")
        r = run(tmp_path)

        assert len(gt.real_defects) == 0, "decoys are not defects"
        assert len(gt.decoys) == 20

        # The key used to say nothing here, so a correct analysis read as 20 phantom
        # over-reports against an empty answer key.
        assert gt.decoy_findings() == {"PAYMENT_FAILED": 20}

        got = Counter(str(f.classification) for f in r.correlated.findings)
        assert got.get("PAYMENT_FAILED", 0) == 20
        assert got.get("HALTED_SUBSCRIPTION", 0) == 0, "walked into the trap"

    def test_decoy_findings_exclude_real_defects(self, tmp_path: Path) -> None:
        """Scoped to decoys deliberately.

        A real defect's `expected_classification` is what the classifier should say
        BEFORE correlation, and correlation then legitimately promotes some of them —
        a MISSING order whose payment failed is reported as PAYMENT_FAILED. Counting
        those here would swap one misleading number for another.
        """
        d = _batch(tmp_path)
        run(d)
        gt = GroundTruth.read(d / "ground_truth.json")
        assert gt.real_defects, "the demo profile plants real defects"

        # Only decoys contribute. The real defects here include MISSING orders, whose
        # expected_classification is MISSING — and correlation correctly reports them
        # as PAYMENT_FAILED, so counting them would reintroduce the mismatch.
        expected = gt.decoy_findings()
        assert sum(expected.values()) == len(gt.decoys)
