"""A reproducible fingerprint over what a run CLAIMS.

The project asserts determinism in prose in several places. This turns that into a line
a reader can check in one command: run the same command on your machine, compare sixteen
characters. If they match, you reproduced the run exactly; if they do not, something the
engine claims is different here, and that is worth knowing before trusting the table.

WHAT IS DELIBERATELY EXCLUDED. Wall-clock timing. `seconds` and `rows_per_second` are
measurements of the machine that ran the matrix, not statements about the engine, and a
fingerprint covering them could never reproduce anywhere — it would be a number that
looks like a proof and functions as a liability, failing on a slower laptop and inviting
the reader to conclude the engine is non-deterministic when only the CPU was.

So the fingerprint covers the claims: money in paise, defect counts, recall, decoys
resisted, and whether the balance identity held. Those are exactly the figures the
metrics table reports, and every one of them is an integer or a ratio of integers.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Measurements of the host, not of the engine. See the module docstring.
TIMING_FIELDS = frozenset({"seconds", "rows_per_second", "timestamp", "generated_at"})

# Short enough to read aloud and compare by eye, long enough that a collision is not a
# thing that happens: sixteen hex characters is sixty-four bits.
LENGTH = 16


def _claims_only(value: Any) -> Any:
    """The payload with every host-dependent field removed, at any depth."""
    if isinstance(value, dict):
        return {k: _claims_only(v) for k, v in value.items() if k not in TIMING_FIELDS}
    if isinstance(value, list | tuple):
        return [_claims_only(v) for v in value]
    return value


def fingerprint(payload: Any) -> str:
    """A short, stable digest of `payload`'s claims.

    Canonical JSON — sorted keys, no incidental whitespace — so that two structures
    carrying the same claims hash the same regardless of the order they were built in.
    """
    blob = json.dumps(
        _claims_only(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:LENGTH]
