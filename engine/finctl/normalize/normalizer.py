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
import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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


# Excel's day-zero. Serial 1 is 1900-01-01, but Excel wrongly treats 1900 as a leap
# year, so the epoch that makes modern dates come out right is 1899-12-30.
EXCEL_EPOCH = datetime(1899, 12, 30, tzinfo=UTC)

# The window in which a bare number is read as an Excel serial rather than epoch
# seconds. 20000 is 1954-10-03 and 80000 is 2119-01-25 — wider than any settlement
# file will contain, and four orders of magnitude below the epoch-seconds range for
# the same dates (2020-01-01 is serial 43831 but epoch 1577836800). The two
# interpretations are therefore separated by a gap of ~10^4, not adjacent ranges
# needing a judgement call. See ADR-037.
EXCEL_SERIAL_MIN = 20_000
EXCEL_SERIAL_MAX = 80_000


def _looks_numeric(text: str) -> bool:
    """True for a bare decimal number, e.g. "44658" or "44658.44689814815".

    Deliberately narrower than float(): it rejects "1e9", "inf", "nan" and signed
    values, none of which are dates, so they fall through to the string formats and
    ultimately to a raised error rather than being coerced.
    """
    if not text:
        return False
    whole, _, frac = text.partition(".")
    return whole.isdigit() and (frac == "" or frac.isdigit())


def _from_excel_serial(serial: float) -> datetime:
    """Convert an Excel/OOXML serial date to UTC.

    The fractional part is the time of day: 44658.44689814815 is 2022-04-07 10:43:32.
    """
    return EXCEL_EPOCH + timedelta(days=serial)


def _parse_timestamp(value: Any, source_name: str, row_num: int) -> datetime | None:
    """Parse a timestamp to UTC. Accepts Excel serials, epoch seconds, ISO, DD/MM/YYYY.

    The Excel-serial branch exists because Razorpay's own dashboard exports carry them.
    In `sample-settlements-recon-report.xlsx` the SAME column holds both
    `44658.44689814815` and `29/06/2022 07:34:39` — a spreadsheet writes whichever the
    cell format dictates, so a real file mixes the two. Reading 44658 as epoch seconds
    yields 1970-01-01, which is not an error a merchant would ever see raised: it is a
    plausible-looking date that quietly makes every settlement look years late. See
    ADR-037.
    """
    if value in (None, ""):
        return None

    # A real datetime can arrive already parsed (openpyxl hands back datetimes for
    # date-formatted cells). Nothing to do but normalise the timezone.
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)

    text = str(value).strip()

    # Excel serial, integer or fractional. Checked BEFORE epoch seconds: the ranges do
    # not overlap, and getting the order wrong is the silent-1970 bug.
    if _looks_numeric(text):
        number = float(text)
        if EXCEL_SERIAL_MIN <= number <= EXCEL_SERIAL_MAX:
            return _from_excel_serial(number)
        # A fractional number outside the serial window is not a timestamp we know.
        # Refusing beats coercing it into a date that looks reasonable.
        if not float(number).is_integer():
            raise NormalizationError(
                f"{source_name} row {row_num}: {value!r} is fractional but outside the "
                f"Excel serial-date range ({EXCEL_SERIAL_MIN}–{EXCEL_SERIAL_MAX}). "
                "Refusing to guess whether it is a date."
            )

    # Epoch seconds — what Razorpay's API returns.
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=UTC)

    # "%d/%m/%Y %H:%M:%S" and "%d-%m-%Y %H:%M:%S" are the shapes Razorpay's dashboard
    # exports use alongside the serials. Longest-first so a datetime is not truncated
    # to a bare date by an earlier partial match.
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise NormalizationError(
            f"{source_name} row {row_num}: cannot parse timestamp {value!r}. "
            "Accepted: Excel serial date, epoch seconds, YYYY-MM-DD, "
            "DD/MM/YYYY, or ISO 8601."
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


# File formats we can read. Razorpay's dashboard exports .xlsx; a merchant's own
# bookkeeping is usually .csv. Both must work, because "export your settlement report"
# hands a merchant an Excel file and an upload path that rejects it stops them on step
# one. See ADR-043.
TABULAR_SUFFIXES = frozenset({".csv", ".xlsx", ".xlsm"})


def _read_tabular(path: Path, source_name: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Read a CSV or Excel file into (headers, row dicts).

    Returns raw cell values. Every mapping, money and timestamp decision happens
    downstream, so the two formats cannot diverge in how a value is interpreted — the
    only difference this function is allowed to introduce is where the bytes came from.
    """
    suffix = path.suffix.lower()

    if suffix in (".xlsx", ".xlsm"):
        return _read_excel(path, source_name)

    if suffix and suffix not in TABULAR_SUFFIXES:
        raise NormalizationError(
            f"{source_name}: cannot read {path.name} — unsupported format {suffix!r}. "
            f"Accepted: {', '.join(sorted(TABULAR_SUFFIXES))}."
        )

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        return headers, list(reader)


def _read_excel(path: Path, source_name: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Read the first worksheet of an .xlsx/.xlsm file.

    `data_only=True` returns the cached value of a formula rather than the formula
    text. A settlement report with a SUM in it must yield the number, not "=SUM(A1:A9)".

    Cells are handed on as-is: openpyxl returns real `datetime` objects for
    date-formatted cells and floats for numbers, and `_parse_timestamp` and
    `parse_money` both accept those. Stringifying here would throw away type
    information and re-create the Excel-serial ambiguity of ADR-037.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as exc:   # pragma: no cover - dependency is declared
        raise NormalizationError(
            f"{source_name}: reading {path.name} needs openpyxl. "
            "Install the engine's dependencies."
        ) from exc

    try:
        # Razorpay's exports carry no default style block, which openpyxl warns about on
        # every single file. The warning is about cosmetics we never read — we take cell
        # VALUES — so it is noise that would train a user to ignore warnings.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*no default style.*")
            wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise NormalizationError(
            f"{source_name}: cannot open {path.name} as an Excel workbook: {exc}"
        ) from exc

    try:
        ws = wb.worksheets[0]
        grid = ws.iter_rows(values_only=True)

        try:
            header_row = next(grid)
        except StopIteration:
            return [], []

        # Razorpay's settlements export opens with a blank spacer column, so trailing
        # and empty headers are dropped rather than becoming a column named "None".
        headers = [
            str(h).strip() for h in header_row if h is not None and str(h).strip()
        ]
        width = len(headers)

        rows: list[dict[str, Any]] = []
        for values in grid:
            # A wholly empty row is spacing, not data. Excel files are full of them, and
            # one would otherwise become a row of empty strings that fails money parsing.
            if all(v is None or (isinstance(v, str) and not v.strip()) for v in values):
                continue
            rows.append(dict(zip(headers, values[:width], strict=False)))

        return headers, rows
    finally:
        wb.close()


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

    headers, raw_rows = _read_tabular(path, source_name)
    if not headers:
        raise NormalizationError(
            f"{source_name}: {path} has no header row. Refusing to read positionally."
        )

    mapping = resolve_columns(headers, aliases, required, source_name)
    rows: list[dict[str, Any]] = []

    for row_num, raw in enumerate(raw_rows, start=2):
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
