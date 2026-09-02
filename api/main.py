"""FastAPI wrapper. Deliberately thin.

ADR-001: the engine is the project; this is presentation. Every endpoint here calls
`finctl.pipeline.run()` and reshapes the result for HTTP. No reconciliation logic lives
in this file, and none should — anything the UI can do, the CLI must be able to do first.
If a number appears only in the browser, it is not testable and does not exist.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# The engine is a sibling package, not an installed dependency of this app.
ENGINE_DIR = Path(__file__).parent.parent / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from finctl.classify.classifier import Classification  # noqa: E402
from finctl.config.loader import load_config  # noqa: E402
from finctl.money import format_rupees  # noqa: E402
from finctl.pipeline import PipelineResult, run  # noqa: E402

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


@app.get("/api/batches")
def list_batches() -> dict[str, Any]:
    if not DATA_ROOT.is_dir():
        return {"batches": []}
    out = []
    for path in sorted(DATA_ROOT.iterdir()):
        if path.is_dir() and (path / "ledger.csv").exists():
            out.append({
                "name": path.name,
                "has_ground_truth": (path / "ground_truth.json").exists(),
            })
    return {"batches": out}


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
def audit(batch: str) -> dict[str, Any]:
    """What was ingested, and what the engine did with it."""
    result = _load(batch)
    return {
        "batch": batch,
        "manifest": result.batch.manifest(),
        "match": result.matches.summary(),
        "classification": result.classified.summary(),
        "correlation": result.correlated.summary(),
    }
