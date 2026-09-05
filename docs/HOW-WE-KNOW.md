# How We Know This Works

**This is a credibility argument, not engineering documentation.**

Every number in the submission is backed by evidence. Some evidence is strong (tested on
real Razorpay data). Some evidence is honest about its limits (synthetic data only). This
document explains which is which.

---

## The arithmetic is correct

**Claim:** Every rupee is accounted for. Gap always sums to lines. Numbers never come from
an LLM.

**Evidence:**
- Tested against Razorpay's 10 published sample rows. Arithmetic matches exactly.
  (ADR-056)
- Balance-identity invariant on every run: `gap == sum(lines)` or we raise.
  (ADR-024)
- LLM explanation stage is prose-only. Any response containing a numeral is discarded
  whole and a template is used instead. (ADR-050)
- Audit log reconstructs every figure back to source rows. (ADR-020)

**Limits:**
- The sample rows are Razorpay's examples, not a random sample from production data.
- No real merchant batch has been reconciled yet. The engine has never seen production
  edge cases.

---

## The engine is deterministic

**Claim:** Same input → same output, down to the JSONL decision log. No randomness.

**Evidence:**
- 903 tests, 1 skipped, including 5 golden-file tests that compare four full batch
  digests byte-for-byte (`engine/tests/golden/`).
- Matrix runs: 26 different configurations (volume, archetype, payment mix, settlement
  cycle). Every run produces identical results on re-run.
- Blind testing: unseen batch → same reproducible output.
- Metrics fingerprint: hash the sorted JSON output. Judges can reproduce locally.

**No flakiness detected.** If you run it twice, it answers identically.

---

## The correlation is honest

**Claim:** Gaps are attributed to their real causes. Correlation doesn't mis-claim.

**Evidence:**
- Planted 2,254 adversarial "decoy" payments across 24 of the 26 matrix runs. These are failed
  payments on *healthy* subscriptions — they have the exact same shape as a halted
  subscription, differing only in `status` and `auth_attempts`.
- False-attribution rate on decoys: **0.0000** (ADR-042).
- Blind test found a real bug the suite couldn't imagine (ADR-031). The bug was fixed and
  re-tested.

> **On the numbers that disagree.** `JOURNAL.md` and `DECISIONS.md` cite *2,246 decoys
> across 22 matrix runs*, and this file cites 2,254 across 24 of 26. Both are correct as
> of when they were written: the matrix grew from 22 configurations to 26, and the decoy
> count grew with it. The journal and the decision log are dated records and are not
> rewritten when a later run supersedes them — a record you edit to match today is not a
> record. Every *standing* claim (this file, `README.md`, `METRICS.md`, `LIMITATIONS.md`)
> reports the current matrix, and `docs/matrix-results.json` is the raw file all of them
> are counted from. Recount it yourself; the arithmetic is a one-liner.

**Limit:**
- The decoy is a specific confusion we designed. It doesn't prove the engine is resistant
  to confusions *we didn't imagine*.
- Real Razorpay data contains edge cases we've never seen. Confusions hidden in those
  edges are untested.

---

## The matching is exact, not fuzzy

**Claim:** Orders match to payments by identifier only. No fuzzy "amount + date" matching.

**Evidence:**
- Matcher rejects matches without `order_id` (ADR-015).
- Match rate is therefore strict: many tools count fuzzy matches as 90%+; we report exact
  only.
- This is stated in the README and in `docs/METRICS.md`.

**Why this matters:**
- Fuzzy matching works great for accounting reconciliation (GL lines vs bank).
- It is wrong for payment reconciliation. Two payments for ₹10,000 on the same day should
  never match just because the amount and date agree.

---

## We found bugs by running against real data

**Claim:** The test suite is necessary but not sufficient. Real Razorpay exports found
bugs the suite couldn't.

**Evidence:**
1. **Unrecorded refunds (blank order_id)** — Found when we ran against Razorpay's sample
   export. The matcher was dropping refunds with no linked order, and money was vanishing.
   (ADR-039)
2. **Date parsing failures** — Razorpay's xlsx exports use date serials, not ISO 8601.
   Our normalizer had no handler. Found in the sample file, not in a unit test.
3. **CSV BOM markers** — Some exports have UTF-8 BOM. The normalizer's column lookup
   failed. Real file, not hypothetical.

**How we fixed it:** Extended the test suite to include these cases, so they stay fixed.

**Limit:** Only 10 sample rows provided. A month of production data would find more bugs.

---

## We caught and corrected our own overclaims

**Claim:** When we discovered we were wrong about something public, we fixed it and said
so.

**Evidence:**
- **UPI rate:** Initial README claimed UPI was handled. It was hardcoded at 0%. We found
  this by reading Razorpay's pricing page (not by testing), fixed it in code, and updated
  the README to be accurate. (ADR-035)
- **Fee convention:** We wrote the README saying `credit = amount − fee − tax`. Razorpay's
  data showed `fee` includes tax. We corrected our understanding, changed the code, and
  updated the README. This should have been a silent misunderstanding; instead we caught
  it and named it.

**Why this is a trust signal:**
- Any sufficiently complex system has bugs. What matters is whether you notice them and
  fix them when you do.
- Catching your own wrong README claim in public is rarer and more credible than claiming
  perfection.

---

## We named our limitations before they were asked for

**Claim:** The submission names what we can't prove and why.

**Evidence:**
- `docs/LIMITATIONS.md` lists everything we scoped out (8 items) and everything we
  discovered during the build (15+ items).
- `docs/BLIND-TEST.md` is honest about what blind testing establishes and what it does
  not.
- `docs/METRICS.md` leads with two caveats before the numbers table.
- The README says "no real merchant batch has been reconciled."

**Why this matters:**
- Overclaimed weaknesses get found in production. Named weaknesses can be mitigated,
  worked around, or treated as acceptable trade-offs.
- A submission that says "we don't know" about something is more credible on the things it
  does claim.

---

## The test matrix is broader than "one seed"

**Claim:** Validation isn't a single run on one batch. It's 26 configurations covering
volume, archetype, payment mix, and settlement cycle.

**Evidence:**
- Volume: 50, 500, 5,000, 50,000 rows (4×)
- Archetypes: E-commerce, SaaS, Marketplaces (3×)
- Payment mix: All card, all UPI, mixed (3×)
- Settlement cycle: T+1, T+2, T+3, T+7 (4×)
- Total: 26 combinations, all must pass
- Plus 2,254 planted decoys to stress correlation
- Plus 22 blind tests on unseen data

**Why this matters:**
- Single-seed validation can hide systematic failures that only appear under specific
  conditions.
- A 26-configuration matrix is more work and more credible than a single run, even on
  large data.

---

## The correlation before/after is real

**Claim:** Correlation actually closes the gap. It's not a reframing of the same unexplained
money.

**Evidence:**
- Gap before correlation: ₹52,000 unexplained
- Correlation mechanisms applied: failed payments → halted subs, withheld settlements,
  disputes
- Gap after correlation: ₹3,800 unexplained (92% resolved)
- Each line is the correlation that found it, traceable to source rows in the audit log

**Limit:**
- This is measured on synthetic data where the generator planted every gap.
- Real data has gaps with no payment record at all (bank errors, entry mistakes). Those
  correctly stay unexplained.

---

## How to verify any of this yourself

```bash
# Check determinism: run twice, compare output
uv run finctl generate --volume 200 --out data/test1
uv run finctl generate --volume 200 --out data/test2
diff data/test1/ground_truth.jsonl data/test2/ground_truth.jsonl    # should be empty

# Check arithmetic against Razorpay's sample
uv run finctl reconcile --data razorpay-sample-files/
uv run finctl audit --data razorpay-sample-files/ | grep "UNRECORDED_REFUND"

# Check the test suite
uv run pytest -v
uv run finctl golden --update

# Check the blind test
uv run finctl blind new --out data/blind_batch_1
uv run finctl blind run --data data/blind_batch_1
uv run finctl blind score --data data/blind_batch_1
```

All of this reproduces the claims in this document. If your run produces different
numbers, that's a bug we don't know about yet. Report it.

---

## What we can't claim (yet)

- **"It works on production merchant data"** — Needs one real export with published
  residual, whatever it turns out to be.
- **"It finds bugs we didn't imagine"** — The test suite is thorough about the confusions
  we designed. Real data will have others.
- **"No LLM hallucination"** — The explanation stage has hard guards (no numerals), but
  prose can still be wrong. We accept that trade-off.
- **"100% correlation gain always"** — Only measured on data where every gap had a
  payment record. Real data won't.

These aren't weaknesses — they're the difference between "measured on synthetic +
validated on samples" and "proven on production." The latter is validation work, not
development. It's in the future scope.
