# Build Journal

Chronological log of what was actually done, what broke, how it was diagnosed, and what
fixed it. Written as the work happens, not reconstructed afterwards.

Rationale over narration: the useful entry is the one that says *why* something was
tried, not merely that it was.

---

## 2026-09-02 — Phase 0: foundations

**Goal.** A repo that can hold the build: secrets hygiene, Python toolchain, package
skeleton, documentation spine. No engine logic.

### Starting state

Empty directory. The three planning documents (`PROJECT-CONTEXT.md`, `build-spec.md`,
`build-plan-3.5-days.md`) existed only as conversation context, not on disk.

### What was done, in order

1. **`git init`** on branch `main`.

2. **`.gitignore` and `.env.example` first, before any other file.** Deliberate
   ordering — see ADR-002. The ignore rule must predate the file it protects, because a
   key committed and then deleted is still in history.

3. **Planning docs written to disk.** They are the reference the rest of the
   documentation points back at, so they need to be in the repo rather than in a chat
   log.

   *Obstacle:* the pasted source had mojibake throughout — `â¹` where `₹` belonged, and
   similar for `·`, `→`, `⚠`. Classic UTF-8 bytes decoded as latin-1 somewhere upstream.
   *Fix:* rewrote with correct characters and verified with `grep -c '₹'` on each file
   (12 / 9 / 2 occurrences). Worth catching now: this text feeds the LLM explanation
   prompt and the UI copy later, and mojibake propagates silently.

4. **Python project via `uv`.** `engine/pyproject.toml` with pandas, pydantic, pyyaml,
   typer, rich as base dependencies. FastAPI, anthropic and httpx deliberately placed in
   `[project.optional-dependencies]` rather than the base set — see ADR-001. The
   packaging metadata is what enforces "the engine does not depend on the web layer";
   relying on discipline alone would not survive a late night.

5. **Package skeleton** — one subpackage per pipeline stage (`generate`, `normalize`,
   `stage`, `match`, `classify`, `correlate`, `rank`, `explain`, plus `config`, `audit`,
   `adapters`). Empty but named, so the architecture is visible in the file tree from the
   start and there is never a question of where a new file goes.

6. **Smoke test + CLI.** One trivial passing test, so the suite is green from commit one.
   A red suite on day one teaches you to ignore the suite.

   *Obstacle:* `uv run finctl version` failed with "Got unexpected extra argument(s)
   (version)". Typer collapses a single-command app into the root command, so the
   subcommand name became an unexpected positional argument.
   *Fix:* added a second command, `doctor`, which restores subcommand dispatch. Not a
   workaround — `doctor` prints resolved versions of every dependency and is the first
   thing to run when the engine misbehaves, so it earns its place independently.

### Toolchain verified

```
python   3.13.3        pandas  3.0.5
pytest   9.1.1  (1 passed)
ruff     0.16.5 (all checks passed)
finctl   0.1.0  (CLI responds)
```

### Surprise worth recording

`uv` resolved **pandas 3.0.5**, not 2.x. Pandas 3 makes copy-on-write mandatory and
changes the default string dtype. Judged low-risk for this workload — money is held as
integers and the pipeline does not mutate slices in place — so accepted rather than
pinned back. Recorded as ADR-005 and as a risk in `LIMITATIONS.md`, with the pin as a
known one-line escape hatch if Phase 1 disagrees.

### Decisions recorded this phase

ADR-001 (engine as library + CLI), ADR-002 (secrets first), ADR-003 (integer paise),
ADR-004 (ground-truth file), ADR-005 (pandas 3).

### State at end of phase

Repo initialised, toolchain green, documentation spine in place, zero engine logic
written. Next: Phase 1 step 1 — the config layer (rate cards, tolerances, archetypes),
deliberately before the generator so that hardcoded fee constants are impossible rather
than something to clean up later.

---

## 2026-09-02 — Phase 1 pre-work: the shape probe

**Trigger.** A read of the two planning documents that looked like a contradiction and
wasn't. `build-spec.md` §4 says *"Stage 1 — Prove the pipe (do not skip)"*;
`build-plan-3.5-days.md` says seeded data on Day 1, live API on Day 2. These conflict only
if "prove the pipe" means *build the adapter*. It doesn't — it means **look at one real
response before designing anything**.

The distinction, stated by the project owner and now recorded as ADR-006:

> **real API = verification, not foundation.**

The purpose of touching Razorpay early is not to depend on it. It is to check that our
fake data resembles reality. Under an hour of work; converts an unbounded schema risk into
a file on disk.

### It immediately earned its keep

Fetching Razorpay's actual documented response shapes surfaced **three schema errors** in
the sketch from `PROJECT-CONTEXT.md` §7. Each would have produced a confidently broken
engine, and none would have been caught by our own tests — because our tests would have
asserted our own wrong assumption. This is the one class of error the rest of the plan's
rigour cannot catch, which is precisely why the probe goes first.

1. **`payment_id` is null on `type: "payment"` rows.** The payment id lives in
   `entity_id`. Our join chain was going to join on `payment_id` — it would have matched
   **nothing**, and every order would have been reported `MISSING`. The demo would have
   shown a 0% match rate.

2. **Refunds are their own rows, not a column.** There is no `refund_adjustment` field.
   The recon report is type-discriminated (`payment` / `refund` / `transfer` /
   `adjustment`), and a refund is a **debit**, not a negative credit. Our one-sided-refund
   planted defect would have been undetectable.

3. **`fee` vs `tax` is genuinely ambiguous** — see below. This one is not our error;
   it is an ambiguity in Razorpay's own published material.

### The obstacle worth the most

Razorpay's docs state plainly that `fee` is the processing charge and `tax` is *"the tax
on the fee charged"*, with `Net = Gross − MDR − GST on MDR`. That reads as
`credit = amount − fee − tax`.

Their own documented example response says otherwise:

```json
"amount": 100000, "fee": 2900, "tax": 0, "credit": 97100
```

`credit = amount − fee` exactly, and `tax` is zero. If `fee` were MDR-only at 2% it would
be 2000 with tax 360; it is 2900 with tax 0.

*Why this is the most dangerous bug available to us:* our verdict screen has a line
reading *"Razorpay's cut + tax on it — matches your rate."* Subtracting tax that is
already inside `fee` makes **every card transaction wrong by the GST amount**, in the
merchant's favour, and the residual "we can't explain" bucket absorbs it silently. It
looks like rounding noise at 50 rows and like a real discrepancy at 5,000. It is the exact
failure mode this product exists to detect, occurring inside the product.

*Fix — and deliberately not a guess.* The engine derives the convention from the data.
For every settled payment row, exactly one identity holds:

```
credit == amount - fee          →  fee is GST-inclusive
credit == amount - fee - tax    →  fee is MDR-only
```

`analyse_fee_convention()` tests both across the batch, picks the consistent one, and
**raises on a mixed or inconsistent batch** rather than taking a majority vote. Recorded
as ADR-007.

Run against the documented fixture, it reports:

```
verdict: UNDETERMINED: every row has tax == 0, so both identities hold
ambiguous_rows: pay_DEXrnipqTmWVGE, pay_FGh5lS8dDlDrV3
```

Which is the correct answer. The data genuinely cannot distinguish the two conventions,
and saying so is better than picking one and being quietly wrong. It also turns Day-2's
live capture from a vague intention into a specific, non-optional task with a known
question to answer.

### Built

- `finctl/probe.py` — not part of the pipeline; nothing in the engine imports it.
  `finctl probe` reads committed fixtures offline (no network, no keys) and prints a field
  inventory plus the fee-convention analysis. `--live` is stubbed for Day 2.
- Three fixtures under `engine/tests/fixtures/razorpay/`, each carrying a `_provenance`
  block declaring `live_capture: false` inline, plus a `PROVENANCE.md` listing exactly
  what must happen on Day 2.
- 15 tests, all passing — including one that asserts the fee verdict is `UNDETERMINED`.
  **That test is expected to fail when real data arrives**, and its failure is the signal
  to update ADR-007 with the real answer. A test designed to break on new information.

### A safety detail worth recording

`fetch_live()` refuses any key not starting with `rzp_test_`. The probe writes API
responses to disk in a git-tracked directory, so a live-mode key must be unable to put
real customer data into a committed fixture. The guard is in the code, not in a comment.

### Decisions recorded

ADR-006 (API as verification), ADR-007 (fee convention derived, not assumed),
ADR-008 (canonical schema follows Razorpay's real names).

### State

Fixtures committed, contract tests green, schema corrected before a line of the generator
was written. Next: Phase 1a — the config layer, now with a known-correct target schema.

---

## 2026-09-02 — Phase 1a: the config layer

**Goal.** Every rate, tolerance and threshold in YAML before any engine logic exists, so
that a hardcoded fee constant is *impossible* rather than something to clean up later.

### A security incident, first

Test-mode Razorpay keys were pasted into **`.env.example`** rather than `.env`.
`.env.example` is git-tracked, so the values were staged to ship.

*Caught by:* checking for `.env` before using it, and finding only `.env.example` with the
IDE reporting it open.

*Contained:* values moved to `.env` (gitignored, mode 600), `.env.example` restored to
placeholders, verified zero diff on the tracked file. Nothing was ever committed, so
nothing is in history.

*The real lesson.* The pre-commit hook **would not have caught this.** It deliberately
allows `rzp_test_` — test keys are shareable and the demo needs them. But a real key in a
*tracked template* is wrong regardless of mode. The hook now has a rule: any `*.example`,
`*.sample` or `*.template` file containing a real-looking key is blocked, test-mode
included. Verified by attempting a blocked commit.

Worth recording plainly: the original hook was written to catch the obvious failure and
missed an adjacent one. Finding that gap through an actual near-miss rather than
imagination is the honest version of "we thought about security."

### Built

**Four YAML config files.** `rate_card.yaml` · `tolerances.yaml` · `archetypes.yaml` ·
`payment_mixes.yaml`. Every number the engine will use to make a judgement lives in one of
them.

**`finctl/money.py`** — the arithmetic core. Integer paise only, `Decimal` used solely at
the single rounding boundary. `parse_money()` is the one place rupee strings are parsed,
handling `"1,234.50"`, `"₹1,234.50"`, `"1234.5"` — and *refusing* sub-paise precision
rather than rounding it away silently.

**`finctl/config/loader.py`** — validated dataclasses. Every failure raises at **load**
time, not at use time, so a bad rate card is caught before a batch starts rather than
midway through 50,000 rows.

**`finctl/fees.py`** — expected-fee arithmetic returning a `FeeBreakdown` that carries
every input and output. That object *is* the proof required by BEHAVIOR.md invariant 3;
it goes into the audit log verbatim and is what the UI `[detail]` view will render.

**`finctl rates`** — a CLI command printing the fee for one amount across every method.
This is the answer to *"what about a UPI-heavy merchant?"* in one command, with the
arithmetic visible rather than asserted.

### Design decisions worth naming

**Rates are integer basis points, not float percentages** (ADR-010). ADR-003 removed
floats from money, but a float *rate* smuggles them back in at the multiplication —
`amount * 0.02` is float arithmetic, and `0.02` is not exactly representable in binary.
With integer bps the whole calculation is integer × integer ÷ 10000, one explicit
rounding boundary. The result is a property that can be stated flatly: **no float touches
a money value anywhere in the engine.**

**The config layer's job is to refuse** (BEHAVIOR.md, stage `config`). `rate_for()` on an
unpriced method raises and names the known methods. It never returns a default. This is
the single most important refusal in the project: a default 2% would charge a UPI-heavy
merchant 2% *in our model*, making every row show a fee discrepancy that is **ours, not
theirs** — the engine manufacturing the very problem it claims to detect.

Validation also refuses `gst.applies_to: amount` (≈18× fee overstatement), non-zero UPI
MDR, float MDR values, and materiality lists that mark a classification both always-benign
and always-actionable. Cross-file validation catches an archetype naming a method the rate
card does not price — at load, not deep inside a batch.

**GST on the rounded MDR, half-up** (ADR-009), answering the open question from the last
report. The reason is a UI-honesty property, not a numerical one: the `[detail]` view
shows MDR and GST as separate lines, and if GST were computed against an unrounded
intermediate the merchant never saw, those two lines would not reconcile by hand. Our own
proof would be unverifiable with a calculator, which defeats showing it. Both the mode and
the step-vs-end behaviour are config, so matching Razorpay is a config change if live data
disagrees.

### Verified, not assumed

```
₹10,000 card_credit → MDR ₹200.00 · GST ₹36.00 · fee ₹236.00 · net ₹9,764.00
₹10,000 upi         → MDR   ₹0.00 · GST  ₹0.00 · fee   ₹0.00 · net ₹10,000.00
```

The canonical case from the brief matches exactly. UPI is genuinely zero, not
approximately zero.

**103 tests green**, including: GST asserted *not* to equal 18% of the transaction amount;
10,000 repeated fee applications summing exactly with no drift; every rail asserted to use
its own rate; debit proven cheaper than credit; and a test that a *different* rate card
produces a different answer, proving the values are config rather than constants wearing a
YAML costume.

### Obstacles

**Ruff caught a genuinely muddled branch** in `expected_fee()` — the `gst_on_rounded_mdr:
false` path had a dead `if False` expression left in from an abandoned approach. It
computed the right answer by accident through the surviving branch. Rewritten to fold both
rates into a single bps product with one division. A lint rule catching a real logic
smell, not a style nit.

**`pytest.raises(match="must sum to 1.0")`** — the `.` is an unescaped regex
metacharacter. Ruff RUF043 flagged it. Harmless here, but the class of bug is a match
pattern that passes for the wrong reason.

### State

Config layer complete and proven. Zero magic numbers in code. Next: Phase 1b — the seeded
generator, which will consume this config and emit Razorpay-shaped records validated
against the fixtures captured in the probe.

---

## 2026-09-02 — Live probe run (delegated to a subagent, in parallel with Phase 1a)

Keys arrived, so the `--live` half of ADR-006 was delegated to a subagent while the main
session built the config layer. Different files, no collision. Worth recording that the
parallelism worked: two independent workstreams, one merge conflict of zero.

### What the live probe actually established

**Reachability, and nothing else.** The account authenticates and returns `200` on
`/v1/payments`, `/v1/orders`, `/v1/settlements`, `/v1/customers`, `/v1/invoices` and
`/v1/settlements/recon/combined` — every one of them with `count: 0`. The account has never
processed a payment.

This is a genuinely useful negative result. It means the probe proved the *pipe*, which was
`build-spec.md` Stage 1's actual instruction, without proving anything about *shape*.

### Two findings that change what we can claim

**1. Subscriptions is not enabled.** `/v1/subscriptions` and `/v1/plans` return
`401 Unauthorized` while the same key returns `200` everywhere else. I reproduced this
independently with `curl` rather than taking the agent's word for it, because it directly
threatens the demo centrepiece. Confirmed: it is product activation, not authentication.

Nothing changes about the build — the track bar explicitly allows synthetic data, and the
`halted` lifecycle is documented Razorpay behaviour we are modelling rather than inventing.
But we can no longer say the subscription shape is live-verified, so `LIMITATIONS.md` now
says exactly that. See ADR-011.

**2. ADR-007 is still open, and may be unanswerable in test mode.** The reason matters and
is easy to blur: not *"the data was ambiguous"* but *"there is no data."* Zero settled
rows, not zero-tax rows. And test mode does not reliably generate settlements on the T+2
schedule, so even creating and capturing a payment may not produce a settled recon row.

The agent's response to this was the right one: rather than leave a note someone must
remember, it added `test_live_recon_capture_has_no_rows_to_settle_adr_007`, which **fails
the moment any capture lands real rows**. An unresolved assumption tracked in prose gets
forgotten under time pressure — which is exactly when it matters. A failing test cannot be.
See ADR-012.

### The bug worth the delegation

While verifying the overwrite path, the agent found that `write_capture()` trusted its
caller to have already redacted PII. Writing a non-empty payload from anywhere other than
`capture_live()` would put raw `email`, `contact` and `vpa` values straight into a
git-tracked file. It reproduced this by writing `real@person.com` to disk.

Redaction now happens at the **write boundary** — the last point before disk — with a
regression test, and it preserves nulls, since nullability is part of the shape the fixture
exists to capture.

The detail that makes this worth recording: **the path never executed during the live run**,
because both collections were empty. It would have sat latent until the first run that
actually had data — which is to say, until the first run where it mattered. I verified the
fix directly (`redact_pii` on a payload with real-looking values, checking idempotency and
null preservation) rather than accepting the report.

### Empty-account guard

The agent correctly did **not** overwrite the documented-shape fixtures with empty
collections — that would have destroyed the contract the test suite relies on and replaced
it with nothing. Empty captures landed as `*_live.json` alongside. Verified: all three
documented fixtures still carry their original item counts.

### Also fixed

`.env` could not be `source`d from bash. The angle-bracket placeholders I had written
(`<your-anthropic-api-key>`) break shell parsing, since `<` is a redirect. Fixed in both
`.env` and the template, with a comment in `.env.example` explaining why the values are
quoted, so the next person does not reintroduce it.

### Verification of the agent's work

Every checkable claim was checked rather than taken at face value: the 401s reproduced with
`curl`; the PII fix exercised directly; the documented fixtures confirmed intact; the full
suite and repo-wide lint re-run. **104 tests green, ruff clean.**

One reported issue was a phantom: the agent flagged an `RUF043` in `test_config.py` as
pre-existing and out of its scope. It was mine, from concurrent work, and I had already
fixed it. Timing overlap, not a disagreement.

---

## 2026-09-02 — Phase 1b: the seeded generator

**Goal.** Razorpay-shaped synthetic data, configurable on every test-day axis, with a
machine-readable ground truth so "defects caught / missed" is an assertion rather than a
claim someone remembers to check.

### Built

`finctl/calendar.py` · `finctl/generate/ground_truth.py` · `finctl/generate/generator.py` ·
`finctl/generate/writer.py` · `finctl/config/defaults/defects.yaml` · `finctl generate` ·
`finctl golden`

### The calendar deserved its own module

T+2 means two *working* days. Model it as calendar days and a Friday capture "settles" on
Sunday, and the engine reports a third of a normal batch as missing money — manufacturing
the exact problem it exists to detect.

It is deliberately shared between generation and judgement. Using different logic in each
would let a generator bug hide behind a matching classifier bug, which is the same class of
error ADR-013 addresses for fees.

The canonical case now emerges rather than being special-cased:

```
2026-09-04 Fri  +T2 -> 2026-09-08 Tue   (4 calendar days)
```

*"47 Friday orders land Tuesday"* is arithmetic, not a story we tell.

### The circularity question, faced directly (ADR-013)

The generator calls `expected_fee()` — the same function the classifier will use. That
looks circular, and choosing it over an independent implementation was the main design
decision of this phase.

Two independent fee implementations written by the same person on the same day share the
same misunderstanding. The batch reconciles perfectly, both are wrong, and the green suite
proves nothing. Worse, any *innocent* difference between them (a rounding tie-break)
surfaces as a phantom defect the classifier must be taught to ignore — training the engine
to tolerate real errors.

So the generator models a **correct** Razorpay, and a defect is an explicit, recorded
perturbation of that baseline. The classifier is not tested on "can you recompute a fee"
but on "can you detect a known deviation" — which is the actual job. Fee correctness is
proven separately in `test_fees.py` against the brief's worked example, which is external
truth rather than our own output.

The `clean` profile is the self-check: with nothing planted, every generated fee must equal
the contracted fee exactly. Asserted.

### The best decision of this phase (ADR-014)

ADR-007 says we do not know whether Razorpay's `fee` is GST-inclusive or MDR-only. The
generator still has to write *something* into `fee` and `credit`.

The trap was writing one convention silently. The detector would then only ever see the
convention we picked, pass forever, and prove nothing — detector and generator agreeing
because the same person wrote both on the same assumption.

Instead `fee_convention` is an explicit parameter, and **both are tested**:

```
gst_inclusive  -> fee is GST-INCLUSIVE (credit = amount - fee)      broken=0
mdr_only       -> fee is MDR-ONLY (credit = amount - fee - tax)     broken=0
```

Neither test can pass by accident — they demand opposite verdicts from the same detector.

This converts an unresolved *external* question into a tested *internal* capability. We
still do not know what Razorpay does. We can now say, with tests, that the engine handles
either answer and detects which one it is looking at. The open question stopped being a
risk to correctness and became a fact awaiting discovery.

### Tuning the demo, and why the shape matters

The first run had timing lag at ₹1.69L against a fee defect of ₹69 — timing swamping
everything and the fee line invisible. Retuned to 30 fee defects at 40bps and timing down
to 10%:

```
₹87,912.10  timing_lag             (20 rows)   <- biggest, and needs NO action
₹27,208.00  halted_subscription     (6 rows)   <- smallest but the only actionable one
₹23,628.00  one_sided_refund        (8 rows)
₹17,481.00  missing_order           (3 rows)
   ₹603.50  wrong_fee_rate         (30 rows)   <- invisible per row, real in aggregate
```

That ordering *is* the product argument: the largest number is benign, the actionable one
is small. And the fee defect is deliberately too small to notice on any single row — which
is precisely why a merchant needs a tool to see it at all.

Exactly 6 halted subscriptions. Six customers, not "about six."

### Golden files — and proving they can fail

Set up per the Day-1 working practice. A golden test that cannot fail is worse than none,
so rather than trust it, I injected a regression: changed `card_credit` from 200 to 210
basis points. It caught it and named the moved totals:

```
card_heavy_t1_100: totals changed
  expected: recon_fee_paise 934656, recon_tax_paise 133901
  actual:   recon_fee_paise 974555, recon_tax_paise 139988
```

Reverted; green again. The safety net demonstrably works.

`finctl golden --update` regenerates, with a docstring saying not to run it to turn a red
test green without reading the diff first — the diff *is* the finding.

### Throughput, measured now rather than assumed on test day

```
    50 orders   0.005s    9,809/sec
   500 orders   0.021s   24,046/sec
 5,000 orders   0.189s   26,496/sec
50,000 orders   1.730s   28,897/sec
```

Linear to 50k. The generator is not the bottleneck; whatever we find on test day will be in
matching, which is where an O(n²) join would live. Worth having this baseline before the
matcher exists, so the comparison is honest.

### Obstacles

Minor. Ruff caught `datetime.timezone.utc` where `datetime.UTC` is the modern alias, and an
unused variable in the CLI. Both auto-fixed. Nothing structural — the design work was done
in the ADRs before the code, which is why.

### State

167 tests green, ruff clean. Generator produces Razorpay-shaped data across every test-day
axis (volume × archetype × payment mix × settlement cycle × defect profile × fee
convention), with ground truth that makes scoring automatic.

Next: Phase 1c — normalize, stage, match, classify, correlate, ending at the Day-1
checkpoint: unexplained-before ≠ unexplained-after in a console.

---

## 2026-09-02 — Phase 1c-i: normalize, stage, match

**Goal.** Get from files on disk to a reported match rate, with the two-pass structure
naming which leg broke.

### Built

`finctl/schema.py` (canonical columns + alias tables) · `finctl/normalize/normalizer.py` ·
`finctl/stage/staging.py` · `finctl/match/matcher.py` · `finctl reconcile`

### The result that matters

```
Order -> PSP   did each sale reach Razorpay?      191/200  (95.5%)
PSP  -> Bank   did Razorpay's payout reach bank?   32/32  (100.0%)

Expected ₹10,74,709.00 · Received ₹10,12,708.70 · Gap ₹62,000.30
```

**This is why there are two passes.** A single ledger-to-bank join reports a ₹62,000 gap
and stops. Two passes say the break is entirely on the sale-to-Razorpay leg and the payout
leg is perfect — which is a different problem with a different fix. The merchant does not
need to know money is missing; they need to know *where* it went missing.

Verified against ground truth: the 9 unmatched orders are an **exact set match** with the
9 planted gaps (3 missing + 6 halted). No false positives. And the gap decomposes to zero
residual — ₹62,000.30 = ₹17,311.30 fees + ₹44,689.00 missing.

### Two bugs found, one in my own code and one much worse

**1. Every well-formed file was rejected.** The alias resolver collected `"order_id"` and
`"orderid"` as two hits for the same canonical field — but both fold to the same key, so
they were the *same input column* counted twice. It raised "ambiguous mapping" on the very
first real file. Fixed by de-duplicating hits before the ambiguity check: the same column
hit twice is one candidate; only *distinct* columns are a genuine ambiguity.

Caught immediately by running against real generated data rather than only unit tests —
worth noting, because a unit test with a hand-written header list would have passed.

**2. The generator silently under-planted defects.** Much more serious.

A staging test at `volume=40` failed with zero subscriptions. Not a staging bug: the demo
profile demands **51 defects** (3 + 30 + 8 + 6 + 4), and each order carries at most one.
Below 51 orders, the index slices ran off the end and the *last* defect types silently got
nothing — while `ground_truth.json` still cheerfully claimed 6 halted subscriptions were
planted.

That is the one failure mode this project cannot tolerate: **a batch whose metrics are
confidently wrong.** Every accuracy number computed from it would have been a fabrication,
and nothing would have flagged it. The generator now refuses, naming the arithmetic:

```
defect profile 'demo' demands 51 defects but the batch has only 40 orders
(missing_order=3, wrong_fee_rate=30, one_sided_refund=8, halted_subscription=6,
timing_lag=4). Each order carries at most one defect. Either raise --volume or use a
rate-based profile such as 'scale'.
```

The guard then found a **second** instance: the `chaos` profile's rates summed to **1.55**
— impossible by construction. It had been silently under-planting since Phase 1b. Fixed to
sum to 1.0, which is what "nothing reconciles" actually means.

Worth recording plainly: I wrote that profile, tested it, and it passed, because the test
only asserted "does not crash and records something." The guard found what the test could
not. This is the argument for invariants over assertions — a test checks the case you
thought of, an invariant checks every case.

### Design decisions

**Identifier-only matching, no fuzzy fallback** (ADR-015). Fuzzy matching on amount and
date proximity would raise our headline match rate substantially. It would also mean two
₹4,999 orders on the same Friday are indistinguishable, and matching the wrong one produces
a reconciliation that is *confidently* wrong — totals balance, match rate looks excellent,
one customer's payment attributed to another's order, and nothing signals that it needs
investigating. An honest unmatched row can be investigated; a confident wrong match cannot.

This costs headline match rate, and that is the right trade: *"every number traces back to
a Razorpay record"* is incompatible with a number that traces to a heuristic. What fuzzy
matching would have guessed at, `correlate` will recover with evidence — still a join,
still deterministic.

**Empty batches report 0%, not 100%** (ADR-016). `matched/total` is undefined at zero, and
the convenient answer renders as a perfect green 100%. But an empty batch has not achieved
a perfect reconciliation; it has said nothing. Worse, it is a *silent* lie — an empty
upload looks identical to a clean one in the summary. Same instinct as ADR-004: a metric
that can be accidentally flattering is worse than no metric.

**Refunds excluded from pass-1 matching.** A refund row is not evidence that a sale reached
Razorpay. Counting it would let a refunded-but-never-settled order appear matched — an
order that lost money twice, showing as reconciled.

### State

253 tests green, ruff clean. The pipeline runs end to end from CSV to match rate in 7ms on
200 rows (~86k rows/sec).

Next: 1c-ii — classify and correlate, ending at the Day-1 checkpoint.

---

## 2026-09-02 — Phase 1c-ii: classify + correlate — THE DAY-1 CHECKPOINT

**The gate the whole project depends on.** From `build-plan-3.5-days.md`: *"Unexplained-
before ≠ unexplained-after, printed to console. If this doesn't work, everything
downstream is decoration."*

### It works

```
════════  CORRELATION: the checkpoint  ════════

  unexplained BEFORE         ₹44,689.00
  unexplained AFTER               ₹0.00
  resolved by joining        ₹44,689.00

  ✓ the number moved  (100.0% of the residual resolved)

  overall recall 100.0%  (54 caught, 0 missed, 13 below tolerance)
  0 false positives
```

And the verdict screen the product promised:

```
Expected ₹10,51,081.00 · Received ₹10,12,708.70 · Gap ₹38,372.30

  →     ₹30,501.15   7 not missing, just late
  →        ₹603.50  30 Razorpay's cut + tax on it
  →     ₹23,628.00   8 refunds recorded on one side only
  ⚠     ₹27,208.00   6 subscriptions died silently — recoverable
  ⚠     ₹17,481.00   3 payments that failed
             ₹0.00   we can't explain

  → One thing needs you this week: those 6 customers.
```

### But the first 100% was a lie, and finding out why was the work

The correlator reported 100% resolution immediately. That is exactly the moment to be
suspicious rather than pleased, because a perfect score on the first run usually means the
measurement is wrong, not the engine.

Checking planted-vs-detected per defect type:

```
one_sided_refund   planted= 8  ₹23,628.00      REFUND found = 0   ₹0.00
timing_lag         planted=20  ₹87,912.10      TIMING found = 7   ₹30,501.15
```

**Zero of eight refunds.** The 100% was real but vacuous — correlation had resolved 100%
of the residual *the classifier produced*, and the classifier was not producing these at
all. A metric measuring the wrong denominator.

### Two real bugs behind it

**1. The generator recorded refunds without creating them.** The one-sided-refund defect
wrote a ground-truth entry and changed nothing in the data. Ledger and settlement agreed
exactly, so `gap_paise == 0` and the classifier correctly found nothing.

Same failure class as the under-planting bug from 1c-i: **ground truth asserting a defect
the data does not contain.** Fixed so the ledger row is actually written down by the refund
amount, which is what makes the Side A / Side B divergence real.

**2. I had the refund direction backwards.** With the data fixed, still 0 of 8. The gap was
**negative** and my classifier only labelled `REFUND` on a positive gap.

Reasoning it through properly: a one-sided refund is one the *merchant* recorded that never
reached settlement. Their ledger is written DOWN; Razorpay still shows the full amount. So
the shape is `settlement > ledger` — negative under our sign convention. I had reasoned
about it as "the merchant expected less money", which is true of the *net* but not of the
recorded order amount.

The opposite sign is a genuinely different problem — the ledger expected more than Razorpay
ever recorded, which is money that never arrived rather than money that went back. Both
directions now carry an explicit `interpretation` field, because this is evidently easy to
get backwards.

After both fixes: **8 of 8, exact to the rupee.**

### The timing "misses" were not misses (ADR-017)

13 of 20 timing defects unflagged. But the generator plants 1–2 day lags and `grace_days: 1`
means a one-day lag is *within tolerance by design*. Counting those as misses would report
a correctly-working tolerance as an engine failure — and would push toward removing a
tolerance that exists for a good reason.

So the score has three categories: `caught` / `missed` / `below_tolerance`, with recall over
`caught + missed` only. Both collapses misrepresent the engine in opposite directions; the
third category is the only one that describes what actually happened. A judge reading
"13 below tolerance" next to `grace_days: 1` can verify that judgement themselves.

### The refusals matter more than the resolutions (ADR-019)

A correlator that resolves everything is not impressive, it is lying. The tempting shortcut
is treating any failed subscription payment as evidence of a halted subscription — they
co-occur constantly and it would raise the resolution rate.

Verified by direct test that the engine refuses:

```
no payment record at all                     -> MISSING          (not resolved)
failed payment, NO subscription              -> PAYMENT_FAILED
failed pay, subscription ACTIVE (decoy)      -> PAYMENT_FAILED   ← not claimed as halted
failed pay, subscription HALTED              -> HALTED_SUBSCRIPTION
subscription halted but id DOES NOT resolve  -> PAYMENT_FAILED   ← no borrowing
```

A failed payment on an *active* subscription is a normal retryable failure, not silent
revenue death — claiming otherwise tells a merchant to chase a customer whose subscription
works fine. This is the false-attribution guard Day 3 will attack deliberately, built
before the attack rather than after it.

**False positives are tracked separately and matter more than misses** (ADR-018). Recall
alone is one-sided: an engine flagging every order scores 100%. A miss is a coverage gap; a
false positive is the engine telling a merchant something untrue, which costs them real time
and erodes the only thing that makes a short list worth reading. Currently zero across every
tested configuration.

### The golden files earned their keep again

Three failed after the generator fix. Correct behaviour — the data legitimately changed. Per
my own rule I read the diff before regenerating:

```
gross_paise: 107470900 -> 105108100     (difference: exactly ₹23,628)
```

Exactly the refund total, nothing else moved. One explainable line, so regenerating was
justified. This is precisely the discipline the golden files exist to enforce: had something
*else* moved, I would have found out before shipping it.

A fourth failure was my own test's arithmetic — the gap-decomposition assertion predated
refunds existing in the data, so it was missing a term. And the term is negative, which is
the same sign trap as the classifier bug: a one-sided refund means the bank received MORE
than the ledger expected, shrinking the gap rather than widening it.

### Honest note on the 100%

100% resolution across every archetype and volume tested is **not** a claim that
correlation resolves everything in general. It reflects a property of our synthetic data:
every planted gap has a correlatable payment record, because the generator only creates
gaps that way. Real data contains gaps with no payment record at all — bank errors,
timing at month boundaries, data-entry mistakes — and those correctly stay UNEXPLAINED, as
the refusal tests demonstrate.

Recorded in `LIMITATIONS.md`. Day 3's decoy exists precisely to attack this.

### State

**296 tests green, ruff clean.** Full pipeline runs CSV → verdict in 9ms on 200 rows.
The Day-1 checkpoint is passed and verified against ground truth.

Next: Phase 2 — FastAPI wrapper, then the verdict screen in Next.js.
