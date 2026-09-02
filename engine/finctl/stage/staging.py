"""Staging entries: validated, not yet reconciled. Immutable.

Adopted from Hyperswitch's published recon design — see docs/PRIOR-ART.md.

BEHAVIOR.md, stage `stage`:
  Promises  — re-running over the same staged batch produces the same result and does
              not mutate the batch.
  Refuses   — to modify an entry after creation. Corrections create a new batch.
  Bad input — the same file staged twice is detected by content hash and reported as a
              duplicate rather than silently doubling every figure.

Immutability is what makes the audit trail possible. If a second run can mutate the
first run's records, then the audit log describes a state that no longer exists, and
"every number traces back to a Razorpay record" stops being true.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finctl.schema import Source


class DuplicateBatchError(ValueError):
    """Raised when the identical file is staged twice into one batch.

    Deliberately loud. Silently accepting a duplicate would double every total on the
    verdict screen, and the merchant would have no way to tell that from real growth.
    """


def content_hash(payload: Any) -> str:
    """A stable hash of content, independent of key order and whitespace.

    Used for duplicate detection, so it must depend on the DATA and nothing else — not
    filename, not mtime, not row order within the file. The same rows uploaded twice
    under different names are still a duplicate.
    """
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class StagedSource:
    """One ingested file, frozen at the moment it was read."""

    source: Source
    rows: tuple[dict[str, Any], ...]
    content_sha256: str
    origin: str
    column_mapping: str = ""

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class StagedBatch:
    """A complete set of inputs, ready to reconcile.

    Sources are added once and then read-only. The batch itself is mutable only in the
    sense that sources are added during ingest; after `seal()` it refuses further writes.
    """

    batch_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    sources: dict[Source, StagedSource] = field(default_factory=dict)
    _sealed: bool = False

    def add(
        self,
        source: Source,
        rows: list[dict[str, Any]],
        origin: str,
        column_mapping: str = "",
    ) -> StagedSource:
        """Stage one source. Raises if the same content was already staged."""
        if self._sealed:
            raise ValueError(
                f"batch {self.batch_id} is sealed; staging entries are immutable. "
                "Corrections create a new batch."
            )

        digest = content_hash(rows)

        # An EMPTY source cannot be a duplicate of another empty source. Two empty files
        # hash identically because they contain the same nothing, and treating that as a
        # duplicate upload made the adversarial "empty batch" case raise instead of
        # answering "nothing to reconcile" — which BEHAVIOR.md requires to be a valid
        # answer that reaches the verdict stage.
        candidates = self.sources.items() if rows else []
        for existing_source, existing in candidates:
            if existing.content_sha256 == digest:
                raise DuplicateBatchError(
                    f"refusing to stage {origin!r} as {source}: identical content "
                    f"({digest[:12]}…, {len(rows)} rows) was already staged as "
                    f"{existing_source} from {existing.origin!r}. "
                    "Staging it twice would double every total."
                )

        if source in self.sources:
            raise ValueError(
                f"source {source} already staged in batch {self.batch_id} from "
                f"{self.sources[source].origin!r}. Corrections create a new batch."
            )

        staged = StagedSource(
            source=source,
            rows=tuple(rows),
            content_sha256=digest,
            origin=origin,
            column_mapping=column_mapping,
        )
        self.sources[source] = staged
        return staged

    def seal(self) -> StagedBatch:
        """Close the batch to further staging. Returns self for chaining."""
        self._sealed = True
        return self

    def get(self, source: Source) -> tuple[dict[str, Any], ...]:
        """Rows for a source, or an empty tuple.

        Empty rather than raising: a batch with no bank statement is a two-way
        reconciliation, which is a supported mode, not an error.
        """
        staged = self.sources.get(source)
        return staged.rows if staged else ()

    def require(self, source: Source) -> tuple[dict[str, Any], ...]:
        """Rows for a source, raising if it was never staged."""
        if source not in self.sources:
            raise ValueError(
                f"batch {self.batch_id} has no {source} data staged. "
                f"Staged sources: {sorted(s.value for s in self.sources)}"
            )
        return self.sources[source].rows

    def manifest(self) -> dict[str, Any]:
        """A description of exactly what was ingested. Goes into the audit log.

        This is the answer to "what did you actually read?" — including the resolved
        column mapping, so a disputed number can be traced to the column it came from.
        """
        return {
            "batch_id": self.batch_id,
            "created_at": self.created_at.isoformat(),
            "sealed": self._sealed,
            "sources": {
                s.value: {
                    "origin": staged.origin,
                    "rows": staged.row_count,
                    "sha256": staged.content_sha256,
                    "column_mapping": staged.column_mapping,
                }
                for s, staged in sorted(self.sources.items())
            },
        }


def stage_from_dir(data_dir: Path, batch_id: str | None = None) -> StagedBatch:
    """Ingest a generated or downloaded batch directory into a sealed StagedBatch.

    Missing optional sources are tolerated: no bank.csv means two-way reconciliation,
    no subscriptions.json means correlation has one fewer path. Both are legitimate
    configurations rather than errors, and the manifest records what was absent.
    """
    from finctl.normalize.normalizer import (
        load_collection,
        normalize_bank,
        normalize_ledger,
    )

    batch = StagedBatch(batch_id=batch_id or data_dir.name)

    ledger_path = data_dir / "ledger.csv"
    if ledger_path.exists():
        rows, mapping = normalize_ledger(ledger_path)
        batch.add(Source.LEDGER, rows, str(ledger_path), mapping.describe())

    bank_path = data_dir / "bank.csv"
    if bank_path.exists():
        rows, mapping = normalize_bank(bank_path)
        batch.add(Source.BANK, rows, str(bank_path), mapping.describe())

    for source, filename in (
        (Source.RECON, "settlement_recon.json"),
        (Source.PAYMENTS, "payments.json"),
        (Source.SUBSCRIPTIONS, "subscriptions.json"),
    ):
        path = data_dir / filename
        if path.exists():
            batch.add(source, load_collection(path, source.value), str(path))

    return batch.seal()
