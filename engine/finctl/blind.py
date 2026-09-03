"""Blind testing: generate a batch whose ground truth the engine cannot see.

WHY THIS EXISTS. Every accuracy number this project reports so far was measured against
data the engine was designed alongside. That is honest as far as it goes — we control
ground truth, so the metrics are measured rather than estimated — but it cannot answer
the harder question: does the engine work on a batch nobody tuned it for?

A blind test answers that. Someone else picks the seed and the defect mix, the ground
truth is written somewhere the engine's operator does not look, the engine reports what
it found, and only then are the two compared.

Two mechanics make it real rather than ceremonial:

  1. `finctl blind new` prints NOTHING about what it planted. The usual `generate`
     command prints a defect table, which would spoil the answer immediately.
  2. The ground truth is written to a separate directory, by default OUTSIDE the batch,
     so it cannot be read by accident while debugging.

The engine then runs with no ground truth present, which is also exactly how it behaves
on real merchant data — so this doubles as a test of that path.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finctl.config.loader import Config
from finctl.generate.generator import Generator
from finctl.generate.writer import write_batch

# Axes a blind run can vary. Kept to values the engine is expected to handle, because
# the question is "does it work on an unseen batch", not "does it survive nonsense" —
# adversarial input has its own tests.
ARCHETYPES = ("saas_subscription", "d2c_ecommerce")
MIXES = ("upi_heavy", "card_heavy", "even")
CYCLES = (1, 2)
PROFILES = ("demo", "scale", "clean")


@dataclass
class BlindSpec:
    """What was generated. Written to the answer key, never to the batch."""

    seed: int
    archetype: str
    payment_mix: str
    volume: int
    cycle_days: int
    defect_profile: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "archetype": self.archetype,
            "payment_mix": self.payment_mix,
            "volume": self.volume,
            "cycle_days": self.cycle_days,
            "defect_profile": self.defect_profile,
        }


def random_spec(rng: random.Random) -> BlindSpec:
    """Pick a configuration at random.

    Volume is drawn from a range rather than a fixed set, so the row count itself is not
    a hint about which preset was used.
    """
    profile = rng.choice(PROFILES)
    # The `demo` profile plants a fixed count of defects and needs enough orders to
    # hold them; `scale` and `clean` are rate-based and work at any size.
    low = 150 if profile == "demo" else 60
    return BlindSpec(
        seed=rng.randrange(1, 2**31),
        archetype=rng.choice(ARCHETYPES),
        payment_mix=rng.choice(MIXES),
        volume=rng.randrange(low, 900),
        cycle_days=rng.choice(CYCLES),
        defect_profile=profile,
    )


def create(
    config: Config,
    batch_dir: Path,
    answer_dir: Path,
    spec: BlindSpec,
) -> dict[str, Any]:
    """Generate a batch, and write its ground truth somewhere separate.

    Returns a receipt containing content hashes of the batch files. The receipt proves,
    when the answer is revealed, that the data was not altered between generation and
    scoring — without it, "we ran it blind" is a claim rather than a fact.
    """
    batch = Generator(
        config,
        seed=spec.seed,
        archetype=spec.archetype,
        payment_mix=spec.payment_mix,
        volume=spec.volume,
        settlement_cycle_days=spec.cycle_days,
        defect_profile=spec.defect_profile,
    ).generate()

    paths = write_batch(batch, batch_dir)

    # Move the ground truth out of the batch directory entirely. Leaving it in place and
    # relying on nobody opening it would be an honour system, not a control.
    answer_dir.mkdir(parents=True, exist_ok=True)
    ground_truth = (batch_dir / "ground_truth.json").read_text()
    (answer_dir / "ground_truth.json").write_text(ground_truth)
    (batch_dir / "ground_truth.json").unlink()

    receipt = {
        "batch_dir": str(batch_dir),
        "files": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            for name, path in sorted(paths.items())
            if name != "ground_truth" and path.exists()
        },
    }
    (answer_dir / "spec.json").write_text(
        json.dumps({**spec.as_dict(), "receipt": receipt}, indent=2)
    )
    (batch_dir / "blind_receipt.json").write_text(json.dumps(receipt, indent=2))

    return receipt


def changed_files(batch_dir: Path, receipt: dict[str, Any]) -> set[str]:
    """Which batch files differ from the receipt taken at generation time."""
    return {
        problem.split(" ")[0]
        for problem in verify_receipt(batch_dir, receipt)
    }


def verify_receipt(batch_dir: Path, receipt: dict[str, Any]) -> list[str]:
    """Check the batch files still match the hashes taken at generation time.

    Returns a list of complaints; empty means the data is untouched.
    """
    problems = []
    name_to_file = {
        "ledger": "ledger.csv",
        "bank": "bank.csv",
        "recon": "settlement_recon.json",
        "payments": "payments.json",
        "subscriptions": "subscriptions.json",
    }
    for name, expected in receipt.get("files", {}).items():
        filename = name_to_file.get(name)
        if not filename:
            continue
        path = batch_dir / filename
        if not path.exists():
            problems.append(f"{filename} is missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        if actual != expected:
            problems.append(f"{filename} changed since generation ({expected} -> {actual})")
    return problems
