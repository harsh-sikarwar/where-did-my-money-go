# Build Spec — AI Finance Controller (Track 04)

> **Product promise:** You got paid. Was it the right amount? Here's every rupee of the gap, which parts are normal, and the one thing you need to act on.

---

## 1. Architecture

Concept model adapted from Hyperswitch's published recon design (staging entries, rule evaluation, exception taxonomy) and Cointab's Side A / Side B ingestion model. Scale discipline: no infrastructure the problem doesn't need.

```
┌─ INGEST ───────────────────────────────────────────────┐
│  Razorpay test API   →  settlements, recon report,     │
│                         payments (incl. failed),       │
│                         subscriptions + invoices       │
│  CSV upload          →  merchant ledger (Side A)       │
│  CSV upload          →  bank statement                 │
└────────────────────────────────────────────────────────┘
                          ↓
┌─ NORMALIZE ────────────────────────────────────────────┐
│  Column mapping → canonical schema                     │
│  Currency to paise (int), timestamps to UTC            │
│  Fail loudly on unmappable columns — never guess       │
└────────────────────────────────────────────────────────┘
                          ↓
┌─ STAGE ────────────────────────────────────────────────┐
│  Staging entries: validated, not yet reconciled        │
│  Immutable. Re-runnable. This is what makes the        │
│  audit trail possible.                                 │
└────────────────────────────────────────────────────────┘
                          ↓
┌─ MATCH (two passes) ───────────────────────────────────┐
│  Pass 1  Order → PSP    join on order_id/payment_id    │
│          "did each sale reach Razorpay correctly?"     │
│  Pass 2  PSP → Bank     join on settlement_id/UTR      │
│          "did Razorpay's payout reach the bank?"       │
│  Two passes, not one join → tells you WHICH leg broke  │
└────────────────────────────────────────────────────────┘
                          ↓
┌─ CLASSIFY (deterministic) ─────────────────────────────┐
│  FEE · TAX_ON_FEE · TIMING · REFUND · ROUNDING ·       │
│  DUPLICATE · MISSING · UNEXPLAINED                     │
│  → NEEDS_REVIEW when >1 explanation fits               │
│  Arithmetic resolves what arithmetic can prove.        │
│  No LLM touches this stage.                            │
└────────────────────────────────────────────────────────┘
                          ↓
┌─ CORRELATE  ←── the differentiator ────────────────────┐
│  For each UNEXPLAINED row, look up payment status:     │
│    failed?      → error_reason explains the gap        │
│    subscription → halted? invoice generated, never     │
│                   charged = silent revenue death       │
│  Measure: unexplained ₹ BEFORE vs AFTER                │
└────────────────────────────────────────────────────────┘
                          ↓
┌─ RANK ─────────────────────────────────────────────────┐
│  Materiality: benign (explained, no action) vs         │
│  actionable (needs a human)                            │
│  Success = SHORT list, not long one                    │
└────────────────────────────────────────────────────────┘
                          ↓
┌─ EXPLAIN (LLM, scoped) ────────────────────────────────┐
│  Input: resolved exception cluster + proof             │
│  Output: plain-language cause + recommended action     │
│  Never invents numbers. Numbers come from the engine.  │
└────────────────────────────────────────────────────────┘
                          ↓
        UI: verdict → detail → correlation → audit
```

**Statuses** (adopted from Hyperswitch, not invented):
`Pending · Reconciled · Exception · Partially Reconciled · Archived · Void`
Rule: *Partially Reconciled is only ever set by a human*, never the engine.

---

## 2. Where AI is used — and deliberately isn't

| Stage | AI? | Why |
|---|---|---|
| Column mapping | Optional | ReconPe does this well; nice-to-have, not core |
| Matching | **No** | An LLM must never decide if two numbers are equal |
| Fee arithmetic | **No** | Deterministic, verifiable, must be exactly right |
| Classification | **No** | Rules with proof on every row |
| Correlation | **No** | It's a join, not a judgment |
| Materiality ranking | Borderline | Start rules-based; upgrade only if rules fail |
| Explanation | **Yes** | The one thing rules genuinely cannot do |
| Recommended action | **Yes** | Reasoning over already-resolved facts |

This table *is* your answer to the "AI judgment — and where you chose not to use one" criterion. Put it in the submission verbatim.

---

## 3. Stack

- **Backend:** FastAPI + pandas. (Aligns with the API-design learning you're already doing — one project, two purposes.)
- **Frontend:** Next.js + Tailwind. Your strongest area; this is where you out-execute a backend-heavy field.
- **Storage:** SQLite or flat files. Deliberately not Postgres at this scale — be ready to say why.
- **Audit log:** JSON Lines, human-readable. You'll debug with it at 2am.
- **LLM:** one scoped call per exception cluster, structured JSON in, prose out.

---

## 4. Build sequence

**Stage 1 — Prove the pipe** *(do not skip)*
Pull one real settlement recon response from test mode. Look at the actual JSON before designing anything. Docs and reality diverge; find out now, not the night before.

**Stage 2 — Seeded data generator**
Ledger + bank CSVs with *known* planted defects. You control ground truth, so your metrics are honest rather than estimated. Plant: missing order, wrong fee rate, one-sided refund, timing lag, duplicate, and a cluster of halted subscriptions.

**Stage 3 — Deterministic matcher**
Two passes. Match rate reported. Nothing clever yet.

**Stage 4 — Classifier + proof**
Every exception row carries the arithmetic that explains it.

**Stage 5 — Correlation**  ← *the differentiator; protect this time*
Fold failure + subscription data into the unexplained bucket. Measure before/after.

**Stage 6 — Materiality ranking**
Benign vs actionable. Short list.

**Stage 7 — LLM explanation layer**
Genuinely the easy 20%. Do not start here.

**Stage 8 — UI**
Four screens: verdict / detail / correlation / audit.

**Cuttable if time runs short:** AI column mapping, live webhooks, multi-gateway support, bank statement leg (fall back to two-way recon).
**Never cuttable:** correlation metric, honest exception list, audit trail.

---

## 5. UI

Default screen is **four lines and a verdict** — the answer first, not a wall of charts. Hyperswitch and Cointab build for a finance operator who lives in the tool; you're building for a merchant who opens it for two minutes on Monday, and who needs the depth to exist for the Monday they don't. The detail screens are reached from the verdict, not shown alongside it.

```
Expected ₹8,40,000 · Received ₹7,88,000 · Gap ₹52,000

→ ₹31,000  not missing, just late — 47 Friday orders land Tuesday   [detail]
→ ₹12,400  Razorpay's cut + tax on it — matches your rate           [detail]
→ ₹4,800   refunds you gave but didn't record                       [detail]
⚠ ₹3,800   6 subscriptions died silently — recoverable              [detail]
  ₹0       we can't explain

→ One thing needs you this week: those 6 customers.
```

Every finance term is either explained inline or absent. `[detail]` expands to MDR breakdown, GST on MDR, settlement_id, transaction list. **Layered, not dumbed down** — the depth proves the simplicity is a choice.

Ship a **"load demo data"** button. Judges will not upload CSVs during a 2-minute demo.

---

## 6. Testing scalability & generalizability

This section is what separates a demo from a build. Most entrants will test one happy path.

### 6a. Volume scaling

| Batch | Purpose | Report |
|---|---|---|
| 50 | Meets track minimum | Match rate, exception list |
| 500 | Realistic small merchant/month | Throughput (records/sec) |
| 5,000 | Mid-size D2C monthly volume | Where does it degrade? |
| 50,000 | Breaking point | Name the bottleneck honestly |

Report **records/second and wall-clock time** at each tier. Finding and *naming* your bottleneck ("matching is O(n²) above 10k, would need indexed joins") scores better than pretending there isn't one.

### 6b. Business archetypes — the real generalizability test

Generate a distinct seeded dataset per archetype. Each stresses different logic:

| Archetype | Stresses | Trap to catch |
|---|---|---|
| **D2C e-commerce** | High volume, small ticket, heavy refunds | Refund-offset math, rounding at scale |
| **SaaS subscription** | Recurring, halted states, invoices | Correlation path — your core claim |
| **Marketplace (Route)** | Split payments to linked accounts | Settlement ≠ single merchant |
| **Services / B2B invoicing** | Low volume, large ticket, TDS | 194-O TDS deduction, long gaps |
| **Education / one-time** | Bursty, seasonal | Timing tolerance breaks on spikes |

If your engine only works on archetype 2, say so. A stated limitation beats a discovered one.

### 6c. Payment-method mix — the sharpest axis

**Fee structures differ fundamentally by rail, and this will break naive implementations.** UPI carries zero MDR as mandated for banks, while cards carry ~2% MDR plus 18% GST on that MDR. A UPI-heavy merchant and a card-heavy merchant have *completely different* expected-fee profiles.

Test at minimum:
- 90% UPI / 10% card (typical Indian small merchant)
- 90% card / 10% UPI (typical cross-border or high-ticket)
- Even mix across UPI, card, netbanking, wallet
- International cards (different rate, currency conversion)

A hardcoded 2% fee assumption will pass demo #1 and fail every UPI-heavy merchant in India. This is the most likely place your build is quietly wrong.

### 6d. Settlement cycle variation
Standard is T+2; merchants with strong history and low chargeback rates can get T+1. International runs longer. Your timing tolerance must be **configurable, not hardcoded** — test T+1, T+2, T+7.

### 6e. Adversarial / robustness cases

Run these and report what happened:

- Empty batch
- Batch where everything matches (does it correctly say "nothing to do"?)
- Batch where nothing matches (does it fail loudly or silently produce nonsense?)
- Same file uploaded twice → duplicate detection
- Bank statement arriving *after* first run → re-run and merge, don't corrupt
- Ledger with renamed/reordered columns → does normalization catch it or guess?
- Amounts as `"1,234.50"` strings vs paise integers
- One order paid across two settlements (partial settlement)
- Refund issued *before* the original settled

### 6f. Correlation-specific tests

Your headline claim needs its own test matrix:

- **Correlation gain:** unexplained ₹ before vs after, per archetype. Should be large for SaaS, near-zero for one-time-payment businesses — and *saying* that is honest calibration, not weakness.
- **False attribution:** plant a gap that looks like a halted subscription but isn't. Does the engine wrongly claim it? **Find a case where it does, show it, fix or disclose it.** This is your failure-recovery evidence — criterion four, handed to you.

### 6g. What to report

```
Batch size · Archetype · Payment mix
Match rate %
Auto-resolved vs escalated (count + ₹)
Unexplained BEFORE correlation → AFTER
Seeded defects caught / missed  ← the honest list
Throughput (records/sec)
Known failure modes
```

One cherry-picked match proves nothing. A table across five archetypes and four volume tiers, with a miss list, proves a lot.

---

## 7. Claims discipline

**Don't say:** "Nobody does AI reconciliation." Demonstrably false — Cointab, ReconPe, Hyperswitch, Microsoft all ship versions.

**Do say:** "Existing tools are architecturally siloed — recovery, reconciliation and cost are separate products. An anomaly spanning two of them has no owner, so it reaches the merchant as 'unexplained.' We close that gap and measure how much of the unexplained it eliminates."

Verifiable, specific, and doesn't require calling anyone lazy.

**Also say openly:** architecture informed by studying Hyperswitch's published design. "I looked at how people who solved this at scale structured it" is a strong answer to *how do you think*. Getting caught quietly reproducing it mid-demo is the bad version.
