"""JSONL audit log.

BEHAVIOR.md, stage `audit`:
  Promises  — every engine decision appended, human-readable: which rule fired, on which
              row, with which numbers, at which stage. Enough to reconstruct any figure
              on the verdict screen back to its source records.
  Refuses   — to log secrets, or to summarise. The log is raw and complete; reading it
              is the UI's problem.

JSON Lines rather than a database because the debugging tool at 11pm is `grep`, and a
format you can `tail -f` beats one you have to query. One event per line, append-only,
no rewriting — an audit trail that can be edited is not one.

The claim this file exists to support is "every number traces back to a Razorpay record".
That is only true if it is checkable, which means every figure on the verdict screen must
be reachable from here by following ids.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Keys whose values are never written, at any nesting depth. The engine does not
# currently handle credentials, but an audit log is exactly the file that quietly
# accumulates them later — so the guard exists before the need does.
REDACT_KEYS = frozenset({
    "key_secret", "api_key", "secret", "password", "token", "authorization",
    "razorpay_key_secret", "anthropic_api_key",
})


def _scrub(value: Any) -> Any:
    """Recursively drop anything credential-shaped. Structure is preserved."""
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if k.lower() in REDACT_KEYS else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


@dataclass
class AuditEvent:
    """One thing the engine did, with enough context to check it."""

    stage: str
    event: str
    detail: dict[str, Any] = field(default_factory=dict)
    order_id: str | None = None
    settlement_id: str | None = None

    def as_dict(self, sequence: int, batch_id: str) -> dict[str, Any]:
        out: dict[str, Any] = {
            "seq": sequence,
            "at": datetime.now(UTC).isoformat(),
            "batch": batch_id,
            "stage": self.stage,
            "event": self.event,
        }
        if self.order_id:
            out["order_id"] = self.order_id
        if self.settlement_id:
            out["settlement_id"] = self.settlement_id
        out["detail"] = _scrub(self.detail)
        return out


class AuditLog:
    """Append-only event log for one reconciliation run.

    Held in memory during the run and written once, rather than opened and flushed per
    event: a 50,000-row batch produces a lot of events, and per-event fsync would make
    the audit trail the bottleneck rather than the matcher.
    """

    def __init__(self, batch_id: str) -> None:
        self.batch_id = batch_id
        self.events: list[dict[str, Any]] = []

    def record(
        self,
        stage: str,
        event: str,
        detail: dict[str, Any] | None = None,
        *,
        order_id: str | None = None,
        settlement_id: str | None = None,
    ) -> None:
        self.events.append(
            AuditEvent(
                stage=stage, event=event, detail=detail or {},
                order_id=order_id, settlement_id=settlement_id,
            ).as_dict(len(self.events) + 1, self.batch_id)
        )

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for event in self.events:
                fh.write(json.dumps(event, sort_keys=False, default=str) + "\n")
        return path

    def by_stage(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.events:
            counts[e["stage"]] = counts.get(e["stage"], 0) + 1
        return counts

    def for_order(self, order_id: str) -> list[dict[str, Any]]:
        """Every decision touching one order — the drill-down a dispute needs."""
        return [e for e in self.events if e.get("order_id") == order_id]

    def __len__(self) -> int:
        return len(self.events)


def read_log(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL log back.

    A malformed line raises rather than being skipped: silently dropping audit records
    would make the log claim completeness it does not have.
    """
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{n} is not valid JSON: {exc}") from exc
    return out
