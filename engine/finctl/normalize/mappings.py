"""Remembered column mappings, keyed by the shape of the file.

BEHAVIOR.md, stage `normalize`, promises the engine refuses to guess a column mapping.
That refusal is right, and it is also a wall a merchant hits every single week if the
answer is not remembered. Cointab configures a merchant's format once at onboarding;
Hyperswitch has them email a sample file so someone sets it up. Both remember. See
docs/PRIOR-ART.md and ADR-045.

What is stored is a decision a HUMAN made, not a guess the engine made, and it is
reapplied only to a file with the SAME COLUMNS. A remembered mapping is therefore never
an inference about a file it has not seen the shape of.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finctl.schema import normalise_key


def header_fingerprint(headers: list[str]) -> str:
    """A stable id for "a file with these columns".

    Order-independent and fold-insensitive, because a merchant's export tool may reorder
    columns or change their capitalisation between months without the file becoming a
    different KIND of file. It is exactly as tolerant as `resolve_columns` already is,
    and no more: a file that gains or loses a column gets a different fingerprint and is
    asked about again, which is correct — the mapping was never confirmed for that shape.
    """
    folded = sorted(normalise_key(h) for h in headers if h and h.strip())
    return hashlib.sha256("\x00".join(folded).encode()).hexdigest()[:16]


@dataclass
class RememberedMapping:
    """One human decision about one file shape."""

    fingerprint: str
    source: str
    mapping: dict[str, str]
    headers: list[str] = field(default_factory=list)
    remembered_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "source": self.source,
            "mapping": dict(sorted(self.mapping.items())),
            "headers": list(self.headers),
            "remembered_at": self.remembered_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RememberedMapping:
        return cls(
            fingerprint=raw["fingerprint"],
            source=raw["source"],
            mapping=dict(raw["mapping"]),
            headers=list(raw.get("headers", ())),
            remembered_at=raw.get("remembered_at", ""),
        )


class MappingStore:
    """A JSON file of remembered mappings. Deliberately not a database.

    Flat files are the storage decision everywhere else in this engine, and a merchant
    has a handful of file shapes, not thousands. A store that needs migrations to hold
    five entries would be infrastructure the problem does not have.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[str, RememberedMapping] = {}
        self._load()

    def _key(self, source: str, fingerprint: str) -> str:
        # Scoped by source: the same headers mean different things in a ledger and a
        # bank statement, and a mapping confirmed for one must not leak into the other.
        return f"{source}:{fingerprint}"

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            # A corrupt store must not break reconciliation. The cost of ignoring it is
            # that a merchant is asked to map their columns once more; the cost of
            # raising is that they cannot reconcile at all.
            return
        for entry in raw.get("mappings", []):
            try:
                remembered = RememberedMapping.from_dict(entry)
            except (KeyError, TypeError):
                continue
            self._entries[self._key(remembered.source, remembered.fingerprint)] = remembered

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "mappings": [e.as_dict() for e in sorted(
                self._entries.values(), key=lambda e: (e.source, e.fingerprint)
            )],
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n")
        return self.path

    def lookup(self, source: str, headers: list[str]) -> dict[str, str] | None:
        """The remembered mapping for this file shape, if a human confirmed one."""
        entry = self._entries.get(self._key(source, header_fingerprint(headers)))
        return dict(entry.mapping) if entry else None

    def remember(self, source: str, headers: list[str], mapping: dict[str, str]) -> RememberedMapping:
        """Record a human's decision about this file shape.

        Re-confirming the same shape REPLACES the previous answer rather than merging
        with it. A merchant correcting a mapping they got wrong must not be left with a
        half-corrected one, and merging would make the stored state depend on the order
        the corrections happened to arrive in.
        """
        fingerprint = header_fingerprint(headers)
        entry = RememberedMapping(
            fingerprint=fingerprint,
            source=source,
            mapping=dict(mapping),
            headers=list(headers),
            remembered_at=datetime.now(UTC).isoformat(),
        )
        self._entries[self._key(source, fingerprint)] = entry
        self.save()
        return entry

    def forget(self, source: str, headers: list[str]) -> bool:
        return self._entries.pop(self._key(source, header_fingerprint(headers)), None) is not None

    def all(self) -> list[RememberedMapping]:
        return sorted(self._entries.values(), key=lambda e: (e.source, e.fingerprint))
