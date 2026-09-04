# Metrics

Measured results. Every number here was produced by `uv run finctl matrix` and read from
`docs/matrix-results.json` — none is transcribed by hand, and re-running the command
regenerates all of it.

**Run on 2026-09-04.** 26 runs across volume × archetype × payment mix × settlement
cycle, plus two edge profiles. Cycles span T+1 to T+7 — the slow rows were added in
ADR-051, after a scorer bug survived 22 green runs precisely because the matrix only
sampled T+1 and T+2, where the configured and observed cycles agree.

---

## Read this before the numbers

**100% recall and 100% correlation gain are properties of our synthetic data, not
general claims.** Two caveats do most of the work here, and both are load-bearing:

1. **We control ground truth, so we know exactly what is broken.** That is what makes
   the accuracy honest rather than estimated — and it also means the engine is being
   scored against defects it was designed alongside. A real merchant's data contains
   failure modes we have not imagined.

2. **Every gap the generator plants has a correlatable payment record**, because that is
   how the generator creates gaps. Real data contains gaps with no payment record at all
   — bank errors, month-boundary timing, data-entry mistakes — and those correctly remain
   UNEXPLAINED. The refusal tests demonstrate the engine does not over-claim on such
   rows, but the 100% gain figure should be read as *"correlation resolves what it can
   see"*, not *"correlation resolves everything"*.

**What would settle it.** One real merchant batch, with the unexplained residual published
whatever it comes to. That has not been done — no live account was available for this
build — and it is the first item in `LIMITATIONS.md`'s future scope. The nearest thing
achieved is running the engine's central identity over Razorpay's own published sample
export, where it holds on every payment row and found two parsing bugs on the way
(ADR-056). Ten sample rows are not a merchant's month, and nothing below should be read as
if they were.

**Baseline for comparison.** Terra Insight publishes the yardstick: manual VLOOKUP
reconciliation achieves roughly a **51% match rate**; structured tooling reaches **88%+**.
Our match rate is not directly comparable to either, because ours is an **exact-identifier
rate** with no fuzzy matching (ADR-015) — a stricter measure that trades headline
percentage for the guarantee that no match is a guess.

**The false-positive column now means something.** Until 2026-09-03 it was measured on
batches where *every* gap had a real cause to find, so "0 false positives" was partly a
statement about the data. The `demo` and `scale` profiles now plant **decoys**: failed
payments against *healthy* subscriptions, which have the same surface shape as a halted
one (failed payment, `subscription_id`, a gap) and differ in one field — `status=active`,
`auth_attempts=0`. The engine must report `PAYMENT_FAILED` and must **not** claim
`HALTED_SUBSCRIPTION`.

**Result: 2,254 decoys planted across the 26 runs, 0 claimed. False-attribution rate
0.0000.** That is the number to push on, because a false attribution is worse than a
miss: a miss is a gap in coverage, a false attribution is the engine telling a merchant
to chase a customer whose subscription is working fine (ADR-042).

The honest limit is the same as everywhere else on this page: we designed the decoy, so
it tests the confusion we anticipated. It does not prove the engine resists a confusion
we did not think of.

**"Below tolerance" is not a miss.** The generator plants timing lags of 1–2 working
days; `grace_days: 1` means a one-day lag is inside tolerance and deliberately not
flagged. Counting those as misses would report a correctly-working tolerance as failure.
They get their own column (ADR-017).

---

## The matrix

Every run below is reproducible with `uv run finctl matrix`. Numbers come
from `docs/matrix-results.json`, written by that command — not transcribed.

| archetype | mix | vol | cycle | profile | match p1 | match p2 | recall | caught | missed | below tol | FP | balances |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| saas_subscription | upi_heavy | 200 | T+1 | demo | 95.5% | 100.0% | 100.0% | 54 | 0 | 20 | 0 | yes |
| saas_subscription | upi_heavy | 200 | T+2 | demo | 95.5% | 100.0% | 100.0% | 63 | 0 | 11 | 0 | yes |
| saas_subscription | card_heavy | 200 | T+1 | demo | 95.5% | 100.0% | 100.0% | 54 | 0 | 20 | 0 | yes |
| saas_subscription | card_heavy | 200 | T+2 | demo | 95.5% | 100.0% | 100.0% | 63 | 0 | 11 | 0 | yes |
| saas_subscription | even | 200 | T+1 | demo | 95.5% | 100.0% | 100.0% | 54 | 0 | 20 | 0 | yes |
| saas_subscription | even | 200 | T+2 | demo | 95.5% | 100.0% | 100.0% | 63 | 0 | 11 | 0 | yes |
| d2c_ecommerce | upi_heavy | 200 | T+1 | demo | 95.5% | 100.0% | 100.0% | 54 | 0 | 20 | 0 | yes |
| d2c_ecommerce | upi_heavy | 200 | T+2 | demo | 95.5% | 100.0% | 100.0% | 62 | 0 | 12 | 0 | yes |
| d2c_ecommerce | card_heavy | 200 | T+1 | demo | 95.5% | 100.0% | 100.0% | 54 | 0 | 20 | 0 | yes |
| d2c_ecommerce | card_heavy | 200 | T+2 | demo | 95.5% | 100.0% | 100.0% | 62 | 0 | 12 | 0 | yes |
| d2c_ecommerce | even | 200 | T+1 | demo | 95.5% | 100.0% | 100.0% | 54 | 0 | 20 | 0 | yes |
| d2c_ecommerce | even | 200 | T+2 | demo | 95.5% | 100.0% | 100.0% | 62 | 0 | 12 | 0 | yes |
| saas_subscription | even | 50 | T+2 | scale | 96.0% | 100.0% | 100.0% | 11 | 0 | 3 | 0 | yes |
| d2c_ecommerce | even | 50 | T+2 | scale | 96.0% | 100.0% | 100.0% | 8 | 0 | 6 | 0 | yes |
| saas_subscription | even | 500 | T+2 | scale | 95.0% | 100.0% | 100.0% | 116 | 0 | 43 | 0 | yes |
| d2c_ecommerce | even | 500 | T+2 | scale | 95.0% | 100.0% | 100.0% | 118 | 0 | 41 | 0 | yes |
| saas_subscription | even | 5,000 | T+2 | scale | 95.0% | 100.0% | 100.0% | 1161 | 0 | 439 | 0 | yes |
| d2c_ecommerce | even | 5,000 | T+2 | scale | 95.0% | 100.0% | 100.0% | 1137 | 0 | 463 | 0 | yes |
| saas_subscription | even | 50,000 | T+2 | scale | 95.0% | 100.0% | 100.0% | 11562 | 0 | 4438 | 0 | yes |
| d2c_ecommerce | even | 50,000 | T+2 | scale | 95.0% | 100.0% | 100.0% | 11503 | 0 | 4497 | 0 | yes |
| saas_subscription | even | 200 | T+2 | clean | 100.0% | 100.0% | 100.0% | 0 | 0 | 0 | 0 | yes |
| saas_subscription | even | 200 | T+2 | chaos | 65.0% | 100.0% | 100.0% | 174 | 0 | 26 | 0 | yes |

## Throughput

Engine only — batch generation is excluded, since that measures the test
harness rather than the product.

| batch | rows ingested | seconds | rows/sec |
|---|---|---|---|
| 50 | 175 | 0.005 | 32,019 |
| 200 | 636 | 0.015 | 41,083 |
| 500 | 1,539 | 0.027 | 56,575 |
| 5,000 | 15,108 | 0.223 | 67,796 |
| 50,000 | 150,783 | 2.493 | 60,489 |

## Correlation gain by archetype

| archetype | unexplained before | after | resolved |
|---|---|---|---|
| d2c_ecommerce | ₹10,55,728.20 | ₹0.00 | 100.0% |
| saas_subscription | ₹20,91,021.40 | ₹0.00 | 100.0% |

## What the slow-cycle rows established

T+3 and T+7 were added because their absence hid a bug, so it is worth saying what they
now show rather than only that they pass. At both cycles the engine detects the observed
settlement cycle, disagrees with the configured T+2, judges timing against the observed
value, and scores **0 missed** — the same recall it reports at T+1 and T+2.

Before ADR-051 the same matrix reported **48 defects missed** on those rows. That number
was produced by reverting the fix and re-running, rather than inferred: a regression test
nobody has watched fail is a regression test with no evidence behind it.

## Totals across 26 runs

- defects caught: **29070**
- defects missed: **0**
- below tolerance (planted, correctly not flagged): **10192**
- false positives: **0**
- balance identity failures: **0**


---

## The bottleneck, named honestly

The build plan asks us to name our bottleneck rather than pretend there isn't one. At the
first full matrix run, throughput fell from ~64,000 rows/sec at 5,000 rows to **24,620
rows/sec at 50,000** — a 2.6× degradation.

Profiling the 50k run rather than guessing found it: `_is_below_tolerance` in the
**scorer** was doing a linear scan through all 50,000 order matches once per planted
timing defect. 3.0 seconds of a 7.7-second run, and the only super-linear term measured
anywhere in the pipeline.

Two things worth stating precisely:

- **It was in the test harness, not the engine.** Scoring only runs when ground truth
  exists, so no merchant would ever have hit it. It nonetheless made our own published
  throughput figure wrong, in our favour.
- **The fix was an index, not an optimisation pass.** One dict built once instead of a
  scan per defect. 6.1s → 2.4s, and throughput at 50k went from 24,620 to **63,369
  rows/sec** — flat with every smaller tier.

After the fix, throughput is essentially flat from 50 to 50,000 rows. **We have not found
the engine's breaking point at the scale this product targets.** The matcher's joins are
dict-indexed and linear; the next candidate if we pushed further would be memory, since
the whole batch is held in memory by design (flat files, no database — ADR-000).

---

## Adversarial cases

Run and recorded, with what actually happened.

| Case | Expected | Actual |
|---|---|---|
| Empty batch | "nothing to reconcile", not a crash | **Bug found & fixed.** Two empty CSVs hash identically, so duplicate detection fired and it raised. Fixed (ADR-026); now reports ₹0 gap, no lines, 0% match rate — not a flattering 100%. |
| All-match batch (`clean`) | correctly says "nothing to do" | 100% match rate, zero actionable lines, headline "Nothing needs you this week." |
| Mostly-exception batch (`chaos`) | fails loudly, no plausible nonsense | 65.0% match rate reported plainly; 100% recall; balance holds. |
| Same file twice | duplicate detected via content hash | Detected, refused, naming both origins. |
| Duplicated rows *within* a file | no silent double-count | **Bug found & fixed.** ₹7,305.71 left unattributed; the balance invariant caught it. Extra copies are now a `DUPLICATE` line: phantom expectation, named (ADR-025). |
| Bank file arriving late / partial | re-run and merge, no corruption | Balances; the unarrived money appears as in-flight rather than missing. |
| Renamed / reordered ledger columns | mapped or raised — never positional | Mapped; **the gap is byte-identical** to the same batch with canonical headers. |
| Amounts as `"1,234.50"` strings | parse to paise correctly | Parsed; gap identical to the unformatted batch. |
| One order across two settlements | flagged partial, both legs recorded | **Bug found & fixed.** Both legs recorded and `gap = 0` — but per-leg fee rounding made a ₹4,008 order come out ₹0.02 under contract and be flagged as a fee error. The rounding tolerance now scales with the number of settlement legs. A 3-paise error is still caught. |
| Refund settled *before* the original | handled, not double-counted | **Bug found & fixed.** Refund rows DEBIT a settlement, but pass-1 matching ignores refund rows by design, so ₹5,421 left the bank with nothing accounting for it. Now a distinct `REFUND` mechanism, with the inversion named in the proof. |

**Five bugs found by running these cases.** All were found by *executing* the adversarial
scenarios rather than reasoning about the code, and four of the five were surfaced by the
balance invariant converting a silent wrong number into a loud exception.

---

## False attribution

Still to run: deliberately plant a gap that *looks* like a halted subscription but isn't,
and record whether correlation wrongly claims it.

The guard is already built and tested (ADR-019) — a failed payment on an **active**
subscription is not claimed as halted, and a dangling `subscription_id` does not borrow
another subscription's status. Across 22 matrix runs there were **zero false positives**.
What remains is the deliberate adversarial version, which is the point of the exercise.
