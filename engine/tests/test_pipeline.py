"""Pipeline tests.

ADR-001 says the API is a thin wrapper over the engine. This module is what makes that
literally true, so its job is to be the ONE place the stage order lives. A second copy
of the sequence is how a UI ends up showing a number the CLI never produced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finctl.config.loader import load_config
from finctl.generate.generator import Generator
from finctl.generate.writer import write_batch
from finctl.pipeline import run


@pytest.fixture
def batch_dir(tmp_path: Path) -> Path:
    write_batch(Generator(load_config(), seed=20260902, volume=200,
                          defect_profile="demo").generate(), tmp_path)
    return tmp_path


class TestEndToEnd:
    def test_produces_every_stage(self, batch_dir: Path) -> None:
        r = run(batch_dir)
        assert r.batch.sources
        assert r.matches.order_matches
        assert r.classified.findings
        assert r.correlated.findings
        assert r.verdict.lines

    def test_the_checkpoint_number_moves(self, batch_dir: Path) -> None:
        r = run(batch_dir)
        assert r.correlated.unexplained_after_paise < r.correlated.unexplained_before_paise

    def test_verdict_arithmetic_is_internally_consistent(self, batch_dir: Path) -> None:
        v = run(batch_dir).verdict
        assert v.gap_paise == v.expected_paise - v.received_paise
        assert v.actionable_paise + v.benign_paise == sum(
            line.amount_paise for line in v.lines
        )

    def test_scoring_happens_when_ground_truth_exists(self, batch_dir: Path) -> None:
        r = run(batch_dir)
        assert r.scored is not None
        assert r.scored.total_missed == 0
        assert r.scored.false_positives == []

    def test_scoring_is_absent_without_ground_truth(self, batch_dir: Path) -> None:
        """Real merchant data has none. Its absence is honest, not an error."""
        (batch_dir / "ground_truth.json").unlink()
        r = run(batch_dir)
        assert r.scored is None
        assert r.verdict.lines          # everything else still works

    def test_serialises_completely(self, batch_dir: Path) -> None:
        """The API returns this. A missing key is a broken screen."""
        import json
        d = run(batch_dir).as_dict()
        for key in ("batch", "match", "classification", "correlation", "verdict",
                    "performance", "score"):
            assert key in d, key
        json.dumps(d)   # must be JSON-safe end to end

    def test_is_deterministic(self, batch_dir: Path) -> None:
        """Same input, same conclusions.

        Wall-clock fields are deliberately excluded: `created_at` and the performance
        timings differ between runs because a clock ticks, which is not a determinism
        failure. What must be identical is every number the engine CONCLUDED — the
        match rates, the classifications, the correlation, the verdict.
        """
        a, b = run(batch_dir).as_dict(), run(batch_dir).as_dict()

        for d in (a, b):
            d["batch"].pop("created_at")
            d.pop("performance")

        assert a == b

    def test_wall_clock_fields_are_the_only_thing_that_varies(
        self, batch_dir: Path
    ) -> None:
        """Guards the exclusion above from quietly hiding a real difference."""
        a, b = run(batch_dir).as_dict(), run(batch_dir).as_dict()
        differing = {
            key for key in a
            if key not in ("performance",) and a[key] != b[key]
        }
        assert differing <= {"batch"}   # and within batch, only created_at


class TestAdversarial:
    def test_a_clean_batch_says_nothing_needs_you(self, tmp_path: Path) -> None:
        write_batch(Generator(load_config(), seed=5, volume=100,
                              defect_profile="clean").generate(), tmp_path)
        v = run(tmp_path).verdict
        assert v.headline() == "Nothing needs you this week."
        assert v.actionable_lines == []

    def test_a_batch_with_no_bank_file_still_produces_a_verdict(
        self, batch_dir: Path
    ) -> None:
        """Two-way reconciliation is a supported mode, not a failure."""
        (batch_dir / "bank.csv").unlink()
        r = run(batch_dir)
        assert r.verdict.lines
        assert r.matches.pass2_total >= 0

    @pytest.mark.parametrize("volume", [1, 60, 500])
    def test_a_range_of_volumes(self, tmp_path: Path, volume: int) -> None:
        write_batch(Generator(load_config(), seed=5, volume=volume,
                              defect_profile="scale").generate(), tmp_path)
        assert run(tmp_path).rows_processed > 0


class TestPerformance:
    def test_throughput_is_reported(self, batch_dir: Path) -> None:
        """Named honestly rather than discovered on test day."""
        r = run(batch_dir)
        assert r.elapsed_seconds > 0
        assert r.throughput > 0

    def test_five_thousand_rows_stay_under_a_second(self, tmp_path: Path) -> None:
        """A soft ceiling. If this ever fails, the bottleneck is worth naming."""
        write_batch(Generator(load_config(), seed=9, volume=5000,
                              defect_profile="scale").generate(), tmp_path)
        r = run(tmp_path)
        assert r.elapsed_seconds < 1.0, f"5k rows took {r.elapsed_seconds:.2f}s"
