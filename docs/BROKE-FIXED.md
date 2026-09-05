# Bugs Found and Fixed During the Build

A tight, dated record of real defects discovered and repaired. This is the engine's
credibility audit — what we were wrong about, and how we know it's fixed.

These are not potential issues or theoretical risks. They are bugs that would have shipped
undetected if we relied only on code review and unit tests.

---

## Critical bugs (would have broken the product)

### 2026-09-02 — Schema mismatch: `payment_id` is null on payment rows
**Impact:** 0% match rate on all orders. Every order would report `MISSING`.

Razorpay's documented schema said payment rows carry `payment_id`. The actual API returns
`entity_id` instead, with `payment_id` null. Our matcher joined on `payment_id`, so every
Order→PSP join would have failed silently.

**Found by:** Reading Razorpay's actual API responses before writing the matcher (ADR-006).
Not caught by unit tests because our own synthetic data followed our false assumption.

**Fix:** Updated matcher to use `entity_id` for type=payment rows. Verified against 10
published Razorpay sample rows (ADR-007).

**Prevention:** The shape probe (ADR-006) happens before any matching code. It is not
optional.

---

### 2026-09-02 — Fee convention ambiguity: `fee` includes or excludes tax?
**Impact:** Every card transaction wrong by the GST amount (~₹290 per ₹10,000). Residual
absorbed silently in "unexplained" bucket.

Razorpay's docs say: `credit = amount − fee − tax`. Their example says: `credit = amount −
fee` (tax is 0). The fee in the example (₹2,900) is too large to be MDR alone; it includes
GST.

This is the exact failure mode the engine exists to catch — occurring inside the engine.

**Found by:** Reading the ambiguity in published material (ADR-007, ADR-012).

**Fix:** Engine derives the convention from the data, not from the schema. Rate card config
states which convention applies to this batch. Classifier asserts the convention holds
throughout (ADR-012). If it doesn't, the run raises.

**Prevention:** Determinism over guessing. Every assumption is stated in YAML and asserted
at runtime.

---

### 2026-09-03 — Unrecorded refunds: blank order_id causes money to vanish
**Impact:** Settlement refunds with no corresponding order record are dropped before they
reach classification. Money leaves the merchant's account and the engine never sees it.

Razorpay's sample export contained a `type=refund` row with blank `order_id`. The matcher
required `order_id` to be present, so the row was dropped. No classification happened, no
audit entry recorded it, and the gap went unexplained.

**Found by:** Running reconciliation on Razorpay's own published sample file (ADR-039).

**Fix:** Matcher now accepts blank `order_id` on refund rows and stages them as "settlement
refund with no linked order." Classifier tags these as `UNRECORDED_REFUND` and they appear
in the action list (ADR-039).

**Prevention:** Test against real Razorpay samples, not just synthetic data. One sample file
found what 500+ tests could not.

---

### 2026-09-04 — Verdict lines don't sum to gap
**Impact:** Headline arithmetic breaks. Lines sum to ₹99,421 but gap is ₹38,372. Looks like
data is missing. Destroys merchant trust.

Each individual line was correct and tested. The bug was in the relationship between
correct numbers — a failure mode component tests cannot detect.

**Found by:** Human reading the verdict screen (not a test).

**Fix:** Added balance-identity invariant: every reconciliation asserts `gap == sum(lines)`
before rendering. Raises if it fails (ADR-024).

**Prevention:** Invariants on compositions, not just components. For products claiming
"every rupee accounted for," the arithmetic of the headline must be asserted, not assumed.

---

## Configuration bugs (hardcoded values wrong)

### 2026-09-03 — UPI rate hardcoded at 0%
**Impact:** UPI transactions show ₹0 Razorpay fee when they should show ~2% platform fee.

The rate card was configurable for other methods, but UPI defaulted to 0 with no way to
override it. Real UPI has a ~2% platform fee on top of base MDR.

**Found by:** Reading Razorpay's published pricing page (not by the suite).

**Fix:** Unified rate card config across all payment methods (ADR-035). UPI now defaults to
Razorpay's current public rate (2% platform + method-specific MDR). Override in YAML if
your contract differs.

**Prevention:** No hardcoded rates anywhere. All fees come from config. The `config` stage
refuses to supply a default MDR — it must be explicit.

---

### 2026-09-03 — Holiday list was empty, treated as "no holidays"
**Impact:** Settlement delays on holidays are misclassified as late. Produces false
positives in actionable findings.

The holiday calendar defaulted to empty list. An empty list was treated as `None` (no
holidays), not as "observe no holidays." The classifier then flagged Friday→Tuesday
settlements as always late, even in countries that observe Friday-Saturday weekends.

**Found by:** Running the matrix with ADR-037 (weekend handling).

**Fix:** Holiday calendar is explicit and per-country in config. Empty is invalid; must
state a country or an explicit list (ADR-037). Tested against T+1, T+2, T+7 cycles.

**Prevention:** Config validation refuses ambiguous defaults.

---

## Parsing bugs (real Razorpay sample files)

### 2026-09-04 — Date format detection fails on xlsx exports
**Impact:** Dates parsed as integers. Settlement cycle calculations broken. Gap timing
analysis nonsense.

Razorpay's xlsx exports use a date serial format; CSVs use ISO 8601. The normalizer tried
one parser and failed silently, returning `NaT`. The classifier then inferred cycle lengths
from null dates.

**Found by:** Running reconciliation on Razorpay's sample xlsx export (ADR-039).

**Fix:** Normalizer tries five date formats in sequence: ISO 8601, US locale, European
locale, excel serial, unix timestamp. Raises with all attempted formats if all fail (ADR-039).

**Prevention:** Test against multiple real export formats, not hypothetical CSVs.

---

### 2026-09-04 — CSV with BOM marker not recognized
**Impact:** Column headers parse with `﻿` prefix. Column aliases don't match. All rows
rejected as invalid schema.

Some export tools (especially on Windows) prepend a UTF-8 BOM (Byte Order Mark) to CSV
files. The normalizer's column alias lookup expected exact matches. No match → unknown
column → row rejected.

**Found by:** Running against a sample file with BOM.

**Fix:** Normalizer strips BOM from first line before column matching (ADR-039).

**Prevention:** Robust to export tool quirks. Test against real files, and expect the worst.

---

## Explanation-layer bugs (the model that wasn't there)

These are presentation-layer defects, and every one of them is a bug about *prose*. None of
them could put a wrong figure in front of a merchant, because the guard that discards any
model sentence containing a numeral (ADR-050) held throughout — in one case by discarding
so much that it took a measurement to notice. That is the trade the engine chose, visible
in production: a missing sentence, never a fabricated number.

### 2026-09-05 — The API key was never loaded, so the model never ran
**Impact:** Every AI explanation in the dashboard was the deterministic template. The
product looked like it had a language model and did not have one.

`python-dotenv` was declared in `engine/pyproject.toml`'s extras and imported nowhere.
`.env` at the repo root held a working key; nothing read it. `LLMConfig.from_env()` then
correctly found no key, correctly concluded the model was unavailable, and correctly served
the template — which is the right response to a missing key and indistinguishable on screen
from a broken one.

**Found by:** Clicking through the dashboard and noticing that prose which should vary with
the shape of each batch never varied.

**Fix:** A guarded `load_dotenv(..., override=False)` at the two process boundaries where a
key first becomes available — `api/main.py` and `cli.py`. Both wrapped in `ImportError`
handling so the engine still installs and runs with zero LLM dependencies (ADR-001).

**Prevention:** A fallback that is correct prose hides its own cause. `/health` now reports
`llm_credential_present`, so "no key" is a field you can read rather than a diff you have
to reason about.

---

### 2026-09-05 — The prompt carried a figure into a prompt that forbids figures
**Impact:** Eleven of twelve fee questions in the copilot returned the template. Every other
question returned model prose. The question a merchant is most likely to ask was the one
that silently degraded.

The prompt builder quotes `line.explanation`, which is merchant-facing copy and carries a
figure where a figure helps a human: "plus the 18% GST charged on that fee". A model told
never to write a number was being shown one — and `guard()` discards the WHOLE response when
it finds a numeral, so a single echoed `18%` cost the entire answer.

**Found by:** Running all twelve prefilled copilot questions and counting the source of each
reply: 1/12 model on fee questions, 12/12 everywhere else.

**Fix:** `redact_figures()` strips from prompt text anything `guard` would later reject. The
screen keeps its figure; the model is never shown one. Re-measured after the fix: 10/12.

**Prevention:** State the rule at both ends. A prompt that can trip its own guard is a
prompt bug, not a model failure.

---

### 2026-09-05 — The test for that bug asserted the wrong thing
**Impact:** A green test named `test_the_prompt_carries_no_figures` sat beside the bug above
for the whole of that bug's life.

It asserted `"₹" not in line`, over a hand-made fixture rather than the real `LINE_COPY`
taxonomy the prompt actually quotes. Rupee symbols were never the failure mode; a bare `18%`
was. And the fixture could not have contained the string that broke production, because the
fixture and the assertion were written by the same hand in the same sitting.

**Found by:** Fixing the bug and noticing the test passed identically before and after.

**Fix:** Three tests using the engine's own `has_numerals` predicate against the real
`LINE_COPY` entries.

**Prevention:** Test the predicate the product enforces, over the data the product ships. A
test carrying its own private notion of "a number" is testing itself.

---

### 2026-09-05 — Every page load spent a model call on unchanged input
**Impact:** HTTP 429 from the inference endpoint after roughly a minute of ordinary
clicking. In front of a judge: a demo that degrades to templates the longer someone uses it.

`/api/verdict` called `explain_detailed()` on every request. The verdict is deterministic
and the batch does not change between loads, so each call re-derived the same two sentences
at the cost of one request against a token-per-minute budget.

**Found by:** Two fallbacks appearing mid-session that looked like a regression from an
unrelated change. Calling the client directly showed rate-limit headers, not a code bug.

**Fix:** `_summary_cache` keyed by batch, invalidated in `_load()` beside the existing
verdict cache. Repeat loads went from 0.87s to 0.01s.

**Prevention:** Deterministic input, cached output. The budget is per minute and a demo is a
burst.

---

### 2026-09-05 — Four different failures produced one identical screen
**Impact:** Time spent reading a diff for a bug that was an HTTP 429.

No key, a rate limit, a timeout, and a guarded response all rendered the same template with
the same `source: "template"`. The product could not say which path produced the sentence a
merchant read, so neither could the person operating it.

**Found by:** The rate-limit incident above.

**Fix:** `ExplainUnavailable` carries a machine-readable `reason`; `explain_detailed()`
returns `(prose, source, reason)`; the API returns `summary_reason`, and `/health` reports
the last one seen.

**Prevention:** A fallback is a path, not an absence. If it cannot name itself, it is
unobservable.

---

## How we know these are fixed

1. **Determinism test**: Run the same batch twice. Same output down to the JSONL audit log,
   and `checkpoint` prints a fingerprint over the claims — `2310d942c05c4e14` on the default
   seed — that you can compare without reading a single row.
2. **Reproducibility**: 903 unit tests passing, 1 skipped, including adversarial cases
   that trigger each bug.
3. **External validation**: Arithmetic matches Razorpay's 10 published sample rows.
4. **Blind testing**: Engine runs on unseen data and scores perfectly. One hand-edited batch
   found what 26 matrix runs could not (ADR-031).
5. **Real-file testing**: Reconciliation works on Razorpay's own sample exports (ADR-039).

**The one we can't yet claim**: No real merchant batch has been reconciled. These bugs are
all fixed for data this engine generates or that Razorpay published. For production
merchant data, that's validation work, not development.
