"""Audit log tests.

The claim this supports is "every number traces back to a Razorpay record". That is only
true if it is CHECKABLE, so these tests assert traceability rather than merely that a
log file exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finctl.audit.log import AuditLog, read_log
from finctl.config.loader import load_config
from finctl.generate.generator import Generator
from finctl.generate.writer import write_batch
from finctl.pipeline import run


@pytest.fixture
def batch_dir(tmp_path: Path) -> Path:
    write_batch(Generator(load_config(), seed=20260902, volume=200,
                          defect_profile="demo").generate(), tmp_path)
    return tmp_path


class TestLogMechanics:
    def test_events_are_sequenced_from_one(self) -> None:
        log = AuditLog("t")
        log.record("match", "a")
        log.record("classify", "b")
        assert [e["seq"] for e in log.events] == [1, 2]

    def test_round_trips_through_jsonl(self, tmp_path: Path) -> None:
        log = AuditLog("t")
        log.record("classify", "FEE", {"delta_paise": 400}, order_id="O1")
        path = log.write(tmp_path / "audit.jsonl")
        assert read_log(path) == log.events

    def test_one_event_per_line(self, tmp_path: Path) -> None:
        """JSONL so `grep` and `tail -f` work. That is the whole reason for the format."""
        log = AuditLog("t")
        for i in range(5):
            log.record("classify", f"e{i}")
        path = log.write(tmp_path / "a.jsonl")
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 5
        for line in lines:
            json.loads(line)   # each line independently parseable

    def test_a_malformed_line_raises_rather_than_being_skipped(self, tmp_path: Path) -> None:
        """Silently dropping records would make the log claim a completeness it lacks."""
        p = tmp_path / "bad.jsonl"
        p.write_text('{"seq": 1}\nnot json\n')
        with pytest.raises(ValueError, match="not valid JSON"):
            read_log(p)

    def test_missing_file_reads_as_empty(self, tmp_path: Path) -> None:
        assert read_log(tmp_path / "nope.jsonl") == []


class TestRedaction:
    def test_credential_shaped_keys_are_dropped(self) -> None:
        """The engine handles no secrets today, but an audit log is exactly the file
        that quietly accumulates them later."""
        log = AuditLog("t")
        log.record("ingest", "x", {"api_key": "sk-real", "rows": 5})
        assert log.events[0]["detail"]["api_key"] == "[redacted]"
        assert log.events[0]["detail"]["rows"] == 5

    def test_redaction_is_recursive(self) -> None:
        log = AuditLog("t")
        log.record("ingest", "x", {"nested": {"deep": {"password": "hunter2"}}})
        assert log.events[0]["detail"]["nested"]["deep"]["password"] == "[redacted]"

    def test_redaction_survives_lists(self) -> None:
        log = AuditLog("t")
        log.record("ingest", "x", {"items": [{"token": "abc"}, {"ok": 1}]})
        assert log.events[0]["detail"]["items"][0]["token"] == "[redacted]"
        assert log.events[0]["detail"]["items"][1]["ok"] == 1


class TestTraceability:
    """The point of the whole thing."""

    def test_every_stage_is_represented(self, batch_dir: Path) -> None:
        stages = run(batch_dir).audit.by_stage()
        for stage in ("ingest", "match", "classify", "correlate", "rank"):
            assert stages.get(stage, 0) > 0, f"no events for {stage}"

    def test_ingest_records_the_column_mapping(self, batch_dir: Path) -> None:
        """'Which column did you read as the amount?' must be answerable."""
        events = [e for e in run(batch_dir).audit.events if e["event"] == "source_staged"]
        ledger = next(e for e in events if e["detail"]["source"] == "ledger")
        assert "amount_paise" in ledger["detail"]["column_mapping"]
        assert ledger["detail"]["sha256"]

    def test_a_halted_subscription_traces_from_classify_to_correlate(
        self, batch_dir: Path
    ) -> None:
        """The demo centrepiece, followed end to end through the log."""
        result = run(batch_dir)
        halted = next(
            f for f in result.correlated.resolved
            if str(f.classification) == "HALTED_SUBSCRIPTION"
        )
        trail = result.audit.for_order(halted.order_id)

        stages = [e["stage"] for e in trail]
        assert "classify" in stages
        assert "correlate" in stages

        resolution = next(e for e in trail if e["stage"] == "correlate")
        c = resolution["detail"]["correlation"]
        assert c["join_chain"] == "order_id -> payment.subscription_id -> subscription.status"
        assert c["subscription_status"] == "halted"
        assert c["subscription_id"]
        assert c["invoice_id"]

    def test_every_classified_finding_carries_its_arithmetic(self, batch_dir: Path) -> None:
        # The classify stage emits stage-level events too (the reconciled summary, the
        # observed settlement cycle). Those are context, not findings, and carry no
        # proof — a finding is identifiable by having an order attached to it.
        for e in run(batch_dir).audit.events:
            if e["stage"] != "classify" or "order_id" not in e:
                continue
            proof = e["detail"]["proof"]
            assert "arithmetic" in proof or "reason" in proof, e["event"]

    def test_the_residual_is_logged_as_prominently_as_the_resolutions(
        self, tmp_path: Path
    ) -> None:
        """Burying the unexplained would defeat the point of having an honest one."""
        write_batch(Generator(load_config(), seed=1, volume=60,
                              defect_profile="scale").generate(), tmp_path)
        result = run(tmp_path)
        logged = [e for e in result.audit.events if e["event"] == "still_unexplained"]
        assert len(logged) == len(result.correlated.still_unexplained)

    def test_verdict_lines_record_the_policy_that_decided_them(
        self, batch_dir: Path
    ) -> None:
        """Why a line is actionable must be inspectable, not just that it is."""
        lines = [e for e in run(batch_dir).audit.events if e["event"] == "verdict_line"]
        assert lines
        for e in lines:
            assert "actionable" in e["detail"]
            assert "tolerances.yaml" in e["detail"]["policy"]

    def test_verdict_totals_are_reconstructible_from_the_log(
        self, batch_dir: Path
    ) -> None:
        """The strongest form of the claim: recompute the screen from the log alone."""
        result = run(batch_dir)
        from_log: dict[str, int] = {}
        for e in result.audit.events:
            if e["event"] == "verdict_line":
                from_log[e["detail"]["classification"]] = e["detail"]["amount_paise"]

        from_verdict = {
            str(line.classification): line.amount_paise for line in result.verdict.lines
        }
        assert from_log == from_verdict


class TestScale:
    def test_the_log_does_not_enumerate_reconciled_rows(self, tmp_path: Path) -> None:
        """At 5k rows those would be 95% of the log and none of the interest.

        The count is still recorded, so totals stay reconstructible.
        """
        write_batch(Generator(load_config(), seed=9, volume=5000,
                              defect_profile="scale").generate(), tmp_path)
        result = run(tmp_path)
        assert len(result.audit) < 5000
        summary = next(
            e for e in result.audit.events if e["event"] == "reconciled_summary"
        )
        assert summary["detail"]["count"] > 0
