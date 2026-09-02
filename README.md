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
  tests/golden/           golden-file tests

api/                      FastAPI — thin wrapper over the engine (Phase 2)
web/                      Next.js + Tailwind (Phase 2)

PROJECT-CONTEXT.md        the brief
build-spec.md             full architecture + test matrix
build-plan-3.5-days.md    hour-by-hour plan
```

---

## Getting started

```bash
cd engine
uv sync --group dev
uv run finctl doctor      # verify the environment
uv run pytest
```

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

**Phase 0 complete** — repo, toolchain, documentation spine. No engine logic yet.

Progress is tracked in [docs/JOURNAL.md](docs/JOURNAL.md).
