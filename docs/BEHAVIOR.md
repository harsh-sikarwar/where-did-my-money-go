# Behaviour Contract

What each stage promises, what it refuses to do, and how it behaves on bad input.

Written **before** each component is built, so this is a specification, not a
description. Where the code and this file disagree, one of them is a bug — say which.

---

## Global invariants

These hold across every stage. A violation is a bug regardless of how nice the output
looks.

1. **Money is an integer count of paise.** No floats, no rupee decimals, anywhere inside
   the engine. Rupees exist only in display formatting. (ADR-003)
2. **No stage before `explain` may call an LLM.** Matching, fee arithmetic, classification
   and correlation are deterministic. This is a hard architectural boundary, not a
   preference.
3. **Every classification carries its proof** — the arithmetic that produced it, as data,
   not prose. If a row cannot show its working, it is `UNEXPLAINED`, not guessed.
4. **The same input produces the same output.** Given a fixed seed and fixed config, two
   runs are byte-identical. This is what makes golden-file tests possible.
5. **Fail loudly, never guess.** Unmappable input raises. Silent coercion of ambiguous
   data is the failure mode that produces confident wrong answers.
6. **`Partially Reconciled` is set only by a human.** The engine may never assign it.
   (Adopted from Hyperswitch — see `PRIOR-ART.md`.)

---

## Stage: `config`

**Promises.** Loads rate cards, timing tolerances, archetype definitions and defect
profiles from YAML into validated objects. Every rate that could vary by merchant,
payment method or contract lives here.

A merchant's **contracted** rates may be layered over the shipped card, stating only what
they negotiated, so the fee check answers *"was this MY rate?"* rather than *"was this the
standard rate?"* — a materially different question for anyone off standard pricing
(ADR-046). A rate over 100% is refused, naming the unit: entering `2` for "2%" yields
0.02% and would flag every row in the file.

**Refuses.** To supply a default MDR. A missing rate for a payment method is an error,
not an assumed 2%. This is the single most likely place for the build to be quietly
wrong (`build-spec.md` §6c), so the failure is made loud by design.

**On bad input.** Unknown payment method in a rate card → raise, naming the method.
Missing required key → raise, naming the key and the file.

**Key content.**
- Per-method rate: the charge the merchant actually pays. **UPI is ~2%** — zero MDR is
  statutory, but the aggregator's platform fee is deducted anyway and is what appears on
  the settlement row. Conflating the two was a real bug; see ADR-035.
- GST at 18% applied **to the MDR**, never to the transaction amount.
- Settlement cycle (T+1 / T+2 / T+7) and the working-day calendar.
- Tolerances: rounding tolerance in paise, timing tolerance in days.

---

## Stage: `generate`

**Promises.** Emits Razorpay-shaped synthetic records — ledger CSV, bank CSV, settlements,
payments, subscriptions — for a given (seed, volume, archetype, payment mix, settlement
cycle, defect profile). Alongside them, writes `ground_truth.json` recording every planted
defect with its id, type and exact paise impact. (ADR-004)

**Refuses.** To plant a defect it cannot describe in ground truth. If it cannot be scored,
it does not get planted.

**On bad input.** Volume < 1 → raise. Payment mix not summing to 1.0 → raise. Unknown
archetype → raise, listing valid archetypes.

**Planted defects, v1.** missing order · wrong fee rate · one-sided refund · timing lag ·
cluster of ~6 halted subscriptions.

---

## Stage: `normalize`

**Promises.** Reads `.csv` and `.xlsx`/`.xlsm` through one code path — Razorpay's
dashboard exports Excel, so a merchant's own settlement report arrives as `.xlsx`
(ADR-043). Maps arbitrary input columns to the canonical schema. Converts all money to
integer paise and all timestamps to UTC. This is the **only** place rupee strings such as
`"1,234.50"` are parsed.

**Refuses.** To guess a column mapping. An unrecognised or ambiguous column raises with
the column name and the candidates it was between.

**Asks once.** The refusal carries structured data — which fields are unmapped, and every
unclaimed column available — so a human can choose. That choice is remembered against a
fold-insensitive, order-independent fingerprint of the file's headers and replayed only
for that same shape, so it is a recorded decision rather than an inference. A human
override beats the alias table, and the audit trail records which fields a person mapped
by hand (ADR-045).

**On bad input.**
- Renamed/reordered columns → resolved by the mapping table, or raise. Never positional.
- `"1,234.50"`, `"₹1234.50"`, `"1234.5"` → all parse to `123450` paise.
- **Timestamps** → accepts Excel serial dates (`44658.4469`), epoch seconds
  (`1656487479`), `DD/MM/YYYY HH:MM:SS`, `YYYY-MM-DD` and ISO 8601. Razorpay's own
  dashboard exports mix serials and `DD/MM/YYYY` **in the same column**, so this is not
  optional. A bare number in `[20000, 80000]` is a serial; outside it, epoch seconds.
  The ranges are ~10⁴ apart, so this is disjoint, not a guess. A fractional number
  outside the serial window raises rather than being coerced (ADR-037).
- Empty file → returns an empty frame with the correct schema. Not an error: "nothing to
  reconcile" is a valid answer and must survive to the verdict stage.
- Negative amounts → allowed only where the schema expects them (refunds); otherwise raise.

---

## Stage: `stage`

**Promises.** Holds validated-but-unreconciled entries, immutably. Re-running the pipeline
over the same staged batch produces the same result and does not mutate the batch.

**Refuses.** To modify a staged entry after creation. Corrections create a new batch.

**On bad input.** Same file staged twice → detected by content hash, reported as a
duplicate rather than silently doubling every figure.

---

## Stage: `match` (two passes)

**Promises.**
- **Pass 1 — Order → PSP.** Joins ledger to payments/settlement on `order_id` /
  `payment_id`. Answers: did each sale reach Razorpay?
- **Pass 2 — PSP → Bank.** Joins settlement to bank statement on `settlement_id` / `utr`.
  Answers: did Razorpay's payout reach the bank?

Two passes rather than one join, so the output names **which leg** broke.

**Refuses.** To fuzzy-match on amount or timestamp proximity. Matching is on identifiers.
An amount-based near-match is a guess wearing a confidence score.

**On bad input.**
- One order split across two settlements → both legs recorded, flagged as partial. Not an
  error.
- Duplicate `order_id` in the ledger → flagged `DUPLICATE`, not silently deduplicated.
- Nothing matches at all → reports a 0% match rate loudly. It must never produce a
  plausible-looking summary from an empty match set.

---

## Stage: `classify`

**Promises.** Assigns exactly one label per discrepancy, with the arithmetic attached:
`FEE · TAX_ON_FEE · TIMING · REFUND · ROUNDING · DUPLICATE · MISSING · ON_HOLD ·
DISPUTED · UNRECORDED_REFUND · UNEXPECTED_SETTLEMENT · UNEXPLAINED`.

**Withheld money is never also reported as late.** `ON_HOLD` and `DISPUTED` suppress
`TIMING`. "It arrives on its own" is false for money the PSP is holding, and for a
chargeback it is actively harmful — waiting is how a merchant loses one (ADR-041).

Two of these are **settlement-level**, not order-level, and carry no `order_id`:
`UNRECORDED_REFUND` (money Razorpay returned that the merchant never recorded, keyed by
`rfnd_…`) and `UNEXPECTED_SETTLEMENT` (money in for an order the ledger lacks). Both are
identified by `entity_id`, which is how Razorpay's own recon export identifies them.

**Refuses.** To pick a winner when more than one rule fits. Multiple matches →
`NEEDS_REVIEW`, carrying all candidate explanations. (Cointab's "leave it unmatched when
evidence is weak" — see `PRIOR-ART.md`.)

**On bad input.** A discrepancy no rule explains → `UNEXPLAINED`. This is a correct
outcome, not a failure; the residual is the honesty metric, and it is what `correlate`
then works on.

---

## Stage: `correlate` — the differentiator

**Promises.** For every `UNEXPLAINED` row, looks up the payment record and the
subscription record:
- payment `status: failed` → `error_reason` explains the gap
- subscription `halted` → invoice generated, charge never attempted = silent revenue death

Reports **unexplained ₹ before vs after**. That delta is the headline metric.

**Refuses.** To infer a cause from resemblance. Correlation follows the identifier join
chain (`order_id → payment_id → subscription_id`) and nothing else. If the join does not
land, the row stays `UNEXPLAINED`.

**On bad input.** A gap that *looks* like a halted subscription but has no subscription
record must remain `UNEXPLAINED`. This case is planted deliberately on test day
(`build-plan-3.5-days.md`, Day 3 afternoon) — if the engine claims it, that is a real
finding and gets documented rather than hidden.

**Calibration, stated up front.** Correlation gain should be **large for SaaS** and
**near zero for one-time-payment businesses**. Reporting that difference is honest
calibration, not weakness.

---

## Stage: `rank`

**Promises.** Splits resolved exceptions into **benign** (explained, no action needed —
fees, normal timing) and **actionable** (needs a human this week). Success is a *short*
actionable list.

**Refuses.** To rank by rupee value alone. A ₹31,000 timing lag that resolves itself on
Tuesday is benign; ₹3,800 of dead subscriptions is not. Materiality is about
recoverability, not size.

---

## Stage: `explain` — the only LLM stage

**Promises.** Takes a resolved exception cluster plus its proof and returns plain-language
cause and recommended action. Every finance term is explained inline or absent.

**Refuses.** To invent, alter, or recompute any number. Numbers come from the engine and
pass through untouched. Output is validated against the input facts before display.

**On failure.** LLM unavailable, times out, or returns malformed output → falls back to a
templated deterministic explanation. The verdict screen must render with the API key
absent. The demo cannot depend on a network call succeeding.

---

## Stage: `audit`

**Promises.** Every engine decision appended to a JSONL file, human-readable: which rule
fired, on which row, with which numbers, at which stage. Enough to reconstruct any figure
on the verdict screen back to its source records.

**Refuses.** To log secrets, or to summarise. The audit log is raw and complete; reading
it is the UI's problem.
