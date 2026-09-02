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
