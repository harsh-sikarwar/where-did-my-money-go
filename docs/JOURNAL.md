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

---

## 2026-09-02 — Phase 2a: FastAPI wrapper + the verdict screen

**Goal.** The four lines, on a screen, with the drill-down working.

### Built

`finctl/rank/ranker.py` (materiality) · `finctl/pipeline.py` (one entry point) ·
`api/main.py` (FastAPI) · `web/` (Next.js 16 + React 19 + Tailwind 4) ·
`scripts/demo.sh` + root `package.json`

### One pipeline entry point, deliberately

ADR-001 says the API is a thin wrapper. `finctl/pipeline.py` is what makes that literally
true: the CLI and the API both call `run()`, and neither reimplements the stage order.
Two callers with two copies of the sequence is exactly how a UI ends up showing a number
the CLI never produced.

### The ranker got materiality wrong on its first run

`REFUND` landed in the actionable list — ₹23,628 of one-sided refunds marked "needs you
this week", pushing actionable above benign and diluting the headline.

The cause: `REFUND` was in neither config list, so it fell through to the ₹100 amount
threshold. Which re-introduces size as the deciding factor — the precise thing the
ranking design rejects. Recoverability decides; size only orders.

Fixed by listing every classification explicitly (ADR-020). The test is *"does a human
need to DO something this week?"*, not *"is this a discrepancy?"* — everything on the
screen is a discrepancy, that is what the screen is. A one-sided refund is a bookkeeping
divergence for month end; a halted subscription is revenue dying now.

After: benign ₹54,732 vs actionable ₹44,689. The screen reads "mostly fine, one thing to
do", which is the shape the product argues for.

That fix exposed a latent trap: a typo in those config lists would silently fall through
to the threshold, turning a benign-by-policy class actionable purely because it was
large. The loader now validates every name against the `Classification` enum and raises
at load. Found while writing the ranker; fixed there rather than left for later.

### Server-rendered, because a demo is watched not measured (ADR-021)

The verdict was first a client component fetching in `useEffect`. It worked — and the
initial HTML contained no numbers. On a projector, numbers appearing a beat after load
read as slow no matter how fast the engine is, and the engine runs in ~10ms.

Converted the page to a server component that awaits the verdict. **Verified by checking
the rendered HTML actually contains `₹10,51,081.00`** rather than assuming it would.
Drill-downs stay client-side because they are genuinely on demand.

### Verified in a real browser, not just by assertion

Ran Chrome headless against the running app, drove it through the Chrome DevTools
Protocol, clicked the halted-subscriptions line, and read the expanded DOM back:

```
Razorpay stopped attempting charges but kept generating invoices. Nobody was told...
  ₹876.00   sub_DnvzvP0lIuA2ec · halted · invoice inv_MpubiRL…
  ₹8,015.00 sub_aOYfllVOCn5HEC · halted · invoice inv_3GP04aJ…
  ... six in total
```

That is demo step 4 working end to end: click the amber line, six dead subscriptions
with evidence. Plain-English explanation on top, raw Razorpay ids beneath — layered
rather than dumbed down, which is what makes the top-level simplicity defensible.

Screenshots confirmed two layout problems a passing test would never have caught: the
amount column was wider than its widest value, leaving an odd gap, and Next.js's
dev-mode indicator sits as a dark circle in the corner. Both fixed; the second by
`devIndicators: false`, since this gets demoed live.

### `npm run demo`

From the working practices: *"never a seven-step manual ritual."* One command seeds the
batch, prints the checkpoint, starts both services, and waits for each to actually
respond rather than sleeping a guessed number of seconds. Ctrl-C stops both — it kills
the process group, so uvicorn's reloader children go too rather than surviving as
orphans holding port 8000.

### A test that was wrong, not code that was

`test_is_deterministic` failed. The differences were `created_at` and the performance
timings — a clock ticking, not a determinism failure. The assertion was over-broad: what
must be identical is every number the engine *concluded*, not the wall-clock metadata
around it. Narrowed, with a second test guarding that the exclusion is not hiding a real
difference.

### State

**329 tests green**, ruff clean across engine and api, `tsc --noEmit` clean.
The verdict screen renders the demo story.

Next: 2b — correlation screen (before/after, visual) and the audit view.

---

## 2026-09-02 — Phase 2b: correlation screen + audit trail

**Goal.** The two things on the never-cut list that existed only in the CLI: the
before/after correlation number, and the audit trail.

### Built

`finctl/audit/log.py` · pipeline instrumentation · `/api/audit` + `/api/trace` ·
`web/components/Correlation.tsx` · `web/components/Audit.tsx`

### The audit log had to exist before the audit screen could

`BEHAVIOR.md` promised a JSONL decision log since Phase 0 and nothing had written one.
The screen forced it, which is a reasonable order: building the reader first would have
meant guessing at what the record should contain.

78 events on a 200-row batch: ingest (5), match (2), classify (55), correlate (10),
rank (6). Written to `data/<batch>/audit.jsonl`, one event per line, append-only.

JSON Lines rather than a database because the debugging tool at 11pm is `grep`, and a
format you can `tail -f` beats one you have to query.

### The trace that makes the claim checkable

*"Every number traces back to a Razorpay record"* is only a claim if it can be checked.
Following one halted subscription through the log:

```
[  8] classify   MISSING
        expected 87600, settled 0
[ 63] correlate  resolved_as_HALTED_SUBSCRIPTION
        join: order_id -> payment.subscription_id -> subscription.status
        sub=sub_DnvzvP0lIuA2ec status=halted invoice=inv_MpubiRLFFZuSB8
```

Classified with its arithmetic, then resolved via the identifier chain to a specific
subscription and invoice. `/api/trace/{batch}/{order_id}` returns exactly this for any
order — the answer to *"why does this row say what it says?"*, which is the question an
audit trail exists to answer.

The strongest test is `test_verdict_totals_are_reconstructible_from_the_log`: every
figure on the verdict screen must be recomputable from the log alone. If that ever
fails, the audit trail has stopped being one.

### Where the contract and reality had to be reconciled (ADR-022)

`BEHAVIOR.md` says the audit stage *"refuses to summarise."* But a 5,000-row batch is
~95% `RECONCILED`, and one event per correctly-settled order buries the ~250 interesting
events in noise.

Resolved by distinguishing what the refusal protects: it protects **decisions** — which
rule fired, on which row, with which numbers. A `RECONCILED` row is the *absence* of a
decision. No rule fired, nothing was judged, the money arrived as expected. Its per-row
detail adds nothing the count does not, and the reconstructibility test still passes.

Recorded as an ADR rather than quietly done, because it is a deliberate reading of a
contract rather than an obvious implementation detail. If the engine ever makes a real
decision about a reconciled row, that decision gets logged individually — the exemption
is for the absence of a decision, not for a class of row.

### The correlation bar, scaled honestly

Both bars are proportional to the BEFORE figure, so the shrink is visually truthful.
Scaling each bar to its own width would make any gain look total — which would be a
chart that lies while showing correct numbers.

```
BEFORE  ████████████████████████████  ₹44,689.00
AFTER                                      ₹0.00
```

### One page, not four routes (ADR-023)

The brief lists four screens. Built as one page with three progressively deeper
sections, because the demo is a two-minute story told by scrolling rather than a feature
tour navigated by clicking. Every navigation is a moment where the presenter explains
where they are going and the audience reorients — three of those is a meaningful
fraction of a 2-minute slot.

The layering is also the argument: verdict (what a merchant reads Monday) → correlation
(the measured claim) → audit (how you check it). Stacked, that ordering is visible in one
scroll. Split across routes, it has to be asserted verbally.

### Verified in the browser again

Drove Chrome through the DevTools Protocol, clicked "How do I know this is true?", and
read the expanded DOM: content hashes, resolved column mappings, stage filter chips, and
every decision with its arithmetic and order id. The screenshot showed
`expected 87600, settled 0` and
`ledger says 43400, Razorpay recorded gross 86800, difference -43400` — exactly what a
sceptical judge should see.

Two probes came back MISSING that were actually present: `innerText` returns
CSS-uppercased headings, so `'What we read'` did not match `WHAT WE READ`. Worth
recording as a testing-method note rather than a bug — a text probe against transformed
content is checking the wrong string.

### Redaction before the need

The audit log drops credential-shaped keys recursively, through dicts and lists. The
engine handles no secrets today, but an audit log is exactly the file that quietly
accumulates them later, and it is far easier to add the guard now than to audit every
`record()` call site afterwards.

### State

**345 tests green**, ruff clean across engine and api, tsc clean, production build clean.
Full demo story renders: verdict → correlation → audit.

Next: 2c — the LLM explanation layer, the one place AI is used.

---

## 2026-09-02 — The verdict screen did not add up

**Found by the user, not by the test suite.** Looking at the screen: how do
₹30,501 + ₹603 + ₹23,628 + ₹27,208 + ₹17,481 describe a ₹38,372 gap?

They don't. The lines summed to **₹99,421.65** against a **₹38,372.30** gap. A
₹61,049.35 error, on the screen that *is* the product.

### What it was

The ranker built the verdict by summing `Finding.amount_paise` per classification. That
field is not a contribution to the gap — it means something different for each
classification, and I had treated them as commensurable:

| Classification | `amount_paise` meant | The gap needed |
|---|---|---|
| `FEE` | the overcharge vs the rate card (₹603) | the whole fee kept (₹17,311) |
| `TIMING` | the whole order (₹30,501) | **₹0** — it already arrived |
| `REFUND` | the magnitude (₹23,628) | **−₹23,628** — it narrows the gap |
| `HALTED_SUBSCRIPTION` | the whole order (₹27,208) | ₹27,208 ✓ |

One of four correct. Three distinct bugs presenting as one symptom:

1. **Double-counting money that arrived.** `TIMING` counted orders that settled *late
   but had landed*. That money is already inside `received`; counting it again inflated
   the gap by ₹30,501.
2. **A sign error.** A one-sided refund means the merchant wrote their books down while
   Razorpay settled in full — so the bank got **more** than expected and the gap
   *shrinks*. Reporting the magnitude as positive was a ₹47,256 swing.
3. **The wrong fee number.** The gap contains every rupee Razorpay kept (₹17,311), not
   just the excess over the contracted rate (₹603). Whether the *rate* is right is a
   different question, and it belongs in the drill-down.

### The check that proved the engine was fine

Before writing any fix, I decomposed the gap by hand from the matched data:

```
gap                ₹38,372.30
  + fees kept      ₹17,311.30
  + never arrived  ₹44,689.00
  − refund excess  ₹23,628.00
  = ₹38,372.30      residual ₹0.00
```

Exact, to the paise. **The engine's numbers were never wrong — the screen was assembling
them wrongly.** That distinction mattered: it meant the fix was a new composition layer,
not a hunt through the matcher.

### The fix

`finctl/gap.py` computes a **signed decomposition** directly from matched data. Findings
still supply counts, copy and drill-down proof; they no longer supply amounts. The
identity is asserted on every run by `check()`, which raises rather than logs.

`residual_paise` is *computed*, not assumed. If a future change breaks the identity, the
residual goes non-zero and appears on screen as "we can't explain" — the failure surfaces
as honesty rather than as a silent rebalance.

### Why 345 tests missed it

Every individual number was correct and independently tested. Fees right, correlation
right, match rate right, gap right. What nothing asserted was that the lines **add up to
the thing they claim to explain**.

That is a *composition* bug, and component tests cannot see it by construction — each one
verifies its own piece and none looks at the relationship between them. The suite was
thorough in exactly the way that produced false confidence.

`test_gap.py` now asserts the identity across every defect profile, archetype, payment
mix, settlement cycle and volume tier, with one named test per original bug so a
regression says which one came back.

### What I should have caught, and did not

I built a verdict screen and never once checked that its lines summed to its own
headline number. It was visible on the very first screenshot I took, and I looked at that
screenshot and judged the *layout*. A user reading the numbers found it in seconds.

Worth stating plainly rather than filing as a lesson: **I was checking that each part
worked, not that the output was true.** For a product whose entire claim is "every rupee
accounted for", the arithmetic of the headline was the one thing that most needed
asserting, and it was the one thing that wasn't.

### Also changed

Negative lines are rendered explicitly — green, with "narrows the gap" — because a minus
sign alone on a money screen reads as an error rather than as a direction. And the screen
now shows the balancing total: *"₹38,372.30 · every rupee of the gap, accounted for"*.
Not decoration. It is the claim, and the claim was wrong once.

### State

**379 tests green**, ruff clean, tsc clean. The screen adds up:

```
   ₹17,311.30  30 Razorpay's cut + tax on it
  −₹23,628.00   8 refunds you recorded but Razorpay still paid out   narrows the gap
 ⚠ ₹27,208.00   6 subscriptions died silently — recoverable
 ⚠ ₹17,481.00   3 payments that failed
        ₹0.00     we can't explain
   ─────────────
   ₹38,372.30     every rupee of the gap, accounted for
```

---

## 2026-09-02 — Composition audit

**Why.** The verdict-screen bug survived 379 tests because nothing checked whether
*composed output was true* — only that parts worked. The same class of bug could easily
exist elsewhere. This pass checked every number the UI displays against an independent
recomputation.

### Method: recompute from the rawest source, then mutate

`tests/test_composition.py` deliberately **does not reuse the engine's aggregation
helpers**. It parses the ledger CSV by hand rather than calling `parse_money`, so the two
paths share no code. Checking `matches.expected_paise` against `matches.expected_paise`
would prove only determinism; two independent paths agreeing proves something.

Then, because an invariant that cannot fail is the same false confidence in a new place,
each was verified by **deliberately reintroducing a bug**:

```
reintroduce the TIMING double-count  -> caught (no_order_appears_in_two_components)
flip the refund sign back to positive -> caught (balance identity, all configs)
understate the fee total by ₹1        -> caught (fee_line_equals_recon_file)
off-by-one on a line count            -> caught (halted_count_matches_subscriptions)
```

The **₹1** catch is the meaningful one: the assertions are exact, not approximate.

### Two real bugs found

Running the adversarial cases from `build-spec.md` §6e against the balance invariant:

```
empty batch                RAISED DuplicateBatchError
no bank file               balances ✓
renamed ledger columns     balances ✓
comma-formatted amounts    balances ✓
bank file half-arrived     balances ✓
duplicate ledger rows      RAISED ArithmeticError — residual ₹7,305.71
```

**1. Duplicated ledger rows left ₹7,305.71 unattributed.** A duplicated order is in the
ledger twice, so `expected` counts it twice — correctly, that is what the file says. But
the matcher joins *each copy* to the same settlement, so its fee and settled amount were
counted twice too. One real sale, two settlements' worth of arithmetic.

Fixed by treating copies after the first as **phantom expectation**, not duplicated
money (ADR-025). Razorpay settled the sale once; the merchant's books claim it twice, so
the extra copy genuinely widens the gap and belongs on screen under its own name. The
merchant then sees the problem is in *their own file*, which is actionable in a way
"unexplained residual" is not.

**2. An empty batch raised instead of answering.** Two empty CSVs hash identically — they
contain the same nothing — so content-hash duplicate detection fired. `BEHAVIOR.md`
requires "nothing to reconcile" to be a valid answer that reaches the verdict stage.

Fixed by skipping duplicate detection for zero-row sources (ADR-026). An empty file
carries no evidence of having been uploaded at all, and the check exists to catch the
same file uploaded twice.

Both were found by *running* the cases, not by reasoning about the code. The invariant
did its job: it converted a silent wrong number into a loud exception naming the residual.

### What the audit confirmed was already right

Match rates consistent with their counts · before/after arithmetic on the correlation
screen · `resolved_by_class` summing to the resolved bar · recall matching its own
caught/missed · every planted defect in exactly one bucket · audit-log reconstructibility
· `actionable + benign` partitioning the lines · no order in two gap components.

### State

**506 tests green** (up from 379), ruff clean, golden files unchanged, live UI balances.
The adversarial block from Day 3 is now substantially pre-run, with two bugs fixed rather
than discovered on test day.

Next: the Day 3 metrics matrix.

---

## 2026-09-03 — Test day: the matrix

**Goal.** The metrics table. From the build plan: *"treat test day as a build day whose
output is evidence."*

### First, closed the two stated gaps

`split_settlement` and `early_refund` were listed in `build-spec.md` §6e and were the two
adversarial cases the composition audit explicitly recorded as **unverified rather than
known-good**. Generating them immediately found a real bug — which is the argument for
generating them rather than reasoning about them.

**Refund debits were unaccounted for.** A refund row DEBITS a settlement, so it reduces
what the bank received. But pass-1 matching deliberately ignores refund rows (a refund is
not evidence a sale reached Razorpay), so no order-based component could see them.
₹5,421 left the bank with nothing accounting for it, and the balance invariant caught it
as a residual.

Fixing it needed three changes, each a small design decision:

- The matcher now attaches `refund_rows` **separately** from `recon_rows` — pass-1 must
  not treat a refund as evidence of a sale, but the classifier does need to see money
  leaving. Different questions, conflated until now.
- A new `_check_settled_refund` rule, distinct from the one-sided refund in
  `_check_amount_gap`. One is a *disagreement* between ledger and settlement; the other is
  a refund both sides agree on. Both are REFUND to a merchant.
- Components sharing a classification are merged, since the ranker looks them up by name
  and would otherwise silently drop one. A one-sided refund (negative) and a settled
  refund (positive) are both REFUND and must appear as one line.

**Split settlements worked correctly** — both legs recorded, `is_split`, gap ₹0,
`RECONCILED`. Getting that right is harder than reporting a problem: the engine must see
two settlements for one order and conclude nothing is wrong.

### The ₹0.02 that was the tolerance's fault, not the engine's

Four split settlements were scored as misses. Diagnosing rather than assuming: a ₹4,008
order split into two ₹2,004 legs came out **₹0.02** under contract, because the fee is
rounded per leg and two roundings of a half differ from one rounding of the whole.

The engine was arithmetically right that the numbers differed. The *tolerance* was wrong
to assume a single rounding boundary. Fixed by scaling tolerance with the number of legs
(ADR-028) — exactly one paise per boundary the counterparty actually crossed, not a
blanket loosening. Verified a 3-paise error is still caught across two legs.

### The matrix

22 runs: volume × archetype × payment mix × settlement cycle, plus `clean` and `chaos`.

```
Across 22 runs
  defects caught:   26,489
  defects missed:        0
  false positives:       0
  balance identity: holds in every run
```

### The bottleneck, found by profiling rather than guessing (ADR-029)

The first full run showed throughput collapsing at the top tier:

```
 5,000 rows   64,068 rows/sec
50,000 rows   24,620 rows/sec     <- 2.6x degradation
```

I profiled it instead of theorising. It was **not** the matcher, which is where I would
have guessed. `_is_below_tolerance` in the **scorer** was scanning all 50,000 order
matches once per planted timing defect — `O(defects × orders)`, 3.0s of a 7.7s run, and
the only super-linear term anywhere in the pipeline.

Two things worth stating precisely:

**It was in the test harness, not the engine.** Scoring only runs when ground truth
exists, so no merchant would ever have hit it. But it made our own published throughput
number wrong *in our favour* — a benchmark that measures our scoring code and reports it
as engine throughput is a misleading claim even when unintentional.

**The fix was an index, not an optimisation.** A dict built once, replacing a scan per
defect. 6.1s → 2.4s; 50k throughput went 24,620 → **63,369 rows/sec**.

After the fix, throughput is flat from 50 to 50,000 rows (55k–79k/sec, 150,783 rows in
2.4s). So the honest statement is not "here is our bottleneck" but **"we have not found
the engine's breaking point at the scale this product targets"** — with memory named as
the next candidate, since the whole batch is held in memory by design.

`METRICS.md` records the *before* number as well as the after, so the improvement is
visible rather than the slow version being quietly discarded.

### Five bugs found by running the adversarial cases

Across the composition audit and test day, all found by *executing* the scenarios rather
than reasoning about the code, and four surfaced by the balance invariant turning a
silent wrong number into a loud exception:

1. duplicated ledger rows — ₹7,305.71 unattributed
2. empty batch raised instead of answering
3. refund debits unaccounted for — ₹5,421
4. per-leg rounding on split settlements flagged as a fee error
5. the O(n²) in the scorer

### What METRICS.md says before it says anything else

The 100% figures needed their caveats stated *first*, not in a footnote: we control
ground truth, so the engine is scored against defects it was designed alongside; and
every gap the generator plants has a correlatable payment record, because that is how
the generator makes gaps. The honest reading of 100% correlation gain is *"correlation
resolves what it can see"*, not *"correlation resolves everything"*.

Our match rate also is not comparable to the published 51%/88% baseline, because ours is
an exact-identifier rate with no fuzzy matching — a stricter measure that trades headline
percentage for the guarantee that no match is a guess.

### State

**512 tests green**, ruff clean. `docs/METRICS.md` written from real runs, regenerable
with one command.

Remaining: the deliberate false-attribution case, and the submission writeup.

---

## 2026-09-03 — Blind test, and the bug it found

**The user did not trust internally generated results, and was right not to.** Every
accuracy number so far was measured against data the engine was designed alongside.

### Setup

`finctl blind new / run / score`. The generator picks a random configuration, the answer
key goes to `~/finctl-answers/` outside the project, and `blind new` prints nothing about
what it planted. A SHA-256 receipt of every file is stored with both the batch and the
answers and verified at scoring — a blind test whose data could have been adjusted
between generation and scoring proves nothing, and "we didn't change it" is not evidence.

`blind run` also refuses to run if `ground_truth.json` is present, so a non-blind run
cannot be mistaken for a blind one.

### The run

Before scoring, I analysed only the batch files and committed to predictions in writing:
archetype `d2c_ecommerce`, mix `even`, volume 840, profile `demo`, and per-defect counts
of 6/3/8/3/4/30.

All correct. **The cycle I got wrong** — predicted T+2, actual T+1. I had inferred it from
the bank date span, which reflects the order window, not the cycle. Sloppy reasoning that
happened not to matter for the counts.

Result: **PASSED, 0 missed, 0 false positives, ₹0 residual** on a configuration nobody
had tuned for.

### Except one row

```
timing_lag    0 caught   0 missed   84 below tol.   100%
```

84 timing defects planted, none flagged. The score was *honest* about it — 0 missed, not
84 — but zero detection on a whole defect type is worth understanding rather than
accepting.

### My first diagnosis was wrong

I said `grace_days: 1` was swallowing short lags at T+1. Measuring the lag distribution
disproved it — identical at every cycle: 47 rows one day late, 37 rows two days late.

The real bug was in `_check_timing`:

```python
expected = self.calendar.add_working_days(captured, self.tol.cycle_days)
```

`self.tol.cycle_days` is the cycle from **config** — always 2 — regardless of what the
batch actually did. Measured on batches with an identical lag distribution:

```
settled at T+1  ->    0 flagged late
settled at T+2  ->   15 flagged late
settled at T+7  ->  291 flagged late    (nearly every settled order)
```

Two opposite failures from one cause. A T+1 merchant is told nothing about late money. A
T+7 merchant would be told almost everything is late — technically true against a
contracted T+2, useless as advice, and indistinguishable from a broken engine.

Worth recording that I asserted the wrong cause confidently before measuring. The
measurement took two minutes and the guess would have produced a fix that did nothing.

### The fix

`finctl/cycle.py` infers the cycle from the batch — the **mode** of capture-to-settlement
working days, not the mean, because the distribution is deliberately right-skewed by the
planted lags and a mean would drift toward the very thing it is supposed to measure
against.

Observed wins over configured, because "late" is only meaningful relative to what actually
happens. The disagreement is logged rather than resolved silently, and every TIMING proof
now carries `cycle_days` and `cycle_source` so a merchant disputing a call can see the
baseline used. Under 20 settled orders falls back to config — a wrong inference from three
orders would silently rebase every judgement.

On the blind batch: **0 caught / 84 below tolerance → 37 caught / 47 below tolerance.**
Same data, same seed. In the matrix, T+1 and T+2 now detect identically (63/11 vs 63/11)
where T+1 previously caught 54.

### Why 22 matrix runs missed it

The matrix ran T+1 twenty-two times at 100% recall. Recall counts only planted defects,
and the scorer correctly bucketed the unflagged ones as "below tolerance" — so a whole
axis catching *zero* was invisible in the aggregate.

The blind test found it because it forced attention onto **one unfamiliar configuration**
rather than a summary. A green aggregate can hide a systematically dead axis, and no
amount of re-running the aggregate would have surfaced it.

### A latent bug it exposed

The audit scrubber called `k.lower()` on every dict key. The cycle distribution is keyed
by int, so it crashed — meaning *any* integer-keyed dict would have. Only string keys can
name a credential, so only those are checked now.

### State

**531 tests green**, ruff clean, matrix re-run with 0 missed and 0 false positives across
22 runs.

---

## 2026-09-03 — Hand-edited blind test: three `sed` edits, one real bug

The user asked for three edits to a freshly generated blind batch: delete data rows 10
and 19, change row 15's amount to ₹3,456. They noted that opening the CSV in a spreadsheet
corrupts it, so the edits were applied with a Python script instead — no round-trip
through Excel, structure preserved exactly.

### Predictions, made before running

Two deleted orders: Razorpay still settled them, so the settlement holds money the ledger
no longer claims. Should surface as `UNEXPECTED_SETTLEMENT` and **narrow** the gap.

One inflated amount: the ledger now claims ₹1,149 more than arrived — a shortfall, so
`UNEXPLAINED`, **not** `REFUND` (ADR-024's sign rule in the opposite direction).

### The engine crashed, correctly

```
ArithmeticError: gap decomposition does not balance:
  gap=16564940, components sum to 18264169, residual=-1699229
```

**−₹16,992.29** — exactly the net credit of the two orphaned settlements, to the paise.

`decompose()` handled orphan *bank rows* but not orphan *settlements*. The matcher had
been detecting them all along in `unmatched_recon_orders`; the decomposition never
consumed them.

**Why no generated case could ever have found it.** Every planted defect removes money or
moves it, and the generator writes the ledger **first**, deriving settlements from it. So
a synthetic batch cannot produce settled money with no ledger row behind it — the shape is
structurally unreachable by the generator, not merely improbable.

Three `sed` edits found a class of bug that 22 matrix runs, 6 blind configurations and
500+ tests could not. That is the entire argument for hand-editing, demonstrated rather
than asserted.

### After the fix

```
UNEXPECTED_SETTLEMENT   2 rows   -₹16,992.29     <- the deleted orders
UNEXPLAINED             1 row      ₹1,149.00     <- the inflated amount
residual ₹0.00 · balances
```

Both predictions correct. The inflated amount classified `UNEXPLAINED` at exactly
₹1,149.00 with the arithmetic shown — `ledger says 345600, Razorpay recorded gross 230700,
difference 114900` — and correctly not called a refund.

### Then the scorer got it wrong (ADR-032)

`blind score` reported **1 false positive** and `FAILED`. The "false positive" was the
₹1,149.00 the user had personally introduced.

The scorer defines a false positive as *"flagged an order ground truth does not list."* On
a generated batch that is right. On a hand-edited batch it is exactly backwards — the
human planted a defect the generator knew nothing about, so catching it is the point, and
the scorer penalised the engine for succeeding.

Fixed using the receipt it already verifies: when the batch was edited, findings outside
the answer key are printed **with their proof** under "not in the answer key — expected",
and `PASSED` requires only zero *missed* defects. On an untouched batch the strict rule is
unchanged.

Worth being clear this is not a weakened test. A scoring rule that punishes the engine for
finding a real problem would train us away from the most valuable test we have.

### Final result

```
130 caught · 0 missed · 47 below tolerance · recall 100.0%
1 finding not in the answer key — expected, hand-edited:
  order_27VM0IApjRVfO0  UNEXPLAINED  ₹1,149.00
PASSED on a hand-edited batch the engine had never seen
```

### A test of mine that was wrong, not the engine

My first regression test inflated ledger row 15 of a `demo` batch and asserted
`UNEXPLAINED`. It failed — because that row already carried a one-sided-refund defect
(ledger ₹4,920 vs settled ₹9,840), so adding ₹1,149 merely shrank an existing negative
gap and it stayed `REFUND`. Correctly. The test now picks a row the generator left clean.

Second time in this project I have blamed the engine for being right before checking.

### State

**537 tests green**, ruff clean.

---

## 2026-09-03 — Hand-edited blind test, round 2

Three more edits on a fresh 123-order batch: duplicate data row 67, set row 69's amount to
`0`, rename a column header.

### Predictions, before running

- **Renamed header** — `Mode` is in the alias table, so this should resolve silently with
  no change to any number.
- **Duplicated row** — should be `DUPLICATE`, +₹2,244, widening the gap.
- **Zeroed amount** — settlement exceeds ledger, so by the sign rule this becomes `REFUND`.
  **Predicted, and flagged as probably wrong**: a zero is not a refund.

All three correct, including the one I expected to be a bug.

### Two clean passes

The renamed header resolved through the alias table with **every number byte-identical**,
and the audit trail recorded `'Mode'->payment_method` — so a merchant disputing a figure
can see which column was read. That is ADR-015's "never positional" rule working, not
asserted.

The duplicate produced exactly ₹2,244 as phantom expectation. ADR-025 holding.

### One real bug

```
order_pjcaQoN5IL7SQf   REFUND   ₹2,480.00
  "consistent with a refund recorded on the merchant side"
```

The merchant did not record a refund. They recorded the sale as worth **nothing** while
Razorpay settled ₹2,480 for it. Reporting that as a refund tells a merchant they refunded
a customer they never refunded — a **false statement**, strictly worse than an unexplained
one. An honest "we can't explain this" can be investigated; a confident wrong explanation
cannot, because nothing signals it needs checking.

Now classified `UNEXPLAINED`, naming it as a probable data-entry error.

**Why no generated case could reach it:** ticket sizes are drawn from an archetype range
with a ₹299 minimum. A zero-value order is not unlikely there, it is **impossible** — so
that branch had never executed in 22 matrix runs, 8 blind configurations, or 500+ tests.

### A dead branch, found by writing its test

I also added a guard for "the difference exceeds the settled amount, so it cannot be a
partial refund." The test failed, and the code was right: with `gap = ledger − settled` and
a non-negative ledger, `|gap|` can never exceed `settled`. The branch was **unreachable**.

Removed rather than left in. A guard that cannot fire is not protection — it is a false
suggestion that the case was considered and handled.

### What two rounds of hand-editing established

Two bugs found, both in the same place: **a shape the generator cannot produce**, because
its own construction order forbids it. It writes the ledger first (so orphan settlements
are impossible) and draws amounts from a range with a positive minimum (so zero amounts
are impossible).

Synthetic data tests the failure modes you imagined. It cannot test the ones your
generator's *structure* rules out. That is the honest limit of every number in
`METRICS.md`, and it is now demonstrated rather than conceded.

### State

**543 tests green**, ruff clean. Blind score: 26 caught, 0 missed, PASSED.

---

## 2026-09-03 — Real files: the third time reality beat the generator

Obtained Razorpay's twelve official sample report exports. The plan was to use them for
column names before building the upload path. They cost about twenty minutes to read and
falsified four assumptions, one of them a live bug.

### The one that mattered

`sample-settlements-recon-report.xlsx`, column `entity_created_at`:

```
row 1:  44658.44689814815
row 2:  29/06/2022 07:34:39
```

Same column. Same file. A spreadsheet stores dates as serial numbers and writes whichever
form the cell format dictates, so any real export mixes them.

Our parser's first branch was `if text.isdigit(): datetime.fromtimestamp(...)`. And
`"44658"` is all digits. It became **1970-01-01**.

Nothing raises. Nothing looks corrupt. It is a *plausible date*, and it poisons three
things downstream: every affected order looks ~52 years late and files as TIMING (the
benign bucket, so it disappears from the actionable list), `observe_cycle` derives the
settlement cycle from those dates so one bad row skews what the entire batch is judged
against, and the verdict screen calls it "money on its way" — the precise opposite of
true.

The float form was never wrong: `44658.4469` is not `.isdigit()`, so it fell through and
raised loudly. Only the midnight-exact integer form was dangerous. That is why no test
found it — the generator emits epoch seconds, so **no batch it produced could reach that
branch**.

Fixed by parsing serials explicitly, checked before epoch seconds. The two encodings are
four orders of magnitude apart (2020-01-01 is serial `43831`, epoch `1577836800`), so the
range test is disjoint rather than a heuristic. A fractional number outside the serial
window now raises instead of being coerced into a date that looks reasonable. ADR-037.

### The other three

- The exports are **`.xlsx`**, not CSV. The normalizer is `csv.DictReader` only. "Real
  CSV upload" was the wrong name for the feature: Razorpay hands merchants an Excel file.
- Our recon discriminator is `row["type"]`; the real column is **`transaction_entity`**.
  Values match, key does not. ADR-008 exists specifically to prevent this drift, and it
  had drifted anyway — invisibly, because both sides of every test used our name. On a
  real export this drops *every* recon row and reports the whole batch as MISSING. Fixed
  the same day (ADR-038) behind an accessor that reads both spellings, with tests built
  from rows copied verbatim out of the sample file.
- Amounts are **rupee decimals** (`amount: 1.0` = one rupee), not paise.

### And one gift

Row 10 of the recon sample is `transaction_entity: refund`, `debit: 1.0`, `credit: 0.0`,
with a `settlement_id` and no `order_id`. That is the **reverse refund** — the
settlement-side refund the merchant never recorded — sitting in Razorpay's own sample
file. It is the next item on the list, and it can now be built against a real row instead
of an imagined one.

`dispute_id`, `dispute_created_at` and `dispute_reason` are real columns too, so the
DISPUTE rule gets a real schema rather than a synthesised field.

### The pattern, now three for three

ADR-031, ADR-033, and now ADR-037: every bug found in the last two days came from data
the generator **structurally could not produce**, not from reasoning about the code. The
generator tests the failure modes we imagined. Real files test the ones we didn't.

Worth being precise about what this does and does not change: no previously published
metric is invalidated, because none of them ever exercised this path. But that is the
uncomfortable half of the sentence — the numbers measured the engine against the
generator's idea of a date, and the first real file disagreed.

### State

**553 tests green** (6 added, including a named regression for the 1970 case).

---

## 2026-09-03 — The reverse refund, and three latent bugs it dragged out

`LIMITATIONS.md` had carried this since Phase 1b: the reverse refund — a settlement
refund the merchant never recorded — "is not yet generated. Both should exist; only one
does."

Razorpay's sample export has one. Row 10:

```
transaction_entity : refund
entity_id          : rfnd_Jt7Bq2djxtuWo5
debit              : 1.0
settlement_id      : setl_JtAs2E7Uf55JMV
order_id           : (blank)
```

That blank `order_id` turned a missing feature into a live bug. The matcher opened with
`if not row.get("order_id"): continue`, which is right for a payment and catastrophic
for a refund. I reproduced it before fixing anything: a ₹1,000 settlement-side refund on
a batch the engine reported as **RECONCILED**. Money left the account and not one stage
of the pipeline saw the row.

### The part I nearly got wrong

The first version classified it correctly, scored 3 caught / 0 missed, balanced to ₹0.00
— and the verdict screen still didn't show it. The findings existed; the *verdict* is
built from gap components, and the refund debit was being absorbed into the existing
`REFUND` component. Arithmetically identical. Practically invisible: `REFUND` is a line a
merchant reads and moves past.

Correct arithmetic is not the same as a correct answer. Split into its own component,
and ₹1,279 moved from a benign line onto the actionable list.

### Three latent bugs, all of the same species

Adding one defect type dragged out three things that had been wrong for a while and were
waiting for someone to add a defect type:

1. `assigned[DefectType.X]` — emission sites indexed a dict that only had keys for
   defects the profile requested. Any profile omitting one raised `KeyError`.
2. `demanded` was a **hand-maintained tuple** that had drifted from `DefectType.ALL`.
   Adding the type to the enum *and* the config still planted nothing. Ground truth
   would have been silent about a defect the profile explicitly asked for.
3. Fixing (2) by deriving from `ALL` swapped `HALTED_SUBSCRIPTION` and `TIMING_LAG` in
   the iteration order — and **that order is load-bearing**. The generator slices a
   shuffled index range across it in sequence, so the swap reassigned which orders got
   which defect and moved every golden file by ~₹55,000.

The third one is the one worth remembering. I nearly regenerated the goldens and moved
on. The test file says: *"Never regenerate to make a red test go green without reading
the diff first. The diff IS the finding."* The diff said bank credit fell by ₹55,725
while my new defects only totalled ₹2,755 — a 20× discrepancy that had nothing to do
with the feature.

Proving it: set `count: 0`, re-run, goldens matched byte-for-byte. That established the
code changes were behaviour-preserving and the remaining diff was only the three new
defects consuming index slots. *Then* regenerate.

### And a measurement bug

`score.py` joined findings to ground truth on `order_id` alone. A defect without one
scored **MISSED** no matter what the engine reported — the join key simply did not
exist. The engine found all three; the scorecard said zero.

That is the worst kind of bug for this project specifically, because the central claim
is a measurement. Fixed with an `entity_id` fallback (ADR-040). The general shape: the
scorer assumed every unit of work is an *order*, which held while every defect was
something happening to a sale, and stopped holding the moment a defect was something
happening to a **settlement**. Disputes are next, and they key on `dispute_id`.

### Test counts as a design signal

`test_rank.py` asserts the actionable list stays `<= 3`. It's now 5, and I raised the cap
rather than trimming the feature — each addition (ON_HOLD in ADR-036, UNRECORDED_REFUND
here) moves money *out* of a silent bucket onto a line with an owner. But I replaced the
bare number with the property it was protecting: actionable lines must stay a minority of
the verdict. A screen where everything is urgent says nothing.

Same for `test_cycle.py`'s `== 15`, now `== 10`. The load-bearing property there is that
all three settlement cycles **agree**, not the literal count — so I asserted the agreement
directly instead of leaving it implied by three parametrised cases.

### State

**566 tests green**, ruff clean. Demo batch: 0 missed, 0 false positives, gap residual
₹0.00, actionable list 5 lines.
