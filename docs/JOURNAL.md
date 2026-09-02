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
