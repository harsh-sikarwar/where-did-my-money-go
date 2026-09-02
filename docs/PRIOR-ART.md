# Prior Art & Attribution

Every concept borrowed from an existing system, named, with what specifically was taken
and what was deliberately not.

**Why this file exists.** `PROJECT-CONTEXT.md` §10 makes the positioning explicit:
saying openly *"architecture informed by studying Hyperswitch's published design"* is a
strong answer to "how do you think." Being caught quietly reproducing it mid-demo is the
bad version. That defence only works if the specifics can be named on request — hence
this file, maintained as things are borrowed rather than reconstructed for the writeup.

---

## Hyperswitch (Juspay · Apache 2.0 · ~42k GitHub stars)

Razorpay is one of its connectors. Ships **three separate modules**: Revenue Recovery,
Reconciliation, and Cost Observability.

### Taken

| Concept | Where it lands | Note |
|---|---|---|
| **Staging entries** — ingested rows validated but not yet reconciled, held immutable | `finctl/stage/` | This is what makes re-runs safe and the audit trail possible. Without it, a second run mutates the evidence of the first. |
| **Exception status taxonomy** — `Pending · Reconciled · Exception · Partially Reconciled · Archived · Void` | engine status enum | Adopted verbatim, not invented. Using an established vocabulary is cheaper and more defensible than coining one. |
| **"Partially Reconciled is only ever set by a human"** | engine invariant | A machine that can mark its own work partially done will use that state to hide uncertainty. Reserving it for humans keeps the engine's output binary and therefore honest. |
| **Rule-evaluation separated from ingestion** | `normalize`/`stage` vs `classify` | Lets classification rules change without re-ingesting. |

### Deliberately not taken

- **The three-module split itself.** This is precisely the thesis: recovery,
  reconciliation and cost as separate products means an anomaly spanning two of them has
  no owner and reaches the merchant as "unexplained." The correlation stage exists to
  cross that boundary.
- Connector abstraction, multi-gateway support, the full deployment topology — all
  scoped out (`build-plan-3.5-days.md`, "Still cut").

---

## Cointab

Razorpay fee and tax verification. Commercial.

### Taken

| Concept | Where it lands | Note |
|---|---|---|
| **Side A / Side B ingestion model** — merchant's record vs the counterparty's record, reconciled against each other rather than one treated as truth | ingest + two-pass matcher | Ledger is Side A, settlement/bank is Side B. |
| **Leave items unmatched when evidence is weak** | `NEEDS_REVIEW` classification | A forced match is worse than an admitted gap: it converts a visible problem into an invisible one. This is why the classifier emits `NEEDS_REVIEW` when more than one rule fires, instead of picking the highest-scoring rule. |

### Deliberately not taken

Their operator-centric UI model. Cointab builds for a finance operator who lives in the
tool; this builds for a merchant who opens it for two minutes on Monday. Same data,
opposite default screen.

---

## ReconPe (₹3,999/mo)

Rate-card audit plus AI column mapping.

### Taken

**Rate-card audit as a first-class idea** — the question is not only "did the money
arrive" but "was the fee charged the fee that was contracted." Directly motivates the
`FEE` and `TAX_ON_FEE` classifications and the config-driven rate card.

### Deliberately not taken

**AI column mapping.** ReconPe does this well, and it is genuinely useful — but for this
build it is a nice-to-have that would consume time the correlation loop needs, and it
sits in the "AI where determinism would do" category the AI-usage table argues against.
Named as a deliberate cut, not an oversight.

---

## `Sashank2006/Razorpay-Drift-Reconciler` (GitHub)

Cross-batch fee drift detection. Plausibly another entrant in this buildathon.

### Taken

**Scale discipline** — no infrastructure the problem doesn't need. Reinforces the
flat-files/SQLite decision at 50–5,000 rows.

### Relationship, stated plainly

They state *"per-batch matching is a solved problem"* and go **cross-time** (has the fee
rate drifted between batches?). This project goes **cross-domain** (does payment-failure
data explain a settlement gap?). Different axis on the same agreed premise. If asked
directly, that is the answer — not a claim that they are wrong.

---

## Terra Insight

Publishes the matching recipe openly.

### Taken

**The benchmark number.** Manual VLOOKUP reconciliation lands around **51% match rate**;
structured tooling reaches **88%+**. This is the yardstick our measured match rate should
be read against — a match rate reported without a baseline means nothing.

---

## Razorpay's own documentation and terms

- **Settlement, payment and subscription entity shapes** — the canonical schema mirrors
  Razorpay's field names (`utr`, `settled_at`, `error_reason`, …) so that swapping seeded
  data for live API data is a source change, not a schema change.
- **`amount` in paise** — Razorpay's own convention, adopted directly (ADR-003).
- **The `halted` subscription lifecycle** — `failed` → `pending` → `halted`, during which
  invoices continue to be generated but charges are not attempted. This is a *documented
  Razorpay state*, not an invented scenario. It is the demo centrepiece precisely because
  it is real and verifiable.
- **Razorpay's T&C: the merchant is responsible for daily reconciliation**, and
  discrepancies must be reported within 3 days. Razorpay contractually states this is the
  merchant's job — which is the strongest available answer to "why doesn't Razorpay just
  do this for you."

---

## The claim discipline this file enforces

**Never say:** "Nobody does AI reconciliation." Demonstrably false — Cointab, ReconPe,
Hyperswitch and Microsoft all ship versions. A judge will challenge it and be right.

**Say:** "Existing tools are architecturally siloed — recovery, reconciliation and cost
are separate products. An anomaly spanning two of them has no owner, so it reaches the
merchant as 'unexplained.' We close that gap and measure how much of the unexplained it
eliminates."

Verifiable, specific, and it doesn't require calling anyone lazy.
