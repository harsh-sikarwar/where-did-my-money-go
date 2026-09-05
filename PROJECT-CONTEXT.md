# PROJECT CONTEXT — Razorpay Buildathon

> Drop this in the repo root. Read first before writing code. Everything decided so far, and why.

---

## 1. What we're building

**Track 04 — AI Finance Controller.**

**Thesis:** Most tools tell a merchant *that* their money doesn't add up. This one tells them **what happened, how much of it actually matters, and what to do about the part that does** — by correlating settlement data with payment-failure data instead of treating them as separate problems.

**Merchant-facing framing:** *"Where did my money go?"* — not "AI Finance Controller." That's internal/category language.

**Pitch:** Connect Razorpay. Upload your sales ledger and bank statement. Get a plain-English explanation of every rupee between what you expected and what actually arrived.

### The output that IS the product

```
Expected ₹8,40,000 · Received ₹7,88,000 · Gap ₹52,000

→ ₹31,000  not missing, just late — 47 Friday orders land Tuesday   [detail]
→ ₹12,400  Razorpay's cut + tax on it — matches your rate           [detail]
→ ₹4,800   refunds you gave but didn't record                       [detail]
⚠ ₹3,800   6 subscriptions died silently — recoverable              [detail]
  ₹0       we can't explain

→ One thing needs you this week: those 6 customers.
```

Four lines and a verdict. **Not a dashboard.** Merchant opens it for two minutes on Monday, not all day.

---

## 2. Judging criteria (what we're optimizing for)

| Criterion | How we answer it |
|---|---|
| **Problem taste** | Picked the gap *between* the obvious problems, not an obvious one |
| **Build quality** | Deterministic engine, measured match rate, honest residual, audit trail |
| **AI judgment** | Explicit table of where AI is used and where it's deliberately not |
| **Failure recovery** | Deliberately planted false-attribution case, documented |

**Track 04 bar:** close one finance-ops loop across a 50+ record batch of synthetic data, report match rate and unresolved exceptions. Throughput + measured accuracy + honest exception list. *"One cherry-picked match proves nothing."*

---

## 3. Decisions already made (do not relitigate)

| Decision | Why |
|---|---|
| Track 04, not 03 | Recovery is Razorpay's own core product; recon is explicitly left to merchants |
| Recovery data used as **evidence**, not as a recovery feature | Keeps us unambiguously in one track |
| Deterministic engine, LLM only explains | An LLM must never decide if two numbers are equal |
| Two-pass matching, not one join | Tells you *which leg* broke |
| Seeded synthetic data for metrics | Only way to report honest precision — we control ground truth |
| Build against Razorpay-shaped fake data first, real API second | API auth can eat 4h and produce nothing demoable |
| FastAPI + pandas backend, Next.js + Tailwind frontend | Domain fit; frontend is our comparative edge |
| SQLite / flat files, no Postgres | 50–5000 rows. Be ready to say why. |
| Layered UI: plain language default, exact numbers one click down | Wider audience, and proves the simplicity is a *choice* |

---

## 4. Domain knowledge needed

### The four stages of money
1. **Authorization** — bank says the card is good
2. **Capture** — money actually taken
3. **Settlement** — money lands in merchant's bank, usually days later
4. **Reversal** — refund or chargeback pulls it back

Almost every problem in this space = something stuck or lost between two stages.

### Ledger vs settlement
- **Ledger** = merchant's record of what *should* have happened
- **Settlement/bank** = what *actually* happened
- **Reconciliation** = demanding an explanation for every difference

Common legitimate causes of difference: fees, timing (sale today, money in 2 days), refunds/chargebacks not yet reflected on one side, human error.

### Fee math (CRITICAL — most likely place to be wrong)
- **MDR** ≈ 2% on cards
- **GST** = 18% *on the MDR*, not on the transaction
- On ₹10,000 card txn: MDR ₹200, GST on MDR ₹36, net ₹9,764
- **UPI carries ZERO MDR** (mandated for banks)

⚠️ A hardcoded 2% fee will pass the demo and be wrong for most Indian merchants. **Rate card must be config, not constants.**

### Settlement cycles
- Standard **T+2** working days from capture
- **T+1** available to merchants with strong history / low chargebacks
- International longer
- Timing tolerance must be **configurable**

### Why payments fail (three buckets)
- **Card/account** — insufficient funds, expired card, wrong OTP → retry later helps
- **Bank/network** — timeout, downtime → retry soon helps
- **Risk block** — suspected fraud → retrying never helps

### `halted` subscriptions — our demo centrepiece
Razorpay's documented lifecycle: auto-charge fails → subscription goes **pending** (`subscription.pending` webhook) → retries exhaust → **halted** (`subscription.halted`). In halted state, **Razorpay continues generating invoices but does not attempt charges.**

Invoices keep appearing. No money is ever collected. Nobody is told unless watching webhooks. This is literally "revenue quietly dying while the books look normal" — and it's a documented Razorpay state, not something we invented.

---

## 5. Razorpay API facts

### Endpoints we need
| Purpose | Endpoint |
|---|---|
| All settlements | `GET /v1/settlements` |
| Settlement by ID | `GET /v1/settlements/{id}` |
| **Settlement recon report** | settlement recon endpoint — the key one |
| Payments (incl. failed) | `GET /v1/payments` |
| Subscriptions | Subscriptions API |

### Settlement entity shape
```json
{
  "id": "setl_7IZKKI4Pnt2kEe",
  "entity": "settlement",
  "amount": 50000,          // paise
  "status": "processed",    // created | processed | failed
  "fees": 0,
  "tax": 0,
  "utr": "1597813219e1pq6w",
  "created_at": 1509622307
}
```

**Settlement recon report returns:** entity details, debit/credit values, fees, taxes, UTR numbers, associated order receipts. This is the join-rich one.

### Payment failure fields (our correlation input — free decline taxonomy)
`error_code` · `error_description` · `error_source` (e.g. customer) · `error_step` (e.g. payment_authentication) · `error_reason`

### The join chain (this is the whole correlation mechanic)
```
ledger --order_id--> payment --payment_id--> settlement --UTR--> bank
```
An order in the ledger with no `payment_id` in any settlement = the gap.
Look it up in payments → `status: failed` + `error_reason`.
If subscription → invoice generated but subscription `halted`.

**It's a join, not magic.** Explainable in one sentence, deterministic, either works or doesn't.

### Test mode
- **UPI:** `success@razorpay` / `failure@razorpay`
- **Cards:** test cards + error test cards for specific decline scenarios; mock bank page with Success/Failure buttons
- **Subscriptions:** test charge option lets you *choose* the result — so you can produce the full failed→pending→halted arc deliberately
- ⚠️ **Constraint:** in test mode, subsequent debits only work within 3 days of token creation (card tokens valid 3 days). Don't build a demo depending on an old token.
- Postman collection available — poke real endpoints before writing the adapter

### Webhooks (production path — mention by name, don't build)
`payment.failed` · `subscription.pending` · `subscription.halted` · `subscription.charged`

---

## 6. Architecture

```
INGEST      Razorpay API (settlements, recon, payments, subscriptions)
            + ledger CSV (Side A) + bank CSV
                        ↓
NORMALIZE   column mapping → canonical schema; paise ints; UTC
            fail loudly on unmappable columns — never guess
                        ↓
STAGE       staging entries: validated, not yet reconciled
            immutable, re-runnable — this enables the audit trail
                        ↓
MATCH       Pass 1  Order → PSP   (did the sale reach Razorpay?)
            Pass 2  PSP → Bank    (did the payout reach the bank?)
                        ↓
CLASSIFY    FEE · TAX_ON_FEE · TIMING · REFUND · ROUNDING ·
            DUPLICATE · MISSING · UNEXPLAINED
            → NEEDS_REVIEW when >1 explanation fits
            arithmetic resolves what arithmetic can prove
                        ↓
CORRELATE   ←── THE DIFFERENTIATOR
            unexplained rows → payment status / halted subscriptions
            measure: unexplained ₹ BEFORE vs AFTER
                        ↓
RANK        materiality: benign (no action) vs actionable
            success = SHORT list, not long
                        ↓
EXPLAIN     LLM: resolved cluster + proof → plain language + action
            never invents or alters numbers
                        ↓
UI          verdict → detail → correlation → audit
```

**Statuses** (adopted from Hyperswitch): `Pending · Reconciled · Exception · Partially Reconciled · Archived · Void`
Rule: *Partially Reconciled is only ever set by a human*, never the engine.

### Where AI is used — and isn't (put this table in the submission verbatim)

| Stage | AI? | Why |
|---|---|---|
| Column mapping | Optional | nice-to-have, not core |
| Matching | **No** | LLM must never decide if two numbers are equal |
| Fee arithmetic | **No** | must be exactly right, verifiable |
| Classification | **No** | rules with proof on every row |
| Correlation | **No** | it's a join, not a judgment |
| Materiality ranking | Borderline | start rules-based |
| Explanation | **Yes** | the one thing rules genuinely cannot do |
| Recommended action | **Yes** | reasoning over already-resolved facts |

---

## 7. Data schemas

```
LEDGER (CSV upload)
  order_id · amount · timestamp · customer_id · payment_method

SETTLEMENT (API)
  settlement_id · payment_id · order_id · gross · fee ·
  tax_on_fee · refund_adjustment · settled_at · utr

BANK (CSV upload)
  utr · credit_amount · value_date

PAYMENTS (API)
  payment_id · order_id · status · method · amount ·
  error_code · error_description · error_source · error_step · error_reason

SUBSCRIPTIONS (API)
  subscription_id · invoice_id · status (active|pending|halted) · amount
```

### Seeded defects (v1 — keep to five)
1. order missing from settlement
2. fee rate not matching contract
3. refund recorded on one side only
4. timing lag (Friday orders, T+2)
5. **cluster of ~6 halted subscriptions** ← demo centrepiece

Generator must be **configurable from the start**: defect types, volume, payment mix, archetype as parameters. You'll regenerate dozens of times on test day.

---

## 8. Build plan (2.5 days build + 1 day test)

**Day 1 (~10h) — ENGINE.** Generator → normalize/stage → two-pass matcher → classifier → correlation. Console output only. No UI, no API, no LLM.
> **CHECKPOINT:** unexplained-before ≠ unexplained-after, in console. If this doesn't work, everything downstream is decoration.

**Day 2 (~10h) — REAL + VISIBLE.** Verdict screen (P0) → LLM explanation (P0) → live API adapter (P0, **timebox 2h then cut**) → detail drill-down (P1) → correlation screen (P1) → demo-data button (P2).
> **CHECKPOINT:** full demo story runnable out loud, screen by screen.

**Day 2.5 (~6h) — HARDEN.** Audit trail screen → payment-mix correctness (UPI vs card, **not optional**) → second archetype → materiality tuning → UI polish.

**Day 3 (~8h) — TEST DAY.** This is a build day whose output is *evidence*.
- Morning (3h): matrix — volume 50/500/5k/50k × archetype D2C/SaaS × mix UPI-heavy/card-heavy/even × cycle T+1/T+2
- Midday (2h): adversarial — empty batch, all-match, all-exception, duplicate file, late bank file, renamed columns, `"1,234.50"` strings, split settlement, refund-before-settlement
- Afternoon (1h): **plant a gap that looks like a halted subscription but isn't**, let correlation misfire, document it — this is the failure-recovery answer
- Final (2h): submission writeup + metrics table + **rehearse demo 3× out loud**

### Report per run
```
Batch size · Archetype · Payment mix · Settlement cycle
Match rate %
Auto-resolved vs escalated (count + ₹)
Unexplained BEFORE correlation → AFTER
Seeded defects caught / missed  ← the honest list
Throughput (records/sec)
Known failure modes
```

### Cut rules
- Behind Day 1? Take hours from the API adapter, never from the engine.
- API fighting past 2h? Cut it. Synthetic data is explicitly allowed by the track bar.
- Behind Day 2? Day 2.5 becomes finishing time.
- Broken on test day? Freeze features, make what works work perfectly, write honest limitations.
- **Never cut:** four-line verdict · correlation before/after number · honest exception list · audit trail.

### Deliberately out of scope
Multi-gateway · marketplace/Route splits · webhooks · AI column mapping · B2B/TDS archetype · education archetype · production auth · anything beyond SQLite.
*Say so in the submission. Named cuts read as judgment; silence reads as omission.*

---

## 9. Working practices

- **Golden-file tests** — set up end of Day 1. Deterministic engine = perfect fit. Prevents "fixed fees, silently broke timing."
- **Tag working states** — `git tag day1-working`. Known-good is one command away at midnight.
- **`npm run demo`** — one command seeds data, starts everything, lands on verdict. Never a seven-step manual ritual.
- **Config over constants** — fee rates, tolerances, defect types, archetypes.
- **JSONL audit log**, human-readable. You'll debug with it at 11pm.
- **Don't refactor.** Ugly-and-working beats clean-and-half-migrated.
- **`.env` + `.gitignore` from commit one.** Razorpay keys in a public repo fails the submission.
- Tooling: `uv`, `ruff`, `pytest` on the Python side. Razorpay Postman collection before writing the adapter.

---

## 10. Positioning & claims discipline

**✗ Never say:** "Nobody does AI reconciliation." Demonstrably false — Cointab, ReconPe, Hyperswitch, Microsoft all ship versions. A judge will challenge it.

**✓ Say:** "Existing tools are architecturally siloed — recovery, reconciliation and cost are separate products. An anomaly spanning two of them has no owner, so it reaches the merchant as 'unexplained.' We close that gap and measure how much of the unexplained it eliminates."

**✓ Also say openly:** architecture informed by studying Hyperswitch's published design. *"I looked at how people who solved this at scale structured it"* is a strong answer to "how do you think." Getting caught quietly reproducing it mid-demo is the bad version.

### Landscape (verified)
- **Hyperswitch** (Juspay, Apache 2.0, 42k+ stars, Razorpay is a connector) ships **three separate modules**: Revenue Recovery, Reconciliation, Cost Observability. ← this siloing IS our thesis
- **Cointab** — Razorpay fee/tax verification, Side A/Side B model, leaves items unmatched when evidence is weak
- **ReconPe** — rate-card audit, AI column mapping, ₹3,999/mo
- **Terra Insight** — publishes the matching recipe; benchmark: manual VLOOKUP ~51% match rate → structured tooling 88%+
- Razorpay's own T&C: **merchant is responsible for daily reconciliation**, discrepancies must be reported within 3 days. Razorpay contractually says this is the merchant's job.

---

## 11. The 2-minute demo (rehearse out loud 3×)

1. "I expected ₹8.4 lakh. My bank got ₹7.88 lakh. Where's ₹52,000?"
2. Show the four lines.
3. "Only ₹3,800 actually needs me."
4. Click it — six dead subscriptions, with evidence.
5. Show before/after correlation.
6. "Every number traces back to a Razorpay record."

**A story, not a feature tour.** No "here's our API integration, here's our engine." Architecture goes in the writeup.

---

## 12. Known risks

| Risk | Mitigation |
|---|---|
| Not from a finance background | Every finance term in output must be explained by the system or absent. Forcing function on our own learning. |
| Hardcoded fee rate wrong for UPI merchants | Rate card as config; explicit payment-mix test on Day 2.5 |
| Correlation will sometimes mis-attribute | Plant the case deliberately, show it — that's criterion 4 |
| Scope creep now that time expanded | Extra time goes to hardening + testing, **not** more features |
| API integration eats the clock | Hard 2h timebox, seeded fallback ready |

---

*Companion files: `build-spec.md` (full architecture + test matrix), `build-plan-3.5-days.md` (hour-by-hour), `razorpay-buildathon-cheatsheet.md` (competitive gaps). `48-hour-plan.md` is superseded — delete it.*
