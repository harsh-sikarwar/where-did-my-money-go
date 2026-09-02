"""Normalize arbitrary input into the canonical schema.

BEHAVIOR.md, stage `normalize`:
  Promises  — canonical columns, integer paise, UTC. The ONLY place rupee strings parse.
  Refuses   — to guess a column mapping. Unrecognised or ambiguous columns raise.
  Bad input — empty file returns an empty frame WITH the schema; "nothing to reconcile"
              is a valid answer that must survive to the verdict stage.

The refusal to guess is the load-bearing part. A tool that silently maps a column it is
unsure about produces a confident, wrong reconciliation — and a merchant has no way to
tell that from a correct one. Raising costs seconds; guessing costs trust.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from finctl.money import MoneyError, parse_money
from finctl.schema import (
    BANK_ALIASES,
    BANK_REQUIRED,
    LEDGER_ALIASES,
    LEDGER_REQUIRED,
    normalise_key,
)


class NormalizationError(ValueError):
    """Raised when input cannot be mapped or parsed.

    Always names the offending column or value. An error that says only "bad input"
    forces a hunt through a 50,000-row file.
    """


@dataclass(frozen=True)
class ColumnMapping:
    """The resolved input-column -> canonical-column map, kept for the audit trail.

    Recorded rather than discarded because "which column did you read as the amount?"
    is a question a merchant may reasonably ask when a number looks wrong.
    """

    resolved: dict[str, str]           # canonical -> actual input column name
    unmapped: tuple[str, ...]          # input columns we did not use

    def describe(self) -> str:
        pairs = ", ".join(f"{v!r}->{k}" for k, v in sorted(self.resolved.items()))
        extra = f"; ignored {list(self.unmapped)}" if self.unmapped else ""
        return pairs + extra


def resolve_columns(
    headers: list[str],
    aliases: dict[str, tuple[str, ...]],
    required: tuple[str, ...],
    source_name: str,
) -> ColumnMapping:
    """Map input headers onto canonical names, or raise explaining why not.

    Never positional. A reordered file is fine; an unrecognisable one is an error.
    """
    folded = {normalise_key(h): h for h in headers}
    if len(folded) != len(headers):
        seen: dict[str, list[str]] = {}
        for h in headers:
            seen.setdefault(normalise_key(h), []).append(h)
        dupes = {k: v for k, v in seen.items() if len(v) > 1}
        raise NormalizationError(
            f"{source_name}: columns collide after folding: {dupes}. "
            "Rename them so each maps to a distinct field."
        )

    resolved: dict[str, str] = {}
    claimed: set[str] = set()

    for canonical, candidates in aliases.items():
        # dict.fromkeys de-duplicates while preserving order. Several aliases can fold
        # to the same key ("order_id" and "orderid" both fold to "orderid"), so the same
        # input column may be hit more than once - that is one candidate, not an
        # ambiguity. Only DISTINCT input columns constitute a genuine ambiguity.
        hits = list(
            dict.fromkeys(
                folded[normalise_key(c)] for c in candidates if normalise_key(c) in folded
            )
        )
        hits = [h for h in hits if h not in claimed]
        if not hits:
            continue
        if len(hits) > 1:
            # Ambiguity is reported, never resolved by preference order. Picking the
            # "best" candidate is exactly the silent guess this stage exists to refuse.
            raise NormalizationError(
                f"{source_name}: ambiguous mapping for {canonical!r} — "
                f"input has {sorted(hits)}, and more than one could be it. "
                "Rename or remove the extras so the intent is explicit."
            )
        resolved[canonical] = hits[0]
        claimed.add(hits[0])

    missing = [c for c in required if c not in resolved]
    if missing:
        raise NormalizationError(
            f"{source_name}: could not map required column(s) {missing}. "
            f"Input headers: {headers}. "
            f"Accepted spellings: "
            + "; ".join(f"{m}: {list(aliases[m])}" for m in missing)
            + ". Refusing to guess — see docs/BEHAVIOR.md, stage `normalize`."
        )

    return ColumnMapping(
        resolved=resolved,
        unmapped=tuple(h for h in headers if h not in claimed),
    )


def _parse_timestamp(value: Any, source_name: str, row_num: int) -> datetime | None:
    """Parse a timestamp to UTC. Accepts epoch seconds, ISO dates, and ISO datetimes."""
    if value in (None, ""):
        return None
    text = str(value).strip()

    # Epoch seconds — what Razorpay returns.
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=UTC)

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise NormalizationError(
            f"{source_name} row {row_num}: cannot parse timestamp {value!r}. "
            "Accepted: epoch seconds, YYYY-MM-DD, DD/MM/YYYY, or ISO 8601."
        ) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def normalize_ledger(path: Path) -> tuple[list[dict[str, Any]], ColumnMapping]:
    """Read a merchant ledger CSV into canonical rows.

    Amounts arrive as rupee strings and leave as integer paise — this is the boundary.
    """
    return _normalize_csv(
        path,
        aliases=LEDGER_ALIASES,
        required=LEDGER_REQUIRED,
        source_name="ledger",
        money_fields={"amount_paise": False},   # False = negatives not allowed
        timestamp_fields=("captured_at",),
    )


def normalize_bank(path: Path) -> tuple[list[dict[str, Any]], ColumnMapping]:
    """Read a bank statement CSV into canonical rows.

    Credits may legitimately be negative — a settlement reversal debits the account —
    so negatives are permitted here and refused in the ledger.
    """
    rows, mapping = _normalize_csv(
        path,
        aliases=BANK_ALIASES,
        required=BANK_REQUIRED,
        source_name="bank",
        money_fields={"credit_paise": True},
        timestamp_fields=(),
    )
    for i, row in enumerate(rows, start=2):
        raw = row.get("value_date")
        if raw:
            parsed = _parse_timestamp(raw, "bank", i)
            row["value_date"] = parsed.date() if parsed else None
    return rows, mapping


def _normalize_csv(
    path: Path,
    *,
    aliases: dict[str, tuple[str, ...]],
    required: tuple[str, ...],
    source_name: str,
    money_fields: dict[str, bool],
    timestamp_fields: tuple[str, ...],
) -> tuple[list[dict[str, Any]], ColumnMapping]:
    if not path.exists():
        raise NormalizationError(f"{source_name}: file not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        if not headers:
            raise NormalizationError(
                f"{source_name}: {path} has no header row. Refusing to read positionally."
            )

        mapping = resolve_columns(headers, aliases, required, source_name)
        rows: list[dict[str, Any]] = []

        for row_num, raw in enumerate(reader, start=2):
            out: dict[str, Any] = {}
            for canonical, input_col in mapping.resolved.items():
                value = raw.get(input_col)

                if canonical in money_fields:
                    try:
                        out[canonical] = parse_money(
                            value if value not in (None, "") else 0,
                            allow_negative=money_fields[canonical],
                        )
                    except MoneyError as exc:
                        raise NormalizationError(
                            f"{source_name} row {row_num}, column {input_col!r}: {exc}"
                        ) from exc
                elif canonical in timestamp_fields:
                    out[canonical] = _parse_timestamp(value, source_name, row_num)
                else:
                    out[canonical] = value.strip() if isinstance(value, str) else value

            out["_row"] = row_num
            rows.append(out)

    return rows, mapping


def load_collection(path: Path, source_name: str) -> list[dict[str, Any]]:
    """Read a Razorpay collection envelope: {"entity": "collection", "items": [...]}.

    Already canonical — these are Razorpay's own field names (ADR-008), which is the
    whole point of not renaming them. Accepts a bare list too, since a paginated fetch
    may be concatenated before it reaches us.
    """
    if not path.exists():
        raise NormalizationError(f"{source_name}: file not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise NormalizationError(f"{source_name}: invalid JSON in {path}: {exc}") from exc

    if isinstance(data, list):
        return data
    if not isinstance(data, dict) or "items" not in data:
        raise NormalizationError(
            f"{source_name}: expected a Razorpay collection with an 'items' key, "
            f"got keys {sorted(data) if isinstance(data, dict) else type(data).__name__}"
        )

    items = data["items"]
    declared = data.get("count")
    if declared is not None and declared != len(items):
        # A truncated page would silently under-report every total downstream.
        raise NormalizationError(
            f"{source_name}: collection declares count={declared} but carries "
            f"{len(items)} items. Refusing a partial page."
        )
    return items


def to_date(value: Any) -> date | None:
    """Coerce a timestamp-ish value to a UTC date. Used by the matcher and classifier."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC).date()
    if isinstance(value, str) and value.isdigit():
        return datetime.fromtimestamp(int(value), tz=UTC).date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise NormalizationError(f"cannot interpret {value!r} as a date")
