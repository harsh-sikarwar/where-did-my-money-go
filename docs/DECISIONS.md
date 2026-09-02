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
