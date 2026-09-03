"""FastAPI wrapper. Deliberately thin.

ADR-001: the engine is the project; this is presentation. Every endpoint here calls
`finctl.pipeline.run()` and reshapes the result for HTTP. No reconciliation logic lives
in this file, and none should — anything the UI can do, the CLI must be able to do first.
If a number appears only in the browser, it is not testable and does not exist.
"""

from __future__ import annotations

import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The engine is a sibling package, not an installed dependency of this app.
ENGINE_DIR = Path(__file__).parent.parent / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from finctl.classify.classifier import Classification  # noqa: E402
from finctl.config.loader import load_config  # noqa: E402
from finctl.money import format_rupees  # noqa: E402
from finctl.normalize.normalizer import NormalizationError  # noqa: E402
from finctl.pipeline import PipelineResult, run  # noqa: E402
from finctl.schema import Source  # noqa: E402

app = FastAPI(
    title="Where did my money go?",
    description=(
        "Settlement reconciliation with payment-failure correlation. "
        "Every number here comes from the engine; this layer only reshapes it for HTTP."
    ),
    version="0.1.0",
)

# The Next.js dev server. Wide open because this is a local demo tool with no auth and
# no user data — production auth is explicitly out of scope (see LIMITATIONS.md).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_ROOT = ENGINE_DIR / "data"

# One run is cached per batch so the drill-down endpoints do not re-reconcile on every
# click. Keyed by batch name; cleared by regenerating. Deliberately a plain dict: this
# is a single-user demo tool, and a cache library would be infrastructure the problem
# does not have.
_cache: dict[str, PipelineResult] = {}


def _load(batch: str, *, refresh: bool = False) -> PipelineResult:
    if not refresh and batch in _cache:
        return _cache[batch]

    # Reject anything that could escape DATA_ROOT before touching the filesystem.
    if "/" in batch or "\\" in batch or batch.startswith("."):
        raise HTTPException(400, f"invalid batch name: {batch!r}")

    path = DATA_ROOT / batch
    if not path.is_dir():
        available = sorted(p.name for p in DATA_ROOT.iterdir() if p.is_dir()) if DATA_ROOT.is_dir() else []
        raise HTTPException(404, f"no batch {batch!r}. Available: {available}")

    try:
        result = run(path, load_config())
    except Exception as exc:
        # Surface the engine's own message. Its errors are written to be read by a
        # human and name the offending column, row or key — flattening them into
        # "internal error" would discard the most useful part.
        raise HTTPException(422, f"{type(exc).__name__}: {exc}") from exc

    _cache[batch] = result
    return result


def _money(paise: int) -> dict[str, Any]:
    """Money crosses the wire as BOTH paise and a formatted string.

    Paise so the client never does currency arithmetic in JavaScript floats; the string
    so it never has to reimplement Indian digit grouping. ADR-003 does not stop at the
    engine boundary.
    """
    return {"paise": paise, "display": format_rupees(paise)}


@app.get("/health")
def health() -> dict[str, Any]:
    batches = (
        sorted(p.name for p in DATA_ROOT.iterdir() if p.is_dir())
        if DATA_ROOT.is_dir() else []
    )
    return {"status": "ok", "engine": "finctl", "batches": batches}


def _ledger_file(path: Path) -> Path | None:
    """The batch's ledger, in whichever tabular format it was supplied as (ADR-043)."""
    for suffix in (".csv", ".xlsx", ".xlsm"):
        candidate = path / f"ledger{suffix}"
        if candidate.exists():
            return candidate
    return None


@app.get("/api/batches")
def list_batches() -> dict[str, Any]:
    if not DATA_ROOT.is_dir():
        return {"batches": []}
    out = []
    for path in sorted(DATA_ROOT.iterdir()):
        if path.is_dir() and _ledger_file(path):
            out.append({
                "name": path.name,
                "has_ground_truth": (path / "ground_truth.json").exists(),
                "uploaded": (path / ".uploaded").exists(),
            })
    return {"batches": out}


# What a merchant may upload, and where each file lands. The KEY is the form field; the
# VALUE is the on-disk stem `stage_from_dir` looks for.
#
# `ledger` is the only required leg. Everything else is genuinely optional and the engine
# already has an answer for its absence: no bank file is a two-way reconciliation, and no
# subscriptions file means correlation has one fewer path. Demanding all three would
# refuse batches the engine can reconcile perfectly well. See ADR-044.
UPLOAD_SLOTS: dict[str, str] = {
    "ledger": "ledger",
    "bank": "bank",
    "recon": "settlement_recon",
    "payments": "payments",
    "subscriptions": "subscriptions",
}

TABULAR_SUFFIXES = {".csv", ".xlsx", ".xlsm"}
JSON_SUFFIXES = {".json"}

# Slots that must be JSON, because they are Razorpay collection envelopes rather than
# tabular exports (ADR-008).
JSON_SLOTS = {"recon", "payments", "subscriptions"}

MAX_UPLOAD_BYTES = 64 * 1024 * 1024   # 64 MB: ~50k rows of xlsx with room to spare


def _safe_batch_name(name: str) -> str:
    """Reject anything that could escape DATA_ROOT, before touching the filesystem."""
    cleaned = name.strip()
    if not cleaned or cleaned.startswith(".") or "/" in cleaned or "\\" in cleaned:
        raise HTTPException(400, f"invalid batch name: {name!r}")
    if not all(ch.isalnum() or ch in "-_" for ch in cleaned):
        raise HTTPException(
            400,
            f"invalid batch name: {name!r}. Use letters, digits, hyphens and "
            "underscores only.",
        )
    return cleaned


@app.post("/api/upload")
async def upload(
    batch: str = Form(...),
    ledger: UploadFile = File(...),
    bank: UploadFile | None = File(None),
    recon: UploadFile | None = File(None),
    payments: UploadFile | None = File(None),
    subscriptions: UploadFile | None = File(None),
) -> dict[str, Any]:
    """Accept a merchant's own files and reconcile them.

    Deliberately thin, like the rest of this module (ADR-001): it writes the files to a
    batch directory and calls the same `run()` the CLI does. No reconciliation logic
    lives here, and the upload path must not become a second way to reconcile.

    Missing legs are reported, not rejected — the engine's answer for an absent bank file
    is "this money is in flight", which is a better answer than refusing the upload.
    """
    name = _safe_batch_name(batch)
    target = DATA_ROOT / name
    if target.exists():
        raise HTTPException(
            409,
            f"batch {name!r} already exists. Staging entries are immutable — "
            "corrections create a new batch (BEHAVIOR.md, stage `stage`). "
            "Choose another name.",
        )

    supplied = {
        "ledger": ledger, "bank": bank, "recon": recon,
        "payments": payments, "subscriptions": subscriptions,
    }

    target.mkdir(parents=True)
    written: dict[str, dict[str, Any]] = {}
    try:
        for slot, upload_file in supplied.items():
            if upload_file is None or not upload_file.filename:
                continue

            suffix = Path(upload_file.filename).suffix.lower()
            allowed = JSON_SUFFIXES if slot in JSON_SLOTS else TABULAR_SUFFIXES
            if suffix not in allowed:
                raise HTTPException(
                    400,
                    f"{slot}: cannot read {upload_file.filename!r} — expected "
                    f"{' or '.join(sorted(allowed))}, got {suffix or 'no extension'}.",
                )

            payload = await upload_file.read()
            if len(payload) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    413,
                    f"{slot}: {upload_file.filename!r} is "
                    f"{len(payload) // (1024 * 1024)} MB, over the "
                    f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                )

            dest = target / f"{UPLOAD_SLOTS[slot]}{suffix}"
            dest.write_bytes(payload)
            written[slot] = {"filename": upload_file.filename, "bytes": len(payload)}

        (target / ".uploaded").write_text(datetime.now(UTC).isoformat())

        try:
            result = run(target, load_config())
        except NormalizationError as exc:
            # The normalizer's errors name the offending column, row or value and list
            # the spellings it accepts. That message IS the fix instruction, so it is
            # surfaced verbatim rather than flattened into "bad file".
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(422, f"{type(exc).__name__}: {exc}") from exc

    except Exception:
        # A half-written batch would be staged on the next request and silently
        # reconcile a partial upload. Remove it.
        shutil.rmtree(target, ignore_errors=True)
        raise

    _cache[name] = result

    staged = set(result.batch.sources)
    missing = [s.value for s in Source if s not in staged]

    return {
        "batch": name,
        "files": written,
        "rows_processed": result.rows_processed,
        "missing_sources": missing,
        # Named explicitly rather than left for the caller to infer: a merchant who
        # uploads only a ledger and a recon file gets a real answer, and should be told
        # which question it cannot answer rather than assuming it answered all of them.
        "note": _missing_note(missing),
        "manifest": result.batch.manifest(),
        "headline": result.verdict.headline(),
    }


def _missing_note(missing: list[str]) -> str | None:
    if not missing:
        return None
    notes = []
    if "bank" in missing:
        notes.append(
            "No bank statement, so this is a two-way reconciliation: money Razorpay has "
            "released but which has not landed is reported as in flight rather than as "
            "missing."
        )
    if "subscriptions" in missing:
        notes.append(
            "No subscriptions file, so halted-subscription correlation is unavailable — "
            "those gaps stay in the residual rather than being explained."
        )
    if "payments" in missing:
        notes.append(
            "No payments file, so failed-payment correlation is unavailable."
        )
    return " ".join(notes) or None


@app.get("/api/verdict/{batch}")
def verdict(batch: str, refresh: bool = False) -> dict[str, Any]:
    """The four lines and a verdict. The default screen."""
    result = _load(batch, refresh=refresh)
    v = result.verdict

    return {
        "batch": batch,
        "expected": _money(v.expected_paise),
        "received": _money(v.received_paise),
        "gap": _money(v.gap_paise),
        "headline": v.headline(),
        "actionable_total": _money(v.actionable_paise),
        "benign_total": _money(v.benign_paise),
        "unexplained": _money(v.unexplained_paise),
        "lines": [
            {
                "classification": str(line.classification),
                "label": line.label,
                "explanation": line.explanation,
                "count": line.count,
                "amount": _money(line.amount_paise),
                "actionable": line.actionable,
            }
            for line in v.lines
        ],
        "match": {
            "pass1": result.matches.summary()["pass1"],
            "pass2": result.matches.summary()["pass2"],
        },
        "performance": {
            "elapsed_seconds": round(result.elapsed_seconds, 4),
            "rows_processed": result.rows_processed,
            "rows_per_second": round(result.throughput),
        },
    }


@app.get("/api/detail/{batch}/{classification}")
def detail(batch: str, classification: str, limit: int = 200) -> dict[str, Any]:
    """Every row behind one verdict line, with its arithmetic proof.

    This is the `[detail]` click. The proof is what makes the simplicity a choice
    rather than a limitation.
    """
    result = _load(batch)
    try:
        target = Classification(classification.upper())
    except ValueError:
        raise HTTPException(
            404,
            f"unknown classification {classification!r}. "
            f"Known: {sorted(str(c) for c in Classification)}",
        ) from None

    findings = [f for f in result.correlated.findings if f.classification is target]
    line = next((c for c in result.verdict.lines if c.classification is target), None)

    return {
        "batch": batch,
        "classification": str(target),
        "label": line.label if line else str(target).lower(),
        "explanation": line.explanation if line else "",
        "count": len(findings),
        "total": _money(sum(f.amount_paise for f in findings)),
        "truncated": len(findings) > limit,
        "findings": [
            {
                "order_id": f.order_id,
                "settlement_id": f.settlement_id,
                "amount": _money(f.amount_paise),
                "proof": f.proof,
                "candidates": [str(c) for c in f.candidates],
            }
            for f in findings[:limit]
        ],
    }


@app.get("/api/correlation/{batch}")
def correlation(batch: str) -> dict[str, Any]:
    """Before/after — the differentiator, as a number."""
    result = _load(batch)
    c = result.correlated

    return {
        "batch": batch,
        "before": _money(c.unexplained_before_paise),
        "after": _money(c.unexplained_after_paise),
        "resolved": _money(c.resolved_paise),
        "gain_ratio": round(c.gain_ratio, 4),
        "resolved_count": len(c.resolved),
        "still_unexplained_count": len(c.still_unexplained),
        "resolved_by_class": [
            {
                "classification": name,
                "count": info["count"],
                "amount": _money(info["paise"]),
            }
            for name, info in c.summary()["resolved_by_class"].items()
        ],
        "still_unexplained": [
            {
                "order_id": f.order_id,
                "amount": _money(f.amount_paise),
                "outcome": f.proof.get("correlation", {}).get("outcome", "not attempted"),
            }
            for f in c.still_unexplained[:50]
        ],
    }


@app.get("/api/score/{batch}")
def score_endpoint(batch: str) -> dict[str, Any]:
    """Measured accuracy against ground truth. Absent for real merchant data."""
    result = _load(batch)
    if result.scored is None:
        raise HTTPException(
            404,
            f"batch {batch!r} has no ground_truth.json. "
            "Accuracy can only be measured on seeded data.",
        )
    return {"batch": batch, **result.scored.as_dict()}


@app.get("/api/audit/{batch}")
def audit(batch: str, stage: str | None = None, order_id: str | None = None,
          limit: int = 500) -> dict[str, Any]:
    """Every decision the engine made, in order.

    This is what makes "every number traces back to a Razorpay record" checkable rather
    than merely asserted. Filterable by stage or by order so a single disputed figure
    can be followed from ingest to verdict.
    """
    result = _load(batch)
    events = result.audit.events

    if order_id:
        events = [e for e in events if e.get("order_id") == order_id]
    if stage:
        events = [e for e in events if e["stage"] == stage]

    return {
        "batch": batch,
        "manifest": result.batch.manifest(),
        "total_events": len(result.audit),
        "by_stage": result.audit.by_stage(),
        "filtered_count": len(events),
        "truncated": len(events) > limit,
        "events": events[:limit],
        "summary": {
            "match": result.matches.summary(),
            "classification": result.classified.summary(),
            "correlation": result.correlated.summary(),
        },
    }


@app.get("/api/trace/{batch}/{order_id}")
def trace(batch: str, order_id: str) -> dict[str, Any]:
    """Follow one order from ingest to verdict.

    The answer to "why does this row say what it says?" — which is the question an
    audit trail exists to answer.
    """
    result = _load(batch)
    events = result.audit.for_order(order_id)
    if not events:
        raise HTTPException(404, f"no audit events for order {order_id!r} in batch {batch!r}")

    finding = next((f for f in result.correlated.findings if f.order_id == order_id), None)
    order = next((m for m in result.matches.order_matches if m.order_id == order_id), None)

    return {
        "batch": batch,
        "order_id": order_id,
        "ledger": {
            "amount": _money(order.ledger_amount_paise),
            "method": order.ledger_row.get("payment_method"),
        } if order else None,
        "settlement": {
            "matched": order.matched,
            "gross": _money(order.settled_gross_paise),
            "net": _money(order.settled_net_paise),
            "fee": _money(order.fee_paise),
            "settlement_ids": sorted({r["settlement_id"] for r in order.recon_rows}),
            "utrs": sorted({r["settlement_utr"] for r in order.recon_rows if r.get("settlement_utr")}),
        } if order else None,
        "outcome": {
            "classification": str(finding.classification),
            "amount": _money(finding.amount_paise),
            "proof": finding.proof,
        } if finding else None,
        "events": events,
    }
