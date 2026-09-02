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
from pathlib import Path
from typing import Any

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
        if item.get("type") != "payment" or not item.get("settled"):
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
