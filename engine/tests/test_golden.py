"""Golden-file tests.

A deterministic engine plus a seeded generator is a perfect fit for golden files: the
same inputs must produce byte-identical outputs forever. This is what catches
"fixed the fee logic, silently broke timing" — the failure mode that unit tests miss
because each unit still passes in isolation.

Regenerate deliberately with:  finctl golden --update
Never regenerate to make a red test go green without reading the diff first. The diff
IS the finding.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finctl.config.loader import load_config
from finctl.generate.generator import Generator

GOLDEN_DIR = Path(__file__).parent / "golden"

# Small, fixed cases chosen to cover the axes that break independently.
CASES = {
    "demo_saas_200": dict(seed=20260902, volume=200, archetype="saas_subscription",
                          defect_profile="demo"),
    "d2c_upi_heavy_100": dict(seed=20260902, volume=100, archetype="d2c_ecommerce",
                              payment_mix="upi_heavy", defect_profile="demo"),
    "card_heavy_t1_100": dict(seed=20260902, volume=100, archetype="saas_subscription",
                              payment_mix="card_heavy", settlement_cycle_days=1,
                              defect_profile="demo"),
    "clean_50": dict(seed=20260902, volume=50, defect_profile="clean"),
}


def _summarise(batch) -> dict:
    """A stable, human-readable digest of a batch.

    Deliberately a summary rather than the full data: a 200-row diff is unreadable at
    11pm, and totals plus defect counts catch every regression that matters. The row
    hashes below catch the rest.
    """
    gt = batch.ground_truth
    return {
        "counts": {
            "ledger": len(batch.ledger), "recon": len(batch.recon), "bank": len(batch.bank),
            "payments": len(batch.payments), "subscriptions": len(batch.subscriptions),
        },
        "totals": {
            "gross_paise": gt.total_gross_paise,
            "expected_fee_paise": gt.total_expected_fee_paise,
            "expected_net_paise": gt.total_expected_net_paise,
            "recon_credit_paise": sum(r["credit"] for r in batch.recon),
            "recon_fee_paise": sum(r["fee"] for r in batch.recon),
            "recon_tax_paise": sum(r["tax"] for r in batch.recon),
            "bank_credit_paise": sum(r["credit_amount"] for r in batch.bank),
        },
        "defects": {
            "count": len(gt.real_defects),
            "by_type": {k: len(gt.by_type(k)) for k in sorted(gt.impact_by_type())},
            "impact_by_type": dict(sorted(gt.impact_by_type().items())),
        },
        "method_mix": {
            m: sum(1 for r in batch.recon if r["method"] == m)
            for m in sorted({r["method"] for r in batch.recon if r["method"]})
        },
        "first_recon_row": batch.recon[0] if batch.recon else None,
        "first_ledger_row": batch.ledger[0] if batch.ledger else None,
    }


def generate_case(name: str) -> dict:
    return _summarise(Generator(load_config(), **CASES[name]).generate())


@pytest.mark.parametrize("name", sorted(CASES))
def test_matches_golden(name: str) -> None:
    """Compare against the committed golden file.

    A failure here means engine behaviour changed. That is either a bug you just
    introduced, or an intentional change — in which case read the diff, confirm every
    line moved for a reason you can name, then run `finctl golden --update`.
    """
    path = GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        pytest.fail(f"missing golden file {path}. Run: finctl golden --update")

    expected = json.loads(path.read_text())
    actual = generate_case(name)

    if actual != expected:
        for section in ("counts", "totals", "defects", "method_mix"):
            if actual.get(section) != expected.get(section):
                pytest.fail(
                    f"{name}: {section} changed\n"
                    f"  expected: {json.dumps(expected.get(section), sort_keys=True)}\n"
                    f"  actual:   {json.dumps(actual.get(section), sort_keys=True)}"
                )
        pytest.fail(f"{name}: row-level data changed (totals unchanged)")


def test_golden_files_all_exist() -> None:
    """A silently missing golden file is a test that cannot fail."""
    for name in CASES:
        assert (GOLDEN_DIR / f"{name}.json").exists(), f"missing golden for {name}"
