"""Settlement-cycle inference tests.

Written after a blind test on a T+1 batch found the classifier judging EVERY batch
against the configured T+2 regardless of what the batch actually did. On T+1 it computed
due dates a day late and flagged nothing; on T+7 it would have flagged nearly every
settled order as late.

The matrix had run T+1 twenty-two times and reported 100% recall each time. Recall only
counts defects the generator planted, and the scorer correctly classified the unflagged
ones as within tolerance — so a whole axis catching zero was invisible to it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from finctl.calendar import WorkingCalendar
from finctl.classify.classifier import Classification, Classifier
from finctl.config.loader import load_config
from finctl.cycle import observe_cycle
from finctl.generate.generator import Generator
from finctl.generate.writer import write_batch
from finctl.match.matcher import match
from finctl.pipeline import run
from finctl.stage.staging import stage_from_dir


def batch_at(cycle: int, *, volume: int = 400, seed: int = 7) -> Path:
    d = Path(tempfile.mkdtemp())
    write_batch(
        Generator(load_config(), seed=seed, volume=volume,
                  settlement_cycle_days=cycle, defect_profile="demo").generate(),
        d,
    )
    return d


@pytest.fixture
def calendar() -> WorkingCalendar:
    tol = load_config().tolerances
    return WorkingCalendar(tol.weekend_days, tol.holidays)


class TestInference:
    @pytest.mark.parametrize("cycle", [1, 2, 3, 7])
    def test_it_recovers_the_cycle_the_batch_was_settled_on(
        self, calendar: WorkingCalendar, cycle: int
    ) -> None:
        obs = observe_cycle(match(stage_from_dir(batch_at(cycle))), calendar, 2)
        assert obs.observed_days == cycle

    def test_it_uses_the_mode_not_the_mean(self, calendar: WorkingCalendar) -> None:
        """The distribution is skewed by design — planted lags sit in the right tail.

        A mean would drift toward them, which is backwards: the baseline should be what
        NORMALLY happens, so abnormal settlements stand out against it.
        """
        obs = observe_cycle(match(stage_from_dir(batch_at(2))), calendar, 2)
        assert obs.observed_days == 2
        assert max(obs.distribution) > 2, "the batch must contain later settlements"

    def test_too_few_samples_falls_back_to_config(self, calendar: WorkingCalendar) -> None:
        """A wrong inference from three orders would silently rebase every judgement."""
        obs = observe_cycle(match(stage_from_dir(batch_at(1, volume=160))), calendar, 2)
        if obs.sample_size < 20:
            assert obs.observed_days is None
            assert obs.effective_days == 2

    def test_disagreement_with_config_is_reported(self, calendar: WorkingCalendar) -> None:
        obs = observe_cycle(match(stage_from_dir(batch_at(1))), calendar, 2)
        assert not obs.agrees_with_config
        assert obs.configured_days == 2
        assert obs.observed_days == 1

    def test_agreement_is_reported_too(self, calendar: WorkingCalendar) -> None:
        obs = observe_cycle(match(stage_from_dir(batch_at(2))), calendar, 2)
        assert obs.agrees_with_config


class TestTheBugItFixed:
    @pytest.mark.parametrize("cycle", [1, 2, 7])
    def test_timing_detection_is_consistent_across_cycles(self, cycle: int) -> None:
        """THE regression test.

        Before the fix: T+1 flagged 0, T+2 flagged 15, T+7 flagged 291 — on batches with
        an identical lag distribution. The same defects must be detected whatever cycle
        the merchant is on.

        The load-bearing property is AGREEMENT across cycles, not the literal count:
        the count follows from the batch composition, which changes whenever a defect
        type is added (it moved 15 -> 10 when UNRECORDED_REFUND took three index slots,
        ADR-039). A cycle-dependent count is the bug; a composition-dependent one is not.
        """
        result = Classifier(load_config()).classify(
            match(stage_from_dir(batch_at(cycle, volume=300, seed=99)))
        )
        assert len(result.by_class(Classification.TIMING)) == 10

    def test_all_cycles_agree_on_the_same_batch_shape(self) -> None:
        """The invariant behind the case above, asserted directly rather than implied."""
        counts = {
            cycle: len(
                Classifier(load_config())
                .classify(match(stage_from_dir(batch_at(cycle, volume=300, seed=99))))
                .by_class(Classification.TIMING)
            )
            for cycle in (1, 2, 7)
        }
        assert len(set(counts.values())) == 1, f"cycle-dependent detection: {counts}"

    def test_a_slow_cycle_does_not_flag_every_order_as_late(self) -> None:
        """A T+7 merchant is not late. They are on a slower contract.

        Judging them against a configured T+2 flagged 291 of ~291 settled orders — a
        mass false positive that would bury the actionable list.
        """
        result = Classifier(load_config()).classify(
            match(stage_from_dir(batch_at(7, volume=300, seed=99)))
        )
        timing = result.by_class(Classification.TIMING)
        assert len(timing) < 50, f"{len(timing)} orders flagged late on a T+7 batch"

    def test_a_fast_cycle_still_detects_lateness(self) -> None:
        """The opposite failure: T+1 detected NOTHING, because due dates were a day late."""
        result = Classifier(load_config()).classify(
            match(stage_from_dir(batch_at(1, volume=300, seed=99)))
        )
        assert len(result.by_class(Classification.TIMING)) > 0


class TestProvenance:
    def test_the_proof_says_which_cycle_it_judged_against(self) -> None:
        """A merchant disputing a 'late' call must be able to see the baseline used."""
        result = Classifier(load_config()).classify(
            match(stage_from_dir(batch_at(1, volume=300, seed=99)))
        )
        for f in result.by_class(Classification.TIMING):
            assert f.proof["cycle_days"] == 1
            assert f.proof["cycle_source"] in {"observed", "configured"}

    def test_the_audit_log_records_the_cycle_every_run(self) -> None:
        """Recorded always, not only on disagreement, so the audit trail says which
        baseline every timing judgement was made against."""
        result = run(batch_at(2))
        assert any(e["event"] == "settlement_cycle" for e in result.audit.events)

    def test_the_audit_log_flags_a_disagreement(self) -> None:
        result = run(batch_at(1))
        assert any(
            e["event"] == "settlement_cycle_disagrees_with_config"
            for e in result.audit.events
        )

    def test_the_pipeline_exposes_the_observation(self) -> None:
        result = run(batch_at(1))
        assert result.cycle is not None
        assert result.as_dict()["settlement_cycle"]["observed_days"] == 1


class TestAuditScrubberHandlesIntKeys:
    def test_a_dict_keyed_by_int_does_not_crash_the_log(self) -> None:
        """A latent bug the cycle distribution exposed: the scrubber called `k.lower()`
        on every key, so ANY integer-keyed dict would have crashed the audit log."""
        from finctl.audit.log import AuditLog
        log = AuditLog("t")
        log.record("classify", "x", {"distribution": {1: 10, 2: 20}})
        assert log.events[0]["detail"]["distribution"] == {1: 10, 2: 20}

    def test_redaction_still_works_alongside_int_keys(self) -> None:
        from finctl.audit.log import AuditLog
        log = AuditLog("t")
        log.record("classify", "x", {"api_key": "sk-real", "dist": {1: 2}})
        assert log.events[0]["detail"]["api_key"] == "[redacted]"
