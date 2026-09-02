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
