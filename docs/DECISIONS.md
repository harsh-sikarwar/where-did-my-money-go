# Decision Log

Every fork taken during the build, in the order taken. ADR-style: context, options,
choice, why, consequences. Decisions inherited from `PROJECT-CONTEXT.md` §3 are
recorded as ADR-000 and are **not** relitigated here.

This file is submission source material — judging criterion 1 (problem taste) and
criterion 3 (AI judgment) are asking for exactly what is written here.

---

## ADR-000 — Inherited decisions (pre-build)

Made before code, recorded in `PROJECT-CONTEXT.md` §3. Listed here so this log is
self-contained. **Do not relitigate.**

| Decision | Why |
|---|---|
| Track 04 (recon), not Track 03 (recovery) | Recovery is Razorpay's own core product; recon is explicitly left to merchants |
| Recovery data used as *evidence*, not as a feature | Keeps the submission unambiguously in one track |
| Deterministic engine; LLM only explains | An LLM must never decide whether two numbers are equal |
| Two-pass matching, not one join | Tells you *which leg* broke |
| Seeded synthetic data for metrics | Only way to report honest precision — we control ground truth |
| Razorpay-shaped fake data first, live API second | API auth can eat 4h and produce nothing demoable |
| FastAPI + pandas backend, Next.js + Tailwind frontend | Domain fit; frontend is the comparative edge |
| SQLite / flat files, no Postgres | 50–5,000 rows |
| Layered UI: plain language default, exact numbers one click down | Proves the simplicity is a choice, not a limitation |

---

## ADR-001 — Engine is a library with a CLI; the web API is a thin wrapper

**Date:** 2026-09-02 · **Phase:** 0

**Context.** The build plan's Day-1 checkpoint is "unexplained-before ≠ unexplained-after,
printed to a console." That checkpoint is the project's go/no-go gate. If reaching it
requires a running web server, a frontend dev server, and an API key, then every
debugging session drags three extra moving parts along with it.

**Options considered.**
1. FastAPI-first — build the HTTP layer, drive the engine through it.
2. Engine as an importable library with a Typer CLI; FastAPI added later as a caller.
3. Notebook-driven, formalise later.

**Choice.** Option 2.

**Why.** The engine is the project; the web layer is presentation. Making the engine
independently runnable means the Day-1 checkpoint needs exactly one command and zero
services. It also makes the engine testable by `pytest` without an HTTP client, which
is what makes golden-file tests cheap enough to actually write. Option 3 was rejected
because notebooks resist golden-file testing and diff badly in git.

**Consequences.**
- `engine/` has no dependency on `api/` or `web/`. The reverse is allowed.
- Web dependencies live in `[project.optional-dependencies]`, not the base set, so
  `uv sync` for the engine cannot pull in FastAPI. This is enforced by packaging, not
  by discipline.
- Anything the UI can do, the CLI must be able to do first. If a number appears only in
  the browser, it is not testable and does not exist.

---

## ADR-002 — Secrets hygiene lands in commit one, before any code

**Date:** 2026-09-02 · **Phase:** 0

**Context.** `PROJECT-CONTEXT.md` §9 states plainly: "Razorpay keys in a public repo
fails the submission." The repo is public.

**Choice.** `.gitignore` and `.env.example` were the first two files written, before
`pyproject.toml` and before any Python. `.gitignore` denies `.env` and `.env.*` and
re-allows only `.env.example`.

**Why.** A key committed and then removed is still in git history and still leaked. The
only reliable defence is that the ignore rule predates the file it protects. Doing this
first costs five minutes; doing it late may cost the submission.

**Consequences.**
- `.env.example` documents every variable with a comment, and its Razorpay entry
  explicitly says test keys start with `rzp_test_`.
- `data/` is gitignored. Generated batches are reproducible from a seed, so the seed is
  the artefact worth committing, not several megabytes of CSV.

---

## ADR-003 — Money is an integer count of paise, everywhere, with no exceptions

**Date:** 2026-09-02 · **Phase:** 0

**Context.** This engine's entire output is a claim that a set of numbers adds up. Its
core arithmetic is GST-on-MDR: 18% of 2% of an amount. Compounded percentages of
percentages are exactly where binary floating point drifts.

**Options considered.**
1. Floats of rupees — natural to read, matches CSV input.
2. `decimal.Decimal` — exact, but needs context management and is slow across millions
   of pandas cells.
3. Integer paise — matches Razorpay's own API, which returns `amount` in paise.

**Choice.** Option 3, converted at the normalize boundary and never converted back until
the presentation layer formats a string.

**Why.** Razorpay already made this decision; matching it removes a conversion. More
importantly, the engine has a `ROUNDING` classification — if float drift can manufacture
a rounding "defect", then the engine cannot distinguish its own numerical noise from a
real merchant discrepancy, and the honest-residual claim collapses.

**Consequences.**
- Normalize is a hard boundary: rupee strings such as `"1,234.50"` are parsed there and
  nowhere else.
- Rupee formatting is a display concern, allowed only in CLI/UI rendering.
- Half-paise cases (percentage arithmetic yielding a fraction) need one explicit,
  documented rounding policy. Decided in Phase 1 with the rate card.

---

## ADR-004 — The generator emits machine-readable ground truth alongside the data

**Date:** 2026-09-02 · **Phase:** 0

**Context.** The headline metric is "seeded defects caught / missed." Test day runs a
matrix of volume × archetype × payment mix × settlement cycle — dozens of runs.

**Options considered.**
1. Plant defects, inspect output by eye, record results manually.
2. Emit `ground_truth.json` next to every generated batch, listing each planted defect
   with its id, type and exact rupee impact; score the engine against it automatically.

**Choice.** Option 2.

**Why.** Across dozens of runs, manual verification is not merely slow, it is
unreliable — and an unreliable accuracy number is worse than no accuracy number,
because it is the one thing a judge can check. With a ground-truth file, "94% of seeded
defects caught, here are the 3 missed" becomes an assertion the test suite makes, not a
claim a human remembers to verify.

**Consequences.**
- The generator must record intent at planting time, not reconstruct it afterwards.
- A scoring function compares engine output against ground truth and produces the
  caught/missed list directly.
- This gives the false-attribution test (Day 3 afternoon) somewhere precise to land: the
  planted decoy is a ground-truth entry whose expected classification is "not a halted
  subscription."

---

## ADR-005 — Pandas 3.x accepted, with a Phase-1 verification task

**Date:** 2026-09-02 · **Phase:** 0

**Context.** `uv sync` resolved `pandas==3.0.5`. Pandas 3 changed defaults that matter
here: copy-on-write is mandatory, and the default string dtype changed.

**Choice.** Accept pandas 3, and verify behaviour explicitly during Phase 1 rather than
pinning back to 2.x pre-emptively.

**Why.** Neither change threatens this workload — the engine holds money as integers and
does not rely on chained-assignment mutation, which is what copy-on-write breaks. Pinning
backwards to avoid a problem not yet observed adds a constraint without evidence.

**Consequences.**
- Recorded as a known risk. If Phase 1 hits dtype surprises, pinning to `pandas>=2.2,<3`
  is a one-line change, and this entry is the note explaining why.
- Golden-file tests will catch any silent behavioural difference introduced by an
  upgrade later.

---

## ADR-006 — Real API is verification, not foundation

**Date:** 2026-09-02 · **Phase:** 1 (pre-work)

**Context.** The two planning documents appear to disagree. `build-spec.md` §4 opens with
*"Stage 1 — Prove the pipe (do not skip): pull one real settlement recon response from
test mode. Look at the actual JSON before designing anything."* `build-plan-3.5-days.md`
says build Day 1 against a seeded generator and swap in the live API on Day 2, with a hard
2-hour timebox.

Read as *"build the adapter first,"* these conflict. Read correctly, they do not.

**The distinction.**

> **Real API = verification.** Not: real API = foundation.

The purpose of touching the live API early is **not** to depend on it. It is to check that
our synthetic data actually resembles reality — that the fields we invent have the names,
types, units and nullability that Razorpay really uses.

**Choice.** A one-off **shape probe**, run before the generator is written, whose only
output is a captured JSON fixture and a field inventory. The engine never imports it. The
generator is validated against it. The live adapter remains a Day-2 task under its
original 2-hour timebox.

**Why this ordering is strictly better than either extreme.**

- *Adapter-first* risks auth and pagination consuming Day 1, producing no demoable
  artefact — the exact failure `build-plan-3.5-days.md` was written to prevent.
- *Seeded-only* risks building a beautiful engine against a schema that doesn't exist.
  Discovering on Day 2 that `settlement.fees` is a per-settlement aggregate rather than
  per-payment would invalidate the fee classifier after it was already built and tested.
- The probe costs well under an hour and converts an unbounded schema risk into a fixed
  file on disk.

**The cost of being wrong, asymmetrically.** A wrong guess about field shape is not caught
by any test we write, because our tests would assert our own wrong assumption. Golden-file
tests lock in the schema — so locking in an unverified schema is worse than having no
tests at all. This is the one class of error the rest of the plan's rigour cannot catch.

**Consequences.**
- Probe output lands in `engine/tests/fixtures/razorpay/` as committed JSON. Test-mode
  data, no live keys, safe to commit — and it becomes the contract the generator is held to.
- A test asserts generator output is **field-compatible** with the captured fixture. If
  Razorpay's shape and ours diverge, the suite says so rather than a judge saying so.
- If no test credentials are available, the probe degrades to a documented-shape fixture
  transcribed from Razorpay's published docs, clearly labelled as such in the fixture
  file. Blocking Phase 1 on credentials would be the failure this ADR exists to prevent.
- The Day-2 live adapter is unchanged: still P0, still 2-hour timebox, still first to cut.

---

## ADR-007 — The `fee` / `tax` relationship is derived from data, not assumed

**Date:** 2026-09-02 · **Phase:** 1 (shape probe)

**Context.** The shape probe (ADR-006) surfaced a genuine ambiguity in Razorpay's own
published material, on the single number this entire product depends on.

Razorpay's settlement recon documentation states the two fields are separate:
> *"The `fees` field shows the fees charged to process the transaction, while the `tax`
> field shows the tax on the fee charged."*

and gives the settlement formula as:
> `Net = Gross − MDR − GST on MDR − refunds − chargebacks`

Read literally, `credit = amount − fee − tax`.

But the documented example response on the fetch-recon page does not follow that:

```json
"amount": 100000, "fee": 2900, "tax": 0, "credit": 97100
```

Here `credit = amount − fee` exactly, with `tax` zero. If `fee` were MDR-only at 2%, it
would be 2000 with tax 360 — this shows 2900 with tax 0. So either that example's `fee`
is GST-inclusive with `tax` left unpopulated, or the example is illustrative rather than
real.

**Why this matters more than it looks.** Our four-line verdict has a line reading
*"Razorpay's cut + tax on it — matches your rate."* If the engine subtracts tax that was
already inside `fee`, every card transaction is wrong by the GST amount, in the merchant's
favour, and the residual "we can't explain" bucket absorbs the error silently. It would
look like a small rounding issue at 50 rows and like a real discrepancy at 5,000.

**Options considered.**
1. Assume `fee` is MDR-only and always subtract tax separately (follows the prose).
2. Assume `fee` is GST-inclusive and never subtract tax separately (follows the example).
3. **Derive it per batch** from the identity that must hold, and assert it.

**A third convention, at the settlement level (added 2026-09-03).** The ambiguity above
is on the *recon* endpoint. The settlement object itself does something different again:
both documented examples — `amount: 9973635` and `amount: 50000` — report `fees: 0` and
`tax: 0`, with the note that *"in case of a normal settlement, the fee charge will be 0."*

So a settlement-level `fee` of zero does **not** mean no fee was charged. It means the
fees were already netted off at the payment level and are itemised on the recon rows, not
re-stated on the settlement. An engine that read fees from the settlement object would
conclude a merchant paid nothing at all.

This strengthens the case for Option 3 rather than complicating it: there are at least
three conventions in play across two endpoints of one provider, so *any* assumed reading
is wrong somewhere. Deriving the relationship per batch and refusing an inconsistent one
is the only approach that survives all three. It also sharpens where we read fees from:
the recon rows, never the settlement envelope.

**Choice.** Option 3.

For every settled row, exactly one of these holds:
```
credit == amount - fee          →  fee is GST-inclusive  (tax is informational)
credit == amount - fee - tax    →  fee is MDR-only       (tax is additive)
```
The engine tests both on ingest, picks whichever is consistent across the batch, records
the verdict in the audit log, and **raises if neither holds or the batch is mixed**.

**Why.** This is a question the data answers unambiguously, so guessing is unnecessary. It
also converts a silent, systematic, GST-sized error into a loud failure at ingest time —
which is the behaviour `BEHAVIOR.md` demands everywhere else, applied to the place it
matters most. As a bonus, an engine that *detects* its counterparty's fee convention is a
stronger answer to "how do you know your fee math is right" than one that hardcodes it.

**Consequences.**
- `config` still holds the expected MDR rate card — that is what "does the fee *match your
  contract*" is checked against, a separate question from "how is the fee encoded."
- The derived convention is a field in the audit log, so any number on the verdict screen
  can be traced back to which convention produced it.
- Day-2 live API work has a concrete first task: confirm the convention against real
  test-mode data and pin it. Currently our answer comes from synthetic data we generate,
  so this remains **unverified against reality** until then — logged in `LIMITATIONS.md`.

---

## ADR-008 — Canonical schema follows Razorpay's real field names, including its oddities

**Date:** 2026-09-02 · **Phase:** 1 (shape probe)

**Context.** The probe found three places where the schema sketched in
`PROJECT-CONTEXT.md` §7 differs from Razorpay's actual recon response. Each would have
produced a silently broken engine.

| Sketched | Actually | Consequence if unfixed |
|---|---|---|
| `settlement.payment_id` identifies the payment | `payment_id` is **null** on `type: "payment"` rows; the id is in **`entity_id`** | Pass-1 join matches nothing. Every order reads as `MISSING`. |
| `refund_adjustment` is a column on the settlement row | Refunds are **their own rows**, discriminated by `type` (`payment`/`refund`/`transfer`/`adjustment`) | Refund logic looks for a column that never exists; one-sided-refund defect undetectable. |
| `gross · fee · tax_on_fee` all subtract | `debit`/`credit` are the settled movement; `amount` is the transaction | See ADR-007. |

**Choice.** Adopt Razorpay's field names and semantics verbatim in the canonical schema —
`entity_id`, `type`, `debit`, `credit`, `settlement_utr`, `settled_at` — rather than a
tidier invented schema mapped at the boundary.

**Why.** The whole point of the two-source design is that swapping seeded data for live
API data should be a *source* change, not a *schema* change. Every renaming is a place
where the swap can silently mismatch on Day 2, under a 2-hour timebox, which is precisely
when there is no time to debug it. Razorpay's naming is also what a judge will recognise,
and what the audit trail must cite for "every number traces back to a Razorpay record" to
be literally true.

**Consequences.**
- The join chain is corrected to:
  `ledger.order_id → recon.order_id → recon.entity_id (= payment id) → settlement_utr → bank.utr`
- The generator must emit `type`-discriminated rows, including refund rows, not a
  refund column. This makes the one-sided-refund defect realistic rather than a toy.
- `PROJECT-CONTEXT.md` §7's schema sketch is superseded on these three points. The
  document is left unedited as the original brief; this ADR is the amendment.

---

## ADR-009 — GST is computed on the rounded MDR, half-up, and the policy is config

**Date:** 2026-09-02 · **Phase:** 1a

**Context.** GST-on-MDR is a percentage of a percentage, so it produces fractional paise
constantly. ₹10,000 at 2% is a clean ₹200 → ₹36. ₹333 at 2% is ₹6.66 → GST ₹1.1988.
Something must round, and where the rounding happens changes the answer.

**Options considered.**
1. Round only at the end — compute GST against the unrounded MDR, round the total once.
   Fewest rounding operations, smallest theoretical error.
2. Round at each step — round MDR to whole paise, then compute GST on the *rounded* MDR.
3. Don't round; carry fractional paise through the engine.

**Choice.** Option 2, half-up, with both the mode and the step-vs-end behaviour exposed as
config (`rounding.mode`, `rounding.gst_on_rounded_mdr`).

**Why.** The product promise is *"every number traces back to a Razorpay record"* and the
`[detail]` view shows an MDR line and a GST line separately. Under option 1 those two
lines do not independently reconcile: a merchant who takes the displayed MDR and computes
18% of it gets a different number from the one displayed, because our GST came from an
unrounded intermediate they never saw. That makes our own proof unverifiable by hand,
which defeats the point of showing it.

Option 3 is rejected outright: fractional paise cannot be compared to Razorpay's integer
paise fields without rounding somewhere, so it moves the decision rather than removing it.

Half-up over banker's rounding because it is the common commercial convention in Indian
payments and is what a merchant checking by hand will expect. Banker's rounding is
available as `half_even` for the same reason the whole thing is config.

**Consequences.**
- Both fee lines in `[detail]` are independently checkable by a merchant with a
  calculator. This is a UI-honesty property enforced by an arithmetic decision.
- The alternative is one config flag away, so if live data shows Razorpay rounds
  differently, matching them is a config change, not a code change.
- The engine's own rounding is bounded at one paise per line, well inside the
  `rounding_paise: 1` tolerance — so our rounding can never manufacture a spurious
  `ROUNDING` classification.

---

## ADR-010 — Rates are integer basis points, never float percentages

**Date:** 2026-09-02 · **Phase:** 1a

**Context.** ADR-003 established money as integer paise. Rates were still open: a 2% MDR
could be stored as `0.02`, as `2.0`, or as `200` basis points.

**Choice.** Integer basis points (1 bps = 0.01%) throughout config, code and audit log.

**Why.** ADR-003 removes floats from money but a float *rate* reintroduces them at the
multiplication: `amount_paise * 0.02` is a float operation whose result must then be
coerced back to int, and `0.02` is not exactly representable in binary. With integer bps
the calculation is `amount * bps / 10000` — integer times integer, with a single division
whose rounding boundary is explicit and controlled by ADR-009.

The practical consequence is that **no float ever touches a money value anywhere in the
engine.** That is a property that can be stated flatly and defended, rather than a
convention that mostly holds.

**Consequences.**
- The rate card reads `mdr_bps: 200` rather than `2%`. Slightly less readable, so every
  entry carries a comment with the percentage.
- `apply_bps()` is the single chokepoint for rate application, so the rounding policy has
  exactly one implementation.
- Float is permitted in exactly one place: payment-mix proportions in the generator, which
  are population weights and never produce a money value. The loader validates they sum to
  1.0 with a float tolerance; this is called out in the code so it is not mistaken for a
  money tolerance.

---

## ADR-011 — Subscriptions is not enabled on the test account; the demo does not depend on it

**Date:** 2026-09-02 · **Phase:** 1a (live probe)

**Context.** The live probe reached Razorpay test mode successfully. `/v1/payments`,
`/v1/orders`, `/v1/settlements`, `/v1/customers`, `/v1/invoices` and
`/v1/settlements/recon/combined` all return `200`. But:

```
GET /v1/subscriptions  → 401 {"error":"Unauthorized"}
GET /v1/plans          → 401 {"error":"Unauthorized"}
```

Independently reproduced with `curl` using the same key that returns `200` elsewhere, so
this is **not** an authentication failure. The Subscriptions product is not enabled on
this account — it requires separate activation on the Razorpay dashboard.

**Why this matters more than a missing endpoint.** The `halted` subscription cluster is
the demo centrepiece. Six subscriptions dying silently is the "one thing needs you this
week" line, and the entire correlation claim is illustrated through it.

**Choice.** Nothing changes. The demo continues to run on seeded data, and this is
recorded as an open item rather than a blocker.

**Why this is not a crisis.**
1. The track bar explicitly permits synthetic data — *"close one finance-ops loop across a
   50+ record batch of synthetic data."* Seeded data was always the demo path (ADR-006);
   the live API was always verification.
2. The `halted` lifecycle is *documented* Razorpay behaviour. We are not inventing a state;
   we are modelling a published one. The subscription entity shape in our fixture comes
   from Razorpay's own documentation.
3. The account is empty anyway. Even with Subscriptions enabled, there would be zero
   subscriptions to capture until some were created and deliberately failed.

**Consequences.**
- `LIMITATIONS.md` carries this as a stated limitation: our subscription shape is
  documented-derived, not live-verified. Said plainly, this is stronger than silence.
- If Subscriptions is enabled later, the path to closing it is known: enable on the
  dashboard, create a plan and subscription, use the test-charge option to force the
  `failed → pending → halted` arc, then re-run `finctl probe --live`. Note the 3-day
  test-token validity constraint — do not build the demo on an old token.
- This does not consume the Day-2 API timebox. That budget is for the settlement/payment
  adapter, which works.

---

## ADR-012 — ADR-007 may be unanswerable in test mode, and that is now a tripwire not a hope

**Date:** 2026-09-02 · **Phase:** 1a (live probe)

**Context.** The live probe was expected to settle ADR-007 — whether `fee` is GST-inclusive
or MDR-only. It could not, for a reason worth distinguishing carefully:

**Not** "the data was ambiguous." **The account has never processed a payment.**
`/v1/settlements/recon/combined` returns `200` with `count: 0` for every month tried. There
are zero settled rows, not zero-tax rows.

A further constraint surfaced: test-mode settlements are not reliably generated on the
usual T+2 schedule, so even creating and capturing a test payment may not produce a settled
recon row. **ADR-007 may not be answerable in test mode at all.**

**Choice.** Keep the derive-from-data mechanism exactly as built, and convert the open
question from a note someone must remember into a **test that fails when it becomes
answerable**.

`test_live_recon_capture_has_no_rows_to_settle_adr_007` asserts the live capture is empty.
The moment any capture lands real rows, that test fails — which is the prompt to re-run the
convention analysis and close the ADR.

**Why.** An unresolved assumption tracked only in prose gets forgotten under time pressure,
which is exactly when it matters. A failing test cannot be forgotten. This is the same
device used for the original `UNDETERMINED` assertion: a test designed to break on new
information.

**Consequences.**
- The engine's behaviour is unchanged and correct: it derives the convention per batch and
  raises on inconsistency. What is unverified is only whether Razorpay's real data matches
  either identity — not whether our detection works, which is tested directly.
- The honest answer to *"how do you know your fee math is right?"* remains: **the engine
  detects the convention rather than assuming one, and refuses a batch where the identity
  fails. We could not confirm against live data because the test account has no
  settlements, and we say so rather than implying we checked.**
- This is a genuinely good failure-recovery artefact for criterion 4: a real limitation,
  found by real investigation, with a mechanism that closes it automatically.

---

## ADR-013 — The generator computes fees with the engine's own fee code

**Date:** 2026-09-02 · **Phase:** 1b

**Context.** The generator must produce settlement rows whose fees the classifier will
later check. There are two ways to arrange that.

**Options considered.**
1. Give the generator its own independent fee implementation, so generator and engine are
   genuinely separate and agreement means something.
2. Have the generator call `expected_fee()` — the same function the classifier uses — to
   model a *correct* Razorpay, and introduce defects by explicitly perturbing that
   correct baseline.

**Choice.** Option 2.

**Why, despite it looking circular.** Option 1 sounds more rigorous and is worse. Two
independent implementations of GST-on-MDR written by the same author on the same day will
share the same misunderstanding, and the batch will reconcile perfectly while both are
wrong — a green suite proving nothing. Worse, any *innocent* difference between the two
implementations (a rounding mode, a tie-break) shows up as a phantom defect the classifier
must then be taught to ignore, which trains the engine to tolerate real errors.

Under option 2, the generator's baseline is correct *by construction*, and a defect is the
deliberate, recorded difference from it. What the classifier is tested on is not "can it
recompute a fee" but "can it detect a known perturbation" — which is the actual job.

The correctness of `expected_fee()` itself is established separately, by
`tests/test_fees.py`, against the worked example from the brief and against arithmetic
identities. That is where fee correctness is proven; the generator is not the place.

**Consequences.**
- The `clean` defect profile is a self-check: with nothing planted, every generated fee
  must equal the contracted fee exactly. Asserted by test.
- A bug in `expected_fee()` would make generator and classifier agree wrongly. Mitigated
  by `test_fees.py` testing it against external truth (the brief's worked example), not
  against the generator.

---

## ADR-014 — The generator can emit either fee convention, and both are tested

**Date:** 2026-09-02 · **Phase:** 1b

**Context.** ADR-007 established that we do not know whether Razorpay's `fee` field is
GST-inclusive or MDR-only, and ADR-012 established we may not find out in test mode. The
generator nevertheless has to write *some* value into `fee` and `credit`.

**The trap.** Picking one convention silently would mean the engine's detector only ever
sees the convention we chose. It would pass, always, while proving nothing — the detector
and the generator agreeing because they were written by the same person on the same
assumption.

**Choice.** `fee_convention` is an explicit generator parameter (`gst_inclusive` |
`mdr_only`), defaulting to `gst_inclusive`, and **both are tested**:

```
gst_inclusive -> fee already contains GST, credit = amount - fee
mdr_only      -> fee is MDR alone,        credit = amount - fee - tax
```

**Why.** This converts an unresolved external question into a tested internal capability.
We still do not know what Razorpay does — but we can now say, with tests, that **the engine
handles either answer and detects which one it is looking at**. The open question stops
being a risk to correctness and becomes a fact to be discovered.

**Consequences.**
- Two tests assert the detector correctly identifies each convention with zero
  inconsistent rows. Neither can pass by accident, since they demand opposite verdicts.
- When ADR-007 is finally answered by live data, the change is a default value, not a
  redesign.
- Honest framing for a judge: *"we found an ambiguity in Razorpay's own documentation,
  built the engine to detect which convention a batch uses rather than assume, and tested
  it against both."*

---

## ADR-015 — Matching is identifier-only; no fuzzy matching, ever

**Date:** 2026-09-02 · **Phase:** 1c-i

**Context.** Reconciliation tools commonly fall back to fuzzy matching when an identifier
join fails: same amount, same day, close enough — match it with a confidence score. It
raises the headline match rate substantially, which is the number everyone reports.

**Choice.** Identifier joins only. If `order_id` does not join, the order is unmatched.
No amount proximity, no date windows, no scores.

**Why.** A fuzzy match is a guess wearing a number. Two ₹4,999 orders on the same Friday
are indistinguishable on amount and date, and matching the wrong one produces a
reconciliation that is *confidently* wrong — every total balances, the match rate looks
excellent, and one customer's payment has been attributed to another's order. A merchant
cannot detect that from the output. An honest unmatched row can be investigated; a
confident wrong match cannot, because nothing signals that it needs investigating.

This costs us headline match rate, and that is the correct trade. The product promise is
*"every number traces back to a Razorpay record"* — a probabilistic match does not trace
to a record, it traces to a heuristic.

**Consequences.**
- Our reported match rate is directly comparable to the Terra Insight baseline only with
  this caveat stated: ours is an exact-identifier rate, which is a stricter measure.
- Unmatched rows flow to `correlate`, which resolves them using the *identifier chain*
  into payments and subscriptions — still a join, still deterministic. The differentiator
  recovers what fuzzy matching would have guessed at, but with evidence.
- Asserted by test: same amount, same day, different order id must not match.

---

## ADR-016 — Empty batches report a 0% match rate, not 100%

**Date:** 2026-09-02 · **Phase:** 1c-i

**Context.** `matched / total` is undefined when total is zero. The convenient answer is
1.0 ("nothing failed"), which renders as a perfect green 100% on a demo screen.

**Choice.** Return 0.0, and let the surrounding output say there was nothing to match.

**Why.** An empty batch has not achieved a perfect reconciliation; it has said nothing. A
100% on an empty batch is exactly the kind of number that reads well on a slide and is a
lie — and it is a *silent* lie, because an empty upload looks identical to a clean one in
the summary. This is the same instinct as ADR-004: a metric that can be accidentally
flattering is worse than no metric.

**Consequences.**
- The adversarial "empty batch" case from `build-spec.md` §6e produces `0.0` and a zero
  gap, asserted by test.
- Any UI rendering a match rate must distinguish "0% of 0" from "0% of 200". The summary
  carries `total` alongside `match_rate` for exactly this reason.

---

## ADR-017 — Scoring distinguishes "missed" from "below tolerance"

**Date:** 2026-09-02 · **Phase:** 1c-ii

**Context.** Scoring the engine against ground truth revealed that the engine and the
generator can legitimately disagree about what counts as a defect. The generator plants
timing lags of 1–2 working days. `tolerances.yaml` sets `grace_days: 1`, so a one-day lag
is *within tolerance* and deliberately not flagged.

Naively, that reads as 13 of 20 timing defects missed — a 35% recall on timing.

**Options considered.**
1. Count them as misses. Honest-looking, but wrong: it reports the tolerance working
   correctly as an engine failure, and would push us to remove a tolerance that exists
   for a good reason.
2. Count them as caught. Flattering and wrong in the other direction.
3. Give them their own category and report all three numbers.

**Choice.** Option 3: `caught` / `missed` / `below_tolerance`, with recall computed over
`caught + missed` only.

**Why.** Both collapses misrepresent the engine, in opposite directions. The third
category is the only one that describes what actually happened: the defect was planted,
the engine did not flag it, and *config says it should not have*. A judge reading
"13 below tolerance" alongside `grace_days: 1` can verify that judgement themselves —
which is the whole point of reporting it rather than smoothing it away.

**Consequences.**
- Recall is computed over defects the engine was genuinely expected to find.
- `below_tolerance` is printed on the checkpoint screen with an explanatory footnote,
  never silently dropped.
- Currently only timing has a tolerance large enough to swallow a whole defect; fee and
  amount tolerances are one paise. If that changes, `_is_below_tolerance` needs the new
  case, and its absence would show up as a sudden drop in recall rather than silently.

---

## ADR-018 — False positives are tracked separately, and matter more than misses

**Date:** 2026-09-02 · **Phase:** 1c-ii

**Context.** Recall alone is a one-sided metric. An engine that classified *every* order
as a problem would score 100% recall.

**Choice.** The score report counts false positives — orders flagged with a problem
classification that were never planted as defects — and reports them separately, never
folded into a single accuracy figure.

**Why they matter more than misses.** A miss is a gap in coverage: the merchant does not
learn about something. A false positive is the engine *telling a merchant something
untrue* — chase this customer, question this fee, investigate this order. Acting on it
costs real time and can damage a customer relationship. Worse, it erodes the one thing
that makes the tool useful: that its short list is worth reading.

This is the same reasoning as ADR-015's refusal of fuzzy matching. An honest gap can be
investigated; a confident wrong answer cannot, because nothing signals it needs checking.

**Consequences.**
- `test_no_false_positives` is asserted on every archetype, not just the demo batch.
- Currently zero across all tested configurations. That will be re-checked on test day
  against the deliberately planted decoy, where a false positive is the *expected*
  finding and the point of the exercise.

---

## ADR-019 — Correlation requires the identifier join to land, not to resemble

**Date:** 2026-09-02 · **Phase:** 1c-ii

**Context.** Correlation resolves an unexplained gap by looking up the payment and
subscription behind it. The tempting shortcut is to treat a *failed subscription payment*
as evidence of a halted subscription — they co-occur constantly, and it would raise the
resolution rate.

**Choice.** Two conditions must BOTH hold before claiming `HALTED_SUBSCRIPTION`: the
payment must carry a `subscription_id` that resolves to a real subscription record, AND
that subscription's status must literally be `halted`. Anything less is
`PAYMENT_FAILED` — still resolved, still useful, but a different and truthful claim.

**Why.** A failed payment on an *active* subscription is a normal retryable failure, not
silent revenue death. Claiming otherwise tells the merchant to chase a customer whose
subscription is working fine. And a dangling `subscription_id` must never borrow a
different subscription's halted status — the join either lands on that specific record or
it does not.

**Consequences.**
- Three refusal tests, asserted: active subscription not claimed as halted; unresolvable
  subscription id not attributed elsewhere; successful payment does not explain a gap.
- Correlation also never overrides arithmetic proof — a `FEE` finding is proven by
  arithmetic and correlation leaves it alone. Correlation adds evidence where there was
  none; it does not relabel what is already explained.
- This is the false-attribution guard that Day 3 will attack deliberately. Building it
  now means the test-day exercise measures a real defence rather than its absence.

---

## ADR-020 — Materiality is a config policy, and REFUND is benign

**Date:** 2026-09-02 · **Phase:** 2a

**Context.** The ranker's first run put `REFUND` in the actionable list, because it was
in neither config list and fell through to the ₹100 amount threshold. ₹23,628 of
one-sided refunds became "needs you this week", pushing actionable above benign and
diluting the headline.

**Choice.** Every classification is explicitly listed as benign or actionable in
`tolerances.yaml`. `REFUND` and `DUPLICATE` are benign; `PAYMENT_FAILED`, `UNEXPLAINED`
and `UNEXPECTED_SETTLEMENT` join the actionable list.

**Why.** The test is *"does a human need to DO something this week?"*, not *"is this a
discrepancy?"*. Everything on the verdict screen is a discrepancy — that is what the
screen is. A one-sided refund is a bookkeeping divergence to reconcile at month end; a
halted subscription is revenue dying now. Both are real, only one is an action.

The fall-through threshold is a poor default for this question because it re-introduces
size as the deciding factor, which ADR-scale reasoning already rejected: recoverability
decides, size only orders.

**Consequences.**
- After the change, benign ₹54,732 exceeds actionable ₹44,689 — the screen reads
  "mostly fine, one thing to do", which is the intended shape.
- A typo in these config lists would silently fall through to the threshold, so the
  loader now validates every name against the `Classification` enum and raises at load.
  Found while writing the ranker, fixed there rather than left as a trap.

---

## ADR-021 — The verdict is server-rendered; only drill-downs fetch on the client

**Date:** 2026-09-02 · **Phase:** 2a

**Context.** The verdict screen was first written as a client component fetching in
`useEffect`. It worked, but the initial HTML contained no numbers — they appeared a
moment after load.

**Choice.** The page is a server component that awaits `api.verdict()` and passes the
data in. Drill-downs stay client-side.

**Why.** The product promise is a two-minute Monday glance, and this gets demoed live on
a projector. Numbers that flash in after a beat read as slow regardless of how fast the
engine is — and the engine runs in ~10ms, so there is no reason to pay a round trip
after paint. Verified by checking the rendered HTML actually contains
`₹10,51,081.00` rather than trusting that it would.

Drill-downs remain client-fetched because they are genuinely on demand: fetching every
classification's findings up front would move real work to the initial load for content
most viewers never open.

**Consequences.**
- `export const dynamic = "force-dynamic"` — the verdict must not be baked at build time,
  since the batch changes when data is regenerated.
- The API being down now renders a server-side error message naming the fix
  (`npm run api`) rather than an empty page with a console error.

---

## ADR-022 — The audit log summarises reconciled rows, and only those

**Date:** 2026-09-02 · **Phase:** 2b

**Context.** `BEHAVIOR.md` says the audit stage *"refuses to summarise"* — the log is raw
and complete. But a 5,000-row batch is ~95% `RECONCILED`, and emitting one event per
correctly-settled order produces a log that is almost entirely noise, in which the ~250
interesting events are unfindable.

**Choice.** Every non-`RECONCILED` finding gets its own event with full proof.
`RECONCILED` rows are collapsed into a single `reconciled_summary` event carrying the
count.

**Why this does not violate the contract.** The refusal to summarise protects
*decisions* — which rule fired, on which row, with which numbers. A `RECONCILED` row is
the absence of a decision: no rule fired, nothing was judged, the money simply arrived as
expected. Its per-row detail adds nothing that the count does not.

The test that keeps this honest is `test_verdict_totals_are_reconstructible_from_the_log`:
every figure on the verdict screen must be recomputable from the log alone. The count
preserves that property; enumerating the rows would not improve it.

**Consequences.**
- A 5,000-row batch produces well under 5,000 events, asserted by test.
- If a `RECONCILED` row is ever disputed, the source data is still on disk and the
  matcher is deterministic — re-running reproduces it exactly.
- If the engine ever makes a *decision* about a reconciled row, that decision must be
  logged individually. The exemption is for the absence of a decision, not for a class
  of row.

---

## ADR-023 — Verdict, correlation and audit are one page, not three routes (superseded)

**Date:** 2026-09-02 · **Phase:** 2b · **Superseded:** 2026-09-05, by the dashboard
rebuild in `57cdeff` (see the addendum below).

**Context.** The brief describes four screens: verdict, detail, correlation, audit. The
obvious implementation is four routes with navigation between them.

**Choice (original).** One page with three progressively deeper sections; detail expands
inline.

**Why (original).** The demo is a two-minute story told by scrolling, not a feature tour
navigated by clicking. Every navigation is a moment where the presenter has to explain
where they are going and the audience has to reorient — and in a 2-minute slot, three of
those is a meaningful fraction of the time.

The layering is also the argument. Verdict is what a merchant reads on Monday;
correlation is the measured claim; audit is how anyone checks it. Stacked, that ordering
is visible in a single scroll. Split across routes, the relationship has to be asserted
verbally.

**Consequences (original, no longer current).**
- The audit section is collapsed by default and fetches on demand — it is the one view
  nobody opens on a normal Monday, so paying for it on every page load would be
  backwards.
- Verdict and correlation are fetched together server-side, so the initial HTML carries
  both. Two sequential round trips would have been visible.
- If the audit view grows enough to need its own filtering and pagination UI, it earns a
  route. It has not yet.

**Addendum — superseded by the dashboard rebuild.** The single-scroll layout was rebuilt
into a 12-route dashboard (`web/app/(dashboard)/`) alongside deploy prep and demo docs.
The scrolling-story argument above didn't survive contact with the rest of the brief:
runs list, a run wizard, rules, settings, and per-order trace views don't compress into
one scroll without becoming a very long page, and a route per concern reads as more
finished for a submission judges click through on their own rather than watch presented.
Audit, correlation, and the order trace are now dedicated routes (`/audit/[batch]`,
`/analysis/[batch]`, `/orders/[batch]/[orderId]`) rather than inline sections. See the
route table in the README for the current shape. This ADR is kept for the record of why
the single-page layout was chosen originally; treat its "Choice" and "Consequences" as
historical, not current.

---

## ADR-024 — The verdict is built from a gap decomposition, not a sum of findings

**Date:** 2026-09-02 · **Phase:** 2b (bug fix)

**Context.** The user looked at the verdict screen and asked how ₹30,501 + ₹603 +
₹23,628 + ₹27,208 + ₹17,481 could describe a ₹38,372 gap. They were right: the lines
summed to **₹99,421.65** against a **₹38,372.30** gap — a ₹61,049.35 error, on the
screen that *is* the product.

**Root cause.** The ranker built the verdict by summing `Finding.amount_paise` per
classification. But that field is not a contribution to the gap. It means something
different for each classification:

| Classification | What `amount_paise` meant | What the gap needed |
|---|---|---|
| `FEE` | the **overcharge** vs the rate card (₹603) | the **whole fee kept** (₹17,311) |
| `TIMING` | the whole order (₹30,501) | **₹0** — that money already arrived |
| `REFUND` | the magnitude (₹23,628) | **−₹23,628** — it narrows the gap |
| `HALTED_SUBSCRIPTION` | the whole order (₹27,208) | ₹27,208 ✓ |

Only one of four was right. Three distinct bugs wearing one symptom:

1. **Double-counting arrived money.** `TIMING` counted orders that settled *late but had
   arrived*. That money is inside `received`, so counting it again inflated the gap.
2. **A sign error.** A one-sided refund means the merchant wrote their books down while
   Razorpay settled in full — the bank received **more** than expected. It narrows the
   gap. Reporting its magnitude as positive was a ₹47,256 swing.
3. **The wrong fee number.** The gap contains every rupee Razorpay kept, not just the
   excess over the contracted rate. Whether the *rate* is correct is a separate question,
   answered in the drill-down.

**Choice.** A new module, `finctl/gap.py`, computes a **signed decomposition** directly
from the matched data. Findings still supply counts, copy and drill-down proof; they no
longer supply amounts. The identity

```
gap = fees_kept + never_arrived + in_flight − settled_above_ledger + residual
```

is asserted on **every run** by `GapDecomposition.check()`, which raises rather than
logging.

**Why this class of bug survived 345 tests.** Every individual number was correct and
independently tested. Fees were right, correlation was right, the match rate was right,
the gap was right. What no test asserted was that the lines **add up to the thing they
claim to explain** — the relationship *between* correct numbers. A composition bug is
invisible to component tests by construction.

`test_gap.py` now asserts the identity across every defect profile, archetype, payment
mix, settlement cycle and volume tier, plus one named test per original bug so a
regression says which one returned.

**Consequences.**
- `residual_paise` is **computed**, not assumed. If a future change breaks the identity,
  the residual becomes non-zero and appears on screen as "we can't explain" — the
  failure surfaces as honesty rather than as a silent rebalance.
- Negative lines are now possible and are rendered explicitly: green, with "narrows the
  gap", because a minus sign alone on a money screen reads as an error.
- The screen shows the balancing total. It is not decoration — it is the claim, and the
  claim was wrong once.
- The `Ranker.rank()` signature changed to take `MatchResult` rather than loose totals,
  because the decomposition needs the matched rows and passing pre-summed figures is what
  allowed the composition to drift in the first place.

**The wider lesson.** *"Every number traces back to a Razorpay record"* was true. It was
not sufficient. Individually traceable numbers can still be assembled into a false
statement, and the assembly needs its own invariant. Caught by a human reading the
screen, which is the one test that was missing.

---

## ADR-025 — Duplicated ledger rows are phantom expectation, not duplicated settlement

**Date:** 2026-09-02 · **Phase:** composition audit

**Context.** Duplicating five ledger rows produced a **₹7,305.71 residual** — money the
decomposition could not attribute. Found by running the adversarial cases from
`build-spec.md` §6e against the balance invariant, not by reasoning about the code.

**The mechanism.** A duplicated order is in the ledger twice, so `expected` counts it
twice — correctly, that is what the file says. But the matcher joins *each copy* to the
same settlement, so its fee and settled amount were also counted twice. One real sale,
two settlements' worth of arithmetic.

**Choice.** The first occurrence of an order is the real one and is processed normally.
Every copy after it becomes a `DUPLICATE` component carrying its ledger amount, and is
excluded from fee, settlement and refund arithmetic.

**Why that framing is the correct one.** The duplicate is not duplicated *money*, it is
duplicated *expectation*. Razorpay settled the sale once; the merchant's books claim it
twice. So the extra copy is a real contribution to the gap — the merchant is expecting
money that was never owed — and it belongs on the screen under its own name rather than
being netted away silently.

**Consequences.**
- `DUPLICATE` appears as a verdict line when it occurs, with the copies' order ids.
- Duplicating a ledger row no longer changes the `FEE` line, asserted by test.
- The merchant sees the problem is in *their own file*, which is actionable in a way
  "unexplained residual" is not.

---

## ADR-026 — Two empty sources are not duplicates of each other

**Date:** 2026-09-02 · **Phase:** composition audit

**Context.** The adversarial "empty batch" case raised `DuplicateBatchError` instead of
answering "nothing to reconcile". Two empty CSVs hash identically — they contain the same
nothing — so content-hash duplicate detection fired on them.

**Choice.** Duplicate detection is skipped for sources with zero rows.

**Why.** `BEHAVIOR.md` requires "nothing to reconcile" to be a *valid answer that survives
to the verdict stage*, not an exception. An empty ledger and an empty bank statement being
"identical" is a true statement about their bytes and a meaningless one about their
meaning — the check exists to catch the same file uploaded twice, and an empty file
carries no evidence of having been uploaded at all.

**Consequences.**
- An empty batch now produces a ₹0 gap, no lines, "Nothing needs you this week", and a
  **0%** match rate rather than a flattering 100% (ADR-016 still holds).
- Duplicate detection is unweakened for real data: any source with rows is still checked
  against every other.

---

## ADR-027 — Composition invariants are verified by mutation, not by passing

**Date:** 2026-09-02 · **Phase:** composition audit

**Context.** After ADR-024, the obvious risk was writing tests that assert the identity
and *pass* without being capable of failing — the same false confidence in a new place.

**Choice.** Every composition invariant was verified by deliberately reintroducing a bug
and confirming the suite catches it. Four mutations were run:

| Mutation | Caught by |
|---|---|
| Reintroduce the TIMING double-count | `test_no_order_appears_in_two_gap_components` |
| Flip the refund sign back to positive | the balance identity, all configurations |
| Understate the fee total by **₹1** | `test_fee_line_equals_the_fees_in_the_recon_file` |
| Off-by-one on a line count | `test_halted_count_matches_the_subscriptions_file` |

**Why.** A ₹1 error being caught is the meaningful result: it shows the assertions are
exact rather than approximate, so a real drift of any size surfaces.

The audit tests also deliberately **do not reuse the engine's aggregation helpers**. They
recompute from the rawest available source — parsing the ledger CSV by hand rather than
calling `parse_money`. Checking `matches.expected_paise` against `matches.expected_paise`
would prove only that a property is deterministic; two independent paths agreeing proves
something.

**Consequences.**
- 127 composition tests across 6 configurations, each verified capable of failing.
- The four mutations are documented here so the same checks can be re-run after any
  future change to the decomposition.

---

## ADR-028 — Rounding tolerance scales with the number of settlement legs

**Date:** 2026-09-03 · **Phase:** test day

**Context.** Generating the split-settlement case surfaced a fee "discrepancy" of
**₹0.02** on a ₹4,008 order split into two ₹2,004 legs. The engine was arithmetically
correct: fee is computed and rounded per leg, and two roundings of a half can differ from
one rounding of the whole.

**Choice.** `rounding_paise × number_of_settlement_legs`, not a flat tolerance.

**Why.** The engine was right that the numbers differed; the *tolerance* was wrong to
assume a single rounding boundary. Razorpay legitimately splits settlements, so a
merchant on a split order genuinely crosses two boundaries.

This is deliberately not a blanket loosening — it is exactly one paise per boundary the
counterparty actually crossed. A 3-paise error across two legs is still caught, asserted
by test. Widening the flat tolerance to 2 paise instead would have blinded the engine on
single-leg orders too, where no second boundary exists.

**Consequences.**
- The proof carries `settlement_legs` and `rounding_tolerance_paise`, so a merchant can
  see why a small difference was tolerated rather than having to trust it.
- Found on test day by generating an adversarial case, not by reasoning about the code.

---

## ADR-029 — The 50k bottleneck was in the scorer, and it is named

**Date:** 2026-09-03 · **Phase:** test day

**Context.** The first full matrix run showed throughput falling from ~64,000 rows/sec at
5,000 rows to **24,620 rows/sec at 50,000** — a 2.6× degradation. The build plan asks for
the bottleneck to be named honestly rather than hidden.

**What it actually was.** Profiling — rather than guessing — found `_is_below_tolerance`
in `finctl/score.py` doing a linear scan through all 50,000 order matches once per
planted timing defect: `O(defects × orders)`, 3.0s of a 7.7s run. The only super-linear
term measured anywhere in the pipeline.

**Choice.** Build the order index once and pass it in. 6.1s → 2.4s; 50k throughput went
from 24,620 to **63,369 rows/sec**, flat with every smaller tier.

**Two things worth stating precisely.**

1. **It was in the test harness, not the engine.** Scoring runs only when
   `ground_truth.json` exists, so no merchant would ever have executed that code. It
   nonetheless made our own published throughput number wrong — *in our favour*, which is
   the direction that matters. A benchmark that measures our scoring code and reports it
   as engine throughput is a misleading claim even when unintentional.
2. **The fix was an index, not an optimisation pass.** No algorithm changed, nothing was
   made cleverer. A dict replaced a scan.

**Consequences.**
- Throughput is now essentially flat from 50 to 50,000 rows (55k–79k rows/sec). **We have
  not found the engine's breaking point at the scale this product targets**, which is a
  more honest statement than naming a bottleneck we no longer have.
- The next candidate if pushed further is memory: the whole batch is held in memory by
  design (flat files, no database). That is a stated architectural choice, not an
  oversight.
- The profiling result is recorded in `METRICS.md` including the *before* number, so the
  improvement is visible rather than the slow version being quietly discarded.

---

## ADR-030 — The settlement cycle is observed from the batch, not read from config

**Date:** 2026-09-03 · **Phase:** blind testing

**Context.** A blind test on a T+1 batch caught every defect except timing: **0 caught,
84 "below tolerance"**. The engine reported 100% recall and PASSED, because the scorer
correctly classified unflagged lags as within tolerance.

**The actual bug.** `_check_timing` computed the due date as
`add_working_days(captured, self.tol.cycle_days)` — the cycle from **config**, always 2,
regardless of what the batch in front of it had done. Measured across cycles on batches
with an *identical* lag distribution:

```
batch settled at T+1  ->    0 orders flagged late
batch settled at T+2  ->   15 orders flagged late
batch settled at T+7  ->  291 orders flagged late   (nearly every settled order)
```

Two opposite failures from one cause. A T+1 merchant is told nothing about late money; a
T+7 merchant would be told almost every order is late — technically true against a
contracted T+2, useless as advice, and indistinguishable from a broken engine.

My first diagnosis was wrong: I attributed it to `grace_days` swallowing short lags at
T+1. Measuring the lag distribution disproved that — it was identical at every cycle
(47 rows one day late, 37 rows two days late). The difference was entirely in the
*baseline*, not the lag.

**Choice.** `finctl/cycle.py` infers the cycle from the batch — the **mode** of
capture-to-settlement working days — and the classifier judges against that. Config
remains the contracted value, and a disagreement is reported rather than resolved
silently.

**Why the mode and not the mean.** The distribution is deliberately skewed: planted lags
and genuinely late settlements sit in the right tail. A mean drifts toward them, which is
backwards — the baseline should be *what normally happens*, so abnormal settlements stand
out against it.

**Why observed wins over configured.** "Late" is only meaningful relative to what actually
happens. A merchant moved from T+2 to T+1 without the config being updated should still
get correct timing analysis. The disagreement is logged (`settlement_cycle_disagrees_with_config`)
so it is never silent, and every TIMING proof carries `cycle_days` and `cycle_source`, so
a merchant disputing a call can see the baseline used.

**Guard against over-inference.** Fewer than 20 settled orders falls back to config. A
wrong inference from three orders would silently rebase every timing judgement, which is
worse than using a possibly-stale contract value.

**Why the matrix missed it.** The matrix ran T+1 twenty-two times at 100% recall. Recall
counts only planted defects, and the scorer correctly bucketed the unflagged ones as
"below tolerance" — a whole axis catching zero was invisible to it. **The blind test found
it because it forced attention onto a single unfamiliar configuration rather than an
aggregate.** A green aggregate can hide a systematically dead axis.

**Consequences.**
- T+1 and T+2 now detect identically on matching data (63/11 vs 63/11), where T+1
  previously caught 54 with 20 below tolerance.
- Fixing this exposed a latent bug in the audit scrubber: it called `k.lower()` on every
  dict key, so any integer-keyed dict — like the cycle distribution — crashed the audit
  log. Only string keys can name a credential, so only those are now checked.

---

## ADR-031 — Settlements for orders the ledger does not contain narrow the gap

**Date:** 2026-09-03 · **Phase:** blind testing (hand-edited)

**Context.** A hand-edited blind test — two ledger rows deleted with `sed` — left
**₹16,992.29** unaccounted for. The balance invariant caught it as a negative residual,
and the number was exactly the net credit of the two settlements whose ledger rows had
been removed.

**The gap in the decomposition.** `decompose()` handled orphan *bank rows* (a credit with
no settlement behind it) but not orphan *settlements* (money Razorpay settled for an order
the ledger has no record of). The matcher had been detecting them all along in
`unmatched_recon_orders`; the decomposition simply never consumed them.

**Why no generated case had found it.** Every planted defect either removes money or moves
it, and the generator writes the ledger **first**, deriving settlements from it. So no
synthetic batch could ever produce settled money with no ledger row behind it — the shape
was structurally unreachable by the generator, not merely unlikely.

That is precisely what hand-editing exists to reach. Three `sed` edits found a class of
bug that 22 matrix runs, 6 blind configurations and 500+ tests could not.

**Choice.** Orphan settlements become a negative `UNEXPECTED_SETTLEMENT` component: the
money reached the bank and sits inside `received`, but nothing in `expected` claims it, so
it narrows the gap.

**Consequences.**
- "Money in for an order you don't have" is now a verdict line a merchant can see, which
  is a real exception in its own right — unexplained money arriving is as notable as money
  missing, and it usually means a bookkeeping failure on the merchant's side.
- The user's other two edits were handled correctly with no change needed: an inflated
  ledger amount classified `UNEXPLAINED` at exactly ₹1,149.00, and **not** `REFUND` — the
  sign rule from ADR-024 holding in the opposite direction.

---

## ADR-032 — On a hand-edited batch, findings outside the answer key are not false positives

**Date:** 2026-09-03 · **Phase:** blind testing

**Context.** After the hand-edited run, `blind score` reported **1 false positive** and
`FAILED`. The "false positive" was the ₹1,149.00 shortfall the user had personally
introduced by editing an amount. The engine had caught it exactly, with the arithmetic
shown.

**The flaw.** The scorer defines a false positive as *"the engine flagged an order that
ground truth does not list as a defect."* On a generated batch that is right. On a
hand-edited batch it is exactly backwards: the human planted a defect the generator knew
nothing about, so the engine catching it is the whole point of the exercise — and the
scorer penalised it for succeeding.

**Choice.** `blind score` already verifies a SHA-256 receipt, so it knows whether the
batch was edited. When it was, findings outside the answer key are listed with their proof
under "not in the answer key — expected", and `PASSED` requires only zero **missed**
defects. On an untouched batch, false positives still fail the run.

**Why this is not weakening the test.** The strict rule is preserved wherever it is
meaningful. What changed is that the tool no longer reports a correct answer as a failure
in the one mode specifically designed to test unfamiliar defects. A scoring rule that
punishes the engine for finding a real problem would train us to avoid the most valuable
test we have.

**Consequences.**
- The unmatched findings are printed with their arithmetic, so the human can check them
  against the edits they actually made — which is the correct way to score a hand-edited
  run, by inspection rather than by a list the generator wrote.

---

## ADR-033 — A ledger amount of zero is a data-entry error, not a refund

**Date:** 2026-09-03 · **Phase:** blind testing (hand-edited, round 2)

**Context.** A hand-edited blind test set one ledger amount to `0.00` against a real
₹2,480 settlement. The engine classified it `REFUND`, on the correct general rule that
settlement-exceeding-ledger is the shape a one-sided refund makes (ADR-024).

**Why that is wrong here.** The merchant did not record a refund. They recorded the sale
as worth **nothing**, while Razorpay settled real money for it. Reporting that as a refund
tells a merchant they refunded a customer they never refunded — a **false statement**,
which is strictly worse than an unexplained one. An honest "we can't explain this" can be
investigated; a confident wrong explanation cannot, because nothing signals it needs
checking. Same reasoning as ADR-015's refusal of fuzzy matching.

**Choice.** A zero ledger amount against a non-zero settlement classifies `UNEXPLAINED`,
with an interpretation naming it as a probable data-entry error.

**Why no generated case found it.** The generator draws ticket sizes from an archetype's
configured range, whose minimum is ₹299. A zero-value order is not merely unlikely there,
it is **unreachable** — so this branch had never once executed in 22 matrix runs, 8 blind
configurations, or 500+ tests.

**A dead branch removed on the way.** I also added a guard for "the difference exceeds the
settled amount, so it cannot be a partial refund." Writing the test proved it
**unreachable**: with `gap = ledger − settled` and a non-negative ledger, `|gap|` can never
exceed `settled`. The only boundary case is zero, which the first check already handles.
Removed rather than kept as an untested branch — a guard that cannot fire is not
protection, it is a false suggestion that the case was considered and handled.

---

## ADR-034 — What the hand-edited rounds establish about coverage

**Date:** 2026-09-03 · **Phase:** blind testing

Two rounds of human edits found **two real bugs**, both structurally unreachable by the
generator:

| Edit | Bug found | Why generation could not reach it |
|---|---|---|
| Delete two ledger rows | Orphan settlements left ₹16,992.29 unaccounted (ADR-031) | The generator writes the ledger **first** and derives settlements from it, so settled money with no ledger row cannot occur |
| Set an amount to `0` | A zero ledger amount reported as `REFUND` (ADR-033) | Ticket sizes are drawn from an archetype range with a ₹299 minimum |

Three edits that found **nothing** are equally worth recording, because they are evidence
the design decisions they probe actually hold:

| Edit | Result |
|---|---|
| Rename `payment_method` → `Mode` | Resolved through the alias table; **every number byte-identical**; the mapping recorded in the audit trail (ADR-015: never positional) |
| Duplicate a ledger row | Correctly `DUPLICATE`, +₹2,244, phantom expectation widening the gap (ADR-025) |
| Inflate an amount | Correctly `UNEXPLAINED` at exactly the difference — **not** `REFUND` (ADR-024's sign rule, opposite direction) |

**The generalisable finding.** Both bugs were in the same place: a *shape* the generator
cannot produce, because the generator's own construction order forbids it. Synthetic data
tests the failure modes you imagined; it cannot test the ones your generator's structure
rules out. Only data from outside the generator reaches those.

This is the honest limit of every accuracy number in `METRICS.md`, and it is now
demonstrated rather than merely conceded.

---

## ADR-035 — Zero MDR is not a zero fee: UPI carries the platform fee

**Date:** 2026-09-03 · **Phase:** review

**Context.** The rate card shipped `upi: mdr_bps: 0`, and `config/loader.py` enforced it
— a non-zero UPI rate raised `ConfigError`. Both cited the same fact: UPI carries zero
MDR, mandated under Section 10A of the Payment and Settlement Systems Act 2007, in force
since January 2020.

The fact is true. The inference from it was wrong.

Zero MDR is a statement about **interchange** — what the network and issuing bank levy.
It is not a statement about what the merchant pays. Razorpay is a payment aggregator, not
a bank: it charges a **platform fee** for the rails, and its published pricing applies ~2%
+ 18% GST to standard bank-to-bank UPI *despite* the zero MDR. It is the platform fee, not
the MDR, that lands in the `fee` field of a settlement row.

So on a real UPI transaction the merchant sees ~2% deducted. The engine expected 0, and
would have reported a FEE discrepancy on **every UPI row of every real batch** — worst on
exactly the `upi_heavy` merchants the config layer was built to serve.

**Why 22 passing configurations did not catch it.** ADR-013 has the generator compute fees
with `expected_fee()` — the engine's own function. So the generator emitted zero-fee UPI
rows, the classifier expected zero-fee UPI rows, and they agreed. This is precisely the
failure mode ADR-013 accepted and `LIMITATIONS.md` names: *generator and classifier can be
wrong together, and the test suite cannot see it.* The 0-false-positive result across the
matrix was real, and structurally blind to this.

It is worth being exact about what the risk register got wrong. The row read "Hardcoded fee
rate wrong for UPI-heavy merchants → Mitigated by design, unverified," and the mitigation
was "rate card is config, config refuses a default MDR." That mitigation addressed the
*mechanism* — no hardcoded rate, no silent default — and the mechanism worked as designed.
The **value** it faithfully applied was wrong. A config layer guarantees a rate is easy to
change; it cannot make the shipped default correct. Worse, the loader's guard promoted the
wrong value from a default into an *invariant*, so the one place that might have caught it
instead enforced it.

**Decision.**
1. `upi.mdr_bps` is **200** — the platform fee. `mdr_component_bps: 0` records that the MDR
   component is genuinely zero, for explanation only; it never enters the arithmetic.
2. The loader guard is **inverted**: a UPI rate of *zero* now raises, since that is the
   error that silently flags every UPI row. A merchant genuinely paying nothing must say so
   deliberately.
3. `card_debit` moves 90 → 200. The RBI debit cap is real, but Razorpay's published card
   pricing is a flat 2%; the 90 bps was the same category error.
4. A new method `upi_rupay_credit` at **215** bps. A RuPay credit card paid through a UPI
   app is a credit-card transaction wearing a UPI mask, priced at 2.15% + GST. Two
   different rates can both arrive labelled `method: upi` (see LIMITATIONS.md).

**Consequences.** Four golden files were regenerated. Defect counts, volumes and method
mixes are byte-identical; only rupee amounts moved — fee/tax/credit on UPI rows, and
`timing_lag` impact, which is measured in settled rupees and so shifts when fees do. A
blind run on a 610-order `upi_heavy` batch passes with 0 missed and 0 false positives, with
`wrong_fee_rate` at 30/30 — that detector is now exercised against a non-zero baseline
rather than agreeing trivially at zero.

**What this says about the method.** The bug was not found by the test suite, the metrics
matrix, or the blind harness. It was found by reading a vendor's published pricing page.
Every layer of internal verification here shares one assumption set; checking against the
world outside it is a *different* activity, and the only one that could have caught this.
ADR-029 established that hand-edited data reaches failures the generator cannot invent.
This is the same lesson one level up: an external *fact* reaches errors that no amount of
internally-consistent data can.

---

## ADR-036 — `on_hold` is a classification, not an unexplained gap

**Date:** 2026-09-03 · **Phase:** review

**Context.** Razorpay's settlement recon schema carries two booleans we were reading past:
`on_hold` (the settlement for this payment is being withheld) and `settled`. We parsed
them into the staged batch and then ignored them.

The consequence is specific. When `on_hold` is true, the money is not late and not
missing — it is being withheld on purpose, usually for pending KYC, a risk review, or a
dispute. Our engine had no rule for it, so such an order fell through every money check
and landed in UNEXPLAINED. That is the worst available answer: the engine tells a merchant
*"we cannot account for this"* while the reason sits in a field it already parsed. Worse,
once the settlement cycle elapsed, `_check_timing` would eventually call it TIMING —
"on its way, it arrives on its own" — which is actively false. Held money does not arrive
on its own; waiting is precisely the wrong action.

**Decision.** Add `ON_HOLD` as a first-class classification.

1. `_check_on_hold` runs **before** `_check_timing`. Ordering is load-bearing: a held
   payment also looks late, and "late" is the wrong answer.
2. It is **not** in `BENIGN`. TIMING is benign because it resolves itself; a hold does not.
   It needs a human to open the Razorpay dashboard, so it belongs on the actionable list.
3. The verdict copy says so plainly: *"waiting will not release it."*
4. `gap.py` gets an `ON_HOLD` component. A held order is `matched` — a recon row exists —
   so it skips the "never reached settlement" branch, but its money never reaches the
   bank. Without its own component that money lands in the residual and the decomposition
   refuses to balance. It is booked at **net of fee**, since the fee is already counted in
   the FEE component.

**Generating it.** A classification with no data to exercise it is unverified, which is
the ADR-035 lesson applied. `payment_on_hold` is now a defect type: 2 in the `demo`
profile. The generator emits the recon row with `on_hold=true` and deliberately **excludes
it from settlement grouping** — no `settlement_id`, no UTR, no `settled_at`, and no bank
credit. A test asserts that inverse invariant directly, because a held row that acquired a
UTR would mean money appearing in the bank while the engine reported it withheld.

**Consequences.** Three golden files gained 2 defects each, with bank credit down by
exactly the held amount. On a 400-order `upi_heavy` demo batch, `payment_on_hold` scores
2 caught / 0 missed with 0 false positives and the gap still balances to ₹0.00.

**Cost.** `on_hold` narrows UNEXPLAINED, so the honest-residual number gets slightly
smaller for a reason that is not engine cleverness — it is reading a field we already had.
Worth stating plainly rather than claiming as an accuracy improvement.

---

## ADR-037 — An Excel serial date read as epoch seconds is a silent 1970

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** We obtained Razorpay's twelve official sample report files
(`razorpay-sample-files/`) to build the upload path against real headers rather than
imagined ones. The first thing they falsified was not a column name — it was a date.

`sample-settlements-recon-report.xlsx` carries this in the `entity_created_at` column:

| row | value |
|-----|-------|
| 1   | `44658.44689814815` |
| 2   | `29/06/2022 07:34:39` |

The **same column**, in the **same file**, in two formats. A spreadsheet stores a date as
a serial number and writes whichever representation the cell format dictates, so any real
export mixes them.

Our `_parse_timestamp` had this as its first branch:

```python
if text.isdigit():
    return datetime.fromtimestamp(int(text), tz=UTC)   # epoch seconds
```

`"44658"` is all digits. It parsed as 44,658 seconds after the Unix epoch:
**1970-01-01 12:24:18**. The correct answer is 2022-04-07.

This is the worst class of bug this project exists to prevent, and it was inside the
project. It does not raise. It does not look like corruption. It produces a *plausible
date*, and every downstream consumer trusts it:

- `_check_timing` compares captured-at against settled-at, so every affected order
  appears **~52 years late** — TIMING, the benign bucket, absorbing a real anomaly.
- `observe_cycle` derives the settlement cycle from those same dates, so one poisoned
  batch corrupts the cycle the *whole batch* is judged against.
- The verdict screen reports it as "money on its way", which is the one thing it is not.

The float form (`44658.44689814815`) was never silently wrong — it is not `.isdigit()`,
so it fell through to `fromisoformat` and raised. Only the bare-integer form was
dangerous. That is worth stating precisely: the bug needed a date whose time component
was exactly midnight to trigger, which is why no synthetic test found it. The generator
emits epoch seconds, so no batch it produced could reach this branch.

**Decision.** Parse Excel serial dates explicitly, and check that branch **before** epoch
seconds.

1. `EXCEL_EPOCH = 1899-12-30`. Not 1900-01-01: Excel wrongly treats 1900 as a leap year,
   and 1899-12-30 is the origin that makes modern dates come out right.
2. A bare number in `[20000, 80000]` is an Excel serial. That window is 1954-10-03 to
   2119-01-25 — wider than any settlement file, and **four orders of magnitude** away
   from the epoch-seconds encoding of the same dates (2020-01-01 is serial `43831` but
   epoch `1577836800`). The two interpretations are separated by a gap of ~10⁴, so this
   is a disjoint-range test, not a heuristic. A number outside the window still parses
   as epoch seconds, so the Razorpay API path is untouched.
3. A **fractional** number outside the serial window raises rather than being coerced.
   We can tell it is not epoch seconds (those are integers) and not a serial (out of
   range), which leaves no reading we can defend.
4. `datetime`/`date` objects pass through, because `openpyxl` hands back real datetimes
   for date-formatted cells and re-stringifying them to re-parse would be a second place
   to get this wrong.
5. Added `%d/%m/%Y %H:%M:%S` and siblings to the string formats — the other shape the
   real files use. Ordered longest-first so a datetime is not truncated to a bare date
   by an earlier partial match.

**Why a range test rather than "trust the file extension".** Tying the interpretation to
`.xlsx` would be wrong in both directions: a CSV exported *from* Excel carries serials
too, and an xlsx can hold epoch seconds in a text cell. The value's own magnitude is the
only honest evidence available.

**Consequences.** Six tests added, including a named regression for the 1970 case and one
asserting epoch seconds still resolve correctly. 553 tests green.

**Cost, stated plainly.** This is a bug found by obtaining real files, not by reasoning
about the code — the same lesson as ADR-031 and ADR-033, now for the third time. Every
prior accuracy figure was measured on generated data using epoch seconds, so **no
previously published metric is invalidated by this fix**; equally, none of them ever
exercised this path. The honest reading is that the metrics measured the engine against
the generator's idea of a date, and the first real file disagreed.

---

## ADR-038 — Read the recon discriminator through an accessor, not a key

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** ADR-008 committed to using Razorpay's own field names, including their
oddities, so that swapping seeded data for live data would be a **source** change rather
than a **schema** change. The stated reason was that every rename is a place the swap can
silently mismatch under time pressure.

Razorpay's actual settlement recon export names the row discriminator
**`transaction_entity`**. We wrote **`type`**.

The values agree exactly — `payment`, `refund` — so only the key drifted. The failure
mode is total and silent: `row.get("type")` on a real export returns `None`, no branch
matches, and **every recon row is dropped**. Each order then looks unmatched, and the
engine reports MISSING — "no PSP record at all" — for a batch where Razorpay recorded
everything.

No test could catch this. Both sides of every test used our spelling, so the generator
wrote `type` and the matcher read `type` and agreed with itself. This is the same class
of blind spot as ADR-031/033/037, in a different disguise: not a shape the generator
could not produce, but a **name only we used**.

**Decision.** Add `recon_type(row)` and `is_recon_type(row, ReconType.X)` to `schema.py`,
reading `transaction_entity` first and falling back to `type`. Replace all five direct
reads (`matcher.py` ×2, `gap.py` ×2, `probe.py` ×1).

1. **An accessor, not scattered `or` clauses.** A third spelling — and Razorpay's reports
   are not internally consistent, see the settlements report's blank leading column — is
   then a one-line change here rather than a hunt through call sites.
2. **`recon_type` returns the raw string, not a `ReconType`.** Coercing an unrecognised
   discriminator into a known member would silently reclassify a row we do not
   understand. An unknown value stays visible and matches nothing.
3. **Both spellings stay supported permanently.** The live API and our generator use
   `type`; the dashboard export uses `transaction_entity`. Neither is "wrong" — they are
   two real Razorpay surfaces, and the engine ingests both.

**Consequences.** Five tests added, using rows copied verbatim from
`sample-settlements-recon-report.xlsx` — including the reverse-refund row that the next
piece of work needs. Verified end to end: a `transaction_entity` row now matches, where
before it produced a false MISSING. 558 tests green.

**What this says about ADR-008.** The principle was right and we still drifted from it,
because there was no *check* that our field names matched Razorpay's — only an intention
to keep them aligned. The sample files are now that check. Naming a convention is not the
same as enforcing one.

---

## ADR-039 — A refund with no `order_id` is money leaving that nothing was watching

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** `LIMITATIONS.md` has carried this since Phase 1b:

> **Refunds are modelled as one-sided by omission.** The one-sided-refund defect is a
> refund the merchant recorded that never reaches settlement. The reverse case — a
> settlement refund the merchant never recorded — is not yet generated.

Razorpay's own sample recon export contains one. Row 10 of
`sample-settlements-recon-report.xlsx`:

```
transaction_entity : refund
entity_id          : rfnd_Jt7Bq2djxtuWo5
debit              : 1.0        credit : 0.0
settlement_id      : setl_JtAs2E7Uf55JMV
order_id           : (blank)
```

**The blank `order_id` is the whole finding.** Razorpay keys these rows by `rfnd_…`, and
nothing links them to a sale. Our matcher opened with:

```python
for row in recon:
    if not row.get("order_id"):
        continue          # <- the refund row dies here
```

For a *payment* that `continue` is right: a payment with no order cannot be attributed.
For a *refund* it was catastrophic and silent. Money genuinely left the merchant's bank
account, and **no stage of the engine ever saw the row**. Not classify, not correlate,
not the verdict. Reproduced before fixing: a ₹1,000 settlement-side refund on a batch
that the engine reported as `RECONCILED`.

This is the mirror of `UNEXPECTED_SETTLEMENT` (ADR-031) — that is money arriving for a
sale the merchant has no record of; this is money leaving for a refund they have no
record of. ADR-031's lesson was that the matcher had detected the orphans all along and
the decomposition never consumed them. Here the matcher did not even detect them.

**Decision.** Add `UNRECORDED_REFUND` as a first-class classification.

1. `MatchResult.unattributed_refunds` collects refund rows no ledger order claims —
   both those with a blank `order_id` and those naming an order the ledger lacks.
2. The classifier emits one finding per row, with `entity_id`, `arn`, `settled_at` and
   the `refund_notes` reason carried into the proof. A refund reason sitting in the row
   is exactly what the merchant needs to identify it in their dashboard.
3. **It is not `BENIGN`.** The merchant's books overstate their balance and nothing in
   their own records would ever reveal it.
4. **It gets its own gap component**, split out from `REFUND`. This is the subtle half.
   Both are debits of identical size and sign, so the arithmetic balances either way —
   but the verdict screen is built from components, and `REFUND` is a line a merchant
   reads and moves past. Folding them together meant the finding existed, scored as
   caught, and *still never reached the actionable list*. Correct arithmetic is not the
   same as a correct answer.

**Generating it.** Per ADR-004, a defect that cannot be scored does not get planted, and
per ADR-035/036 a classification with no data to exercise it is unverified. So
`unrecorded_refund` is a defect type: 3 in `demo`, rate-based in `scale`. The generated
row deliberately carries **no `order_id` and no `payment_id`** — the shape that broke us
— but it *does* carry `payment_method`, because Razorpay's real refund rows do
(`bank_transfer` in the sample). An earlier draft omitted it and produced a row shape
that does not occur in real data.

**Three latent bugs this surfaced.**

1. **`assigned` was not total.** Emission sites read `assigned[DefectType.X]` directly,
   so a profile omitting a defect raised `KeyError` rather than planting none of it. Now
   `{d: set() for d in DefectType.ALL}`.
2. **`demanded` was a hand-maintained tuple** that had drifted from `DefectType.ALL`.
   Adding the type to the enum *and* the profile still planted nothing, and ground truth
   would have been silent about a defect the profile asked for. Now derived from `ALL`.
3. **`DefectType.ALL`'s order is load-bearing** and nobody had said so. The generator
   slices a shuffled index range across it in sequence, so deriving `demanded` from `ALL`
   silently swapped `HALTED_SUBSCRIPTION` and `TIMING_LAG`, reassigning which orders got
   which defect and shifting every golden file by ~₹55,000 for no real reason. The tuple
   now preserves the historical order with a comment saying why, and new types are
   appended at the end. Verified by setting `count: 0` and confirming the goldens matched
   byte-for-byte — proof the code changes were behaviour-preserving and the remaining
   diff was only the three new defects consuming index slots.

**Consequences.** 8 tests added. Demo batch: 3 caught, 0 missed, 0 false positives, gap
residual ₹0.00. The actionable list grew from 3 lines to 5 — and the cap in
`test_rank.py` was raised deliberately rather than the feature trimmed to fit it, because
each addition moves money *out* of a silent bucket and onto a line with an owner.

**Cost, stated plainly.** Like ADR-036, this narrows the residual for a reason that is
not engine cleverness: it is reading rows we were throwing away. The `REFUND` line on
every prior demo was slightly overstated, since settlement-side refunds we now name
separately were previously either invisible or folded in.

---

## ADR-040 — Ground truth cannot be scored by `order_id` alone

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** `score.py` joined findings to planted defects on one key:

```python
found[f.order_id].add(f.classification)
...
assigned = found.get(defect.order_id or "", set())
```

Every defect the engine has ever been scored against had an `order_id`, so this held.
`UNRECORDED_REFUND` does not have one — Razorpay identifies those rows by `rfnd_…`
(ADR-039). The consequence is worse than a crash: the defect scored as **MISSED**
regardless of what the engine actually reported, because *the join key did not exist*.
The engine found all three, and the scorecard said it found none.

That is a measurement bug, and this project's central claim is a measurement.

**Decision.** Score on `entity_id` where there is no `order_id`.

1. A second index, `found_by_entity`, keyed on `finding.proof["entity_id"]`.
2. The order-keyed lookup is tried first; the entity key is a **fallback**, not a
   parallel path. Existing behaviour is untouched.
3. Ground truth records `entity_id` in `detail` for exactly this join.

**The general shape of the bug.** The scorer assumed every unit of work is an *order*.
That was true while every defect was something happening to a sale. It stopped being
true the moment a defect was something happening to a **settlement**, and settlement-
level entities — refunds, disputes, adjustments, transfers — are a large part of what
Razorpay's recon export actually contains. Disputes are next, and they carry
`dispute_id`, not `order_id`. This fallback is what makes that possible.

**Consequences.** `unrecorded_refund` scores 3 caught / 0 missed / 0 false positives.
The false-positive check still keys on `order_id`, which is correct: a false positive is
an order the engine flagged that was never planted, and order-less findings cannot be
false positives in that sense. Worth revisiting if a future defect type can be
*wrongly* attributed to an entity.

---

## ADR-041 — A chargeback is not a delay, and "it arrives on its own" is the worst answer

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** Razorpay's settlement recon export carries three columns we were reading
past: `dispute_id`, `dispute_created_at` and `dispute_reason` (confirmed against
`sample-settlements-recon-report.xlsx`; the generator had `dispute_id: None` as a
placeholder and nothing else). Razorpay's own settlement formula names them —
`Net = Gross − MDR − GST on MDR − refunds − chargebacks` (ADR-007) — so a disputed
payment was money the documentation told us to expect and the engine had no rule for.

Without a rule, a disputed order falls through every money check to UNEXPLAINED, or —
once the settlement cycle elapses — to TIMING. TIMING is `BENIGN`. Its merchant-facing
copy reads *"Razorpay has released this money but it has not landed in your account yet.
It arrives on its own."*

For a chargeback that is not merely wrong, it is the single most damaging sentence this
engine can produce. A dispute carries a response deadline. Waiting is exactly how a
merchant loses one.

**Decision.** Add `DISPUTED` as a first-class classification, modelled on ON_HOLD.

1. `_check_dispute` reads `dispute_id` from the recon row, carrying `dispute_reason` and
   `dispute_created_at` into the proof — a merchant needs both to find the case in their
   dashboard.
2. **Not `BENIGN`.** There is a deadline, and doing nothing forfeits the money.
3. Its own gap component, booked at `amount − fee` (net of fee, since the FEE component
   already counts that part).
4. Generated: 2 in `demo`, rate-based in `scale`, with the recon row deliberately
   excluded from settlement grouping — no `settlement_id`, no UTR, no `settled_at` —
   because withheld money must not appear in the bank.

**The bug this exposed, which was older than this work.**

ADR-036 stated that `_check_on_hold` runs before `_check_timing` and called the ordering
"load-bearing". **The ordering never protected anything.** TIMING is emitted from the
`independent` set — the branch that deliberately bypasses the money-rule contest so a
wrong fee and a late settlement can both be reported — so it was never in the contest
that ordering governs. Verified directly:

```
ON_HOLD  -> ['TIMING', 'ON_HOLD']
DISPUTED -> ['TIMING', 'DISPUTED']
```

Every held payment since ADR-036 was reported as *both* withheld *and* "on its way, it
arrives on its own". The guarantee was in the docstring, in the ADR, and in the rule
order — and in none of the behaviour.

**Fix.** TIMING is suppressed when any withholding rule fires:

```python
withheld = {Classification.ON_HOLD, Classification.DISPUTED}
if any(h[0] in withheld for h in hits):
    hits = [h for h in hits if h[0] is not Classification.TIMING]
```

"Late" and "withheld" are not orthogonal facts about the same money the way a wrong fee
and a late settlement are. Withheld money is not late; it is not coming at all until a
human acts. A parametrised test now asserts this for both, plus the inverse — a
genuinely late payment must still be TIMING.

**Two decomposition bugs, both found by the hand-edited composition test.**

The deleted ledger row in that test happened to be a disputed order, which is the only
reason either surfaced:

1. **Tax double-counted.** The component booked `amount − fee − tax`, but the FEE
   component books `m.fee_paise`, which is the `fee` column alone. The decomposition
   came up short by exactly the tax on the disputed rows.
2. **A disputed orphan must be claimed by neither component.** First attempt booked from
   `primary_rows`, so a disputed order whose ledger row was deleted was skipped and the
   decomposition fell short by its net. The over-eager fix then claimed it in the
   DISPUTED component and produced a *surplus* of the same amount. The correct answer:
   with no ledger row it contributes nothing to `expected`, and with the money withheld
   it contributes nothing to `received` — it nets to zero on both sides. The
   orphan-settlement component must still exclude it explicitly, because that one books
   `credit − debit` and a disputed row carries a credit it never paid out.

**Consequences.** 10 tests added. Demo batch: 2 caught, 0 missed, 0 false positives,
residual ₹0.00. `UNEXPECTED_SETTLEMENT` is now correctly smaller in the hand-edited
case, since a disputed orphan's credit is no longer counted as money that arrived.

**Cost.** The actionable list is now 5 lines and at its cap. The next classification
added will force a real product decision — grouping, or a "more" affordance — rather
than another cap raise. Recorded in LIMITATIONS.

---

## ADR-042 — The decoy is what makes "0 false positives" a claim about the engine

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** The headline number across 22 matrix runs was *0 defects missed, 0 false
positives*. The second half of that was weaker than it looked, and `LIMITATIONS.md` said
so: every gap in a generated batch has a real cause, because the generator creates gaps
by planting causes. An engine that flagged *everything* it saw would still score zero
false positives on such data, provided it happened to attach the right label.

So the number measured the DATA — "no gap here lacks an explanation" — rather than the
ENGINE — "this thing does not invent an explanation when one is dangled in front of it."

The scaffolding for fixing this had existed since Phase 1b and was never used:
`PlantedDefect.is_real_defect`, `GroundTruth.decoys()`, and a comment reading *"the
false-attribution test (Day 3) plants a gap that looks like a halted subscription but
isn't."* Day 3 arrived several times without it being run.

**Decision.** Plant decoys in the generator and score them explicitly.

The decoy is a **failed payment against a healthy subscription**. Its surface shape is
identical to the demo centrepiece — failed payment, `subscription_id`, a gap where money
should be — and it differs in exactly the fields that matter:

| | halted (real defect) | healthy (decoy) |
|---|---|---|
| `status` | `halted` | `active` |
| `auth_attempts` | 3 | 0 |
| `error_reason` | `subscription_halted` | `insufficient_funds` |

That is the whole trap: Razorpay has **not** given up, so nothing died silently. The
right answer is `PAYMENT_FAILED` — retryable, worth one email — and the wrong answer is
`HALTED_SUBSCRIPTION`, which tells a merchant to chase a customer whose subscription is
working fine.

**Scored separately from false positives**, because they answer different questions:

- *false positives* — "did the engine flag something unplanted?" Trivially answerable on
  cooperative data.
- *decoys claimed* — "does the engine assert a cause that is NOT there when invited to?"
  The question the headline needs.

`ScoreReport` gains `decoys_resisted`, `decoys_claimed` and `false_attribution_rate`, and
the matrix carries the last two as columns.

**Two design points worth stating.**

1. **Reporting a decoy as UNEXPLAINED is NOT a false attribution.** Only classifications
   asserting a specific cause with an owner count as claiming it. Declining to explain
   is the behaviour `BEHAVIOR.md` asks for, and penalising it would train the engine
   toward exactly the over-claiming this guards against. Ground truth carries an explicit
   `must_not_claim` list per decoy.
2. **Resisting the trap is not sufficient.** A separate test asserts the decoy still gets
   the *milder correct answer*, `PAYMENT_FAILED`. An engine that declined to say anything
   would resist every trap and fail every merchant.

**A scoring bug this found immediately.** The first run reported 4 decoys resisted **and
4 false positives** — the same four orders. `planted_orders` was built from
`truth.real_defects`, so a decoy order looked unplanted, and the engine's *correct*
answer scored as a false positive. Left unfixed, planting decoys would have looked like a
regression and discouraged anyone from ever adding one. Decoy orders now count as
planted.

**Result.** **2,246 decoys across the 22 matrix runs, 0 claimed, false-attribution rate
0.0000.** Resisted at every volume from 50 to 50,000, on both archetypes, all three
payment mixes, and T+1/T+2/T+7 — a parametrised test asserts the guard does not depend on
the merchant's settlement terms.

**Count tuning, and why it is not fudging.** The demo profile plants 2, not the 4 first
tried. At 4 the decoys pushed `PAYMENT_FAILED` to 7 findings, which outranked the 6
halted subscriptions and changed the demo headline from *"those 6 customers"* to *"7
payments that failed"*. The decoys were being resisted correctly in both cases; the count
was drowning the story the demo batch exists to tell. Reduced deliberately, recorded
here so it is visible rather than quiet.

**The honest limit.** We designed the decoy, so it tests the confusion we anticipated. It
does not prove the engine resists a confusion we did not think of — the same structural
limit as every other number in `METRICS.md`, and the reason the hand-edited blind rounds
(ADR-031/033) and the real sample files (ADR-037/038) exist alongside it.

---

## ADR-043 — The upload path reads `.xlsx`, because that is what Razorpay hands a merchant

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** The planned feature was "real CSV upload". Razorpay's sample exports are all
`.xlsx`, and so is what the dashboard's *Download Report* button produces. The normalizer
was `csv.DictReader` only.

So the feature as specified would have shipped a door a real merchant cannot walk through:
they export their settlement report, get an Excel file, and the tool rejects it on step
one. "Real CSV upload" was the wrong name for the requirement.

**Decision.** Read both formats behind one function.

`_read_tabular(path, source_name)` returns `(headers, rows)` and dispatches on suffix.
Everything downstream — column resolution, money parsing, timestamp parsing, the refusal
to guess — is untouched and shared. The only difference the function may introduce is
where the bytes came from.

That constraint is the point. A separate xlsx path would be a **second implementation of
the engine** rather than a second door into it, and the two could drift into giving
different answers for the same data. A test asserts a batch supplied as `.xlsx`
reconciles to the same gap, the same headline, the same score and the same decoy result
as the identical batch as `.csv`.

**Four things the real files forced.**

1. **`data_only=True`.** Returns the cached value of a formula rather than its text. A
   settlement report containing a `SUM` must yield the number, not `"=SUM(A1:A9)"`.
2. **Blank leading columns are dropped.** `sample-settlements-report.xlsx` opens with an
   empty spacer column; without this it becomes a field named `"None"` and the header
   count reads 27 instead of 7.
3. **Wholly blank rows are skipped.** Excel files are full of them, and one would become
   a row of empty strings that fails money parsing on a file that is perfectly valid.
4. **Cell values are passed on untouched.** openpyxl returns real `datetime` objects for
   date-formatted cells and floats for numbers. Stringifying them to re-parse would
   discard type information and *re-create the Excel-serial ambiguity of ADR-037* — the
   exact bug, one layer up. Verified: the recon export's `entity_created_at` arrives as
   `datetime(2022, 4, 7, 10, 43, 32)`, and `_parse_timestamp` now has a passthrough
   branch for it.

**A dependency, deliberately in the core.** `openpyxl` is a hard dependency, not an
extra. The API and LLM deps are optional because the engine must run without them; being
unable to read the format the PSP actually exports is not an optional gap. (`pandas` has
been declared since Phase 0 and is imported nowhere — worth removing separately.)

**`stage_from_dir` finds either.** `ledger.csv` or `ledger.xlsx`, same for `bank`. CSV
wins if both exist — a tie-break for determinism, not a judgement about which is better.

**What this does not do.** It reads the format. It does not yet accept an HTTP upload,
map unfamiliar column names interactively, or take a merchant's own rate card — those are
the next three pieces. And these sample files remain tiny and synthetic: authoritative
for schema and format, not a substitute for one real merchant's data.

---

## ADR-044 — Upload: missing legs are reported, not rejected

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** Every number this engine has produced came from a directory on the machine
running it. The honest description was *"a well-engineered engine demonstrated on data it
generated itself."* The gap between that and a tool is a door a merchant can walk through
with their own files.

**Decision.** `POST /api/upload`, deliberately thin.

It writes the posted files into a batch directory and calls the same `run()` the CLI
does. No reconciliation logic lives in it, per ADR-001 — and the constraint is stronger
here than elsewhere, because an upload path that grew its own parsing or classification
would become a **second implementation of the engine** that could disagree with the
first. The test file says so explicitly: if the upload path ever needs its own
reconciliation tests, that is the signal it has become one.

**Only the ledger is required.** The other four legs are optional, because the engine
already has a real answer for each absence:

| absent | what the engine does instead |
|---|---|
| bank | two-way reconciliation — released money is reported **in flight**, not missing |
| subscriptions | halted-subscription correlation unavailable; those gaps stay in the residual |
| payments | failed-payment correlation unavailable |

Demanding all three would refuse batches the engine reconciles perfectly well. The
missing-bank case is the strongest demo in the product — *"this money is on its way"* is
a better answer than *"this money is gone"* — and rejecting the upload would throw it
away.

But absence is **named**, never silent. The response carries `missing_sources` and a
`note` saying which question the answer does not cover. A merchant who uploads two files
gets a real reconciliation and is told what it could not see, rather than being left to
assume it saw everything.

**Errors surface the engine's own message.** A `NormalizationError` is returned verbatim
in a 422. That message names the offending column and lists the spellings the engine
accepts — it *is* the fix instruction, and it is what the column-mapping UI will render.
Flattening it to "bad file" would discard the most useful part of the refusal-to-guess
design.

**Four safety properties, each tested.**

1. **Batch names are validated before touching the filesystem** — no `/`, no `\`, no
   leading dot, alphanumerics plus `-_` only. Tested with `../escape`, `a/b`, `.hidden`,
   empty and `has space`.
2. **Reusing a batch name is a 409, not an overwrite.** Staging entries are immutable and
   corrections create a new batch (BEHAVIOR.md, stage `stage`). Silently overwriting
   would destroy the audit trail the previous run's numbers depend on.
3. **A failed upload removes its directory.** Otherwise a half-written batch is staged on
   the next request and silently reconciles a partial upload — the exact class of
   confidently-wrong answer this project exists to prevent.
4. **Per-slot format enforcement.** Tabular slots take `.csv`/`.xlsx`/`.xlsm`; recon,
   payments and subscriptions take `.json`, because they are Razorpay collection
   envelopes rather than tabular exports (ADR-008). 64 MB cap.

**Consequences.** 18 tests, driven through the real ASGI app rather than by calling the
handler directly. `/api/batches` no longer hardcodes `ledger.csv` — it finds the ledger
in whichever format it was supplied as, and reports whether a batch was uploaded or
generated.

**What is still missing.** A merchant whose CSV uses unfamiliar column names gets a
correct, informative 422 and no way to act on it from the browser. That is the column
mapping picker, and it is next. The rate card is after it.

---

## ADR-045 — Remembered mappings: refuse once, then never again

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** `BEHAVIOR.md` promises the normalizer refuses to guess a column mapping, and
ADR-044 shipped an upload path that returns that refusal to the browser. It is the right
refusal — a silently mapped column produces a confident wrong reconciliation a merchant
cannot distinguish from a correct one — and it is also **a wall a merchant hits every
single week** if the answer is never recorded.

`AI column mapping` is a deliberate cut (LIMITATIONS): it is AI applied where determinism
would do. The alternative is not AI. It is asking a human once, which is what the prior
art does — Cointab configures a merchant's format at onboarding; Hyperswitch has them
email a sample file so someone sets it up (docs/PRIOR-ART.md).

**Decision.** Three pieces, none of which weakens the refusal.

**1. A structured error.** `UnmappedColumnsError` subclasses `NormalizationError`, so
every existing handler and every test matching on the message keeps working — the message
is byte-identical. What it adds is `as_dict()`: which canonical fields are unmapped, the
spellings accepted for each, and **every unclaimed column** in the file.

Every unclaimed column, not a ranked guess. Ordering candidates by similarity would put a
suggestion in front of the one person who is being asked precisely *because* the engine
cannot tell — and a plausible wrong suggestion accepted without thought is worse than no
suggestion at all. That is the same reason `resolve_columns` refuses to break an
ambiguity by preference order.

**2. An override that wins.** `resolve_columns(..., overrides)` applies human choices
*before* the alias table. A person who has looked at their own export knows more about it
than our alias list does. Three refusals guard it — an unknown canonical field, a column
not in the file, and one column claimed by two fields — because silently ignoring a bad
override would fall through to the alias table and produce a mapping nobody asked for.

`ColumnMapping.overridden` records which fields a human decided, and it reaches the audit
trail. *"We recognised this column"* and *"someone told us what this column was"* are
different kinds of claim, and when a number is disputed it matters which one is behind it.

**3. A store keyed by file shape.** `header_fingerprint` is order-independent and
fold-insensitive — an export tool that reorders columns or changes their capitalisation
has not produced a different *kind* of file, and the fingerprint is exactly as tolerant
as `resolve_columns` already is. A file that gains or loses a column gets a different
fingerprint and is asked about again, which is correct: nobody has confirmed a mapping
for that shape.

The store is a JSON file. Flat files are the storage decision everywhere else here, and a
merchant has a handful of file shapes, not thousands.

**Four properties worth stating.**

- **Mappings never leak between sources.** The same headers mean different things in a
  ledger and a bank statement, so the key is `source:fingerprint`.
- **Re-confirming replaces, never merges.** A merchant correcting a mapping they got
  wrong must not be left half-corrected, and merging would make the stored state depend
  on the order corrections happened to arrive in.
- **A corrupt store does not break reconciliation.** Cost of ignoring it: one more
  mapping question. Cost of raising: they cannot reconcile at all.
- **A remembered mapping is never an inference.** It is replayed only for a header set a
  human was shown and decided on.

**`POST /api/inspect`** completes the loop: it reads a file's headers, says whether a
mapping is already remembered, and returns **three real sample rows**. A merchant
choosing between `amount` and `total` needs to see what is actually in each column, not
guess from its name.

**Consequences.** 26 tests. The loop verified end to end: upload an export with
`txn_ref`/`sale_value`/`when` → 422 with candidates → inspect → remember → upload
succeeds, and next month's reordered export is recognised without asking again. The
manifest shows `mapped by hand: [amount_paise, captured_at, order_id]` alongside
`'rail'->payment_method`, which the alias table resolved on its own.

**A test-isolation bug this found.** `MAPPINGS_PATH` derives from `DATA_ROOT` at import
time, so patching only `DATA_ROOT` let remembered mappings leak between tests through the
real data directory — which is also exactly how they would leak between merchants in any
multi-tenant deployment. Production auth is out of scope (LIMITATIONS), but the store is
now explicitly scoped to a data root rather than global, so that scoping is a
configuration change rather than a rewrite.

---

## ADR-046 — The rate card must be the merchant's, or the fee check answers the wrong question

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** `rate_card.yaml` ships `standard-india-2026`, and every fee finding this
engine has produced compares against it. For a merchant on standard pricing that is
correct. For anyone else it silently answers a different question:

> **"Was this the standard rate?"** — what we check
> **"Was this MY contracted rate?"** — what a merchant is asking

Merchants negotiate away from standard pricing and enterprise pricing is common. A
merchant contracted at 1.75% who is billed 2% sees *nothing* from us, because 2% is
exactly what our card expects. The overcharge is invisible precisely to the merchant it
is happening to.

ADR-035 already made this mistake once in the other direction: the mechanism was right
and the shipped *value* was wrong for UPI. That was a value we could fix. This one cannot
be fixed by picking better defaults — the right number is in a contract we have never
seen.

**Decision.** `RateCard.with_merchant_rates(overrides, source)` layers a merchant's
contracted rates over the shipped card.

**Layered, not replacing.** A contract that renegotiates UPI alone should not require
restating GST and every other method. Each restatement is a chance to get one wrong, and
a merchant would have no way to notice: the wrong number would simply make some fees look
correct that are not.

**Two spellings**, because the common case should be short:

```yaml
methods:
  upi: 175                                   # "UPI is 1.75% for us"
  card_credit: {mdr_bps: 185, note: "tier 3"}
```

**The refusal survives intact.** An override may add a method the shipped card lacks — a
merchant may genuinely be billed for a rail we did not ship — but `rate_for` still raises
for anything neither knows about. The config layer's whole point is that it never invents
a rate, and layering must not become a back door to a default.

**The unit error is the one worth refusing.** Someone entering `2` meaning "2%" gets 2
basis points, or 0.02%. Every single transaction then looks overcharged, the FEE line
explodes, and the engine confidently reports a catastrophe that is not happening. So a
rate over 10,000 bps (100%) is refused with a message naming the unit. The *low* end
cannot be refused — 2 bps is a legal, if tiny, rate and is indistinguishable from intent
— but the absurd end catches the transposition that actually occurs. `fixed_fee_paise`
gets the same treatment: `2.00` meaning ₹2 is refused, because accepting it as 2 paise
would understate every fee.

**API.** `GET /api/rate-card` returns the active card with a `source` of `merchant` or
`standard` **per method** — a merchant reading "you were overcharged" deserves to know
whether the comparison used their number or ours. `PUT` validates by building the card
before writing anything, and **clears the run cache**: a cached run was scored against
the old card, and serving it would show fee findings computed from rates the merchant has
just replaced.

**What it changes, measured.** On the demo batch with a contracted 1.75%:

| card | FEE findings | total overcharge |
|---|---|---|
| `standard-india-2026` | 30 | ₹595.37 |
| merchant-contracted | 189 | ₹3,552.01 |

Same data, same engine, different contract. The proof reads *"charged 3391 vs contracted
2968"* using the merchant's number, which is the sentence this product exists to produce.
The gap identity still balances to ₹0.00 under a merchant card — a test asserts it,
because changing what "expected" means is exactly the kind of change that breaks a
decomposition.

**A distinction worth keeping straight.** The verdict's FEE *line* is the whole fee
Razorpay kept — a fact from the data, unchanged by any rate card. The rate card drives
the *drill-down*: whether that fee matched the contract. Conflating them would make the
headline gap move when a merchant edits a config file, which would be alarming and wrong.

---

## ADR-047 — Screens for the three flows, and the bug that only driving them found

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** Upload (ADR-044), column mapping (ADR-045) and the merchant rate card
(ADR-046) were built, tested and unreachable. `page.tsx` opened with `const BATCH =
"demo"` — one hardcoded batch — so a merchant could upload files through the API and
never see the result. `LIMITATIONS.md` said so in those words: *"the endpoints are built
and tested" is not "a merchant can do this."*

**Decision.** Four components, and `page.tsx` becomes a client component.

That last part is a real trade. The page was a server component so the numbers arrive in
the initial HTML rather than flashing in after hydration — a deliberate choice worth
keeping where it can be. But *which batch is on screen* is now state a merchant changes,
and a page that can only ever render one hardcoded batch makes the entire upload path
invisible. Reachability wins over first-paint.

**`Upload`** carries the loop that matters. A 422 with `error: unmapped_columns` becomes
a picker rather than an error message; the merchant's answer is remembered against the
file's shape; the upload is retried automatically. Every unclaimed column is offered **in
file order, unranked** — the UI must not reintroduce by visual ordering the guess the
engine refuses to make. Only the ledger is marked required, and the response's `note`
("no bank statement, so this is a two-way reconciliation…") is rendered rather than
swallowed, because what an answer does *not* cover is part of the answer.

**`RateCard`** takes **percentages**, not basis points. The API takes bps because
integers keep money arithmetic exact, but no merchant thinks in bps, and asking them to
would invite exactly the unit error ADR-046 refuses. The UI converts. Each row is
labelled `yours` or `standard`, so a merchant reading "you were overcharged" can see
whose number produced it.

**`BatchPicker`** hides itself when there is only one batch — a control offering a single
choice is furniture, not a control.

**The bug.** Driving the flows against a live server found something 665 tests had not:

```
PUT /api/rate-card   → 200
GET /api/detail/{uploaded-batch}/FEE → 500 UnmappedColumnsError
```

`_load` re-runs the pipeline on any cache miss and **was not passing the mapping store**.
Uploading worked, because that path passed it. Every subsequent read of an uploaded batch
whose columns a human had mapped failed — after a fresh process, after `refresh=true`,
or, as here, after a rate-card change cleared the cache.

The cache is what hid it. The first read was served from memory, so the shortest path
that reveals the bug is *upload → change something → drill down*: three steps, in the
browser, in that order. No unit test I wrote covered it, and I only saw it because the
rate-card form made me change rates and then look at fees.

Fixed, and guarded by two tests that fail without the fix (verified by reverting it).
Same species as ADR-040: a code path correct on the route it was written for and never
exercised on the route that shares it.

**Consequences.** 665 → 667 tests. Verified end to end against a live server: upload an
export with `txn_ref`/`sale_value`/`when` → picker → remember → 597 rows reconciled →
appears in the batch picker as *yours* → contracted 1.75% turns 89 fee findings into 191
→ reverting restores 89.

**Still not built.** The action list (named customers, amounts, failure reasons, CSV
export) has no screen either, and correlation still has one mechanism.

---

## ADR-048 — The action list: naming the customers the verdict counts

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** The verdict has always ended with *"One thing needs you this week: those 6
customers"* — and could not name them. A merchant reading that had no next step except
to go looking in the Razorpay dashboard for six people the engine had already identified.

That is the gap between an insight and a tool, and it is the one the README's argument
against dashboards implies most directly: if the case against a dashboard is that a
merchant should be handed the work rather than a chart of it, then not handing over the
work is the sharpest possible inconsistency.

**Decision.** `finctl/actions.py`, a **projection** rather than an analysis.

Nothing in it is computed. Every field is lifted from a finding's proof — correlation
already resolved `customer_id`, `subscription_id` and `error_reason` on the way to
labelling the gap. That is deliberate: a projection cannot disagree with the verdict it
accompanies, and a second computation of the same numbers could. Tests assert the totals
and the item count match the findings exactly.

`PipelineResult.actions` is a **property**, not a stored field, for the same reason.
Computing and storing it would create a second copy that could drift.

**Three design points.**

1. **Each group carries an imperative next step, not a category name.** *"Email these
   customers a new payment link. Razorpay stopped attempting charges and will not restart
   on its own"* is an instruction; *"review halted subscriptions"* is a label wearing a
   verb. A parametrised test asserts every actionable classification has one — a cause
   the engine can report and cannot advise on is a dead end.
2. **Largest first, within groups as well as across them.** If a merchant only gets
   through some of the list, they should get through the expensive part.
3. **Benign lines are absent.** A merchant asking "what needs me?" is not asking to be
   shown the fee they agreed to pay. Including them would rebuild the dashboard.

**A gap the ledger closed.** Only the subscription join was writing `customer_id` into a
proof, so the first version could name the customer behind a halted subscription and
**not** the one behind a failed payment — precisely backwards, since the failed payment is
the one you email today. `build()` now takes the ledger rows, which name the buyer on
every order. Correlation's answer still wins where it exists: it resolved the customer
through the subscription, which is the more specific claim.

Not every row has one, and that is correct rather than a hole: `UNRECORDED_REFUND` has no
`order_id` by definition (ADR-039), so there is no buyer to name and inventing one would
be exactly the guess this engine refuses. Those rows lead with their `rfnd_…` id.

**The CSV is the feature, not a nicety.** The difference between a dashboard and a tool
is whether the work leaves the screen — a merchant sorts it, forwards it, or hands it to
whoever does the chasing. Amounts are written in **rupees**, not paise: `87600` under a
column headed "amount" invites a very expensive misread by a human or a spreadsheet.
Every row carries its own `next_step`, so the file is useful to someone who never saw the
screen.

**Available in three places.** `finctl actions --data <dir>` (with `--csv <path>`),
`GET /api/actions/{batch}`, and the UI. Per ADR-001 the CLI came first: anything the UI
can do, the CLI must be able to do, or it is not testable.

**Consequences.** 35 tests. On the demo batch: 17 items worth ₹68,317 across three
groups, every order-backed row naming a customer, and the six headline customers listed
by name with their amounts and `subscription_halted` as the reason.

**What it exposes.** Two groups — `REFUND` and `UNRECORDED_REFUND` — have no `reason`,
because nothing upstream attaches one. The instruction covers it, but the per-row "why"
column is empty where the other groups have `subscription_halted` or `incorrect_otp`.
Worth stating rather than papering over with a generic string.

---

## ADR-049 — Correlation gets two more mechanisms, and an order of precedence

**Date:** 2026-09-03 · **Phase:** real-data

**Context.** Correlation is the stated differentiator, and `LIMITATIONS.md` recorded the
weakness plainly: it had **one mechanism**. The halted-subscription join, plus the
failed-payment fallback that is really the same join stopping one hop earlier. *"We found
a clever join"* and *"we built a correlation layer"* are different claims, and only the
first was supported.

Disputes and holds were already *classified* (ADR-036, ADR-041) — but only on an order
the matcher **paired**. An order the ledger has and the matcher could not pair arrives at
correlation as `MISSING`, and `dispute_id` / `on_hold` were never looked at on that path.

Reproduced before fixing:

```
ledger: O1
payment: {status: failed, dispute_id: disp_1, dispute_reason: chargeback}
-> PAYMENT_FAILED, "resolved: payment failed"
```

A chargeback reported as a payment failure. The action list then tells the merchant to
*"retry or ask for another payment method"* — on money a customer has formally contested,
with a response deadline running. The instruction is not merely unhelpful; following it
wastes the window.

**Decision.** `_withholding()` runs **before** the payment-failure path.

Two joins, both reading fields Razorpay's own export carries:

| field | mechanism | what it means |
|---|---|---|
| `dispute_id` | chargeback | there is a deadline; evidence must be submitted |
| `on_hold` | withheld | pending KYC or a risk review; a dashboard action |

Both are checked on the recon rows **and** on the payment record, because a real export
carries `dispute_id` in both places and which one we have depends on which files the
merchant uploaded. Which file they happened to send should not change the answer.

**Precedence is the substance of this ADR.** A disputed payment on a halted subscription
is *both* things, and the engine must pick one to lead with. Withholding wins, because
the two answers imply different actions and only one has a clock on it: "email them a new
payment link" is wrong for money under dispute, while "submit evidence" is never wrong for
a disputed payment that also sits on a dead subscription. Ordering by consequence rather
than by which rule happens to run first is the whole decision, and a test asserts it.

**The refusal is unchanged.** `_withholding` returns `None` when neither field is present,
so the payment path runs exactly as before. A test asserts that a payment record carrying
`dispute_id: None` and `on_hold: False` does not acquire either label — the same
discipline as the halted/active distinction that the decoys exist to guard (ADR-042).
Resemblance is not evidence.

**Consequences.** 8 tests. Three mechanisms now: halted subscription, dispute,
withholding — plus the failed-payment fallback. Matrix re-run: **0 missed, 0 false
positives, 2,246 decoys resisted, 0 claimed**, gap residual ₹0.00 on `demo`, `chaos` and
`scale`. The action list picks up `chargeback` and `kyc_pending` as per-row reasons where
it previously had none.

**Stated honestly.** These mechanisms are not *measured* by the matrix, because the
generator has no batch where a disputed payment sits behind an unmatched order — the
residual is zero on every profile, which is a property of the generator rather than proof
the correlator is complete. What the new joins have is unit coverage of the shapes real
exports produce. That is the same limit as everything else in `METRICS.md`, and it is why
the hand-edited rounds and the real sample files exist alongside it.

---

## ADR-053 — The action list disagreed with the verdict, and a test held it in place

**Date:** 2026-09-04 · **Phase:** review

> *Numbered out of sequence deliberately.* This was written as a second ADR-049 — two
> sessions claimed the number the same morning. It keeps its position here, which is
> chronological, and took the next free number rather than renumbering the four ADRs
> that followed it and the code comments citing them.

**Context.** An external critique ran the engine and put the two screens side by side:

| Classification | Verdict | Action list |
|---|---|---|
| DISPUTED | ₹8,693.87 | ₹0.00 |
| ON_HOLD | ₹14,734.85 | ₹0.00 |
| REFUND | −₹18,988.00 | ₹22,334.00 |

Same product, same batch, two answers, differing by ₹1,094.72 in total — and the REFUND
line differing in **sign**, which is worse than differing in size.

ADR-048 claimed this could not happen. `actions.py` opens by saying the module "cannot
disagree with the verdict it accompanies". It did, on every batch, from the day it was
written.

**Cause.** `actions.py` summed `finding.amount_paise`. That is precisely the mistake
`gap.py` exists to prevent, and its docstring says so in as many words: the field means
the *overcharge* for FEE, the *whole order* for HALTED_SUBSCRIPTION, and a *magnitude
whose sign is negative* for REFUND. Those are not commensurable and adding them was never
going to equal anything.

The lesson was learned in `gap.py` and not carried into `actions.py`, because
`actions.py` was written later. A fix applied in one module is not an invariant.

**What makes this the worse kind of bug.** `test_the_totals_match_the_findings` asserted
that the action totals equalled `sum(finding.amount_paise)`. It passed. It was pinning
the defect in place: the test encoded the buggy quantity as the expected answer, so the
suite would have rejected the correct behaviour. A green suite was evidence of
consistency with the bug, not of correctness.

**Decision.**

1. `build()` takes the `GapDecomposition` and reads its amounts from it. Both screens now
   derive from one computation instead of agreeing by inspection.
2. `ActionGroup.total_paise` returns the **component** total, not a re-sum of its items,
   so a component the decomposition tracks in aggregate cannot report zero.
3. Components that were tracked in aggregate now carry their `order_ids`: the refund
   debits, the settled-above-ledger excess, and the shortfall. Without this the group
   total was right and every row beneath it read ₹0.00 — the same defect as the
   chargeback, one component further down.
4. An unrecorded refund has no `order_id` on either side; that absence is what makes it
   unrecorded. Those rows are keyed by refund `entity_id` instead.
5. The test was replaced by three that assert the property ADR-048 only claimed: every
   group equals its verdict line, the actionable totals match, and **no actionable row
   reads zero**.

**On the ₹0.00 chargeback specifically.** The critique proposed sourcing the amount from
`proof["amount_disputed_paise"]`. That field is computed by

```python
amount = sum(r.get("credit", 0) or 0 for r in disputed) or sum(...)
```

and `X or Y` falls through only when the left side is exactly zero. A clawed-back
chargeback has a *negative* credit sum, which is truthy, so it is kept — that is the
third of the three conflicting figures for one dispute, not a fix for the other two.
Taking the amount from the decomposition avoids the falsy-fallback chain entirely.

**Verified.** The demo batch now reports ₹8,693.87 / ₹14,734.85 / −₹18,988.00 on both
screens, sign intact; items sum exactly to their group in every group; no row reads zero;
and the matrix still holds the balance identity across all 22 runs with 0 defects missed
and 0 false positives.

**What this cost the project's own argument.** The failure record is the strongest thing
here, and this is the entry that tests it: the engine's numbers were right and the screen
was assembling them wrongly — the identical sentence that opens `gap.py`. Twice is a
pattern, and the response to a pattern is an invariant, not a third fix. Hence the
assertion rather than the correction.

---

## ADR-050 — The explanation stage, and where a model is allowed to be wrong

**Date:** 2026-09-04 · **Phase:** review

**Context.** ADR-053's sibling finding: the README claimed an LLM wrote the explanations
and the recommended actions. Neither was true — `finctl/explain/` was a one-line stub and
there was no model call anywhere in the codebase. The claim was corrected first (the
table read **Not built** for a day), because a false capability claim in a project whose
argument is *measured rather than asserted* costs more than a missing capability.

This ADR is the other resolution: build it, so the claim is true.

**Decision.** One model call, per batch, writing the two-sentence summary above the
verdict lines. It is given facts that are already resolved and asked only to phrase them.

**Where the model is NOT.** Unchanged from the original argument, and worth restating
because building the stage is exactly when it would erode: matching, fee arithmetic,
classification, correlation and ranking are all deterministic. An LLM must never decide
whether two numbers are equal. A reconciliation engine that hallucinates is worse than no
engine.

**The rule that makes it safe: no figure a merchant reads comes from a model.**

The model is never shown a number. `_facts` describes lines by RANK — "largest line",
"needs action" — so there is no figure in the prompt to echo back. `guard` then discards
any response containing a digit or a number word, and the caller falls back to the
template. Every amount on screen is rendered by `format_rupees` from an integer the model
never touched.

*One numeral discards the whole response*, not just the offending sentence. Salvaging the
clean half is tempting and wrong: the surviving sentence was written believing the
invented figure was true, so "act now" would follow from a shortfall the engine never
found. It is also the rule a reviewer can check in one pass.

**Fallback is the default path, not the error path.** No key, no network, a timeout, an
empty response, or prose that fails the guard all produce the deterministic template. The
demo runs offline exactly as before. `explain()` returns `(prose, source)` and the API
returns `summary_source`, because a product that cannot say whether a model wrote
something is not one you can audit — the verdict screen says so to the merchant too.

**Provider is configuration, not a dependency.** Any OpenAI-compatible endpoint;
`urllib` rather than a vendor SDK, so the engine still installs with zero LLM
dependencies. Default: Groq serving GPT-OSS-20B (Apache 2.0, open weights).

**Three things found by running it, all of which would have shipped silently:**

1. **GPT-OSS is a reasoning model.** At default effort it spent its entire token budget on
   hidden reasoning and returned `content: ""` with `finish_reason: "length"` — a blank
   explanation on the verdict screen. Fixed with `reasoning_effort: "low"` and
   `max_completion_tokens`; an empty response is now treated as a failure, not an answer.

2. **Groq rejects `Python-urllib`.** HTTP 403, Cloudflare `error code: 1010`, no mention
   of a user agent in the response — while the identical request through curl succeeded.
   The obvious reading of that 403 is a bad key, which is the wrong place to look. An
   explicit `User-Agent` fixes it.

3. **The model invented a direction.** The first working run produced *"You have a net
   gain this week"* over a batch where the merchant received ₹78,720 **less** than
   expected. The prompt gave line labels and rankings but never said which way the money
   went, so it guessed. The guard catches numbers; it cannot catch a wrong direction. **A
   fact the model needs and is not given is a fact it will invent** — the prompt now
   states the direction in words and forbids the opposite framing.

The third is the one worth keeping. The guard is a backstop against a model that
misbehaves; the prompt is what stops it needing to. Neither alone is sufficient, and the
failure was silent, plausible, and about the single most important thing on the screen.

**The suite stays hermetic.** `tests/conftest.py` disables the stage for every test.
A developer with `GROQ_API_KEY` exported was otherwise running a different, slower,
network-dependent suite (9.4s against 4s on the API tests alone) — a suite whose result
depends on whose laptop it runs on is not evidence. `test_explain.py` covers both paths
with a stub client, including a model that returns a hallucinated amount.

**What is still not claimed.** The recommended actions are still deterministic copy, and
the table says **No**. `NEXT_STEP` is a fixed string per classification, and it is good
copy; routing it through a model would add a failure mode to a sentence that is already
right.

---

## ADR-051 — The scorer graded against a cycle the engine never used

**Date:** 2026-09-04 · **Phase:** review

**Context.** `cycle.py` exists because the classifier once judged every batch against a
configured T+2 regardless of what the batch actually did. That fix gave the **classifier**
an observed cycle. It never gave one to the **scorer**.

So on any batch settling slower than T+2, `score()` read `config.tolerances.cycle_days`
— the stale configured value — while the engine had correctly detected the real cycle and
classified those orders RECONCILED. Every late-but-within-cycle order the engine got right
was counted as a MISS.

Measured on a 400-order demo batch:

| cycle | caught | missed | below tolerance | reported recall |
|---|---|---|---|---|
| T+1 | 24 | 0 | 16 | 1.000 |
| T+2 | 24 | 0 | 16 | 1.000 |
| T+3 | 24 | **16** | **0** | **0.600** |
| T+7 | 24 | **16** | **0** | **0.600** |

The engine was right at every cycle. Its own report card said 0.600 at T+3 and above.

**Why this is the rarer direction.** A measurement bug that *overstates* accuracy is the
one everybody looks for. This one understated it: the project was reporting itself as
worse than it was, on an axis nobody was sampling.

**Why 22 green matrix runs never saw it.** The matrix ran T+1 and T+2 only. At those
values the configured and observed cycles are close enough that the wrong baseline still
produces the right answer. **An axis that samples only where two values agree cannot
detect that it is reading the wrong one.**

**Decision.**

1. `score()` and `_is_below_tolerance()` take an optional `cycle_days`, defaulting to the
   configured value so an unaware caller still works.
2. Both callers — `pipeline.run()` and `finctl checkpoint` — pass
   `classifier.cycle_days`, the exact number the classifier judged against. The CLI was
   discarding its classifier; it now keeps it.
3. The matrix gains T+3 and T+7 rows on both archetypes: **26 runs, up from 22.** T+7 is
   not hypothetical — it is the international and high-risk-category settlement cycle,
   and the merchant most likely to be confused about where their money is.

**Verified by reverting.** With the fix backed out, the extended matrix reports **48
defects missed**; with it, **0**. The new rows genuinely detect the bug rather than merely
passing beside it.

**The invariant, stated so the next stage inherits it.** Any stage that judges timing must
be handed the same cycle the classifier used.
`test_the_scorer_uses_the_cycle_the_classifier_used` asserts the two are equal, and
asserts the batch actually disagrees with config — a test where they happen to match
proves nothing.

---

## ADR-052 — The action list said "email these customers" and had no email

**Date:** 2026-09-04 · **Phase:** review

**Context.** ADR-048 built the action list so the verdict's *"One thing needs you this
week: those 6 customers"* could name them. It named them with `cust_DnvzvP0lIu`.

Every actionable row carried `email: null` and `contact: null`. The product's single most
important instruction — "Email these customers a new payment link. Razorpay stopped
attempting charges and will not restart on its own." — could not be carried out from what
the product handed over. That is the same gap ADR-048 set out to close, one step further
in: a list of ids is an insight; a list you can act on is a tool.

**Cause: three layers, none of them the join.** `actions._LOOKUPS` was already looking for
`email`, `customer_email`, `contact` and `customer_contact` — the correct names. Nothing
upstream produced them:

1. the generator emitted no contact fields at all;
2. `writer.py` writes a fixed ledger header, so a new field would not have reached disk;
3. `LEDGER_COLUMNS` did not list them, so the normalizer dropped them at staging.

The lookup was right and had nothing to find.

**Decision.** Produce the data at every layer, modelled on the real exports:

- **Generator.** `_contact()` derives an address and an Indian mobile from `customer_id`,
  so one customer has one address in the ledger, the payments feed and the subscriptions
  feed. A customer whose email differed per source would make a correct join look wrong.
  Addresses end `@example.invalid` — reserved by RFC 2606, can never route. Demo data
  that could reach a real inbox is one accidental send away from a problem, and this
  file gets handed to people.
- **Column names follow Razorpay.** `email`/`contact` on the payments rows,
  `customer_email`/`customer_contact` on the subscriptions rows — confirmed against
  `sample-payments-report.xlsx` and `sample-subsciptions-report.xlsx`.
- **Recon rows deliberately get neither.** Razorpay's settlement recon export carries no
  contact columns, and inventing one produces a batch only this engine can read. A
  first patch added them there by pattern-matching on `"currency": "INR"`; caught by
  checking each insertion against the real file rather than the diff.
- **Schema.** `email` and `contact` join `LEDGER_COLUMNS` and stay out of
  `LEDGER_REQUIRED`. A real merchant export may lack them, and making them mandatory
  would turn a nice-to-have into a reason the tool cannot be used at all. Aliases are
  deliberately narrow: mapping the wrong column into an address a merchant then writes
  to is worse than having no address.

**Golden files.** Four regenerated. The diff was read first, as `test_golden.py` instructs:
**two fields added, none removed, none changed** — every id, amount and total byte-identical,
confirming the RNG sequence was not perturbed. That was the real risk, and it is why the
diff is read rather than the file rewritten.

**The frontend needed no change.** `Actions.tsx` already rendered
`item.email ?? item.customer_id ?? "—"`. It had been falling through to the id for every
row since it was written.

**What is still empty, correctly.** `UNRECORDED_REFUND` rows have no customer and no
contact, because they have no order on either side — that absence is what makes them
unrecorded (ADR-039). Filling those would be inventing a customer.

---

## ADR-054 — "Actionable" is one policy, and the action list was applying a second one

**Date:** 2026-09-04 · **Phase:** review

**Context.** ADR-053 made the action list agree with the verdict on the *amounts*. It did
not make the two screens agree on *which rows belong there at all*. Reading both against
the `blind` batch:

| Screen | Total | Groups |
|---|---|---|
| Verdict — actionable | ₹31,417.00 | HALTED_SUBSCRIPTION, PAYMENT_FAILED |
| Action list — chase | ₹33,661.00 | …plus DUPLICATE, ₹2,244.00 |

₹2,244 was presented to a merchant as work to do on a screen headed *"What needs you"*,
while the verdict on the same page called it benign.

**The two rules.** They were never the same rule:

- `actions.build` filtered on `BENIGN` — a frozenset in `classifier.py` holding five
  classifications that mean "arithmetic that came out right".
- The verdict asks `Ranker.is_actionable`, which reads `tolerances.yaml`: `always_benign`
  first, then `always_actionable`, then a materiality floor. That list also names
  **REFUND** and **DUPLICATE** — *"a bookkeeping divergence to reconcile, not a
  this-week action"* and *"a data-entry issue in the merchant's own ledger"*.

So the config had already answered the question, in a file whose whole purpose is to hold
that answer, and one of the two consumers was not reading it. `DUPLICATE` is a real
discrepancy — it is on the verdict, it is in the gap, it widens the expectation — but a
merchant cannot *chase* it. There is nobody to email. The fix is to delete a row from
their own ledger, which is why the policy calls it benign.

**Decision.** The verdict's ruling is the authority, and `build()` takes it as an
argument rather than deriving a second opinion:

```python
actions.build(..., actionable=frozenset(
    line.classification for line in verdict.actionable_lines
))
```

`BENIGN` stays as the floor for the direct unit-test path that supplies no verdict. Where
a verdict exists — every production caller — its answer wins.

**Why not widen `BENIGN` instead.** It would have fixed this batch and been wrong in
principle. `BENIGN` means "this arithmetic is correct"; `always_benign` means "this needs
no human this week". A `DUPLICATE` is not correct arithmetic — it is a real defect that
happens not to be chaseable. Collapsing the two would make the distinction unavailable to
anything that later needs it, and materiality is configurable precisely so test day can
vary it: a threshold change must not silently alter which screen shows what.

**The test was enforcing the bug, again.** `test_every_actionable_finding_reaches_the_list`
asserted `listed == len([f for f in findings if f.classification not in BENIGN])` — the
coarse rule, as an equality. It *required* the action list to carry rows the verdict
called benign, so the correct behaviour would have failed it. This is the second time in
two ADRs that a test held a disagreement in place by asserting the weaker of two
available rules; the pattern is worth naming: **a test that restates the implementation's
rule cannot detect that the rule is the wrong one.** It now asserts against the verdict's
judgement, plus the converse the old test could not express — that nothing the verdict
calls benign appears as work.

**Measured.** All six batches on disk now report identical figures on both screens.
`chase_total` on `/api/actions/{batch}` equals `actionable_total` on
`/api/verdict/{batch}`, exactly, everywhere. 797 tests green.

**What this does not fix.** The negative-component case is now unreachable through this
path rather than solved: with REFUND correctly excluded, no group on any current batch
carries a negative total. The UI still handles one — magnitude-based bar widths, an
`offsets the gap` legend entry rather than a dropped segment — because a future
classification could be both negative and actionable, and the previous behaviour was to
render `width: -74.2%` and silently draw nothing.

---

## ADR-053 — The holiday calendar was empty, which is not the same as neutral

**Date:** 2026-09-04 · **Phase:** review

**Context.** `tolerances.yaml` shipped `holidays: []`, with a comment arguing that a short
known-correct list beats a guessed-at full one. The argument is right. The empty list was
not the conclusion it implies — it makes the engine treat every bank holiday as a working
day, so a payout that was never going to arrive is judged late and a merchant is told to
chase money the bank is closed for. Diwali week is precisely when a merchant most wants to
know where their money is.

**Decision.** Populate the fixed-date national holidays on which Indian banks close under
the Negotiable Instruments Act, for 2025 and 2026: Republic Day, Independence Day, Gandhi
Jayanti, Christmas.

**What is deliberately absent, and why that is the honest half.** Most Indian bank
holidays are lunar or state-declared. Diwali, Holi, Eid and Good Friday move every year
and differ by state, and Maharashtra's list — the one that governs settlement, since the
clearing houses sit there — is published annually rather than derived.

Guessing them would produce a calendar confidently wrong on the dates that matter most,
and the asymmetry decides it: **a missing holiday makes one settlement look a day late,
while a wrong holiday makes a real delay look benign.** This engine's argument is that it
does not quietly explain money away, so it errs toward flagging.

A merchant running a real batch across Diwali pastes that year's RBI list into the config.
That is an edit to a YAML file, not a code change, which is what the config layer is for.

`test_the_list_is_deliberately_fixed_date_only` asserts the absence, so adding a moving
feast is a decision someone makes on purpose with a published list in hand, rather than a
lint someone silences.

**No effect on the accuracy figures.** The generator and the classifier share one
`WorkingCalendar` — deliberately, so a generator bug cannot hide behind a matching
classifier bug — so both moved together and the matrix is unchanged: 26 runs, 0 missed,
0 false positives, balance identity holding. Only the timing fields in
`matrix-results.json` differ, and those measure the machine.

---

## ADR-054 — 488 statements at 0%, in the interface everything else reaches around

**Date:** 2026-09-04 · **Phase:** review

**Context.** `cli.py` had no tests at all. `pipeline.run()` was exercised from a dozen
angles; `finctl checkpoint` — the command the README tells a reader to type first — from
none. The suite tested the engine through the door the tests use, not the one a person
uses.

The cost is not hypothetical. Twice during this session a wrong option name (`--cycle-days`
for `--cycle`, a positional argument for `--amount`) produced a usage error that no test
would ever have caught, because nothing typed these commands.

**Decision.** Smoke tests over every subcommand, asserting the contract a CLI actually
has rather than re-testing the engine underneath it:

- exit 0 on the happy path, non-zero on the sad one
- no traceback, ever
- the numbers printed are the engine's, not a second copy
- a command that refuses says what to do instead

`catch_exceptions=False`, so a crash fails loudly rather than passing as a deliberate
refusal — which is the distinction these tests exist to draw.

**What they found immediately.** Two commands were leaking internal exceptions to the
terminal as eighteen lines of Rich traceback:

```
ConfigError: unknown archetype 'not_an_archetype'. Known: ['d2c_ecommerce', …]
ValueError: defect profile 'demo' demands 34 defects but the batch has only 5 orders …
```

Both messages are excellent — they name the fix, not just the fault, which is this
engine's stated standard for errors. The CLI was taking the best thing about its own error
handling and burying it under a stack dump. The critique flagged "two leaked internal
exceptions"; these are they.

`_Refuse` turns those into the message alone plus exit 1. Deliberately narrow —
`ConfigError`, `MoneyError`, `NormalizationError`, `ValueError` — because a blanket
`except Exception` would hide the next real bug behind a tidy one-liner. **A traceback is
the right output for a bug and the wrong one for a refusal.**

**Coverage moved where it should.** cli.py 0% → 70%, blind.py 0% → 91%, overall 75% → 89%.

The blind tests assert the property that matters there, which is what the command does
*not* print: no defect type names, no archetype, no configuration values, and no bare
integers. A first version asserted on the bare word "defect" and failed on the sentence
explaining that nothing is printed — an assertion about prose describing the guarantee
rather than about a breach of it.

**Still uncovered, and named.** 148 statements: the `probe --live` path (needs Razorpay
credentials and a network), and Rich table rendering in the deeper drill-downs. Both are
presentation over data that is tested where it is produced.

---

## ADR-055 — CI, and the one number it refuses to gate on

**Date:** 2026-09-04 · **Phase:** review

**Context.** Every check in this project ran by hand. The evidence for "it works" was that
it worked on one laptop — and two of the four defects fixed in ADR-049..052 were found by
an outsider running the engine, which is what CI is: an outsider with no context and no
muscle memory.

**Decision.** Four jobs on every push: `engine` (ruff, pytest, coverage), `metrics` (the
accuracy matrix), `web` (tsc, next build), `secrets`.

**The matrix job is the one worth having.** It re-derives the headline claim on every push
and fails the build if the summary stops saying `defects missed: 0`, `false positives: 0`,
`balance identity: holds in every run`. A claim that is only ever regenerated by hand is a
claim that can quietly stop being true between regenerations.

It also checks `docs/matrix-results.json` against a fresh run, **excluding `seconds` and
`rows_per_second`.** That exclusion is the whole design: those measure the machine, not
the engine, and they differ on every run. A byte-for-byte diff would fail on a slow runner,
and a check that cries wolf on hardware noise is one people learn to re-run until green —
worse than no check, because then a real accuracy regression looks like the usual flake.
Caught by running the check locally before committing it, where it failed immediately.

**No coverage threshold, deliberately.** cli.py sat at 0% while the classifier, correlator,
matcher, gap and ranker sat at 95–100%. A single repo-wide percentage would have been
satisfied by the wrong work — and the honest reading was always per-module. Coverage is
reported, not gated.

**Format check is non-blocking.** 41 files would reformat, and a reformat commit that
large would bury the history this project keeps deliberately readable. The check runs so
the number is visible and shrinking rather than unknown.

**No API key in CI.** The explanation stage falls back to its template without one, and
`tests/conftest.py` disables it for every test regardless. A suite that reaches a
third-party endpoint has red builds that must be diagnosed before they can be trusted.

**The secrets job enforces a rule that predates the code.** `.env` has been gitignored
since commit one; this fails the build if it is ever tracked, and greps for key *shapes*
rather than running a generic entropy scan — a false positive here trains people to ignore
the job.

---

## ADR-056 — Running the arithmetic against Razorpay's own file, and the two bugs it found

**Date:** 2026-09-04 · **Phase:** review

**Context.** METRICS.md says it plainly at the top: every accuracy figure is measured
against data this project generated, where the generator defines truth. A closed loop.
The critique named breaking that loop as the single highest-value change available —
"one real batch converts *100% on our synthetic data* into *it works*."

A live merchant account was not available. What was available is
`razorpay-sample-files/`: Razorpay's own exports, not written by us and not written for
us. `test_normalize.py` already proved they were READABLE. It did not prove the money
arithmetic agreed with them, and those are different claims.

**Decision.** Run the engine's central identity over Razorpay's own settlement recon
export:

    credit - debit == amount - fee - tax

on every payment row, in integer paise through `money.py` — not in float, since the
reason that module exists is that this is where binary floating point drifts.

**It holds on all nine payment rows.** The tenth is the refund, where it correctly does
NOT hold: a refund is a debit that nets negative against a positive amount, which is why
`gap.py` books refunds as their own signed component. Asserting the exception is what
makes the rule meaningful.

**Two real bugs, neither of which the generator could have produced.**

**1. There were two date parsers and only one was good.** `to_date` reached only
`date.fromisoformat`, so it raised a bare `ValueError: Invalid isoformat string:
'29/06/2022 07:34:39'` — a string taken verbatim from Razorpay's export, in the very
column `_parse_timestamp`'s docstring cites. That function has read DD/MM/YYYY correctly
since ADR-044. The matcher and classifier were calling the weaker one. It now delegates,
so a bad date also gets the engine's own message ("Accepted: Excel serial date, epoch
seconds, YYYY-MM-DD…") instead of a stack trace.

The generator writes one timestamp format per column, because nobody would think to
generate a column that mixes two. Razorpay's file mixes them — a spreadsheet writes
whichever the cell format dictates.

**2. A naive datetime was shifted by the machine's timezone.** `openpyxl` returns naive
datetimes for every date cell in an .xlsx, and `.astimezone(UTC)` interprets a naive value
as LOCAL time. On an IST machine (+5:30) a settlement stamped 02:00 read as the PREVIOUS
DAY. A silent, machine-dependent off-by-one on a settlement date — precisely the class of
error this engine exists to find in other people's systems, and it would have made the
same batch reconcile differently in Mumbai and in London.

The sample rows are afternoon timestamps, so the bug was latent even there: it needed a
value near midnight to surface. It was found by checking the parsing directly rather than
by the row happening to trip it, which is the argument for asserting on a real file rather
than eyeballing its output.

**What this does and does not establish.** Ten rows is not a merchant's month. The honest
claim is: **the engine's core identity holds on real Razorpay-authored rows, and two
parsing bugs that only real data exposes are now fixed.** It is not "it works on
production data" — that still needs a live account, and LIMITATIONS.md keeps saying so.

The value was never the ten rows. It is that two hours against a file we did not write
found two defects that 825 tests against a file we did write did not.

## ADR-057 — The design's daily chart, and the three ways it could have lied

**Date:** 2026-09-04 · **Phase:** design conformance

**Context.** The handoff bundle (`Reconciliation tool UI mockups-handoff`) specifies a
"Gap by day" chart on the analysis screen and a sparkline of the same data on the
landing card. Neither was built. `globals.css` carries a `drawLine` keyframe with no
consumer, which is the fingerprint of the detailed view's expected-vs-received chart
being designed and never implemented either.

Nothing in the API could have served them. `Finding` and `Detail` carry no date, and
`GapComponent` carried a component total plus a list of order ids — enough to say
*what* explains the gap, not *when* it happened.

**Decision.** Attribute at the source, then bucket. `GapComponent` gains `per_order`,
recorded at each of the twelve sites where an amount is computed. `timeline.py` buckets
those by the order's capture date. No amount is derived twice.

That last point is the whole design. The alternative — recomputing per-order amounts
downstream from findings — is exactly how the fee row came to disagree with its own
drill-down by 162×. A second derivation of the same number is a second chance to get it
wrong.

**Three ways this chart could have lied, and what each cost to avoid.**

**1. Spreading what it cannot place.** In-flight settlements and orphan bank credits
have no ledger order, and an unrecorded refund is keyed by refund entity because the
absence of an order id is what makes it unrecorded. Prorating that money across days
would have produced a chart that balances and is fiction. It is returned as
`undated_paise` and printed under the chart: *"₹3,000.00 of the gap has no capture date
behind it and is not shown above."* On `qa-C` that line is exactly the unrecorded-refund
line, which is the correct and self-explaining answer.

**2. Colouring by magnitude.** The mockup colours tall bars amber. This product spends
its first sixty lines of CSS establishing that amber means money that needs a decision
and nothing else. A chart that made amber mean "big" would be the first place that
stopped being true, so `TimelineDay` carries `actionable_paise` — the verdict's own
materiality answer, handed over rather than recomputed, as ADR-054 requires of the
action list — and a bar is amber because that day needs a decision. A tall grey bar is a
busy day, not a problem.

**3. Zooming until the story looked better.** On a healthy cycle the gap is a few percent,
so cumulative expected and received very nearly coincide. Zooming the y-axis off zero
would have made the band look dramatic and would have been drawing a claim the data does
not support. The axis stays at zero and the distance is annotated at the right edge, so
the reader gets the quantity without the chart overstating it. `received` is derived per
day as `expected - gap` rather than summed from the bank side — the bank credits land on
settlement dates belonging to other days, and deriving it makes it structurally
impossible for the two lines to sit any distance apart other than the gap.

**Invariant.** `dated + undated == gap`, asserted on every build, in the same style and
for the same reason as `GapDecomposition.check()`. `tests/test_timeline.py` holds it,
holds that both cumulative lines total the figures printed at the top of the page, and
holds that a tall benign day never outranks a smaller day that needs a decision.

**What was NOT adopted.** The mockup's "Attached evidence" slots are a design-tool
affordance for dropping screenshots into a canvas. There is no such thing in the
product, and inventing an upload to fill a rectangle would be building the mockup rather
than the design.

---

## ADR-058 — A count and an amount that described different orders

An external QA pass reconciled nine runs against the built-in answer key and found the
maths sound: expected − received = gap = sum of lines, to the paise, in every run. What
it found broken was the reporting layer. Three of its eighteen findings are addressed
here; the rest are still open and listed at the end.

### F3 — the fee line contradicted its own drill-down

The verdict's fee row read "40 orders · ₹37,023.69" on `qa-C`. Expanding that same row
showed "40 orders · ₹227.90". A ratio of 162x under one label.

Neither number was wrong. They answered different questions:

* **The gap component** books the WHOLE fee — every rupee Razorpay kept — because that
  is money which genuinely left the merchant. 574 orders paid one.
* **The findings** carry the OVERCHARGE — the delta against the rate card — because a
  fee charged at the contracted rate is not a discrepancy and emits no finding. 40
  orders were overcharged.

`Ranker.rank` then took the count from one and the amount from the other:

```python
count=counts.get(classification, component.count),   # findings: overcharged orders
amount_paise=component.amount_paise,                 # component: the whole fee
```

The comment above it argued for preferring the finding count, on the grounds that "6
subscriptions" is a human fact while a component count is an accounting artefact. That
reasoning is right wherever the two populations coincide. For FEE they never do, and
pairing them produced a line describing no real set of orders at all. On `qa-B` — a
clean run — it claimed 250 orders and ₹31,310.75 while the drill-down was empty.

**The fix is not to pick one number.** Both are true and a merchant needs both: the fee
is what payment processing cost, and the overcharge is the only part that can be
disputed. The overcharge previously appeared nowhere in the UI, which the QA pass
correctly called the most commercially interesting number the engine computes.

So the fee line now counts the orders whose money it shows (574 · ₹37,023.69), and the
overcharge rides along as a `LineNote` — a figure ABOUT a line rather than another
contribution to the gap. That distinction is structural, not cosmetic: the overcharge is
a SUBSET of money already counted, so adding it as a component would double-count and
`GapDecomposition.check()` would fail. Nothing sums notes.

**Actionability.** `FEE` sits in `always_benign`, and that is correct for the fee — it
is the contracted cost of taking payments, and there is nothing to chase. It is wrong
for the overcharge, so the note is judged on materiality alone rather than through
`is_actionable`. The config entry now says which of the two it governs. The row stays
benign and unflagged, but prints the overcharge in the action tone when it is material:
an actionable figure hidden inside a collapsed benign row is the same defect, quieter.

**The test that had to change.** `test_line_counts_match_the_findings_behind_them`
asserted count == len(findings) for every line, and its docstring — "a wrong count is a
wrong claim" — is exactly the principle at issue. Its implementation assumed the two
populations always coincide, which is what forced the mismatched pairing. It now skips
FEE and a dedicated test pins the real invariant: the fee line counts at least as many
orders as were overcharged, the note matches the findings exactly, and the note never
exceeds the line it qualifies.

### F1 — both primary CTAs did nothing

"Send payment links" and "Mark reviewed", in the panel the entire product points at,
had no handler. No request, no state change, no label change. The QA pass wrapped
`window.fetch` and clicked both: `fetchCalls []`, `innerHTML changed false`.

The labels were also promises the product cannot keep — nothing here sends an email or
opens a dashboard. Both halves are now honest:

* **The label names what the click does.** Copying is the truthful verb: the work leaves
  the screen and lands in whatever actually does the chasing — a mail client, a
  spreadsheet, a support tool — none of which this product is.
* **What a group can offer depends on its data, not its name.** A group with customers
  behind it offers their addresses; `UNRECORDED_REFUND` is a correction to the books
  with nobody to chase, so it offers its order ids instead. The count is in the label,
  so the button says what you are about to get.
* **"Copied" is only claimed once the write resolves**, and reverts after two seconds so
  the control can be used again. A blocked clipboard says so — silence there would
  reintroduce the original defect.
* **"Mark reviewed" survives collapsing the card** (state lives in the parent) and is
  visible on the collapsed header: a reviewed group surrenders the TOP badge and the
  one repeating animation in the product, because both mean "start here". It is
  deliberately per-session and not persisted — claiming a review outlived a reload would
  be a second inert control in the other direction.

### F7 — the action table was unreachable on a phone

At 360px the detail table rendered 624px wide inside a 299px container, and the card's
`overflow-hidden` — which exists to clip the corner radius — meant no horizontal scroll.
The customer, reason and order id columns were simply unreachable, and the amount alone
is not something anyone can act on.

The scroll now belongs to the table rather than the card, with `-mx-5 px-5` so it runs
to the card's edges instead of stopping inside the padding and reading as a mistake.

### Still open

Fifteen findings remain, including three the QA pass rates above these: `unexplained`
is structurally incapable of being non-zero while the correlation section on the same
page names ₹2,480.00 outstanding (F2); 213 detected late settlements are never shown
(F4); and the scorecard reports 1.00 recall on a run that caught 72% of what was planted
(F5, F6). Also open: missing-source gating (F8), duplicated percentages (F9), rate-card
retroactivity (F10), heading semantics (F11), the raw error page (F12), unnamed early
refunds (F13), and the polish items (F14–F18).

**Numbering note.** Two entries above both claim ADR-054. Left as they are — renumbering
existing decisions would break every reference to them.

---

## ADR-059 — Four things the product said about itself that were not true

The second pass over the QA dossier. ADR-058 took the two findings it ranked first;
these are the next four, and they share a shape with those: the engine was right every
time, and the layer reporting on it said something else.

### F2 — a check that could not fail

The waterfall's closing row read "Unexplained — nothing in the data accounts for this —
₹0.00". It read that on every run ever made, including 2,500 orders with 849 planted
defects. Scroll down the same page and the correlation section said ₹2,480.00 was still
unexplained, and named the order.

`Verdict.unexplained_paise` was `GapDecomposition.residual_paise` — gap minus the sum of
the components. The components are *constructed* so as to close the gap, and `check()`
raises when they do not, so that number is structurally incapable of being non-zero. It
was decoration presented as a check, on a page whose whole promise is that every rupee is
accounted for.

Two different quantities had one name. They now have two:

* `unexplained_paise` / `unexplained_count` — the CORRELATION residual. Money that IS in
  the lines above but which no rule could attribute to a cause, after the payments and
  subscriptions files were brought in. It can be non-zero, and on `blind` it is.
* `residual_paise` — the decomposition's own residual. Still computed, still asserted,
  no longer displayed as though it were a finding.

**The bar had to change too.** `unexplained` was appended as a segment to the stacked
bar. That was harmless while it was structurally zero — it drew nothing. As the
correlation residual it is money already inside the lines, so drawing it would paint the
same rupees twice and the bar would no longer be the gap. The bar is now the lines, and
only the lines.

**Nine tests asserted `sum(lines) + unexplained == gap`.** That identity is real and
worth keeping — it just belongs to `residual_paise`. The test names already said
"residual", which is what the assertion was always reaching for. Only two of the nine
failed, on the batches where the correlation residual happens to be non-zero; the other
seven would have kept passing while asserting the wrong field.

### F4 — 213 late payouts detected, never mentioned

The engine classifies late settlements with full working — captured date, expected date,
actual date, working days late — and writes every one to the audit log. 41 on `qa-A`,
213 on `qa-D`. No TIMING line appears in any verdict, and the words "late" or "T+2"
appear nowhere in the analysis UI outside the collapsed audit trail.

There is a good reason for the missing line and it is worth stating, because it is why
this was never simply an oversight: money that settled late but HAS arrived is already
inside `received`. Its contribution to the gap is zero, and counting it again was the
original double-count `gap.py` was written to prevent. It cannot go in the waterfall.

Zero gap impact is not zero information. A merchant financing operations on money that
lands two days after it was promised has a working-capital problem whether or not it
nets out by the end of the cycle. So `LatePayouts` reports count, value delayed, median
and worst delay, and the cycle it was measured against — beside the waterfall, in a
panel that says in as many words that it is not part of the gap. No rupee is
double-counted, and nothing the engine detected is silently discarded.

Every figure is aggregated from proof the classifier already wrote. Nothing is
recomputed, for the same reason the fee overcharge is not recomputed downstream
(ADR-058).

### F5 — 1.00 recall on a run that found 612 of 849

`recall` is `caught / (caught + missed)`, which drops `below_tolerance` from the
denominator. That is defensible on its own terms: those are defects config declares
immaterial — a timing lag inside `grace_days` — and an engine is not wrong to stay
silent about them. But it makes the figure incapable of falling below 1.00 on any run
whose only misses are sub-threshold, and 1.00 is what it reported on every run tested.

Both are now reported, with strict as the primary. `recall_strict` is `caught /
planted`, forgiving nothing:

```
qa-D   strict 0.72   lenient 1.00   612 caught, 237 below tolerance
qa-A   strict 0.85   lenient 1.00   341 caught,  59 below tolerance
qa-C   strict 0.87   lenient 1.00   104 caught,  15 below tolerance
```

The tolerance window is printed alongside, because a recall figure without its
threshold cannot be argued with. The lenient figure is kept rather than deleted — it
answers a real question ("of what we were asked to report, how much did we get?") and
the two together say more than either alone. A judge who sees 1.00 everywhere concludes
the scorer is decorative; 72.1% beside a stated grace window is the more persuasive
number, and the only one that can go down when the engine gets worse.

### F6 — the answer key disagreed with a correct analysis

`healthy_subscription_decoy` plants orders with genuinely failed payments on
still-active subscriptions. They are not defects — the engine is supposed to decline to
claim them as halted subscriptions, and it does, on every run. But they produce real
`PAYMENT_FAILED` findings, and the key listed nothing at all for them: `defect_count: 0`
against 20 correct findings.

So the loop this product invites — generate a scenario, check whether we caught it —
reported phantom over-reporting on every run containing decoys.

Decoys now declare the findings they should legitimately produce. On `qa-decoy` the key
and the analysis now reconcile exactly: 20 reported = 0 real defects + 20 decoys.

**Scoped to decoys deliberately.** The obvious generalisation — counting
`expected_classification` across all planted defects — produces a number that is wrong
in a new way. A real defect's `expected_classification` is what the CLASSIFIER should
say, before correlation runs, and correlation then legitimately promotes some of them: a
MISSING order whose payment failed is reported as PAYMENT_FAILED, which is the entire
point of the correlation pass. Counting those would swap one misleading number for
another. With decoys accounted for, the remaining difference on `qa-C` and `qa-D` is
exactly the MISSING → PAYMENT_FAILED promotion:

```
qa-C   engine 18 = 6 decoys + 12 promoted from MISSING   (engine MISSING = 0)
qa-D   engine 100 = 50 decoys + 50 promoted from MISSING (engine MISSING = 0)
```

Nothing is unexplained, and the engine was correct in all three runs.

### Still open

Eleven findings remain: missing-source gating (F8), two percentages per line (F9),
rate-card retroactivity (F10), heading semantics (F11), the raw error page (F12),
unnamed early refunds (F13), and the polish items (F14–F18). F5's separate note about
`caught` being inflated by non-findings on `qa-split` — 20 split settlements the engine
correctly ignored, recorded as 20 caught — is untouched and needs its own decision about
what "catching" a non-defect should mean.

---

## ADR-060 — The remaining eleven, and the two that are worth more than a patch

Nine of the QA dossier's remaining findings are fixed here. Two are documented in
LIMITATIONS instead, because both need engine-wide changes disproportionate to what they
change on screen, and a hurried version of either would be worse than an honest note.

### F8 — a ledger-only upload was analysed as if every file were present

Uploading a ledger with no settlement, bank, payments or subscriptions file produced a
confident analysis: a 100% gap, "every rupee of that difference is accounted for below",
and "0 of 2 orders reached Razorpay". All three describe the missing file rather than the
merchant's money — nothing reached Razorpay because no Razorpay file was supplied.

The backend knew. `missing_sources` was computed at upload time and returned in the
upload response, then never surfaced again — and the analysis page is where anyone
actually reads a verdict. It is now computed on every read of the verdict, with the
`recon` case (which had no copy at all) named as the severe one, and rendered ABOVE the
figures. Below them it would be a footnote on a number the reader has already believed.

This is also the first-run path for anyone bringing their own data.

### F12 — the error page dumped internals

`/analysis/does-not-exist` rendered the backend string verbatim, including a Python list
literal of every batch on disk. Upload errors leaked absolute server paths with an
un-normalised `../` in them.

The 404 is now a sentence that names a few recent runs. The paths are trimmed to
basenames at the API boundary — not in the engine, which is right to name the file it
choked on, because a CLI user is the operator and needs it. The trimming happens where
the reader stops being the operator, and the rest of the message survives: "ledger.csv
has no header row. Refusing to read positionally." is still the fix instruction.

### F11 — no headings anywhere on the analysis page

Zero `h1`–`h6` elements. "WHAT NEEDS YOU", "Your rates", "How do I know this is true?"
were all styled `div`s, so a screen-reader user had no way to navigate the document.

`Eyebrow` now renders `h2` by default, which fixes most of the page in one edit, with
`as="div"` still available where it is genuinely a label — a heading outline full of
things that head nothing would be a new problem, not a fix. Two collapsible sections had
their headings INSIDE the button; a heading nested in a button is invalid and assistive
tech may drop it from the outline, so the heading now wraps the control instead.

The page `h1` is visually hidden. The design deliberately leads with the figures rather
than a title, and inventing a visible one to satisfy the outline would change the design
to fix an accessibility bug that does not require it.

### F17 — "One thing needs you this week: 2 no record at Razorpay at all."

`LINE_COPY`'s label is a descriptive phrase. It reads correctly as a row label and
ungrammatically with a count in front of it. A label and a countable noun are different
parts of speech, so `LINE_NOUN` now supplies the second: "2 orders with no record at
Razorpay". A classification absent from that map falls back to a shape needing no noun,
so a future addition degrades to clumsy rather than to broken — and a test asserts every
displayable classification has one.

The summary named the same line twice — "The largest line is X and it needs you; what
needs you this week is X" — whenever the largest line was also the actionable one and
there were no benign lines to take the other branch. That case now has its own clause.

### F9 — two percentages, forty pixels apart

The bar legend announced share of the positive-parts sum; the rows announce share of the
net gap. The dossier read this as a bug. It is not: the code documents why the bar uses
the positive sum — a signed denominator makes segments exceed the track they are drawn
in — and share of net gap is the honest figure for a row, since a refund line
legitimately goes negative.

Two correct percentages with two denominators and one word is still a defect, though. The
fix is to name the denominator in both places ("of the bar", "of the gap"), not to force
one number. Worth noting the bar's figure is `sr-only`: the reader hearing both was
always the screen-reader user, which is who this fix is for.

### F15, F16, F18, F14

The seed input reserves `11ch` so its own eight-digit default stops rendering as
"2026090". The volume error moved onto the field — it was already displayed, but at the
foot of a long form beside the disabled button, thirty rows from the input it was about.
The CSV download link is padded to the 24px WCAG 2.2 AA minimum (it was the only element
on the page that missed it), and `NumberInput` states `inputMode` rather than relying on
`type=number` to imply it.

For F14, the accessibility half only: `text-label` goes 11px → 12px and two badges 10.5px
→ 11px. The dossier also proposes collapsing fourteen type steps to six. That is a
restyle of every component for a cosmetic gain on a page whose contrast already passes at
139 of 139 text nodes, so it is not done here.

### Deferred to LIMITATIONS, with reasons

**F13 (early refunds have no line)** needs a new classification threaded through the
classifier, ranker, decomposition, scorer and golden files — with a rule that decides
early-vs-ordinary from settlement dates rather than the generator's label, since the
engine must reach it from data it would have in production. The arithmetic is already
correct; the line is honestly labelled, just less specific than it could be.

**F10 (a saved rate card rewrites sealed runs)** needs config hashing, manifest pinning,
and a decision about what re-analysis under a new card *is*. Our position is that it
should be a new evaluation with both visible rather than an overwrite — which makes batch
identity "the sources plus the config that read them" rather than the folder name. That
is a data-model change and deserves better than a patch.
