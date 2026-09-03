"""Shape probe — verify our synthetic data resembles reality.

ADR-006: real API = verification, not foundation.

This module is NOT part of the pipeline. Nothing in the engine imports it. Its only
output is a set of JSON fixtures under tests/fixtures/razorpay/ plus a field inventory,
which the generator is then held to by test.

Two modes:

    finctl probe            inspect the committed fixtures, print the field inventory
                            and the fee/tax convention analysis. No network, no keys.

    finctl probe --live     call Razorpay test mode and OVERWRITE the fixtures with
                            real captures. Requires RAZORPAY_KEY_ID / _KEY_SECRET.
                            This is the Day-2 task.

The offline mode is the important one: it means the schema question can be interrogated
at any time, by anyone, with no credentials.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finctl.schema import ReconType, is_recon_type

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "razorpay"

# Razorpay test-mode endpoints. Used only by --live.
ENDPOINTS = {
    "settlement_recon": "/v1/settlements/recon/combined",
    "payment_failed": "/v1/payments",
    "subscription_halted": "/v1/subscriptions",
}
BASE_URL = "https://api.razorpay.com"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a committed fixture by name (without .json)."""
    path = FIXTURE_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"No fixture {path}. Run `finctl probe --live` or see PROVENANCE.md.")
    return json.loads(path.read_text())


def field_inventory(fixture: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a field -> {types, nullable, examples} map across all items in a fixture.

    This is what the generator is validated against: not the values, the *shape*.
    """
    items = fixture.get("items", [])
    inventory: dict[str, dict[str, Any]] = {}
    for item in items:
        for key, value in item.items():
            entry = inventory.setdefault(key, {"types": set(), "nullable": False, "examples": []})
            if value is None:
                entry["nullable"] = True
            else:
                entry["types"].add(type(value).__name__)
                if len(entry["examples"]) < 2 and value not in entry["examples"]:
                    entry["examples"].append(value)
    for entry in inventory.values():
        entry["types"] = sorted(entry["types"])
    return inventory


def analyse_fee_convention(recon: dict[str, Any]) -> dict[str, Any]:
    """Decide, from the data, whether `fee` is GST-inclusive or MDR-only.

    ADR-007. For every settled payment row exactly one identity should hold:

        credit == amount - fee          -> fee is GST-inclusive, tax is informational
        credit == amount - fee - tax    -> fee is MDR-only, tax is additive

    We do not assume. We test both across the batch and report. A batch where neither
    holds, or where both conventions appear, is a hard error at ingest time - because a
    silent GST-sized systematic error is exactly the failure this engine exists to catch.
    """
    inclusive: list[str] = []
    additive: list[str] = []
    neither: list[str] = []
    ambiguous: list[str] = []

    for item in recon.get("items", []):
        if not is_recon_type(item, ReconType.PAYMENT) or not item.get("settled"):
            continue
        amount, fee, tax = item.get("amount"), item.get("fee"), item.get("tax")
        credit = item.get("credit")
        if None in (amount, fee, tax, credit):
            continue

        fits_inclusive = credit == amount - fee
        fits_additive = credit == amount - fee - tax
        eid = item.get("entity_id", "?")

        # tax == 0 makes both identities true; that row proves nothing either way.
        if fits_inclusive and fits_additive:
            ambiguous.append(eid)
        elif fits_inclusive:
            inclusive.append(eid)
        elif fits_additive:
            additive.append(eid)
        else:
            neither.append(eid)

    if neither:
        verdict = "ERROR: rows where neither identity holds"
    elif inclusive and additive:
        verdict = "ERROR: batch is mixed - both conventions present"
    elif inclusive:
        verdict = "fee is GST-INCLUSIVE (credit = amount - fee)"
    elif additive:
        verdict = "fee is MDR-ONLY (credit = amount - fee - tax)"
    elif ambiguous:
        verdict = "UNDETERMINED: every row has tax == 0, so both identities hold"
    else:
        verdict = "UNDETERMINED: no settled payment rows to test"

    return {
        "verdict": verdict,
        "gst_inclusive_rows": inclusive,
        "mdr_only_rows": additive,
        "ambiguous_rows": ambiguous,
        "inconsistent_rows": neither,
    }


def fetch_live(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call Razorpay test mode. Only reached via --live."""
    import httpx  # optional dependency, installed with the `live` extra

    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise RuntimeError(
            "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set. Copy .env.example to .env."
        )
    if not key_id.startswith("rzp_test_"):
        raise RuntimeError(
            f"Refusing to probe with a non-test key ({key_id[:12]}...). "
            "This tool writes responses to disk; live-mode data must never land in fixtures."
        )

    resp = httpx.get(
        f"{BASE_URL}{endpoint}",
        auth=(key_id, key_secret),
        params=params or {},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------------------------
# Live capture (--live). Everything below this line touches the network.
# --------------------------------------------------------------------------------------

# Fields that may carry real customer identity. Redacted unconditionally before any
# response is written to disk - a test account is *probably* clean, but "probably" is
# not a basis for committing a file to a public repo.
PII_REDACTIONS: dict[str, Any] = {
    "email": "redacted@example.com",
    "contact": "+910000000000",
    "vpa": "redacted@upi",
    "customer_email": "redacted@example.com",
    "customer_contact": "+910000000000",
    "customer_name": "Redacted Customer",
    "name": "Redacted Customer",
    "card_holder_name": "Redacted Customer",
}


def redact_pii(value: Any) -> Any:
    """Recursively replace PII field values with obvious placeholders.

    Null stays null: nullability is part of the shape we are here to capture, and
    inventing a value where Razorpay returned none would corrupt the very contract this
    fixture exists to establish.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, val in value.items():
            if key in PII_REDACTIONS and val is not None and not isinstance(val, (dict, list)):
                out[key] = PII_REDACTIONS[key]
            else:
                out[key] = redact_pii(val)
        return out
    if isinstance(value, list):
        return [redact_pii(v) for v in value]
    return value


def _provenance_block(
    *,
    endpoint: str,
    params: dict[str, Any],
    note: str,
    why_this_matters: str,
    empty: bool,
) -> dict[str, Any]:
    """Build the _provenance block for a live capture.

    Same key structure as the documented-shape fixtures it replaces, so that the file
    can be read the same way regardless of where it came from.
    """
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    source = f"GET {BASE_URL}{endpoint}" + (f"?{query}" if query else "")
    return {
        "status": "live-capture",
        "source": source,
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "live_capture": True,
        "empty_collection": empty,
        "pii_redacted": True,
        "pii_note": (
            "email / contact / vpa and other identity fields are replaced with fixed "
            f"placeholders ({sorted(PII_REDACTIONS)}) before writing. Redaction is applied "
            "unconditionally, whether or not the response contained any."
        ),
        "note": note,
        "why_this_matters": why_this_matters,
    }


def capture_live() -> dict[str, Any]:
    """Call the three endpoints and return {name: {"payload"|"error", ...}}.

    Errors are captured, not raised: one endpoint being unavailable (a product not
    enabled on the account, say) must not cost us the captures that did succeed. The
    exact status and body are carried through to the report.
    """
    import httpx

    now = datetime.now(UTC)
    plans: dict[str, dict[str, Any]] = {
        # year+month are REQUIRED by this endpoint; verified against the live API - a
        # bare call returns 400 "The year field is required."
        "settlement_recon": {
            "endpoint": ENDPOINTS["settlement_recon"],
            "params": {"year": now.year, "month": now.month},
        },
        "payment_failed": {"endpoint": ENDPOINTS["payment_failed"], "params": {"count": 100}},
        "subscription_halted": {
            "endpoint": ENDPOINTS["subscription_halted"],
            "params": {"count": 100},
        },
    }

    results: dict[str, dict[str, Any]] = {}
    for name, plan in plans.items():
        try:
            payload = fetch_live(plan["endpoint"], plan["params"])
        except httpx.HTTPStatusError as exc:
            results[name] = {
                "endpoint": plan["endpoint"],
                "params": plan["params"],
                "error": f"HTTP {exc.response.status_code}",
                "body": exc.response.text[:2000],
            }
            continue
        except Exception as exc:
            # Deliberately broad: the report wants the failure recorded, not a traceback
            # that aborts the remaining captures.
            results[name] = {
                "endpoint": plan["endpoint"],
                "params": plan["params"],
                "error": type(exc).__name__,
                "body": str(exc)[:2000],
            }
            continue

        if name == "payment_failed":
            # The fixture is about failed payments specifically; keep the whole
            # collection only if nothing failed, so the shape is never lost entirely.
            failed = [i for i in payload.get("items", []) if i.get("status") == "failed"]
            if failed:
                payload = {**payload, "items": failed, "count": len(failed)}

        results[name] = {
            "endpoint": plan["endpoint"],
            "params": plan["params"],
            "payload": redact_pii(payload),
        }
    return results


def write_capture(name: str, result: dict[str, Any], *, preserve_documented: bool) -> Path:
    """Write one capture to disk and return the path written.

    `preserve_documented` is the empty-account guard. An empty live collection carries no
    shape at all, so overwriting a documented-shape fixture with one would destroy the
    contract the test suite relies on and replace it with nothing. In that case the
    capture lands beside the fixture as `<name>_live.json` and the fixture is untouched.
    """
    # Redact at the WRITE boundary, not (only) at the fetch boundary. This function is
    # the last thing standing between a live response and a file in a public repo, so the
    # guarantee belongs here rather than depending on every caller having remembered.
    # redact_pii is idempotent, so applying it twice is free.
    payload = redact_pii(result["payload"])
    empty = not payload.get("items")
    target = FIXTURE_DIR / (f"{name}_live.json" if (empty and preserve_documented) else f"{name}.json")

    notes = {
        "settlement_recon": (
            "Live test-mode capture of the settlement recon endpoint.",
            "ADR-007 lives or dies here: only settled payment rows with NON-ZERO tax can "
            "distinguish a GST-inclusive fee from an MDR-only one. Rows with tax == 0 "
            "satisfy both identities and prove nothing.",
        ),
        "payment_failed": (
            "Live test-mode capture of the payments collection, filtered to status=failed "
            "when any failed payments exist.",
            "error_reason is the correlation input. It is the free decline taxonomy that "
            "lets an unexplained settlement gap be attributed to a specific cause without "
            "any inference.",
        ),
        "subscription_halted": (
            "Live test-mode capture of the subscriptions collection.",
            "The demo centrepiece. In halted state Razorpay CONTINUES generating invoices "
            "but does NOT attempt charges - money silently stops arriving.",
        ),
    }
    note, why = notes[name]
    if empty:
        note += (
            " The account returned an EMPTY collection - it holds no data of this kind, so "
            "this file records reachability and the envelope shape only, not the item shape."
        )

    fixture = {
        "_provenance": _provenance_block(
            endpoint=result["endpoint"],
            params=result["params"],
            note=note,
            why_this_matters=why,
            empty=empty,
        ),
        **{k: v for k, v in payload.items() if k != "_provenance"},
    }
    target.write_text(json.dumps(fixture, indent=2) + "\n")
    return target


def diff_shapes(documented: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """Compare two field inventories. Every difference is a probe finding.

    Docs and reality diverging is exactly what this probe exists to catch, so the
    comparison is reported rather than asserted away.
    """
    doc_inv, live_inv = field_inventory(documented), field_inventory(live)
    only_documented = sorted(set(doc_inv) - set(live_inv))
    only_live = sorted(set(live_inv) - set(doc_inv))
    changed: list[dict[str, Any]] = []
    for field in sorted(set(doc_inv) & set(live_inv)):
        d, live_field = doc_inv[field], live_inv[field]
        if d["types"] != live_field["types"] or d["nullable"] != live_field["nullable"]:
            changed.append(
                {
                    "field": field,
                    "documented": {"types": d["types"], "nullable": d["nullable"]},
                    "live": {"types": live_field["types"], "nullable": live_field["nullable"]},
                }
            )
    return {"only_documented": only_documented, "only_live": only_live, "changed": changed}
