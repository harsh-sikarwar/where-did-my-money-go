# Metrics

Measured results. Populated on test day (Phase 4) from real runs — never estimated,
never from memory.

**Status: empty. No runs yet.** This file stating "no runs yet" is deliberate; a metrics
file with plausible-looking placeholder numbers is how fabricated figures reach a
submission.

---

## Baseline for comparison

Terra Insight publishes the yardstick: manual VLOOKUP reconciliation achieves roughly a
**51% match rate**; structured tooling reaches **88%+**. A match rate reported without a
baseline means nothing, so ours is read against these.

---

## The matrix (to be run — Phase 4 morning)

| Axis | Values |
|---|---|
| Volume | 50 · 500 · 5,000 · 50,000 |
| Archetype | D2C e-commerce · SaaS subscription |
| Payment mix | UPI-heavy (90/10) · card-heavy (90/10) · even |
| Settlement cycle | T+1 · T+2 |

### Per-run report format

```
Batch size · Archetype · Payment mix · Settlement cycle
Match rate %
Auto-resolved vs escalated (count + ₹)
Unexplained BEFORE correlation → AFTER
Seeded defects caught / missed        ← the honest list
Throughput (records/sec, wall-clock)
Known failure modes
```

### Results

*(empty — Phase 4)*

---

## Correlation gain — the headline metric

Unexplained ₹ before correlation vs after, per archetype.

Expected shape, stated in advance so the result cannot be retrofitted to the
expectation: **large gain for SaaS** (halted subscriptions are the mechanism),
**near zero for one-time-payment D2C**. Reporting that difference is calibration, not
weakness.

### Results

*(empty — Phase 4)*

---

## Throughput and the bottleneck

Records/second and wall-clock time at each volume tier.

Naming the bottleneck honestly scores better than pretending there isn't one — e.g.
"matching degrades above 10k records because the join is O(n²); indexed joins would fix
it." The claim goes here once measured, with the number that supports it.

### Results

*(empty — Phase 4)*

---

## Adversarial cases

Run each, record what actually happened — including cases that behaved badly.

| Case | Expected | Actual |
|---|---|---|
| Empty batch | "nothing to reconcile", not a crash | *(pending)* |
| All-match batch | correctly says "nothing to do" | *(pending)* |
| All-exception batch | fails loudly, no plausible nonsense | *(pending)* |
| Same file twice | duplicate detected via content hash | *(pending)* |
| Bank file arriving after first run | re-run and merge, no corruption | *(pending)* |
| Renamed / reordered ledger columns | mapped or raised — never positional | *(pending)* |
| Amounts as `"1,234.50"` strings | parse to paise correctly | *(pending)* |
| Order split across two settlements | flagged partial, both legs recorded | *(pending)* |
| Refund before original settled | handled, not double-counted | *(pending)* |

---

## False attribution — the failure-recovery evidence

Phase 4 afternoon: plant a gap that *looks* like a halted subscription but isn't. Record
whether correlation wrongly claims it, and what was done about it.

Per `build-plan-3.5-days.md`, this is the highest score-per-minute work in the project —
judging criterion 4 is literally "what broke, and what you did about it."

### Result

*(empty — Phase 4)*
