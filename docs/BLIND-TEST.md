# How to run a blind test

**Purpose.** Every accuracy number this project reports was measured against data the
engine was designed alongside. That is honest as far as it goes — we control ground
truth, so the metrics are measured rather than estimated — but it cannot answer the
harder question: *does the engine work on a batch nobody tuned it for?*

A blind test answers that. **You** pick the batch. The engine never sees the answers
until after it has committed to a result.

---

## What you need to know first

Nothing. Three commands, in order. You do not need to choose settings, understand the
defect types, or edit any files.

Open a terminal in the project and run everything from the `engine` directory:

```bash
cd ~/Documents/projects/razorpay-buildathon/project-1/engine
```

---

## Step 1 — Create the batch  *(you run this)*

```bash
uv run finctl blind new
```

This picks a **random** configuration — archetype, payment mix, volume, settlement
cycle, defect profile, and seed — generates the data, and writes the answer key to
`~/finctl-answers/`, outside the project.

It prints nothing about what it planted. That is deliberate: printing it would spoil the
test before it started.

**What you should do now:** nothing except *not* opening `~/finctl-answers/`. There is
no need to look at it, and looking is the only way to accidentally leak it.

> Want to choose the configuration yourself rather than let it randomise? See
> "Driving it manually" at the bottom.

---

## Step 2 — Run the engine  *(you run this, and share the output)*

```bash
uv run finctl blind run
```

The engine reconciles the batch with no ground truth present — which is also exactly how
it behaves on real merchant data, so this doubles as a test of that path.

It prints the verdict and writes `data/blind/findings.json`, which is the engine's
committed answer: one claim per order.

**Paste the printed output into the chat.** That is the engine's answer, on record,
before anyone has seen the key.

---

## Step 3 — Reveal and score  *(you run this, and share the output)*

```bash
uv run finctl blind score
```

This opens the answer key for the first time and scores the run:

- **Integrity** — confirms the batch files are byte-identical to what was generated.
  Without this, "we ran it blind" is a claim rather than a fact.
- **What was actually generated** — the configuration, revealed.
- **Score** — caught / missed / below tolerance per defect type, plus false positives.

`PASSED` requires **zero missed defects and zero false positives.**

---

## Reading the score

| Column | Meaning |
|---|---|
| **caught** | Planted, and the engine found it. |
| **missed** | Planted, the engine should have found it, and did not. **A real failure.** |
| **below tol.** | Planted, not flagged, *because config says it is not a defect* — e.g. a 1-day settlement lag inside `grace_days: 1`. Not a failure. See ADR-017. |
| **false positives** | The engine flagged something that was never planted. **Worse than a miss** — a miss is a coverage gap, a false positive is the engine telling a merchant something untrue. |

---

## Making it harder

The default randomises within the ranges the engine is expected to handle. To push
further:

**Run several.** One pass proves little; ten passes across different archetypes and
mixes proves considerably more.

```bash
for i in 1 2 3 4 5; do
  uv run finctl blind new  --out data/blind-$i --answers ~/finctl-answers/$i
  uv run finctl blind run  --data data/blind-$i --out data/blind-$i/findings.json
done
```

Then score each with `uv run finctl blind score --data data/blind-$i --answers ~/finctl-answers/$i`.

**Edit the data by hand.** After step 1, open `data/blind/ledger.csv` and change
something — delete a row, alter an amount, rename a column, duplicate a line. The
integrity check in step 3 will report the file as changed, which is correct and expected;
the interesting question is whether the engine still behaves sensibly. This tests the
engine against a defect *no generator invented*, which is the strongest version of this
exercise.

---

## Driving it manually

To choose the configuration yourself instead of letting it randomise, generate normally
and move the answer key aside:

```bash
uv run finctl generate --volume 380 --archetype d2c_ecommerce \
    --mix card_heavy --cycle 1 --defects scale --seed 8817 --out data/blind
mkdir -p ~/finctl-answers && mv data/blind/ground_truth.json ~/finctl-answers/
uv run finctl blind run
```

Note that `generate` prints a defect summary, so if you drive it this way, **you** will
see roughly what was planted. That is fine — the engine still does not.

---

## Why the receipt exists

`blind new` records a SHA-256 of every generated file, storing one copy with the answers
and one alongside the batch. `blind score` compares them.

This is not about distrust; it is about making the claim checkable. A blind test whose
data could have been adjusted between generation and scoring proves nothing, and "we
didn't change it" is not evidence.
