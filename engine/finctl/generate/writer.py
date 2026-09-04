"""Write a generated batch to disk.

Ledger and bank go out as CSV because that is what a merchant actually uploads —
and it forces the normalize stage to be exercised against real CSV text, including
its type-erasure, rather than against convenient in-memory dicts.

Recon, payments and subscriptions go out as JSON in Razorpay's collection envelope
(`{"entity": "collection", "count": n, "items": [...]}`), so the same reader works on
generated data and on a live API response. That is what makes the Day-2 swap a source
change rather than a schema change (ADR-008).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from finctl.generate.generator import GeneratedBatch


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Write rows as CSV.

    An empty batch still writes a header row: 'nothing to reconcile' is a valid answer
    and must survive to the verdict stage as an empty file with a schema, not as a
    missing file (BEHAVIOR.md, stage `normalize`).
    """
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_collection(path: Path, items: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps({"entity": "collection", "count": len(items), "items": items}, indent=2)
    )


def write_batch(batch: GeneratedBatch, out_dir: Path) -> dict[str, Path]:
    """Write every artefact of a batch. Returns a map of name -> path written."""
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "ledger": out_dir / "ledger.csv",
        "bank": out_dir / "bank.csv",
        "recon": out_dir / "settlement_recon.json",
        "payments": out_dir / "payments.json",
        "subscriptions": out_dir / "subscriptions.json",
        "ground_truth": out_dir / "ground_truth.json",
    }

    # Ledger amounts are written in RUPEES with a decimal, because that is what a
    # merchant's export contains. The engine converts at the normalize boundary, which
    # is the only place rupee strings may be parsed (ADR-003).
    _write_csv(
        paths["ledger"],
        [
            {
                "order_id": r["order_id"],
                "amount": f"{r['amount'] / 100:.2f}",
                "timestamp": r["timestamp"],
                "customer_id": r["customer_id"],
                # A real merchant's ledger names the buyer, not just an opaque id — the
                # action list's whole instruction is "email these customers", and until
                # ADR-052 it handed over a column of `cust_…` and no address. Written
                # here because this writer, not the generator, decides the on-disk shape.
                "email": r.get("email", ""),
                "contact": r.get("contact", ""),
                "payment_method": r["payment_method"],
            }
            for r in batch.ledger
        ],
        [
            "order_id", "amount", "timestamp", "customer_id",
            "email", "contact", "payment_method",
        ],
    )

    _write_csv(
        paths["bank"],
        [
            {
                "utr": r["utr"],
                "credit_amount": f"{r['credit_amount'] / 100:.2f}",
                "value_date": r["value_date"],
            }
            for r in batch.bank
        ],
        ["utr", "credit_amount", "value_date"],
    )

    _write_collection(paths["recon"], batch.recon)
    _write_collection(paths["payments"], batch.payments)
    _write_collection(paths["subscriptions"], batch.subscriptions)

    if batch.ground_truth is None:
        raise ValueError("batch has no ground truth; refusing to write an unscoreable batch")
    batch.ground_truth.write(paths["ground_truth"])

    return paths
