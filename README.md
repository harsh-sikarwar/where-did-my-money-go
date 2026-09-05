# Where did my money go?

**Razorpay Buildathon · Track 04 — AI Finance Controller**

You got paid. Was it the right amount? This tells you every rupee of the gap between what
you expected and what actually landed — which parts are normal, and the one thing you
need to act on.

**Live demo:** [where-did-my-money-go-tawny.vercel.app](https://where-did-my-money-go-tawny.vercel.app) —
no setup, opens on a seeded batch. The API it talks to is a free-tier host and can take a
few seconds to wake from cold; [Getting started](#getting-started) below covers the
zero-latency local alternative.

---

## Reading this repository

This project documents itself more than most — that's deliberate (see
[Credibility & Validation](#credibility--validation)), but it means the doc set is not
something to read front to back. Start here, then go only as deep as you need:

| You want to... | Read |
|---|---|
| See it work, fast | [Getting started](#getting-started) — one command, one command |
| Understand the pitch in 30 seconds | [The thesis](#the-thesis) + [The output that is the product](#the-output-that-is-the-product) |
| Know what's actually true vs. aspirational | [Status](#status), then [docs/LIMITATIONS.md](docs/LIMITATIONS.md) |
| Check a specific claim | [docs/HOW-WE-KNOW.md](docs/HOW-WE-KNOW.md) (claims → evidence) |
| See what broke and got fixed | [docs/BROKE-FIXED.md](docs/BROKE-FIXED.md) |
| Understand a design decision | [docs/DECISIONS.md](docs/DECISIONS.md), ADR-numbered, referenced by number throughout this README |
| Trace how a stage behaves | [docs/BEHAVIOR.md](docs/BEHAVIOR.md) — contracts, written before the code |
| Get exact measured numbers | [docs/METRICS.md](docs/METRICS.md) — read the caveats at the top first |
| Follow the day-by-day build | [docs/JOURNAL.md](docs/JOURNAL.md) — chronological, verbose, optional |
| Deploy your own copy | [Deploying](#deploying) |

Everything else in `docs/` is support material the table above will link you into as
needed — you don't need to open it directly.

---

## The thesis

Most tools tell a merchant *that* their money doesn't add up. This one tells them **what
happened, how much of it actually matters, and what to do about the part that does** — by
correlating settlement data with payment-failure data instead of treating them as separate
problems.

Existing tools are architecturally siloed: recovery, reconciliation and cost are separate
products. An anomaly spanning two of them has no owner, so it reaches the merchant as
"unexplained." This closes that gap — and measures how much of the unexplained it
eliminates.

## The output that is the product

```
Expected ₹8,40,000 · Received ₹7,88,000 · Gap ₹52,000

→ ₹31,000  not missing, just late — 47 Friday orders land Tuesday   [detail]
→ ₹12,400  Razorpay's cut + tax on it — matches your rate           [detail]
→ ₹4,800   refunds you gave but didn't record                       [detail]
⚠ ₹3,800   6 subscriptions died silently — recoverable              [detail]
  ₹0       we can't explain

→ One thing needs you this week: those 6 customers.
```

Four lines and a verdict — that is the *answer*, and it is what the product opens on.
Everything else in the app exists to let you take that answer apart: each line clicks
through to the rows behind it, and Runs, Exceptions, Analysis, Reports, Audit log and
Sources are there when a merchant needs to prove a figure rather than read one. The
default screen is a verdict rather than a wall of charts; the depth behind it is one
click down, which is what makes the simplicity a choice instead of a limitation.

---

## Repository layout

```
docs/                     the running record of this build
  DECISIONS.md            every fork taken, ADR-style — why, and what it cost
  JOURNAL.md              chronological log: what broke, how it was diagnosed
  PRIOR-ART.md            what was borrowed, from whom, and what wasn't
  BEHAVIOR.md             each stage's contract — written before the code
  METRICS.md              measured results (test day)
  LIMITATIONS.md          deliberate cuts and discovered limits
  BLIND-TEST.md           the protocol for testing against unseen batches
  BROKE-FIXED.md          bugs found and fixed, with evidence of each
  HOW-WE-KNOW.md          credibility audit — what we can claim and why

engine/                   the project. Python, uv-managed, no web dependencies.
  finctl/
    config/               rate cards, tolerances, archetypes — YAML, never constants
    generate/             seeded synthetic data + machine-readable ground truth
    normalize/            → canonical schema, integer paise, UTC
    stage/                immutable staging entries
    match/                two-pass matcher: Order→PSP, PSP→Bank
    classify/             deterministic rules, proof on every row
    correlate/            ← the differentiator
    rank/                 materiality: benign vs actionable
    explain/              the only stage that calls an LLM — prose only, never a number
    adapters/             live Razorpay API (timeboxed, cuttable)
    audit/                JSONL decision log
  tests/                  931 passing, 1 skipped, including golden-file tests

api/                      FastAPI — thin wrapper over the engine
web/                      Next.js App Router, 12-route dashboard

build-spec.md             full architecture + test matrix
```

---

## The pipeline, stage by stage

Each stage's **contract** — what it promises, what it refuses, how it handles bad input —
is in [docs/BEHAVIOR.md](docs/BEHAVIOR.md). This table maps those contracts to the code.

| Stage | Code | What it does |
|---|---|---|
| `config` | [engine/finctl/config/loader.py](engine/finctl/config/loader.py) + [defaults/](engine/finctl/config/defaults/) | Rate cards, tolerances, archetypes, defect profiles — YAML, never constants. Refuses to supply a default MDR. |
| `generate` | [generate/generator.py](engine/finctl/generate/generator.py), [ground_truth.py](engine/finctl/generate/ground_truth.py) | Seeded Razorpay-shaped data + machine-readable ground truth. Refuses to plant a defect it cannot score. |
| `normalize` | [normalize/normalizer.py](engine/finctl/normalize/normalizer.py) | Arbitrary columns → canonical schema, integer paise, UTC. The only place rupee strings are parsed. |
| `stage` | [stage/staging.py](engine/finctl/stage/staging.py) | Immutable staged entries; duplicate files caught by content hash. |
| `match` | [match/matcher.py](engine/finctl/match/matcher.py) | Two passes — Order→PSP, PSP→Bank — so the output names *which leg* broke. Identifier-only, never fuzzy. |
| `classify` | [classify/classifier.py](engine/finctl/classify/classifier.py) | One label per discrepancy with the arithmetic attached. No rule fits → `UNEXPLAINED`. |
| `correlate` | [correlate/correlator.py](engine/finctl/correlate/correlator.py) | **The differentiator.** Joins unexplained gaps to failed payments and halted subscriptions. |
| `rank` | [rank/ranker.py](engine/finctl/rank/ranker.py) | Benign vs actionable. Materiality is recoverability, not size. |
| `audit` | [audit/log.py](engine/finctl/audit/log.py) | Every decision to JSONL — enough to reconstruct any figure back to source rows. |

**Supporting modules.** [money.py](engine/finctl/money.py) (integer paise), [fees.py](engine/finctl/fees.py) (MDR + GST arithmetic), [gap.py](engine/finctl/gap.py) (gap decomposition — ADR-024), [cycle.py](engine/finctl/cycle.py) / [calendar.py](engine/finctl/calendar.py) (settlement timing), [score.py](engine/finctl/score.py) (scoring against ground truth), [matrix.py](engine/finctl/matrix.py) (the metrics matrix), [blind.py](engine/finctl/blind.py) (blind testing), [pipeline.py](engine/finctl/pipeline.py) (`run()` — the one entry point the API calls).

---

## CLI

```bash
cd engine && uv run finctl <command>
```

| Global option | What it does |
|---|---|
| `--no-llm` | Run with the language model switched off. See [Running with no model at all](#running-with-no-model-at-all). |

| Command | What it does |
|---|---|
| `doctor` | Check the environment is sane |
| `version` | Print the engine version |
| `rates --amount N` | Contracted fee for one amount (rupees) across every payment method |
| `probe` | Inspect Razorpay's real response shapes (ADR-006) |
| `generate` | Seeded batch of Razorpay-shaped data plus ground truth |
| `reconcile` | Two-pass match over a staged batch; report match rates |
| `checkpoint` | Score the engine against ground truth — the Day-1 gate |
| `matrix` | Run the test-day matrix, emit `docs/matrix-results.json` |
| `golden --update` | Regenerate the golden files (checking them is `pytest tests/test_golden.py`) |
| `blind new` | Create a blind batch. Prints nothing about what was planted |
| `blind run` | Reconcile a blind batch; needs no ground truth |
| `blind score` | Reveal the answers and score the run |

The blind commands are the honest-testing loop — see [docs/BLIND-TEST.md](docs/BLIND-TEST.md).

---

## API and UI

`api/main.py` is a thin wrapper: it calls `pipeline.run()` and serialises the result. No
business logic lives there.

| Route | Returns |
|---|---|
| `GET /health` | liveness |
| `GET /api/batches` | available batches |
| `GET /api/verdict/{batch}` | the headline — gap, lines, verdict |
| `GET /api/detail/{batch}/{classification}` | drill-down rows for one line |
| `GET /api/correlation/{batch}` | unexplained before vs after |
| `GET /api/score/{batch}` | scoring against ground truth, when it exists |
| `GET /api/audit/{batch}` | the decision log (most recent 500 events) |
| `GET /api/trace/{batch}/{order_id}` | one order's full path through the pipeline |
| `GET /api/rules` | read-only config: tolerances, rate card, classification vocabulary |
| `POST /api/chat/{batch}` | copilot chat: message + history → guarded reply (no numerals from model) |

The UI is a 12-route dashboard in a route group: `web/app/(dashboard)/`. All routes are client
components, styled with inline styles over CSS custom properties (`--dash-*`) rather than
utility classes — Tailwind is still a dependency and still imported by `globals.css`, but
the shipped dashboard uses none of it. The twelve are listed below; `next build` prints
thirteen because it counts its own generated `/_not-found`. The shell (sidebar + topbar) lives in `layout.tsx`; shared primitives in
`web/components/dash/primitives.tsx`, charts in `web/components/dash/charts.tsx`, and the
Copilot chat interface in `web/components/dash/CopilotChat.tsx`.

**Routes:**
- `/` — Overview (replaces the old landing page)
- `/runs` — List of all runs/batches
- `/new-run` — Wizard for upload and generation (absorbs the old `/upload` + `/generate`)
- `/analysis/[batch]` — Full breakdown: Summary / Line items / Evidence (rebuilt with the new shell)
- `/exceptions/[batch]` — Exception queue (actionable + unexplained findings)
- `/orders/[batch]/[orderId]` — Single order detail / trace view
- `/audit/[batch]` — Audit log, grouped by day
- `/sources/[batch]` — Data sources / missing-sources view
- `/settings` — Rate card settings (only rate card is persisted; other sections shown as local-only)
- `/rules` — Read-only view of tolerances, rate card, defect taxonomy (toggles disabled)
- `/reports/[batch]` — Composed client-side from verdict, actions, audit (no new endpoint)
- `/copilot/[batch]` — Full-page chat interface (also available docked as a right-side drawer from any screen)

---

## Getting started

The whole demo, one command — seeds data, starts both services, lands on the verdict:

```bash
./scripts/demo.sh          # → http://localhost:3000
```

Cold, from free ports, that is **1.6 seconds** to a rendered verdict: 0.26s to generate
the batch, 0.25s to score it against ground truth, 0.36s for the API to import, and the
remainder for the web server. Measured, not estimated — re-run it and time it.

That number is why local is still the fastest way to see this work — no host to wake, no
free-tier instance asleep since yesterday. The [live demo](#live-demo) above exists for
anyone who'd rather click a link than clone a repo; the trade is a few seconds of cold
start on the free-tier API the first time it's hit after a period of inactivity. Either
path renders the same numbers, because both run the same engine. The one optional call
either makes is the explanation sentence, and the verdict renders without it.

Or piecewise:

```bash
cd engine
uv sync --group dev
uv run finctl doctor                      # verify the environment
uv run pytest                             # 931 passing, 1 skipped

uv run finctl generate --volume 200 --out data/demo
uv run finctl checkpoint --data data/demo # the engine's own scorecard
```

### Reproducing the numbers

`checkpoint` and `matrix` each end with a fingerprint:

```
  metrics fingerprint  2310d942c05c4e14
```

Sixteen characters over everything the run claims — money in paise, defect counts,
recall, decoys resisted, whether the balance identity held. Run either command yourself
and compare. If it reads the same, you reproduced the run exactly; if it does not,
something this project claims behaves differently on your machine, which is worth
knowing before you trust the table further down.

Wall-clock timing is deliberately **excluded** from it. `seconds` and `rows_per_second`
measure the host, not the engine, and a fingerprint covering them could never reproduce
anywhere — it would look like a proof and function as a liability, failing on a slower
laptop and inviting the reader to conclude the engine is non-deterministic when only the
CPU was. The throughput figures are reported; they are just not part of what the
fingerprint attests.

The verdict screen renders with no API key: the explanation stage falls back to a
deterministic template, and the demo runs offline. You do not have to remove a key to
prove that — `--no-llm` is the switch, and
[Running with no model at all](#running-with-no-model-at-all) shows what it does. That fallback is the default path
rather than an error path — no key, no network, a timeout, or prose that fails the
numeral guard all produce the same template.

With a key, one language model writes the two-sentence summary above the lines. It is
given resolved facts and asked only to phrase them; **any response containing a figure is
discarded whole** and the template used instead, so no number a merchant reads can come
from a model. The response says which produced it (`summary_source`), and the screen says
so too. Default is Groq serving GPT-OSS (Apache 2.0, open weights); any OpenAI-compatible
endpoint works by changing two environment variables. See ADR-050.

Secrets: copy `.env.example` to `.env` and fill it in. `.env` is gitignored — that rule
predates any code in this repo, deliberately.

---

## Where AI is used — and deliberately isn't

| Stage | AI? | Why |
|---|---|---|
| Column mapping | Optional | Nice-to-have, not core |
| Matching | **No** | An LLM must never decide if two numbers are equal |
| Fee arithmetic | **No** | Must be exactly right, and verifiable |
| Classification | **No** | Rules with proof on every row |
| Correlation | **No** | It's a join, not a judgment |
| Materiality ranking | Borderline | Rules-based first |
| Explanation | **Yes** | The one thing rules genuinely cannot do — prose only, never a figure |
| Recommended action | **No** | Deterministic copy, one fixed next step per classification (`actions.py`) |

### The row in that table that was once false

`Explanation` read **Yes** before there was an explanation stage. `finctl/explain/` was a
one-line stub, there was no model call anywhere in this codebase, and the README described
the LLM falling back to a template — a fallback from a path that did not exist. An external
critique found that; we did not.

The row read **Not built** for a day. Then it was built (ADR-050) and earned back, which is
why the entry stays in
[docs/LIMITATIONS.md](docs/LIMITATIONS.md#the-explanation-stage-is-not-built-and-the-readme-claimed-it-was)
instead of being deleted once it stopped being true. `Recommended action` still reads
**No**, and should.

This is pointed at deliberately. A project whose argument is *measured, not asserted* has
one way to show it means that, and it is not a paragraph about honesty — it is the record of
a claim being wrong, kept next to the row it was wrong about. An unearned capability in the
headline table is the most expensive error available here: it invites a reader to discount
the measurements that are real.

### Running with no model at all

```bash
cd engine && uv run finctl --no-llm doctor
```

```
│ llm         │ off  (--no-llm / FINCTL_NO_LLM)                             │
│ llm used by │ web summary + chat prose only; no CLI command calls a model │
```

`--no-llm` sets `FINCTL_NO_LLM` for the process, and `LLMConfig.from_env` is the only
place in this project that decides whether a model is called — so one switch closes every
path. `FINCTL_NO_LLM=1` in the environment does the same for the API server:

```bash
FINCTL_NO_LLM=1 uv run uvicorn api.main:app --port 8000
```

**What it changes is less than you would expect, and that is the point.** No command in the
CLI has ever called a model — matching, fee arithmetic, classification, correlation and
ranking are deterministic, and the engine installs with zero LLM dependencies (they live in
a `pyproject.toml` extra). The model writes prose in two places: the summary sentence and
the chat answers on the web UI. Switch it off and both fall back to the deterministic
templates they already carry. Every figure on every screen is identical either way, because
no figure was ever the model's to produce (ADR-050).

The switch is a real one rather than a claim, and it is separated from the absence of a key
because those are different facts. `/health` reports all three:

```json
{ "llm_credential_present": true, "llm_disabled": true, "llm_enabled": false }
```

A key that is present and deliberately unused reads exactly like that — not as a
misconfiguration. The chat's fallback says which of the two it is, for the same reason: an
operator told "no model is configured" while holding a working key goes hunting for a
problem they do not have.

---

## Deploying

Two free-tier services, no database, no manual server config — the API seeds its own
demo batch on boot if its disk is empty (see the `startup` hook in
[api/main.py](api/main.py)), so a fresh deploy is never a blank screen.

**API → [Render](https://render.com):** push this repo to GitHub, then in the Render
dashboard: **New +** → **Blueprint** → point it at the repo. It reads
[render.yaml](render.yaml) and creates the service with no further clicking. After it's
live, set the `CORS_ALLOW_ORIGINS` env var (Render dashboard → the service → Environment)
to your Vercel URL from the next step.

**Web → [Vercel](https://vercel.com):** import the repo, set the project root to `web/`,
and set one env var: `NEXT_PUBLIC_API_URL` = your Render URL (e.g.
`https://finctl-api.onrender.com`). Next.js needs no other config — see
[web/.env.example](web/.env.example).

Order matters once: deploy the API first (you need its URL for Vercel), then deploy Vercel
(you need *its* URL to finish the Render CORS setting). Both are one-time dashboard steps;
every push after that redeploys both automatically.

Free-tier Render sleeps a service after inactivity — the first request after a while
takes several seconds to wake it, which is the only difference from the local demo. It
does not lose data on wake, only on a redeploy, because there is no data to lose: the
startup hook regenerates the same seeded batch either way.

---

## Status

**Engine, API and UI are built and measured.** 931 tests passing, 1 skipped. The full pipeline runs
end to end: generate → normalize → stage → match → classify → correlate → rank → verdict,
with an audit trail behind every figure.

Measured across 26 configurations (volume × archetype × payment mix × settlement cycle,
T+1 through T+7): **0 defects missed, 0 false positives, 0 balance-identity failures**,
~62,000 rows/sec flat from 50 to 50,000 orders (173 to 151,283 rows). Those runs also plant **2,254 deliberate decoys** — failed
payments on *healthy* subscriptions, which look exactly like the halted ones the engine
is built to find — and **none was claimed**. That is what makes the false-positive column
a statement about the engine rather than about data where every gap had a real cause
(ADR-042). Full numbers and their caveats in
[docs/METRICS.md](docs/METRICS.md) — read the two caveats at the top before the table.

Five bugs were found by *running* the adversarial cases rather than reasoning about the
code ([docs/METRICS.md](docs/METRICS.md)), two more by hand-editing blind batches, and
four more by reading Razorpay's own sample exports — all of them shapes the generator
structurally cannot produce (ADR-031, ADR-033, ADR-037 – ADR-049). That story is in
[docs/JOURNAL.md](docs/JOURNAL.md); what it means for the accuracy claims is in
[docs/LIMITATIONS.md](docs/LIMITATIONS.md).

**The limitation that matters most: no real merchant batch has ever been reconciled.**
Every figure above is measured against data this project generated, where the generator
defines truth — a closed loop, and one that cannot report a defect class nobody thought to
generate. The engine's arithmetic does agree with Razorpay's own published sample rows
(ADR-056), and that contact alone found two parsing bugs the suite could not. But ten
sample rows are not a merchant's month. The claim this repository is entitled to make is
*"measured, reproducible accuracy on synthetic Razorpay-shaped data, with arithmetic that
agrees with Razorpay's own sample"* — not *"it works on production data"*. That second
sentence needs one real merchant export, with the unexplained residual published whatever
it turns out to be; no live account was available for this build. It is the first item in
[the future scope](docs/LIMITATIONS.md#future-scope), and it is not development work.

**Other known open items** — the live-API fee convention is unresolved (ADR-007/ADR-012), the
correlation's two newest mechanisms (disputes, withholding) have unit coverage but are
not exercised by the matrix, and two action-list groups have no per-row reason. All are stated in
[docs/LIMITATIONS.md](docs/LIMITATIONS.md).

---

## Credibility & Validation

**How we know this works:**
- [docs/BROKE-FIXED.md](docs/BROKE-FIXED.md) — 13 bugs found and fixed, dated. What each was,
  how it was found, and why we're confident it's fixed. These include real Razorpay sample
  files finding parsing bugs the suite couldn't imagine, and five in the explanation layer
  found by measuring how often the model was actually answering.
- [docs/HOW-WE-KNOW.md](docs/HOW-WE-KNOW.md) — Claims vs. evidence. What we can assert and
  what we honestly can't (yet). Includes the story of catching and correcting our own
  overclaims (UPI rate, fee convention).

**Validation breadth:**
- **26 configurations:** volume (50–50K orders, i.e. 173–151,283 rows) × archetype (3) ×
  payment mix (3) × settlement
  cycle (T+1 to T+7). Not a single seed — each must pass.
- **2,254 planted adversarial payments** across 24 of the 26 runs. False-positive rate: 0.0000.
- **Blind testing:** Unseen batches, deterministic output, 0 missed defects.
- **Real Razorpay samples:** Arithmetic matches their published rows. Found 2 parsing bugs.

The one gap we can't close without production data is real merchant validation. See
[docs/LIMITATIONS.md](docs/LIMITATIONS.md) for what we can and can't yet claim.
