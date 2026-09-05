# The Build Story

*How "Where did my money go?" was designed, built, broken, fixed, and measured — front to
back, for a judge, a maintainer, or the author reading this back later.*

This document does not introduce new claims. Every number, ADR reference, and bug
description here is drawn from `docs/JOURNAL.md`, `docs/DECISIONS.md`, `docs/BROKE-FIXED.md`,
`docs/LIMITATIONS.md`, `docs/HOW-WE-KNOW.md`, `docs/METRICS.md`, `docs/BLIND-TEST.md`,
`docs/PRIOR-ART.md`, `PROJECT-CONTEXT.md`, `build-spec.md`, and `build-plan-3.5-days.md`. Its
job is to assemble those into one narrative that reads start to finish.

---

## 1. What this is

**"Where did my money go?"** is a Razorpay Buildathon Track 04 (AI Finance Controller)
submission: a reconciliation tool built around one product promise — a merchant uploads
their ledger and bank statement (or connects Razorpay's settlement/payment/subscription
data), and instead of opening on a wall of charts to interpret, they get a four-line
verdict that accounts for every rupee of the gap between what they expected and what
actually landed, tells them which parts are normal, and names the one thing that
actually needs their attention this week. The engine (`finctl`, a Python pipeline) is
deterministic end to end — matching, fee arithmetic, classification and correlation
never touch a language model — with a FastAPI wrapper and a 12-route Next.js dashboard
on top. The one place an LLM is used is to write two sentences of prose above numbers
the engine already computed, under a hard guard that discards any model output
containing a numeral.

---

## 2. The problem, in the merchant's terms

The brief that seeded this build (`PROJECT-CONTEXT.md`) frames reconciliation as a gap
between two records that should agree and usually don't quite: the merchant's own ledger
(what should have happened) and the settlement or bank record (what actually happened).
Almost every real discrepancy traces to something stuck or lost between four stages of
money — authorization, capture, settlement, reversal — and the common, legitimate causes
are boring: fees, timing (money that isn't missing, just two days late), refunds recorded
on one side and not the other, human error.

The sharper framing, and the one the product argues from, is that existing tools are
architecturally siloed. Recovery, reconciliation, and cost observability are treated as
three separate problems by the market (Hyperswitch, cited in `PRIOR-ART.md`, ships them as
three separate modules). An anomaly that spans two of those — a subscription that silently
stopped being charged, which is simultaneously a "missing settlement" problem and a
"payment recovery" problem — has no single owner, so it reaches the merchant labeled
"unexplained" even though the cause is knowable by joining data the merchant already has.
That join — failed-payment and subscription-lifecycle data used as *evidence* for an
unexplained settlement gap, not as a recovery feature in its own right — is the thesis, and
keeping recovery strictly evidentiary is also what keeps the submission inside Track 04
rather than drifting into Track 03 (recovery is explicitly Razorpay's own product).

The demo centerpiece names a specific, real, and easy-to-miss failure mode: Razorpay's
documented subscription lifecycle is `active → pending → halted`, and in the `halted`
state, **Razorpay keeps generating invoices but stops attempting charges.** Nobody is told
unless they are watching webhooks. Revenue dies quietly while the books look normal. This
is not an invented scenario — it's a documented Razorpay state — which is precisely why it
became the case the whole correlation mechanism is built to catch.

---

## 3. Origins and inspiration

`docs/PRIOR-ART.md` exists because of a specific piece of claims discipline recorded in
`PROJECT-CONTEXT.md` §10: *never* say "nobody does AI reconciliation" (Cointab, ReconPe,
Hyperswitch, and Microsoft all ship versions — a judge would be right to challenge it), but
*do* say openly that the architecture was informed by studying published prior art. Being
caught quietly reproducing someone else's design mid-demo is the bad version of that; naming
it up front is the strong answer to "how do you think." What follows is what was actually
taken from each, and what was deliberately left on the table.

### Hyperswitch (Juspay, Apache 2.0, ~42k GitHub stars)

Razorpay is one of its connectors. Hyperswitch ships three separate modules — Revenue
Recovery, Reconciliation, and Cost Observability.

**Taken:** the staging-entry model (rows ingested, validated, but not yet reconciled, and
held immutable — this is what makes a re-run safe and an audit trail possible; without it, a
second run mutates the evidence of the first) landed directly as `finctl/stage/`. The
exception status taxonomy — `Pending · Reconciled · Exception · Partially Reconciled ·
Archived · Void` — was adopted verbatim rather than invented, on the reasoning that an
established vocabulary is cheaper and more defensible than coining a new one, with the rule
that `Partially Reconciled` is only ever set by a human, never the engine (a machine that can
mark its own work partially done will use that state to hide uncertainty). Separating
rule-evaluation from ingestion (`normalize`/`stage` vs. `classify`) also came from
Hyperswitch's structure, so classification rules can change without re-ingesting.

**Deliberately not taken:** the three-module split itself. That split *is* the thesis this
project argues against — recovery, reconciliation, and cost as separate products means an
anomaly spanning two of them has no owner, and the correlation stage exists specifically to
cross that boundary Hyperswitch draws. Also not taken: connector abstraction, multi-gateway
support, and the full deployment topology — all named as deliberate cuts.

### Cointab

Razorpay fee and tax verification, commercial.

**Taken:** the Side A / Side B ingestion model — merchant's record vs. counterparty's
record, reconciled against each other rather than either one treated as ground truth. Ledger
is Side A, settlement/bank is Side B. More importantly, the principle **"leave items
unmatched when evidence is weak"** landed directly as the `NEEDS_REVIEW` classification: a
forced match is worse than an admitted gap, because it converts a visible problem into an
invisible one — which is why the classifier emits `NEEDS_REVIEW` when more than one rule
fires, instead of silently picking the highest-scoring one.

**Deliberately not taken:** Cointab's operator-centric UI model. It builds for a finance
operator who lives in the tool all day; this builds for a merchant who opens it for two
minutes on a Monday. Same underlying data, opposite default screen.

### ReconPe (₹3,999/mo)

Rate-card audit plus AI column mapping.

**Taken:** rate-card audit as a first-class idea — the question is not only "did the money
arrive" but "was the fee charged the fee that was actually contracted." This directly
motivated the `FEE` and `TAX_ON_FEE` classifications and, much later in the build, the
merchant-supplied rate card (ADR-046).

**Deliberately not taken:** AI column mapping. ReconPe does it well, but for this build it
would consume time the correlation loop needed more, and — more importantly — it sits
squarely in the "AI where determinism would do" category the project's own AI-usage table
argues against. Named as a deliberate cut, not an oversight; the substitute that shipped
instead (ADR-045, "refuse once, then remember") is discussed in §6.

### Terra Insight

Publishes its matching recipe openly.

**Taken:** the benchmark number — manual VLOOKUP reconciliation lands around a **51% match
rate**; structured tooling reaches **88%+**. This became the yardstick the project's own
match rate is read against, on the reasoning that a match rate reported with no baseline
means nothing. It is also the source of an important caveat carried into `METRICS.md`: this
engine's match rate is an *exact-identifier* rate with zero fuzzy matching (ADR-015), which
is a stricter measure than the ones the 51%/88% figures describe, so it isn't a
like-for-like comparison unless that's stated — and it is, everywhere the number appears.

### Razorpay's own documentation and terms

Not a competitor's product, but a primary source that shaped more of the engine than any of
the above. The canonical schema mirrors Razorpay's own field names (`utr`, `settled_at`,
`error_reason`, `entity_id`) so that swapping seeded data for live API data is a *source*
change, not a *schema* change (ADR-008). The `amount`-in-paise convention was adopted
directly (ADR-003). The `halted` subscription lifecycle is Razorpay's own documented state,
not an invented scenario. And Razorpay's own recon documentation contains a genuine internal
ambiguity — its prose says `Net = Gross − MDR − GST on MDR`, implying `credit = amount − fee
− tax`, while its own published example response shows `credit = amount − fee` with `tax:
0` — which the engine resolves not by picking a reading but by deriving the convention from
the data and refusing an inconsistent batch (ADR-007; more in §5 and §7). Finally, Razorpay's
own T&C state that the merchant is contractually responsible for daily reconciliation, with
discrepancies reportable within three days — which is the strongest available answer to "why
doesn't Razorpay just do this for you."

---

## 4. Architecture overview

### The pipeline

The engine (`engine/finctl/`) is organized as one subpackage per pipeline stage, visible in
the file tree from the start of the build: `generate → normalize → stage → match → classify
→ correlate → rank → explain`, plus supporting modules `config`, `audit`, and `adapters`.
Concretely, on disk today:

```
config/     rate cards, tolerances, archetypes — YAML, never constants
generate/   seeded synthetic data + machine-readable ground truth
normalize/  arbitrary columns → canonical schema, integer paise, UTC
stage/      immutable staging entries, content-hash duplicate detection
match/      two-pass matcher: Order→PSP, PSP→Bank
classify/   deterministic rules, arithmetic proof on every row
correlate/  the differentiator — joins unexplained gaps to failed payments and halted subs
rank/       materiality: benign vs. actionable
explain/    the only stage that calls an LLM — prose only, never a number
adapters/   live Razorpay API (timeboxed, cuttable)
audit/      JSONL decision log
```

Alongside those: `money.py` (integer-paise arithmetic core), `fees.py` (MDR + GST
arithmetic), `gap.py` (the signed gap decomposition — ADR-024, the single most important bug
fix in the project, covered in §7), `cycle.py`/`calendar.py` (settlement timing, including
observed-vs-configured cycle detection), `score.py` (scoring against ground truth),
`matrix.py` (the metrics matrix runner), `blind.py` (blind testing), `actions.py` (the
projection that names customers to chase), `timeline.py` (day-by-day gap attribution for the
dashboard's chart), and `pipeline.py` — the single `run()` function that both the CLI and the
API call, so there is exactly one implementation of "what does reconciling a batch mean" in
the whole project (ADR-001).

### The deterministic-engine-plus-AI-explains-only split

This split predates any code — it's ADR-000, inherited from `PROJECT-CONTEXT.md` §3 — and it
survived the entire build unmodified. The reasoning, stated as plainly as the project ever
states anything: **an LLM must never decide whether two numbers are equal.** Matching, fee
arithmetic, classification, correlation, and materiality ranking are all deterministic rules
with arithmetic proof attached to every row. The one place a model is used is the two-sentence
summary written above the verdict lines (and, in the dashboard, chat answers), and even there
the model is never shown a number — it's given facts described by rank ("largest line,"
"needs action") — and any response containing a digit or number word is discarded whole,
falling back to a deterministic template (ADR-050). This is enforced in code, not by
convention: `LLMConfig.from_env()` is the single place in the project that decides whether a
model runs, `--no-llm` / `FINCTL_NO_LLM` closes every path through it, and the engine
installs with zero LLM dependencies unless the optional extra is requested. Recommended
actions are deliberately *not* AI-generated either — `NEXT_STEP` is a fixed string per
classification in `actions.py`, on the reasoning that routing already-correct copy through a
model adds a failure mode to a sentence that's already right.

### The API layer

`api/main.py` is intentionally thin — 1,481 lines, but structurally a wrapper: every route
calls `pipeline.run()` (cached per batch) and serializes the result, with no independent
reconciliation logic. The route table covers health, batch listing, the verdict, per-line
drill-downs, correlation before/after, scoring, the audit log, per-order trace, read-only
rule inspection, and the guarded copilot chat endpoint. Several ADRs (ADR-040, ADR-047,
ADR-049, ADR-053, ADR-054) exist specifically because a second caller of shared logic — the
upload path, the rate-card change path, the action list — was, at some point, quietly *not*
calling the same function as the first caller, and produced a different answer. The project's
running fix for that class of bug is structural: reduce to one computation and have every
consumer read from it, rather than trust two call sites to stay in sync.

### From one page to a 12-route dashboard

The original UI design (ADR-023, phase 2b) was deliberately a single scrollable page —
verdict, then correlation, then audit, in one layered scroll — on the argument that a
2-minute demo is a story told by scrolling, not a feature tour interrupted by navigation. That
was the right call for the shape the product had at the time.

It didn't survive contact with the fuller brief. As upload, column mapping, a merchant's own
rate card, the action list, and per-order tracing were built out (documented across
ADR-044 through ADR-049), the product grew a runs list, a new-run wizard, rules and settings
screens, and per-order trace views that don't compress into one scroll without becoming a
very long page. On 2026-09-05, alongside deploy prep and demo documentation, the single page
was rebuilt into a 12-route dashboard under `web/app/(dashboard)/`:

```
/                          Overview (replaces the old landing page)
/runs                      List of all runs/batches
/new-run                   Wizard for upload and generation
/analysis/[batch]          Full breakdown: Summary / Line items / Evidence
/exceptions/[batch]        Exception queue (actionable + unexplained findings)
/orders/[batch]/[orderId]  Single order detail / trace view
/audit/[batch]             Audit log, grouped by day
/sources/[batch]           Data sources / missing-sources view
/settings                  Rate card settings
/rules                     Read-only tolerances, rate card, defect taxonomy
/reports/[batch]           Composed client-side from verdict, actions, audit
/copilot/[batch]           Full-page chat interface (also a docked drawer)
```

ADR-023 records this explicitly as superseded rather than deleted: the scrolling-story
argument was right for what the product was in phase 2b, and the route-per-concern argument is
right for what a submission judges click through on their own, without a presenter. Audit,
correlation, and order trace moved from inline sections to dedicated routes. The route table
above matches the shipped dashboard, confirmed against the actual `web/app/(dashboard)/`
directory structure at the time of writing.

---

## 5. Timeline through the build

**2026-09-02, Phase 0 — foundations.** The day started with `git init`, and — deliberately
before any Python — `.gitignore` and `.env.example`, because a key committed and later
deleted is still in git history (ADR-002). The three planning documents were written to disk
from conversation context and, in the process, a mojibake bug was caught and fixed (`â¹`
where `₹` belonged) before it could quietly propagate into LLM prompts and UI copy later. The
Python project skeleton was built with `uv`, one subpackage per pipeline stage, empty but
named so the architecture was visible in the file tree from commit one. A smoke test kept the
suite green from day one. `uv` resolved pandas 3.0.5 rather than 2.x — accepted rather than
pinned back, since the engine holds money as integers and doesn't rely on the mutation
patterns pandas 3 changed (ADR-005).

**Phase 1 pre-work — the shape probe.** Before writing a line of the generator, the plan
called for looking at one real Razorpay API response — "verification, not foundation"
(ADR-006). It earned its keep immediately: three schema errors surfaced in the brief's own
sketch. `payment_id` is null on payment rows (the real field is `entity_id` — this alone would
have produced a 0% match rate and every order reading `MISSING`); refunds are their own
type-discriminated rows, not a column; and the fee/tax relationship in Razorpay's own
published material was internally ambiguous (§3, ADR-007). None of these would have been
caught by unit tests, because the tests would have asserted the same wrong assumption the
code did — which is exactly the class of error the probe existed to catch before it could
hide.

**Phase 1a — the config layer.** Every rate, tolerance, and threshold went into YAML before
any engine logic existed, specifically so a hardcoded fee constant would be impossible rather
than something to clean up later. A real near-miss happened here: test-mode Razorpay keys
were pasted into `.env.example` (git-tracked) instead of `.env`. Caught before any commit,
and the pre-commit hook was tightened afterward to block real-looking keys in any
`*.example`/`*.sample`/`*.template` file, test-mode included — a gap found through an actual
close call rather than imagined in advance. The core arithmetic decision here was integer
basis points for rates (ADR-010), so that no float ever touches a money value anywhere in the
engine — a property the project can state flatly rather than merely believe.

**Phase 1b — the seeded generator.** The generator computes fees using the engine's own
`expected_fee()` function rather than an independent implementation (ADR-013) — a decision
that looks circular and isn't: two independently-written fee implementations by the same
author on the same day would likely share the same misunderstanding, and a phantom
"agreement" between two wrong implementations is worse than testing one against an external
worked example (which `test_fees.py` does, against the brief's own numbers). The fee
convention question from ADR-007 was still unresolved, so the generator was built to emit
*either* convention as an explicit parameter and tested against both — turning an unanswered
external question into a tested internal capability (ADR-014). Golden-file tests were
deliberately proven capable of failing by injecting a fake regression (a fee rate bumped from
200 to 210 bps) and confirming the test caught it, before trusting it as a safety net.

**Phase 1c — the Day-1 checkpoint.** The build plan's whole go/no-go gate: "unexplained
before ≠ unexplained after, printed to a console. If this doesn't work, everything downstream
is decoration." It worked — but the first run reporting 100% correlation was, in the author's
own words, the moment to be suspicious rather than pleased. Checking per-defect-type revealed
zero of eight planted refunds had actually been detected; the metric was real but vacuous,
measuring the wrong denominator. Two real bugs were behind it (the generator recording a
refund without writing it into the data, and the refund's sign being backwards in the
classifier). After both fixes: 8 of 8, exact to the rupee. This phase also produced ADR-015
(no fuzzy matching, ever) and ADR-019 (correlation requires the identifier join to *land*, not
merely resemble) — both discussed further in §6.

**Phase 2 — the verdict screen did not add up.** The single most consequential bug in the
project's history, and it was found by a human reading the screen, not by any of the 345
tests passing at the time. The four verdict lines summed to ₹99,421.65 against a ₹38,372.30
gap. The root cause was a category error — `Finding.amount_paise` meant a different thing for
each classification (the overcharge for `FEE`, the whole order for `TIMING`, a magnitude for
`REFUND`), and they had been treated as commensurable. The fix was `gap.py`: a signed
decomposition computed directly from matched data, asserted on every run, that raises rather
than silently rebalancing. This is covered at length in §6 and §7 because of how much it
shaped everything downstream — the project's own phrase for it is "every number traces back
to a Razorpay record was true; it was not sufficient."

**2026-09-03 — Test day, and it kept finding real bugs.** The metrics matrix ran 22
configurations (later 26), planting and scoring tens of thousands of defects with zero
missed and zero false positives. But the day's real value was the adversarial and
composition-audit work run alongside it: duplicated ledger rows leaving ₹7,305.71
unattributed (ADR-025), an empty batch raising instead of answering (ADR-026), split
settlements exposing a ₹0.02 rounding artifact that led to per-leg tolerance scaling
(ADR-028), and a 2.6× throughput cliff at 50,000 rows that profiling (not guessing) revealed
was an O(n²) scan inside the *test harness's scorer*, not the engine (ADR-029) — a benchmark
bug that had been making the project's own numbers look worse than the engine actually was.
Blind testing (running the engine against a configuration the author had committed
predictions about in writing, before seeing the answer key) passed cleanly except for one
defect type scoring zero — which led to discovering the classifier was judging every batch
against a *configured* T+2 cycle regardless of what the batch had actually done (ADR-030),
invisible to 22 green matrix runs because the matrix only sampled T+1 and T+2, where
configured and observed cycles happen to agree. Hand-edited blind batches (three `sed` edits
at a time) then found two bugs no generated data ever could, because the generator's own
construction order made the shapes structurally unreachable — orphan settlements (ADR-031)
and a zero-amount ledger row misclassified as a refund (ADR-033). The day closed with
obtaining Razorpay's own twelve sample report exports, which falsified four assumptions in
about twenty minutes, including a live date-parsing bug that silently produced 1970-01-01
(ADR-037) — covered in detail in §7.

**2026-09-03, later — building out the merchant-facing surface.** Once the engine's
correctness was well-tested, the build turned to making the tool actually usable by someone
who isn't its author: real file upload (`.xlsx`, because that's what Razorpay's dashboard
actually produces, not `.csv` — ADR-043), a column-mapping flow that asks a human once and
remembers the answer by file shape rather than guessing (ADR-045), a merchant-supplied rate
card layered over the shipped standard one (ADR-046), and — after those three flows were
built, tested, and completely unreachable because the page still hardcoded `const BATCH =
"demo"` — actual screens for all of it (ADR-047), which immediately surfaced a caching bug
(`_load` wasn't threading the mapping store through on cache-miss reads) that only a
three-step browser sequence (upload → change something → drill down) could expose. The action
list — naming the six customers the verdict had always referred to but never named — was
built the same day (ADR-048), and correlation grew from one mechanism to three: halted
subscriptions, disputes, and withholding, with an explicit precedence order because a
disputed payment on a halted subscription is *both* things and only one has a clock running
on it (ADR-049).

**2026-09-04 — external critique, and fixing what it found.** An outside pass over the
running product found that the action list disagreed with the verdict — on amounts (ADR-053)
and on which rows counted as actionable at all (ADR-054) — and that the README claimed an LLM
wrote the explanations when `finctl/explain/` was a one-line stub with no model call anywhere
in the codebase (ADR-050, covered in §6). Both were corrected rather than defended; the
explanation-stage row in the AI-usage table read **Not built** for a day before the real
stage was built and the claim earned back. A QA dossier (eighteen findings total, addressed
across ADR-058, ADR-059, ADR-060) then found that individually-correct numbers were still
being *presented* wrongly in several places — a fee line disagreeing with its own drill-down
by 162×, two primary buttons with no click handler, an "unexplained" figure that was
structurally incapable of ever being non-zero, a recall metric that read 1.00 on a run that
caught 72% of what was planted. Sixteen of eighteen findings were fixed; two were deliberately
deferred to `LIMITATIONS.md` because closing them properly needs engine-wide changes (a new
classification threaded through five subsystems for early refunds; a config-hashing and
batch-identity redesign for rate-card retroactivity) rather than a patch.

**2026-09-04–05 — Razorpay's own file, deploy, and the dashboard rebuild.** Running the
engine's central arithmetic identity directly against Razorpay's own sample settlement recon
export (not just reading it for schema, but computing against it) found two more bugs
invisible to 825 internal tests — a weaker date parser being called on one code path, and a
timezone bug that silently shifted midnight-adjacent settlement dates backward by a day on an
IST machine (ADR-056). The project was then deployed (Render for the API, Vercel for the web
app, discussed in §10) and, on 2026-09-05, the single-page UI was rebuilt into the 12-route
dashboard described in §4.

---

## 6. Key architecture decisions

The full decision log runs to 60 ADRs; the ones below are the ones that most shaped the
project or were most hard-won.

**ADR-003 — Money is an integer count of paise, everywhere, no exceptions.** The engine's
entire output is a claim that numbers add up, and its core arithmetic (GST on MDR) is a
percentage of a percentage — exactly where binary floating point drifts. Rupee strings are
parsed to integer paise at the normalize boundary and never converted back until display.
Chosen because the engine has its own `ROUNDING` classification, and if float drift could
manufacture a spurious rounding "defect," the engine could never distinguish its own
numerical noise from a real merchant discrepancy.

**ADR-007 — The fee/tax relationship is derived from data, not assumed.** Covered in §3 and
§5: Razorpay's own documentation and its own published example contradict each other on
whether `fee` includes GST or not. Rather than guess, the engine tests both possible
identities against every settled row in a batch, picks whichever holds consistently, records
the verdict in the audit log, and **raises if neither holds or the batch is mixed.** This
converts a silent, systematic, GST-sized error into a loud failure at ingest — the same
discipline `BEHAVIOR.md` demands everywhere else, applied to the single number the whole
product depends on.

**ADR-015 — Matching is identifier-only; no fuzzy matching, ever.** The tempting shortcut —
matching on amount and date proximity when an identifier join fails — was explicitly refused.
Two ₹4,999 orders on the same Friday are indistinguishable by amount and date, and a wrong
fuzzy match produces a reconciliation that is *confidently* wrong: totals balance, the match
rate looks excellent, and one customer's payment has been silently attributed to another's
order, with nothing signaling it needs investigation. An honest unmatched row can be
investigated; a confident wrong match cannot. This costs headline match rate — which is the
correct trade for a product whose promise is "every number traces back to a Razorpay record."

**ADR-020 — Materiality is a config policy, and REFUND is benign.** The ranker's first run
put one-sided refunds in the *actionable* list purely because they weren't explicitly
categorized and fell through to a size threshold — re-introducing amount as the deciding
factor, which the whole ranking design exists to reject. The fix made every classification an
explicit, enum-validated entry in a benign/actionable list, on the principle that the real
test is "does a human need to DO something this week," not "is this a discrepancy" —
everything on the screen is a discrepancy by definition.

**ADR-022 — The audit log summarizes reconciled rows, and only those.** `BEHAVIOR.md`
promises the audit stage "refuses to summarize," but a 5,000-row batch is ~95% cleanly
reconciled, and one event per correctly-settled order would bury the interesting ~5% in noise.
Resolved by distinguishing what the refusal actually protects: *decisions*. A `RECONCILED`
row is the absence of a decision — no rule fired — so collapsing those into a count doesn't
violate the contract; if the engine ever makes a real decision about a reconciled row, that
decision still gets logged individually.

**ADR-024 — The verdict is built from a gap decomposition, not a sum of findings.** The bug
this fixes is narrated in §5 and §7. The structural fix: `finctl/gap.py` computes a **signed**
decomposition directly from matched source data, with the identity `gap = fees_kept +
never_arrived + in_flight − settled_above_ledger + residual` asserted and raising on every
single run. `residual_paise` is computed, not assumed — if a future change breaks the
identity, the residual surfaces as "we can't explain," turning a silent wrong number into
visible honesty. This is the decision most explicitly tied to the project's own thesis:
individually correct, individually traceable numbers can still be assembled into a false
statement, and the assembly needs its own invariant.

**ADR-027 — Composition invariants are verified by mutation, not by passing.** After
ADR-024, the obvious risk was writing an assertion that passes trivially. Every composition
invariant was instead verified by deliberately reintroducing a bug (flip the refund sign back,
understate the fee total by exactly ₹1, off-by-one a line count) and confirming the suite
catches each one — the ₹1 catch is the meaningful result, since it proves the assertions are
exact rather than approximate.

**ADR-042 — The decoy is what makes "0 false positives" a claim about the engine.** For most
of the build, "0 false positives across 22 matrix runs" was a weaker claim than it sounded,
because every gap in generated data has a real cause — an engine that flagged everything would
still score zero false positives there. The fix was planting a **failed payment on a healthy
subscription** — identical surface shape to the halted-subscription centerpiece, differing
only in `status`, `auth_attempts`, and `error_reason` — and scoring whether the engine
resists claiming it as `HALTED_SUBSCRIPTION`. Result, cited throughout the project's
credibility material: 2,254 decoys planted across 24 of 26 matrix runs, **0 claimed**, false
attribution rate 0.0000.

**ADR-046 — The rate card must be the merchant's, or the fee check answers the wrong
question.** The shipped rate card answers "was this the standard rate," and a merchant
contracted at a different rate (very common — enterprise and negotiated pricing exists) would
see *nothing* from the engine even while being genuinely overcharged, because the standard
rate is exactly what the engine expected. Fixed by layering merchant-supplied rates over the
shipped card rather than replacing it, so a renegotiated UPI rate doesn't require restating
GST and every other method (each restatement being one more chance to introduce a silent
error). A refusal was kept intact even here: a rate over 100% (a likely unit-entry error,
"2" meaning 2% typed where 200 bps was meant) is refused with a message naming the unit.

**ADR-050 — The explanation stage, and where a model is allowed to be wrong.** Discussed in
§4 and §5: this is both the decision to finally build the LLM stage the README had prematurely
claimed existed, and the decision about exactly how far to trust it. The rule: no figure a
merchant reads ever comes from the model. It's shown facts described only by rank, never a
number; `guard()` discards the entire response if it contains a digit or number word (not just
the offending sentence, because a "clean" surviving sentence was written believing an invented
figure was true and would still be wrong); and the fallback deterministic template is the
*default* path, not an error path — no key, no network, a timeout, and a guard failure all
produce the identical, correct-by-construction template.

**ADR-053/054 — Two more instances of the same failure class, in the action list.** The
action list summed `finding.amount_paise` the same way the pre-ADR-024 verdict had —
disagreeing with the verdict by ₹1,094.72, with one line differing in *sign*. Worse, the test
guarding it (`test_the_totals_match_the_findings`) asserted the buggy quantity as correct,
which is a genuine pattern worth naming: a test that restates the implementation's own rule
cannot detect that the rule is wrong. The fix made `actions.build()` take the verdict's own
`GapDecomposition` as an argument rather than re-deriving a second opinion — one computation,
two consumers, the same discipline ADR-001 states for the CLI and API generally.

**ADR-023 (superseded) — the dashboard pivot.** Documented at length in §4: originally one
scrolling page, deliberately rebuilt into 12 routes once the product's actual surface area
(runs list, wizard, rules, settings, per-order trace) stopped fitting a single scroll. Both
the original reasoning and the reversal are kept on record rather than the ADR being edited
in place, because the point of a decision log is to show *why* something changed, not just
that it did.

---

## 7. Debugging war stories

**The fee-convention ambiguity, caught before it shipped (ADR-006/ADR-007).** Razorpay's own
recon documentation states `Net = Gross − MDR − GST on MDR`, implying tax is subtracted
separately from fee. Its own published example response shows `credit = amount − fee` with
`tax: 0` — inconsistent with that formula if `fee` were MDR-only. Found by the shape probe,
before a single line of matcher code existed, by the simple act of reading the actual
documented response rather than trusting the prose above it. Had this gone unnoticed, every
card transaction would have been wrong by the GST amount in the merchant's favor, absorbed
silently into the "we can't explain" bucket — the exact failure mode the product exists to
detect, occurring invisibly inside the product itself.

**The verdict screen did not add up (§5, ADR-024).** Found by a human — the project's own
author — looking at the four-line verdict and noticing ₹30,501 + ₹603 + ₹23,628 + ₹27,208 +
₹17,481 does not equal ₹38,372. It was off by ₹61,049.35. 345 passing tests had not caught it
because every individual number was independently correct and independently tested; nothing
tested that the lines, assembled together, equaled the thing they claimed to explain. The
project's own retrospective line on this: *"I built a verdict screen and never once checked
that its lines summed to its own headline number. It was visible on the very first screenshot
I took, and I looked at that screenshot and judged the layout."*

**Duplicated ledger rows and an empty batch, found by running the adversarial cases
(ADR-025/026).** Not reasoned about — run. Duplicating five rows in a ledger left
₹7,305.71 unattributed because the matcher joined each duplicate copy to the same settlement,
double-counting its fee and settled amount; the fix treats every copy after the first as
"phantom expectation" the merchant's own books are wrong about, rather than duplicated money.
Separately, two empty CSVs hash identically, which tripped duplicate-file detection and raised
an exception instead of correctly answering "nothing to reconcile" — fixed by skipping
duplicate detection for zero-row sources, since an empty file carries no evidence of ever
having been uploaded.

**Two bugs that only three `sed` edits could find (ADR-031, ADR-033).** After 22 matrix runs
and 500+ tests, three deliberate hand-edits to a blind batch — delete two ledger rows, zero
out one amount — found two real bugs that no amount of generated data ever could, because the
generator's own construction order made the shapes structurally unreachable: it writes the
ledger *first* and derives settlements from it, so "settled money with no ledger row behind
it" cannot occur in generated data, and ticket sizes are drawn from a range with a positive
minimum, so a zero-value order is impossible to generate. Deleting rows left −₹16,992.29
unaccounted for (an "orphan settlement" the decomposition didn't know how to book); zeroing an
amount got classified `REFUND` when the correct answer was `UNEXPLAINED` — reporting a refund
that never happened is a *false statement*, strictly worse than an honest "can't explain."

**Excel serial dates read as epoch seconds — a silent trip to 1970 (ADR-037).** Found by
obtaining Razorpay's own twelve sample report exports and simply reading them. One column of
one file mixed two date encodings — `44658.44689814815` (an Excel serial) on one row and
`29/06/2022 07:34:39` on the next, in the *same column of the same file*, because a
spreadsheet writes whichever representation the cell format dictates. The parser's first
branch checked `text.isdigit()` and, on `"44658"`, parsed it as epoch seconds:
**1970-01-01**. It did not raise — it produced a *plausible* date, which propagated silently
into three places: the order looked ~52 years late and filed as the benign `TIMING` bucket
(making a real anomaly disappear), the observed settlement cycle for the whole batch was
corrupted, and the verdict screen would have described it as "money on its way" — the exact
opposite of true. It went unnoticed by 553 tests because the generator only ever emits epoch
seconds, so no generated batch could reach that code path. Fixed with a disjoint-range test
(Excel serials and epoch seconds are four orders of magnitude apart for the same real dates)
rather than trusting the file extension, since a CSV exported from Excel carries serials too.

**A refund with a blank order_id made money vanish (ADR-039).** Also found in Razorpay's own
sample file: a `type: refund` row with a blank `order_id`. The matcher's very first line was
`if not row.get("order_id"): continue` — correct for an unattributable *payment*, silently
catastrophic for a *refund*. Reproduced directly before fixing: a real settlement-side refund
on a batch the engine confidently reported as fully `RECONCILED`. Money left the account and
no stage of the pipeline ever saw the row. Fixed by adding `UNRECORDED_REFUND` as its own
classification and its own gap component — deliberately not folded into the existing benign
`REFUND` line, because doing so would have made the finding arithmetically correct but
practically invisible (a merchant reads `REFUND` and moves past it).

**The UPI rate was hardcoded at the wrong number, and the config layer's own safety net
enforced it (ADR-035).** Not found by any test, matrix run, or blind pass — found by reading
Razorpay's own published pricing page. "UPI carries zero MDR" is a true legal fact about
interchange; the engine had encoded it as "UPI carries zero *fee*," which is false, because
Razorpay charges a ~2% platform fee on UPI transactions despite the zero MDR. Worse, the
config loader's own validation guard — built to *prevent* a hardcoded wrong rate — had been
written backward and actively enforced the error, raising if anyone tried to set a non-zero
UPI rate. 22 passing matrix configurations never caught it, for the same structural reason
several other bugs went unnoticed: the generator computes fees using the engine's own fee
function (ADR-013), so the generator and the classifier were wrong together, in perfect
agreement, and no internally-consistent test could see it. Only an external fact — a
pricing page neither side of the test suite had read — could.

**Ten real rows, two more bugs, after 825 internal tests (ADR-056).** Running the engine's
own core arithmetic identity directly against Razorpay's ten-row published sample recon
export — not reading it for column names, but actually computing against it — found a weaker
date parser being called on one code path (raising a bare, unhelpful `ValueError` on a real
date string instead of the engine's own well-formatted error) and a timezone bug: `openpyxl`
returns naive datetimes, and calling `.astimezone(UTC)` on a naive value silently interprets
it as *local* time, shifting a settlement timestamped near midnight backward by a day on an
IST machine. The same batch would have reconciled differently in Mumbai than in London. Ten
rows were enough to find what a much larger internal test suite could not, because they were
the first data in the whole project's history that the project itself hadn't authored.

---

## 8. How correctness was verified

The credibility argument (`docs/HOW-WE-KNOW.md`) is explicit that this is a different kind of
document from engineering documentation — it states what's backed by strong evidence and what
is honestly limited, side by side.

**The test matrix.** 26 configurations — volume (50 to 50,000 orders, i.e. 173 to 151,283
rows) × archetype (D2C e-commerce, SaaS subscription) × payment mix (UPI-heavy, card-heavy,
even) × settlement cycle (T+1 through T+7, with T+3 and T+7 added specifically after ADR-051
found that sampling only T+1/T+2 had hidden a scorer bug for 22 runs) — plus two edge
profiles (`clean`, `chaos`). Across all 26 runs, from `docs/METRICS.md`: **29,070 defects
caught, 0 missed, 0 false positives, balance identity holds in every run.** Throughput is flat
from 50 to 50,000 rows at roughly 60,000 rows/second after the scorer's O(n²) bottleneck
(§5, ADR-029) was fixed — the project states plainly that it has not found the engine's
actual breaking point at the scale this product targets.

**The decoy mechanism.** 2,254 deliberately planted adversarial payments — failed payments on
*healthy* subscriptions, engineered to look exactly like the halted-subscription centerpiece
— across 24 of the 26 matrix runs. **0 claimed.** False-attribution rate 0.0000. This is the
number the project treats as more important than the raw false-positive count, because a
missed defect is a coverage gap while a false attribution is the engine telling a merchant
something untrue.

**Blind testing.** The engine reconciling a batch whose configuration and planted defects it
has never seen, scored against an answer key that was moved outside the project directory
before the run and integrity-checked by SHA-256 receipt afterward (`docs/BLIND-TEST.md`).
Multiple rounds passed cleanly; one round found the T+2-cycle scoring bug (ADR-030); two
rounds of deliberate hand-editing (three `sed` edits at a time) found two bugs no generated
batch could reach (§7, ADR-031/033).

**Real Razorpay sample data.** The engine's central identity — `credit − debit == amount −
fee − tax` — computed in integer paise against Razorpay's own ten-row published settlement
recon sample, holding on all nine payment rows and correctly *not* holding on the tenth (the
refund row, which nets negative by design, proving the identity is meaningful rather than
vacuous). Found two parsing bugs in the process (§7, ADR-056).

**What is explicitly not yet tested.** `docs/LIMITATIONS.md` and `docs/HOW-WE-KNOW.md` are
both unambiguous about the boundary: **no real merchant batch has ever been reconciled.**
Every accuracy figure above is measured against data this project's own generator produced,
where the generator defines truth — a closed loop that structurally cannot report a defect
class nobody thought to generate. The decoy tests a confusion the project designed; it does
not prove resistance to one it didn't imagine. The live Razorpay fee convention (ADR-007) was
never confirmed against a live account with real settlement data, because the test account
processed zero transactions during the build (ADR-011, ADR-012) — this remains an open
assumption, not a hidden one. The correlation mechanisms added for disputes and withholding
(ADR-049) have unit test coverage of the shapes real exports produce, but are not exercised
by the matrix, because the generator has no batch where a disputed payment sits behind an
unmatched order — the residual is zero on every profile by construction of the generator, not
proof the correlator is complete.

---

## 9. Known limitations, stated honestly

**No real merchant batch has ever been reconciled.** Stated first in `LIMITATIONS.md`
because it's the limitation every other claim inherits. Every defect class the project *did*
discover came from contact with something it didn't author — Razorpay's pricing page,
Razorpay's sample export, an external QA pass, an outsider running the engine — and there is
no reason to believe that supply is exhausted. The specific, honest claim this repository is
entitled to make: *"the engine reconciles synthetic Razorpay-shaped data with measured,
reproducible accuracy, and its arithmetic agrees with Razorpay's own published sample rows."*
Not: *"it works on production data."*

**No fuzzy matching, by design — and it costs recall.** ADR-015's refusal is a real trade,
not a free lunch. An alternative design matching on `order_id + amount + date window` with
numeric tolerance would recover some rows this engine leaves unmatched. The chosen failure
mode — report "unmatched, look at it" rather than assert a pairing that can't be proven — is a
real recall cost on messy merchant data, not a claim of unqualified superiority.

**No composite hypotheses.** When two line items together would explain a gap that neither
explains alone, the engine goes to `UNEXPLAINED` rather than attempting to combine partial
explanations. This is a genuine coverage gap, not a design that was attempted and rejected;
compound faults are common in real data, and the residual absorbs them honestly rather than
guessing.

**Marketplace/Route splits and multi-gateway support are out of scope.** Decided before the
build and restated rather than quietly forgotten: settlement-not-equal-to-single-merchant
changes the matching model substantially, and the project's thesis is depth on one PSP's data
model rather than breadth.

**A UPI-labeled row can carry two different rates, and the engine can't always tell which.**
`method: upi` covers both a genuine bank-to-bank UPI payment (~2% platform fee) and a RuPay
credit card paid through a UPI app (2.15% + GST) — a credit-card transaction wearing a UPI
mask. Both are priced in the rate card, but if a batch doesn't distinguish them, the engine
checks the masked case against the wrong rate and reports a small, real discrepancy on a
transaction that was actually billed correctly.

**The actionable list is at a real cap of five lines**, and the project states plainly that
this is a deliberate constraint, not an oversight: a sixth line starts making the product a
dashboard, which is the exact thing it argues against from the README down. Each of the three
times the cap was raised (ON_HOLD, UNRECORDED_REFUND, DISPUTED) moved money out of a silent
bucket onto a line with an owner and was judged the right call; the next addition forces a
real product decision (grouping, or a "more" affordance) rather than another cap raise.

**Two QA findings are deliberately deferred, not dismissed (ADR-060).** Early refunds (a
refund settling before the payment it belongs to) currently fold into the general `REFUND`
line rather than getting their own classification — doing it properly needs a new
classification threaded through the classifier, ranker, gap decomposition, scorer, and golden
files, with a rule that infers early-vs-ordinary from settlement dates rather than the
generator's own label. And a saved rate card currently rewrites the fee analysis of runs
already sealed and hash-stamped, with no record in the audit trail of which rate card produced
which figure — fixing this properly means hashing the resolved config into the batch identity
itself, a data-model change the project judged worth doing right rather than hurriedly.

**The holiday calendar is fixed-date only.** Populated with the national holidays banks
close for under the Negotiable Instruments Act; Diwali, Holi, Eid, and Good Friday are
deliberately absent because they're lunar or state-declared and move annually. The asymmetry
that decided this: a missing holiday makes one settlement look a day late, while a wrong guess
at a moving holiday would make a real delay look benign — so the engine errs toward flagging
rather than guessing.

---

## 10. Where it stands, and what's next

**Current state.** Engine, API, and UI are built and measured. 903 tests passing, 1 skipped.
The full pipeline runs end to end — generate → normalize → stage → match → classify →
correlate → rank → verdict — with an audit trail behind every figure, reproducible via a
16-character metrics fingerprint that deliberately excludes wall-clock timing (which measures
the host, not the engine). The dashboard is the 12-route Next.js application described in §4,
all client components styled with inline styles over CSS custom properties rather than
Tailwind utility classes (Tailwind remains a dependency but is unused by the shipped
dashboard). CI runs four jobs on every push — engine tests and lint, the accuracy matrix
(which fails the build if the headline claim of 0 missed / 0 false positives / balance
identity holding stops being true), the web build, and a secrets check — deliberately without
a repo-wide coverage gate, since a single percentage would have been satisfied by well-tested
core logic masking an untested `cli.py`.

**Deployment.** Two free-tier services, no database. The API deploys to Render via
`render.yaml` as a Blueprint; the web app deploys to Vercel with its project root set to
`web/`. The API seeds its own demo batch on boot if its data directory is empty, so a fresh
deploy is never a blank screen, and a Render cold-start (the only real difference from the
local demo) takes a few seconds to wake after inactivity but never loses data, since there's
nothing stateful to lose — the seeded batch regenerates identically either way.

**What's explicitly deferred as future work**, in the order `LIMITATIONS.md` ranks them by
value rather than by difficulty:

1. **One real merchant batch** — named as the single highest-value thing this project does
   not have, worth more than every other item on this list combined. The engine already reads
   every shape a real export would need (upload, column mapping, and the rate card were built
   for exactly this); what's missing is an introduction to one merchant willing to share a
   month of settlement recon, payments, and their own ledger, with the unexplained residual
   published whatever it turns out to be — a first real batch reconciling to a clean ₹0 would
   be more suspicious than reassuring.
2. **Webhooks**, the production path named by name throughout the build but deliberately not
   built — batch reconciliation is the demonstrable, testable loop; the event-driven version
   (`payment.failed`, `subscription.halted`, `settlement.processed` arriving as they happen)
   is architecturally compatible (`pipeline.run()` is already a pure function over staged
   sources) but needs ingestion, signature verification, idempotency, and — the genuinely hard
   part — row-level deduplication across batches, which content-hash duplicate detection does
   not provide.
3. **Multi-currency, Section 194-O TDS, and partial-settlement netting** — three distinct
   arithmetic problems, each requiring its own correctness testing against an external worked
   example rather than an extension of the existing fee logic.
4. **A moving-holiday calendar** — an annual import of the RBI/Maharashtra settlement holiday
   publication rather than a hardcoded list, so an out-of-date calendar announces itself
   instead of silently mis-flagging a Diwali-week settlement.
5. **Deliberately left alone, and stated as a decision rather than a gap:** an LLM anywhere
   near the arithmetic (the boundary in ADR-050 should not move — a reconciliation engine that
   hallucinates is worse than no engine), AI column mapping (determinism does the job), and a
   chart wall as the landing screen (the app has real detail screens now, but what a merchant
   meets first is four lines and a verdict; every feature request beginning "could it also show"
   is answered "yes, one click down" rather than "yes, on the front page").
