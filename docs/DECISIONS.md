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
