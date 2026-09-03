# Where did my money go?

**Razorpay Buildathon · Track 04 — AI Finance Controller**

You got paid. Was it the right amount? This tells you every rupee of the gap between what
you expected and what actually landed — which parts are normal, and the one thing you
need to act on.

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

Four lines and a verdict. Not a dashboard.

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
    explain/              the only stage that calls an LLM
    adapters/             live Razorpay API (timeboxed, cuttable)
    audit/                JSONL decision log
  tests/                  547 tests, including golden-file tests

api/                      FastAPI — thin wrapper over the engine
web/                      Next.js + Tailwind, one page

PROJECT-CONTEXT.md        the brief
build-spec.md             full architecture + test matrix
build-plan-3.5-days.md    hour-by-hour plan
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

The UI is one page — [web/app/page.tsx](web/app/page.tsx) — composed of
[Verdict](web/components/Verdict.tsx), [Correlation](web/components/Correlation.tsx) and
[Audit](web/components/Audit.tsx). Server-rendered verdict, client-fetched drill-downs
(ADR-021, ADR-023).

---

## Getting started

The whole demo, one command — seeds data, starts both services, lands on the verdict:

```bash
./scripts/demo.sh          # → http://localhost:3000
```

Or piecewise:

```bash
cd engine
uv sync --group dev
uv run finctl doctor                      # verify the environment
uv run pytest                             # 547 tests

uv run finctl generate --volume 200 --out data/demo
uv run finctl checkpoint --data data/demo # the engine's own scorecard
```

The verdict screen renders with no API key — the LLM stage falls back to a deterministic
templated explanation. That is deliberate: the demo cannot depend on a network call.

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
| Explanation | **Yes** | The one thing rules genuinely cannot do |
| Recommended action | **Yes** | Reasoning over already-resolved facts |

---

## Status

**Engine, API and UI are built and measured.** 566 tests green. The full pipeline runs
end to end: generate → normalize → stage → match → classify → correlate → rank → verdict,
with an audit trail behind every figure.

Measured across 22 configurations (volume × archetype × payment mix × settlement cycle):
**0 defects missed, 0 false positives, 0 balance-identity failures**, ~63,000 rows/sec
flat from 50 to 50,000 rows. Full numbers and their caveats in
[docs/METRICS.md](docs/METRICS.md) — read the two caveats at the top before the table.

Five bugs were found by *running* the adversarial cases rather than reasoning about the
code ([docs/METRICS.md](docs/METRICS.md)), two more by hand-editing blind batches, and
four more by reading Razorpay's own sample exports — all of them shapes the generator
structurally cannot produce (ADR-031, ADR-033, ADR-037, ADR-038, ADR-039, ADR-040). That story is in
[docs/JOURNAL.md](docs/JOURNAL.md); what it means for the accuracy claims is in
[docs/LIMITATIONS.md](docs/LIMITATIONS.md).

**Known open items** — the live-API fee convention is unresolved (ADR-007/ADR-012), the
UI renders one hardcoded batch, ingest reads CSV but not the `.xlsx` Razorpay actually
exports, and the deliberate false-attribution decoy is still to be run. All are stated in
[docs/LIMITATIONS.md](docs/LIMITATIONS.md).
