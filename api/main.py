"""FastAPI wrapper. Deliberately thin.

ADR-001: the engine is the project; this is presentation. Every endpoint here calls
`finctl.pipeline.run()` and reshapes the result for HTTP. No reconciliation logic lives
in this file, and none should — anything the UI can do, the CLI must be able to do first.
If a number appears only in the browser, it is not testable and does not exist.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The engine is a sibling package, not an installed dependency of this app.
ENGINE_DIR = Path(__file__).parent.parent / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

# The API key lives in .env at the repo root, and until now nothing read it. The engine
# is built to install and run with zero LLM dependencies (ADR-001), so it cannot reach
# for dotenv itself; this process is the boundary where a key first becomes available,
# which makes it the place to load the file. Without this the explanation layer sees no
# key, concludes the model is unavailable, and serves the deterministic template — the
# correct response to a missing key, and indistinguishable from a broken one.
# `override=False`: a key exported in the shell outranks the file.
try:
    from dotenv import load_dotenv

    load_dotenv(ENGINE_DIR.parent / ".env", override=False)
except ImportError:     # no dotenv installed; the template path still renders
    pass

from fastapi import (  # noqa: E402
    FastAPI,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from finctl.actions import to_csv  # noqa: E402
from finctl.classify.classifier import Classification  # noqa: E402
from finctl.config.loader import ConfigError, load_config  # noqa: E402
from finctl.explain import explain_detailed  # noqa: E402
from finctl.explain.client import ExplainUnavailable, LLMConfig, complete  # noqa: E402
from finctl.explain.render import guard, redact_figures  # noqa: E402
from finctl.money import format_rupees  # noqa: E402
from finctl.normalize.mappings import MappingStore, header_fingerprint  # noqa: E402
from finctl.normalize.normalizer import (  # noqa: E402
    NormalizationError,
    UnmappedColumnsError,
    _read_tabular,
)
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

import os  # noqa: E402

# The Next.js dev server, plus whatever the deployed frontend's origin is (set via
# CORS_ALLOW_ORIGINS, comma-separated). Wide open because this is a demo tool with no
# auth and no user data — production auth is explicitly out of scope (see LIMITATIONS.md).
_extra_origins = [o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", *_extra_origins],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_ROOT = ENGINE_DIR / "data"

# One run is cached per batch so the drill-down endpoints do not re-reconcile on every
# click. Keyed by batch name; cleared by regenerating. Deliberately a plain dict: this
# is a single-user demo tool, and a cache library would be infrastructure the problem
# does not have.
_cache: dict[str, PipelineResult] = {}

# The model's sentence for a batch, kept beside the batch it describes.
#
# `explain()` was called on every single GET of /api/verdict. The verdict for a batch
# cannot change between two reads of the same cached pipeline result, so every page
# load, refresh and back-navigation spent an inference call rewriting a sentence that
# was already correct. On a rationed endpoint that is not merely wasteful: a walk
# through the dashboard exhausted the account's tokens-per-minute inside a minute, the
# model started returning 429, and the product quietly served template prose for the
# rest of the demo. The failure is invisible precisely because the fallback is good.
#
# Cleared wherever `_cache` is, so a re-run gets a fresh sentence and a stale one can
# never outlive the figures it describes.
_summary_cache: dict[str, tuple[str, str, str]] = {}


@app.on_event("startup")
def _seed_demo_batch_if_empty() -> None:
    """Hosted deploys start with an empty, ephemeral disk. Without this, the first
    thing a judge sees after opening the live link is an empty batch list — a dead
    demo. Seeds the same `demo` batch `scripts/demo.sh` creates locally, with the
    project's fixed default seed, so it's reproducible and identical either way.
    """
    if DATA_ROOT.is_dir() and any(DATA_ROOT.iterdir()):
        return

    from finctl.generate.generator import Generator
    from finctl.generate.writer import write_batch

    batch = Generator(_config(), seed=20260902, volume=200).generate()
    write_batch(batch, DATA_ROOT / "demo")


def _load(batch: str, *, refresh: bool = False) -> PipelineResult:
    if not refresh and batch in _cache:
        return _cache[batch]

    # Reject anything that could escape DATA_ROOT before touching the filesystem.
    if "/" in batch or "\\" in batch or batch.startswith("."):
        raise HTTPException(400, f"invalid batch name: {batch!r}")

    path = DATA_ROOT / batch
    if not path.is_dir():
        # A sentence, not a Python repr. This used to render the raw list literal of
        # every batch on disk straight into the browser — the one screen in the app
        # that looked unfinished next to everything around it.
        available = sorted(p.name for p in DATA_ROOT.iterdir() if p.is_dir()) if DATA_ROOT.is_dir() else []
        detail = f"There is no run called {batch!r}."
        if available:
            shown = ", ".join(available[:6])
            more = f", and {len(available) - 6} more" if len(available) > 6 else ""
            detail += f" Recent runs: {shown}{more}."
        raise HTTPException(404, detail)

    try:
        # Remembered mappings are needed HERE too, not only on upload. Any cache miss
        # re-runs the pipeline — a fresh process, a rate-card change clearing the cache,
        # a `refresh=true` — and without the store an uploaded batch whose columns a
        # human mapped would fail on every read after the first. Found by changing the
        # rate card and then opening the fee drill-down. See ADR-047.
        result = run(path, _config(), mappings=_mapping_store())
    except Exception as exc:
        # Surface the engine's own message. Its errors are written to be read by a
        # human and name the offending column, row or key — flattening them into
        # "internal error" would discard the most useful part.
        raise HTTPException(422, _client_error(exc)) from exc

    _cache[batch] = result
    _summary_cache.pop(batch, None)      # the prose describes the old run; drop it
    return result


# Absolute server paths, with an un-normalised `../` in them, were being handed to the
# browser inside otherwise good error messages. The engine is right to name the file it
# choked on — a CLI user needs it — so the path is trimmed to a basename here, at the
# boundary where the reader stops being the operator.
_PATH_IN_MESSAGE = re.compile(r"(?:/[^\s/]+)*/([^\s/]+\.(?:csv|json|xlsx|xls))")


def _client_error(exc: Exception) -> str:
    """The engine's message, with server paths reduced to filenames."""
    return _PATH_IN_MESSAGE.sub(r"\1", f"{type(exc).__name__}: {exc}")


def _money(paise: int) -> dict[str, Any]:
    """Money crosses the wire as BOTH paise and a formatted string.

    Paise so the client never does currency arithmetic in JavaScript floats; the string
    so it never has to reimplement Indian digit grouping. ADR-003 does not stop at the
    engine boundary.
    """
    return {"paise": paise, "display": format_rupees(paise)}


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness, and an honest account of what the model layer is actually doing.

    The booleans are here because "is the AI on?" was not answerable from outside this
    process, and for most of this project's life the honest answer was no: the key sat
    in .env and nothing loaded it, so every screen served template prose that reads
    exactly like model prose. A product whose fallback is good enough to hide its own
    misconfiguration needs somewhere to admit which path it is on.

    `llm_credential_present` is about configuration; `llm_last_summary_source` is about
    what actually happened on the most recent verdict. They disagree when it matters —
    a key that is present but rate-limited reads true, template, "rate_limited".

    `llm_disabled` is the third fact and not derivable from the other two: a run started
    with `FINCTL_NO_LLM=1` has a perfectly good key it will never use.
    """
    batches = (
        sorted(p.name for p in DATA_ROOT.iterdir() if p.is_dir())
        if DATA_ROOT.is_dir() else []
    )
    cfg = LLMConfig.from_env()

    # The most recent cached summary, if any batch has been explained this process.
    last = next(iter(reversed(list(_summary_cache.values()))), None)

    return {
        "status": "ok",
        "engine": "finctl",
        "engine_version": _engine_version(),
        "batches": batches,
        "llm_credential_present": bool(cfg.api_key),
        # Configuration and intent, kept apart. `llm_credential_present` was doing both
        # jobs and could not tell "nobody set a key" from "somebody turned it off",
        # which are the two states an operator most needs distinguished at 2am.
        "llm_disabled": cfg.disabled,
        "llm_enabled": cfg.enabled,
        "llm_model": cfg.model if cfg.enabled else None,
        "llm_base_url": cfg.base_url if cfg.enabled else None,
        "llm_last_summary_source": last[1] if last else None,
        "llm_last_summary_reason": last[2] if last else None,
        "summaries_cached": len(_summary_cache),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _engine_version() -> str:
    from finctl import __version__

    return __version__


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
                "generated": (path / ".generated").exists(),
            })
    return {"batches": out}


# ------------------------------------------------------------------ demo generator
#
# The second way into the product: instead of uploading files, dial a scenario and the
# engine writes one. This is not a mock — it is the SAME generator the test suite and
# the CLI use (ADR-004), so a batch dialled in the browser is scored against a real
# ground truth and reconciled by the same pipeline an upload goes through. A merchant
# evaluating the tool can therefore ask "what would this look like if my UPI mix were
# 90%?" and get a real answer rather than a screenshot.
#
# Every option below is READ FROM CONFIG, never hardcoded here. The UI renders whatever
# this returns, so adding an archetype to archetypes.yaml adds it to the dropdown with
# no frontend change — the config layer is the point (rate_card.yaml's own preamble).

# Human copy for the defect types a merchant dials. The engine names them in
# SCREAMING_SNAKE for its own log; a person choosing "how many subscriptions died
# silently" should not have to read DefectType.ALL to do it.
DEFECT_COPY: dict[str, dict[str, str]] = {
    "halted_subscription": {
        "label": "Subscriptions that died silently",
        "hint": "Invoices kept being raised; the card was never charged. The centrepiece — "
                "recoverable money nobody is looking at.",
    },
    "missing_order": {
        "label": "Orders that never reached settlement",
        "hint": "In your ledger, absent from Razorpay. Usually a failed payment.",
    },
    "wrong_fee_rate": {
        "label": "Orders charged the wrong fee",
        "hint": "Razorpay's cut differs from your contracted rate. Tiny per row, material in aggregate.",
    },
    "timing_lag": {
        "label": "Payouts arriving late",
        "hint": "Friday orders landing Tuesday. Benign, and usually the biggest line in the gap.",
    },
    "one_sided_refund": {
        "label": "Refunds you recorded but Razorpay did not",
        "hint": "Side A / Side B divergence on a refund.",
    },
    "unrecorded_refund": {
        "label": "Refunds Razorpay settled but you did not record",
        "hint": "The mirror case: money left the account with no ledger row.",
    },
    "split_settlement": {
        "label": "Orders paid across two settlements",
        "hint": "Legitimate Razorpay behaviour, not an error. Impact is zero by design — "
                "it tests that the engine does NOT report a discrepancy.",
    },
    "early_refund": {
        "label": "Refunds settling before the payment",
        "hint": "The debit lands in an earlier settlement than the credit.",
    },
    "payment_on_hold": {
        "label": "Payments Razorpay is withholding",
        "hint": "Neither late nor missing — the reason is a field in the data.",
    },
    "disputed": {
        "label": "Chargebacks",
        "hint": "Money withheld pending the outcome, with a response deadline attached.",
    },
    "healthy_subscription_decoy": {
        "label": "Decoys — failed payments on healthy subscriptions",
        "hint": "NOT a defect. Same surface shape as a halted subscription, differing in one "
                "field. The engine must decline to claim these — this is what makes "
                "'zero false positives' a claim about the engine.",
    },
}

# A generated batch is capped well below the upload limit. The generator is fast
# (~50k orders/sec) but the pipeline then reconciles what it wrote, and a browser
# waiting on a synchronous 50k-row run is a worse demo than a refusal.
MAX_GENERATED_VOLUME = 5000


@app.get("/api/generate/options")
def generate_options() -> dict[str, Any]:
    """Every knob the demo generator exposes, and what each choice means.

    Read from the config files rather than listed here, so the dropdowns cannot drift
    from what the engine will actually accept.
    """
    import yaml

    from finctl.config.loader import DEFAULTS_DIR
    from finctl.generate.ground_truth import DefectType

    cfg = _config()
    profiles = yaml.safe_load((DEFAULTS_DIR / "defects.yaml").read_text())

    return {
        "archetypes": [
            {
                "name": a.name,
                "description": a.description,
                "stresses": a.stresses,
                "expected_correlation_gain": a.expected_correlation_gain,
                "ticket_min_paise": a.ticket_min_paise,
                "ticket_max_paise": a.ticket_max_paise,
                "default_mix": a.payment_mix,
            }
            for a in sorted(cfg.archetypes.values(), key=lambda a: a.name)
        ],
        "payment_mixes": [
            {"name": m.name, "description": m.description, "mix": m.mix}
            for m in sorted(cfg.payment_mixes.values(), key=lambda m: m.name)
        ],
        "defect_profiles": [
            {
                "name": name,
                "description": spec.get("description", ""),
                # What this preset plants, so switching preset can prefill the
                # per-defect fields rather than leaving them stale.
                "defects": {
                    k: v for k, v in spec.items() if k != "description"
                },
            }
            for name, spec in sorted(profiles.items())
        ],
        # Ordered as the engine plants them, so the UI lists them in a stable order.
        "defect_types": [
            {
                "name": d,
                "label": DEFECT_COPY.get(d, {}).get("label", d.replace("_", " ")),
                "hint": DEFECT_COPY.get(d, {}).get("hint", ""),
                "is_defect": d != "healthy_subscription_decoy",
            }
            for d in DefectType.ALL
        ],
        "defaults": {
            "archetype": "saas_subscription",
            "payment_mix": None,
            "defect_profile": "demo",
            "volume": 200,
            "cycle_days": cfg.tolerances.cycle_days,
            "seed": 20260902,
        },
        "limits": {"max_volume": MAX_GENERATED_VOLUME, "min_volume": 1},
    }


@app.post("/api/generate")
def generate_batch(payload: dict[str, Any]) -> dict[str, Any]:
    """Write a seeded synthetic batch and reconcile it.

    Returns the SAME shape `/api/upload` does, plus the ground truth. That symmetry is
    deliberate: the UI shows one confirmation screen for both paths, because from the
    merchant's point of view "my files are in" and "the scenario is built" are the same
    moment — the next click is `Analyse` either way.
    """
    from finctl.config.loader import ConfigError
    from finctl.generate.generator import Generator
    from finctl.generate.writer import write_batch

    name = _safe_batch_name(str(payload.get("batch") or ""))
    target = DATA_ROOT / name
    if target.exists():
        raise HTTPException(
            409,
            f"batch {name!r} already exists. Staging entries are immutable — "
            "generate under another name.",
        )

    volume = payload.get("volume", 200)
    if not isinstance(volume, int) or isinstance(volume, bool):
        raise HTTPException(400, f"volume must be a whole number, got {volume!r}")
    if not 1 <= volume <= MAX_GENERATED_VOLUME:
        raise HTTPException(
            400,
            f"volume must be between 1 and {MAX_GENERATED_VOLUME}, got {volume}. "
            "Larger batches are a CLI job: `finctl generate --volume 50000`.",
        )

    seed = payload.get("seed", 20260902)
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 2**63:
        raise HTTPException(400, f"seed must be a non-negative whole number, got {seed!r}")

    cycle = payload.get("cycle_days")
    if cycle is not None and (
        not isinstance(cycle, int) or isinstance(cycle, bool) or not 0 <= cycle <= 30
    ):
        raise HTTPException(400, f"cycle_days must be between 0 and 30, got {cycle!r}")

    # Either a named preset or a dialled-in set of counts. The generator validates the
    # inline form to the same standard as a YAML profile and refuses an unknown defect
    # type by name, so nothing here needs to re-check it.
    defects: str | dict[str, Any] = payload.get("defect_profile") or "demo"
    custom = payload.get("defects")
    if custom is not None:
        if not isinstance(custom, dict):
            raise HTTPException(400, "defects must be an object of {type: {count: n}}")
        defects = custom

    started = datetime.now(UTC)
    target.mkdir(parents=True)
    try:
        try:
            batch = Generator(
                _config(),
                seed=seed,
                archetype=str(payload.get("archetype") or "saas_subscription"),
                payment_mix=payload.get("payment_mix") or None,
                volume=volume,
                settlement_cycle_days=cycle,
                defect_profile=defects,
            ).generate()
        except (ConfigError, ValueError) as exc:
            # The generator's refusals name the arithmetic — "demands 51 defects but the
            # batch has only 40 orders" is the fix instruction, so it is surfaced
            # verbatim rather than flattened. A merchant dialling counts WILL hit this.
            raise HTTPException(422, str(exc)) from exc

        write_batch(batch, target)
        (target / ".generated").write_text(started.isoformat())

        try:
            result = run(target, _config(), mappings=_mapping_store())
        except Exception as exc:
            raise HTTPException(422, _client_error(exc)) from exc
    except Exception:
        # Same reasoning as upload: a half-written batch would reconcile a partial
        # scenario on the next request.
        shutil.rmtree(target, ignore_errors=True)
        raise

    _cache[name] = result
    gt = batch.ground_truth
    assert gt is not None

    return {
        "batch": name,
        "generated": True,
        "rows_processed": result.rows_processed,
        "missing_sources": [],
        "note": None,
        "headline": result.verdict.headline(),
        "manifest": result.batch.manifest(),
        "files": {
            "ledger": {"filename": "ledger.csv", "rows": len(batch.ledger)},
            "bank": {"filename": "bank.csv", "rows": len(batch.bank)},
            "recon": {"filename": "settlement_recon.json", "rows": len(batch.recon)},
            "payments": {"filename": "payments.json", "rows": len(batch.payments)},
            "subscriptions": {
                "filename": "subscriptions.json", "rows": len(batch.subscriptions),
            },
        },
        # What was deliberately planted. Shown because a merchant evaluating the tool
        # should be able to check the verdict against the answer key — that is the
        # whole argument for seeded data over a recorded demo.
        "scenario": {
            "archetype": gt.archetype,
            "payment_mix": gt.payment_mix,
            "volume": gt.volume,
            "settlement_cycle_days": gt.settlement_cycle_days,
            "defect_profile": gt.defect_profile,
            "seed": gt.seed,
            "gross": _money(gt.total_gross_paise),
            "expected_fees": _money(gt.total_expected_fee_paise),
            "defect_count": len(gt.real_defects),
            "decoy_count": len(gt.decoys),
            # Where the batch could not hold what was asked for. The generator clamps a
            # count to the volume rather than refusing (each order carries at most one
            # defect), so asking for 50 halted subscriptions in a 10-order batch plants
            # 10. Ground truth records what was actually planted and stays honest, but
            # a merchant who typed 50 and is shown 10 without being told would think
            # the engine missed 40. Say it.
            "adjusted": [
                {
                    "type": defect_type,
                    "label": DEFECT_COPY.get(defect_type, {}).get(
                        "label", defect_type.replace("_", " ")
                    ),
                    "asked": int(spec["count"]),
                    "planted": len(gt.by_type(defect_type)),
                }
                for defect_type, spec in (
                    defects.items() if isinstance(defects, dict) else []
                )
                if isinstance(spec, dict)
                and "count" in spec
                and len(gt.by_type(defect_type)) < int(spec["count"])
            ],
            "planted": [
                {
                    "type": defect_type,
                    "label": DEFECT_COPY.get(defect_type, {}).get(
                        "label", defect_type.replace("_", " ")
                    ),
                    "count": len(gt.by_type(defect_type)),
                    "impact": _money(impact),
                }
                for defect_type, impact in sorted(
                    gt.impact_by_type().items(), key=lambda kv: -kv[1]
                )
            ],
        },
    }


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

# Where confirmed column mappings live. One file beside the data, because a merchant has
# a handful of file shapes and a database to hold five entries would be infrastructure
# the problem does not have. See ADR-045.
MAPPINGS_PATH = DATA_ROOT / "column-mappings.json"


def _mapping_store() -> MappingStore:
    """Read fresh each time: the file is small and this is a single-user demo tool."""
    return MappingStore(MAPPINGS_PATH)


# The merchant's own contracted rates, if they have told us. Beside the data for the
# same reason the mappings file is. See ADR-046.
RATE_CARD_PATH = DATA_ROOT / "merchant-rate-card.json"


def _merchant_rates() -> dict[str, Any] | None:
    """What the merchant says their contract charges, or None if they have not said."""
    if not RATE_CARD_PATH.exists():
        return None
    try:
        return json.loads(RATE_CARD_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        # Same reasoning as the mapping store: a corrupt file costs the merchant their
        # custom rates, which is visible in the verdict, rather than costing them the
        # ability to reconcile at all.
        return None


def _config():
    """The engine config, with the merchant's contracted rates layered on if set."""
    try:
        return load_config(merchant_rate_card=_merchant_rates())
    except ConfigError as exc:
        raise HTTPException(422, f"rate card: {exc}") from exc


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
            result = run(target, _config(), mappings=_mapping_store())
        except UnmappedColumnsError as exc:
            # The one error a merchant can FIX from the browser. Returned as structured
            # data — which columns are unmapped, and every column available to choose
            # from — so the UI renders a picker instead of a paragraph. The engine still
            # refuses to guess; it now hands a human the evidence to decide. ADR-045.
            raise HTTPException(422, detail=exc.as_dict()) from exc
        except NormalizationError as exc:
            # The normalizer's errors name the offending column, row or value and list
            # the spellings it accepts. That message IS the fix instruction, so it is
            # surfaced verbatim rather than flattened into "bad file".
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(422, _client_error(exc)) from exc

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


def _missing_sources(result: Any) -> list[str]:
    """Sources absent from a staged batch, in the order Source declares them."""
    staged = set(result.batch.sources)
    return [s.value for s in Source if s not in staged]


def _missing_note(missing: list[str]) -> str | None:
    if not missing:
        return None
    notes = []
    if "recon" in missing:
        # The severe case, and the one that was silent. With no settlement file every
        # order is unmatched, so the verdict reads "0 of N orders reached Razorpay" and
        # a 100% gap — describing the absent file, not the merchant's money.
        notes.append(
            "No Razorpay settlement file, so there is nothing to reconcile the ledger "
            "against: every order is reported as never having reached Razorpay, and "
            "the whole of your revenue is reported as the gap. That is a description "
            "of the missing file rather than of your money."
        )
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


@app.get("/api/mappings")
def list_mappings() -> dict[str, Any]:
    """Every column mapping a human has confirmed, and for which file shape."""
    return {"mappings": [m.as_dict() for m in _mapping_store().all()]}


@app.post("/api/mappings")
def remember_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    """Record a merchant's choice for one file shape, so it is asked only once.

    Takes the headers of the file they were shown and the canonical -> column map they
    chose. Keyed by a fold-insensitive, order-independent fingerprint of those headers,
    so next month's export with the same columns in a different order is recognised —
    and one with a DIFFERENT column set is not, because that shape was never confirmed.
    """
    source = str(payload.get("source", "")).strip()
    headers = payload.get("headers") or []
    mapping = payload.get("mapping") or {}

    if source not in {s.value for s in Source}:
        raise HTTPException(400, f"unknown source {source!r}")
    if not headers or not isinstance(headers, list):
        raise HTTPException(400, "headers must be a non-empty list")
    if not mapping or not isinstance(mapping, dict):
        raise HTTPException(400, "mapping must be a non-empty object")

    unknown = [c for c in mapping.values() if c not in headers]
    if unknown:
        raise HTTPException(
            400,
            f"mapping names column(s) {unknown} that are not in the supplied headers. "
            "Refusing to remember a mapping that cannot apply to this file.",
        )

    store = _mapping_store()
    remembered = store.remember(source, headers, mapping)
    return {"remembered": remembered.as_dict()}


@app.post("/api/inspect")
async def inspect(
    source: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """What columns does this file have, and do we already know how to read it?

    Lets the UI show a picker BEFORE a merchant commits to an upload, rather than making
    them upload, fail, and try again.
    """
    if source not in {s.value for s in Source}:
        raise HTTPException(400, f"unknown source {source!r}")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in TABULAR_SUFFIXES:
        raise HTTPException(
            400,
            f"{source}: cannot inspect {file.filename!r} — expected "
            f"{' or '.join(sorted(TABULAR_SUFFIXES))}.",
        )

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / f"inspect{suffix}"
        scratch.write_bytes(await file.read())
        try:
            headers, rows = _read_tabular(scratch, source)
        except NormalizationError as exc:
            raise HTTPException(422, str(exc)) from exc

        sample = [
            {h: ("" if r.get(h) is None else str(r.get(h))) for h in headers}
            for r in rows[:3]
        ]

    return {
        "source": source,
        "headers": headers,
        "row_count": len(rows),
        "fingerprint": header_fingerprint(headers),
        "remembered_mapping": _mapping_store().lookup(source, headers),
        # A few real rows, so a merchant choosing between `amount` and `total` can see
        # what is actually in each column rather than guessing from its name.
        "sample_rows": sample,
    }


@app.get("/api/rate-card")
def get_rate_card() -> dict[str, Any]:
    """The rate card the engine is checking fees against, and whose it is."""
    card = _config().rate_card
    overrides = _merchant_rates() or {}
    merchant_methods = set(overrides.get("methods") or {})
    return {
        "name": card.name,
        "is_merchant_supplied": bool(overrides),
        "gst_rate_bps": card.gst_rate_bps,
        "fixed_fee_paise": card.fixed_fee_paise,
        "methods": [
            {
                "method": name,
                "mdr_bps": rate.mdr_bps,
                "percent": round(rate.mdr_bps / 100, 4),
                # Which lines are the merchant's contract and which are our shipped
                # default. A merchant reading "you were overcharged" deserves to know
                # whether the comparison used THEIR number or ours.
                "source": "merchant" if name in merchant_methods else "standard",
                "note": rate.note,
            }
            for name, rate in sorted(card.methods.items())
        ],
    }


@app.put("/api/rate-card")
def put_rate_card(payload: dict[str, Any]) -> dict[str, Any]:
    """Set the merchant's contracted rates.

    Layered over the shipped card, so a merchant states only what they negotiated —
    restating every method would be several chances to get one wrong, silently.

    Validated by building the card before writing anything: a rate of `2` meaning "2%"
    is 0.02% in basis points and would flag every row as a fee discrepancy, so the
    absurd end of that mistake is refused rather than stored.
    """
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(400, "expected a rate card object")

    try:
        load_config(merchant_rate_card=payload)
    except ConfigError as exc:
        raise HTTPException(422, str(exc)) from exc

    RATE_CARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    RATE_CARD_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    # Every cached run was scored against the OLD card. Keeping them would show a
    # merchant fee findings computed from rates they have just replaced.
    _cache.clear()
    return get_rate_card()


@app.delete("/api/rate-card")
def clear_rate_card() -> dict[str, Any]:
    """Revert to the shipped standard card."""
    RATE_CARD_PATH.unlink(missing_ok=True)
    _cache.clear()
    return get_rate_card()


@app.get("/api/timeline/{batch}")
def timeline(batch: str, refresh: bool = False) -> dict[str, Any]:
    """The gap spread across the days the orders were captured on.

    Answers the question the verdict provokes: not how big, but when. A single bad
    Tuesday and a steady leak of the same size are different problems, and the
    composition bar cannot tell them apart.

    `undated` is money the components could not pin to a dated order — an unrecorded
    refund keyed by entity id, a settlement for an order the ledger never mentioned.
    It is returned rather than spread across the days, so the chart never implies a
    day it cannot evidence. `dated + undated == gap` is asserted engine-side.
    """
    result = _load(batch, refresh=refresh)
    t = result.timeline
    peak = t.peak

    return {
        "batch": batch,
        "gap": _money(t.gap_paise),
        "dated": _money(t.dated_paise),
        "undated": _money(t.undated_paise),
        "days": [
            {
                "day": d.day.isoformat(),
                "amount": _money(d.paise),
                "orders": d.order_count,
                "actionable": _money(d.actionable_paise),
                "expected": _money(d.expected_paise),
                "received": _money(d.received_paise),
            }
            for d in t.days
        ],
        "peak": (
            {
                "day": peak.day.isoformat(),
                "amount": _money(peak.paise),
                "orders": peak.order_count,
                "actionable": _money(peak.actionable_paise),
            }
            if peak
            else None
        ),
    }


@app.get("/api/verdict/{batch}")
def verdict(batch: str, refresh: bool = False) -> dict[str, Any]:
    """The four lines and a verdict. The default screen."""
    result = _load(batch, refresh=refresh)
    v = result.verdict
    missing_sources = _missing_sources(result)

    # The one place a language model touches this product. It writes the summary prose
    # and nothing else: every figure below is rendered by `_money` from an integer the
    # model never saw, and `explain` strips any numeral it emits. With no API key — or a
    # slow endpoint, or an empty response — `source` is "template" and the deterministic
    # summary is returned instead, so this endpoint never fails on a network call.
    # ADR-050.
    cached = _summary_cache.get(batch)
    if cached is None:
        cached = explain_detailed(v)
        _summary_cache[batch] = cached
    summary, summary_source, summary_reason = cached

    return {
        "batch": batch,
        "expected": _money(v.expected_paise),
        "received": _money(v.received_paise),
        "gap": _money(v.gap_paise),
        "headline": v.headline(),
        "summary": summary,
        # Returned, not hidden: a product that cannot say whether a model wrote something
        # is not one you can audit.
        "summary_source": summary_source,
        # Why the template was used, when it was: "no_key", "rate_limited", "timeout",
        # "guarded". "model" when none was needed. A screen that says a model wrote the
        # sentence must also be able to say why it didn't.
        "summary_reason": summary_reason,
        "actionable_total": _money(v.actionable_paise),
        "benign_total": _money(v.benign_paise),
        # Money no rule could account for, after correlation. Not the decomposition's
        # residual, which is an integrity check that must be zero — returned beside it
        # as `residual` so the distinction is visible rather than implied.
        "unexplained": _money(v.unexplained_paise),
        "unexplained_count": v.unexplained_count,
        "residual": _money(v.residual_paise),
        # Which files this batch did NOT have, on every read of the verdict rather than
        # only in the upload response. A ledger-only upload produces a confident 100%
        # gap, and the analysis page is where anyone actually reads it.
        "missing_sources": missing_sources,
        "missing_note": _missing_note(missing_sources),
        # Detected late settlements. Gap-neutral — the money arrived, so it is already
        # inside `received` — but 213 late payouts on a 2,500-order run is a
        # working-capital fact the engine knew and never said.
        "late": (
            {
                "count": v.late.count,
                "value": _money(v.late.value_paise),
                "median_days_late": v.late.median_days_late,
                "max_days_late": v.late.max_days_late,
                "cycle_days": v.late.cycle_days,
            }
            if v.late
            else None
        ),
        "lines": [
            {
                "classification": str(line.classification),
                "label": line.label,
                "explanation": line.explanation,
                "count": line.count,
                "amount": _money(line.amount_paise),
                "actionable": line.actionable,
                # A figure ABOUT the line, already inside its amount. The fee
                # overcharge is the only one so far: the portion charged above the
                # rate card, which is the one fee number a merchant can dispute.
                "note": (
                    {
                        "label": line.note.label,
                        "explanation": line.note.explanation,
                        "count": line.note.count,
                        "amount": _money(line.note.amount_paise),
                        "actionable": line.note.actionable,
                    }
                    if line.note
                    else None
                ),
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


@app.get("/api/actions/{batch}")
def actions(batch: str) -> dict[str, Any]:
    """Who to chase, for how much, and why.

    The verdict says "those 6 customers"; this names them. Every field is lifted from a
    finding's proof — nothing here is computed, so it cannot disagree with the verdict
    it accompanies. See ADR-048.
    """
    result = _load(batch)
    groups = result.actions
    # A component can be negative — a refund the merchant recorded that Razorpay paid
    # out anyway means the bank holds MORE than the books expected. That is a real
    # discrepancy to reconcile, but it is not money to chase, and netting it against
    # recoverable money understates the work: on the demo batch the signed sum is
    # ₹54,468.72 against a verdict actionable total of ₹73,456.72 for the same rows.
    # Both figures are sent, named for what they are, so the UI never has to compute
    # (or format) either one. ADR-001.
    chase = [g for g in groups if g.total_paise > 0]
    return {
        "batch": batch,
        "headline": result.verdict.headline(),
        "total": _money(sum(g.total_paise for g in groups)),
        "chase_total": _money(sum(g.total_paise for g in chase)),
        "chase_count": sum(len(g.items) for g in chase),
        "count": sum(len(g.items) for g in groups),
        "groups": [g.as_dict() for g in groups],
    }


@app.get("/api/actions/{batch}/csv")
def actions_csv(batch: str) -> Response:
    """The same list as a file a merchant can open, sort, or hand to someone else.

    The difference between a dashboard and a tool is whether the work leaves the screen.
    """
    body = to_csv(_load(batch).actions)
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{batch}-actions.csv"',
        },
    )


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


# ------------------------------------------------------------------ rules (read-only)
#
# Human copy for the classifier's vocabulary, same spirit as DEFECT_COPY above: the
# engine names these in SCREAMING_SNAKE for its own log, a person reading the "Rules"
# screen should not have to.
CLASSIFICATION_COPY: dict[str, dict[str, str]] = {
    "RECONCILED": {"label": "Reconciled", "hint": "No discrepancy at all."},
    "FEE": {"label": "Razorpay's fee", "hint": "The contracted cut on a settled order."},
    "TAX_ON_FEE": {"label": "GST on the fee", "hint": "Tax on Razorpay's cut."},
    "TIMING": {"label": "Settlement timing", "hint": "Not missing — arriving on a later cycle."},
    "REFUND": {"label": "Refund", "hint": "Money returned to a customer."},
    "ROUNDING": {"label": "Rounding", "hint": "Sub-tolerance arithmetic noise."},
    "DUPLICATE": {"label": "Duplicate order", "hint": "The same order recorded twice."},
    "MISSING": {"label": "Missing settlement", "hint": "No PSP record at all for this order."},
    "ON_HOLD": {"label": "On hold", "hint": "Razorpay is deliberately withholding this payment."},
    "DISPUTED": {"label": "Disputed", "hint": "A customer charged back."},
    "UNEXPLAINED": {"label": "Unexplained", "hint": "The honest residual — no rule fit."},
    "NEEDS_REVIEW": {"label": "Needs review", "hint": "More than one rule fit; a human should look."},
    "PAYMENT_FAILED": {"label": "Payment failed", "hint": "Correlated to a failed payment attempt."},
    "HALTED_SUBSCRIPTION": {
        "label": "Subscription halted",
        "hint": "Invoices kept being raised; the card was never charged again.",
    },
    "UNEXPECTED_SETTLEMENT": {"label": "Unexpected settlement", "hint": "Money in for an order the ledger never mentioned."},
    "UNRECORDED_REFUND": {"label": "Unrecorded refund", "hint": "Money out the merchant never recorded."},
}


@app.get("/api/rules")
def rules() -> dict[str, Any]:
    """A read-only reflection of the engine's config.

    Nothing here is editable from the browser: the engine's matching and classification
    rules are code, reviewed and tested (ADR-001), not a document a UI can rewrite. The
    "Rules" screen exists so a merchant can SEE what the engine currently enforces —
    tolerances, the rate card, the classification vocabulary — not change it in place.
    Rate-card changes still go through `/api/rate-card`, the one setting that is
    genuinely a merchant input rather than an engine policy.
    """
    cfg = _config()
    t = cfg.tolerances
    card = get_rate_card()

    return {
        "cycle_days": t.cycle_days,
        "grace_days": t.grace_days,
        "count_working_days_only": t.count_working_days_only,
        "rounding": _money(t.rounding_paise),
        "material": _money(t.material_paise),
        "actionable_above": _money(t.actionable_above_paise),
        "always_benign": list(t.always_benign),
        "always_actionable": list(t.always_actionable),
        "rate_card": card,
        "classifications": [
            {
                "name": name,
                "label": CLASSIFICATION_COPY.get(name, {}).get("label", name.replace("_", " ").title()),
                "hint": CLASSIFICATION_COPY.get(name, {}).get("hint", ""),
                "policy": (
                    "always_benign" if name in t.always_benign
                    else "always_actionable" if name in t.always_actionable
                    else "threshold"
                ),
            }
            for name in (str(c) for c in Classification)
        ],
    }


# ------------------------------------------------------------------ copilot chat
#
# The one other place a model touches this product, alongside the verdict summary
# (ADR-050). Same rule, extended from one summary to a conversation: the model is given
# resolved facts and writes prose only, never a figure. `guard` — the SAME function the
# verdict summary uses — strips any numeral it emits; a reply that fails the guard is
# replaced by a fixed, honest sentence rather than shown half-written.

CHAT_SYSTEM_PROMPT = """You are Copilot, answering a merchant's questions about ONE \
reconciliation run inside a settlement reconciliation tool.

Rules, all of them absolute:
- NEVER write a number, an amount, a count, or a currency figure. Not in digits, not in \
words. Every figure on screen is rendered by the app itself from an integer you never \
see; anything numeric you write is deleted before display and will leave a hole in your \
sentence. Point the merchant at "the figure above" or "the breakdown on this page" \
instead of restating it.
- Only use the facts you are given below. Do not speculate about causes you were not \
told. If you don't know, say the run doesn't show that rather than guessing.
- Do not restate a line's mechanism in your own words. Reuse the wording you were given, \
or name the line and stop. Compressing an explanation invents claims: "kept generating \
invoices" is not "kept the money", and a merchant reading the second one will open a \
support ticket about a theft that did not happen.
- Plain English, calm and specific. No jargon beyond what's already on screen, no \
greeting, no sign-off, no markdown, no bullet points unless the question needs a short \
list of named items (order ids, customer emails) — those are not numerals.
- Answer in at most four sentences."""


def _chat_facts(v: Any) -> str:
    """The run's shape, in words, with no figures — same discipline as the verdict
    summary's `_facts()` in `finctl/explain/render.py`, reused here rather than
    duplicated in spirit: rank-ordered lines, no amounts."""
    lines = sorted(v.lines, key=lambda line: -abs(line.amount_paise))
    if not lines:
        return "This run has no discrepancies at all."

    direction = (
        "The bank received LESS than the ledger expected (a shortfall)."
        if v.gap_paise > 0
        else "The bank received MORE than the ledger expected."
        if v.gap_paise < 0
        else "The bank received exactly what the ledger expected."
    )
    parts = [
        f"- {redact_figures(line.label)} "
        f"({'needs action' if line.actionable else 'needs no action'}): "
        f"{redact_figures(line.explanation)}"
        for line in lines
    ]
    actionable = [line for line in v.lines if line.actionable]
    focus = (
        f"The item that most deserves attention is: {max(actionable, key=lambda x: x.amount_paise).label}."
        if actionable
        else "Nothing in this run needs action."
    )
    return "\n".join([direction, "", "Lines on this run, largest first:", *parts, "", focus])


CHAT_FALLBACK = (
    "I can't reach the model right now, so I can't answer that freely — but every "
    "figure on this page is already broken down above; the line labels explain what "
    "each amount is for."
)

# One fallback sentence per reason, because they are not the same situation and a
# merchant can act on the difference. "I can't reach the model" was being shown while
# the model was reachable and answering — it had simply rationed us for the minute,
# which clears on its own and is worth waiting out. Telling someone a temporary limit
# is an outage invites them to go and debug a working integration.
CHAT_FALLBACK_BY_REASON = {
    "no_key": (
        "No model is configured for this run, so I can't answer freely — but nothing "
        "on this page depends on one. Every figure above is computed by the engine, and "
        "the line labels explain what each amount is for."
    ),
    "disabled": (
        "This run was started with the model switched off, so I'm answering from the "
        "engine's own templates. That's the whole offline mode: nothing on this page "
        "changes, because no figure here was ever the model's to produce."
    ),
    "rate_limited": (
        "I've used up this minute's allowance on the model, so I'll sit this one out — "
        "it clears within a minute, so ask me again shortly. Nothing else on this page "
        "is affected: every figure above is the engine's, not the model's."
    ),
    "guarded": (
        "I drafted an answer that quoted a figure, and I'm not allowed to put a number "
        "on screen that the engine didn't compute — so I discarded the whole reply "
        "rather than show you a number I made up. The breakdown above has every amount."
    ),
}


def _chat_fallback(reason: str) -> dict[str, Any]:
    """The template answer, and an honest account of why it is the one being given."""
    return {
        "answer": CHAT_FALLBACK_BY_REASON.get(reason, CHAT_FALLBACK),
        "source": "template",
        "reason": reason,
    }


@app.post("/api/chat/{batch}")
def chat(batch: str, payload: dict[str, Any]) -> dict[str, Any]:
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message must not be empty")
    history = payload.get("history") or []
    if not isinstance(history, list):
        raise HTTPException(400, "history must be a list")

    result = _load(batch)
    v = result.verdict
    cfg = LLMConfig.from_env()

    if not cfg.enabled:
        return _chat_fallback(cfg.off_reason)

    convo = "\n".join(
        f"{'Merchant' if m.get('role') == 'user' else 'Copilot'}: {m.get('content', '')}"
        for m in history[-6:]
        if isinstance(m, dict)
    )
    user_prompt = (
        f"Facts about this run:\n{_chat_facts(v)}\n\n"
        + (f"Conversation so far:\n{convo}\n\n" if convo else "")
        + f"Merchant's question: {message}"
    )

    try:
        raw = complete(CHAT_SYSTEM_PROMPT, user_prompt, cfg)
    except ExplainUnavailable as exc:
        return _chat_fallback(getattr(exc, "reason", "unavailable"))

    safe = guard(raw)
    if safe is None:
        return _chat_fallback("guarded")
    return {"answer": safe, "source": "model", "reason": "model"}
