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
