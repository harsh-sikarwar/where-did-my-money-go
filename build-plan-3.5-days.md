# Build Plan — 2.5 Days Build + 1 Day Test

*Supersedes `48-hour-plan.md`. Delete that one so you don't work from it by accident.*

**Budget:** ~26 productive build hours across 2.5 days, plus ~8 hours on test day.

---

## What the extra time should NOT go into

More features.

This is the trap. Time expanded, so the instinct is to build more of the architecture. Resist it. The extra time goes into three things, in this order:

1. **Making the core bulletproof** — the correlation loop working on every archetype, not just the happy one
2. **The testing matrix** — which is a *deliverable*, not overhead (see below)
3. **The failure-recovery story** — deliberately hunting for where your engine is wrong

The scope from `build-spec.md` was sized for a real project, not 3.5 days. Most of it still stays cut.

## Why the testing day is a scoring goldmine

Re-read the track bar: *throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing.*

Most entrants will spend every hour building and test for twenty minutes. You now have a full day to produce a metrics table across archetypes and volumes, with a miss list. **That table is worth more than any additional feature you could build in the same time.** Treat test day as a build day whose output is evidence.

## Two decisions, revised

**Live Razorpay API — now worth doing, still not first.** Build Day 1 against a seeded generator emitting Razorpay-shaped records. Swap in the real API on Day 2 when you have something working to plug it into. Same de-risking logic, but you now have the hours to actually land it, and real integration is worth real credit.

**FastAPI + pandas — now the right call.** At 48 hours I'd have told you to use whatever you type fastest. At 26 build hours the learning value is worth the friction, it's the same stack you'd planned for your own API project, and "Python finance engine" is a more natural fit for the domain. Budget an extra hour or two for syntax friction and take it.

---

## DAY 1 — THE ENGINE  ·  ~10 hours

**Goal: the correlation number moves, on seeded data, in a console.** No UI. No API. No LLM.

| # | Task | ~Time |
|---|---|---|
| 1 | Seeded data generator — Razorpay-shaped records, configurable defect planting | 2.5h |
| 2 | Normalization + staging entries (immutable, re-runnable) | 1.5h |
| 3 | Two-pass matcher — Order→PSP, PSP→Bank | 2.5h |
| 4 | Deterministic classifier with proof on every row | 2h |
| 5 | Correlation — unexplained → payment status / halted subscriptions | 1.5h |

Build the generator **configurable from the start** — defect types, volume, payment mix, archetype as parameters. You'll regenerate data dozens of times on test day. An hour spent here saves four later.

**Planted defects, v1:** missing order, wrong fee rate, one-sided refund, timing lag, and a cluster of ~6 halted subscriptions.

> **CHECKPOINT — end of Day 1.** Unexplained-before ≠ unexplained-after, printed to console. If this doesn't work, everything downstream is decoration. Do not start the UI.

---

## DAY 2 — REAL + VISIBLE  ·  ~10 hours

| Priority | Task | ~Time |
|---|---|---|
| **P0** | Verdict screen — the four lines | 2.5h |
| **P0** | LLM explanation layer — scoped call, numbers come from engine only | 1.5h |
| **P0** | Live Razorpay API adapter — settlements, recon, payments, subscriptions | 2h |
| **P1** | Exception detail drill-down — arithmetic proof, settlement_id, txn list | 2h |
| **P1** | Correlation screen — before/after, visual | 1.5h |
| **P2** | Demo-data button + CSV upload path | 0.5h |

**On the API adapter:** timebox it to 2 hours. If test-mode auth or response shapes fight you past that, cut it and demo on seeded data — the track bar specifies synthetic data anyway, so this costs you far less than you think. Don't let it eat Day 2.

**On the LLM layer:** the prompt is roughly *"explain this resolved exception in plain language for someone who doesn't know finance terms; do not invent, alter, or recompute any number."* Pass it structured facts, get prose. One call per cluster. Don't over-build it.

> **CHECKPOINT — end of Day 2.** You can run the full demo story out loud, screen by screen. If not, Day 2.5 is for finishing this, not for new work.

---

## DAY 2.5 (half day) — HARDEN + DIFFERENTIATE  ·  ~6 hours

| Rank | Task | ~Time |
|---|---|---|
| 1 | **Audit trail screen** — every engine decision inspectable | 1.5h |
| 2 | **Payment-mix correctness** — UPI (zero MDR) vs card (2% + 18% GST). Make the rate card config, not constants. | 1.5h |
| 3 | **Second archetype** — SaaS-heavy vs D2C-heavy seeded sets | 1h |
| 4 | Materiality ranking refinement — benign vs actionable thresholds | 1h |
| 5 | UI polish — this is your edge, spend the last hour here | 1h |

**Item 2 is not optional.** A hardcoded 2% fee will pass your demo and be wrong for most Indian merchants, since UPI carries zero MDR while cards carry ~2% plus 18% GST on that. If a judge asks "what about a UPI-heavy merchant" and the answer is a shrug, that's the whole build questioned.

---

## DAY 3 — TEST DAY  ·  ~8 hours

This is a build day. The output is evidence.

### Morning — the matrix (~3h)

Run and record:

| Axis | Values |
|---|---|
| Volume | 50 · 500 · 5,000 · 50,000 |
| Archetype | D2C e-commerce · SaaS subscription |
| Payment mix | UPI-heavy · card-heavy · even |
| Settlement cycle | T+1 · T+2 |

Record per run: match rate, auto-resolved vs escalated, unexplained before→after, seeded defects caught/missed, throughput in records/sec.

**Name your bottleneck honestly.** "Matching degrades above 10k records because the join is O(n²); indexed joins would fix it" scores better than silence.

### Midday — adversarial (~2h)

Run these and write down what actually happened:

- empty batch · all-match batch · all-exception batch
- same file uploaded twice
- bank statement arriving *after* the first run (re-run and merge — does it corrupt?)
- renamed / reordered ledger columns
- amounts as `"1,234.50"` strings
- one order split across two settlements
- refund issued before the original settled

### Afternoon — the failure story (~1h)

**Plant a gap that looks like a halted subscription but isn't.** Watch the correlation mis-attribute it. Then either fix it or document it precisely.

This is the highest score-per-minute work in the entire project. Criterion four is literally *"what broke, and what you did about it."* Most teams will scramble for an answer. You can engineer a real one, with evidence.

### Final (~2h)

| Task | Time |
|---|---|
| Submission writeup — thesis, architecture, AI-usage table, honest limitations | 1h |
| Metrics table from the morning's runs | 30min |
| **Rehearse the 2-minute demo out loud, 3×** | 30min |

---

## The demo (unchanged — it's right)

1. "I expected ₹8.4 lakh. My bank got ₹7.88 lakh. Where's ₹52,000?"
2. Four lines.
3. "Only ₹3,800 actually needs me."
4. Click it — six dead subscriptions, with evidence.
5. Before/after correlation.
6. "Every number traces to a Razorpay record."

A story, not a feature tour. The architecture lives in the writeup.

---

## Still cut, even with the extra time

Multi-gateway · marketplace/Route splits · webhooks · AI column mapping · B2B/TDS archetype · education archetype · production auth · any database beyond SQLite.

Say in the submission that these were scoped out deliberately. Named, deliberate cuts read as judgment. Silence reads as omission.

---

## Cut rules

- **Behind at end of Day 1?** The engine is the project. Take hours from Day 2's API adapter, not from the engine.
- **API fighting you past 2 hours?** Cut it. Seeded data is explicitly allowed.
- **Behind at end of Day 2?** Day 2.5 becomes finishing time. Drop differentiators, keep the core.
- **Something fundamental broken on test day?** Freeze features, make what works work perfectly, and write the honest limitations section. That section is worth real points.
- **Never cut:** four-line verdict · correlation before/after number · honest exception list · audit trail.

> If the correlation loop works flawlessly and the verdict screen is beautiful, you have a compelling submission even if nothing else got built. Protect those two.
