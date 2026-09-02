# Limitations & Deliberate Cuts

Two kinds of entry: things scoped out **on purpose**, and limits **discovered** during
the build. Both belong in the submission.

Named, deliberate cuts read as judgment. Silence reads as omission.

This file grows continuously — the moment a limit is found it is written here, not
remembered for later.

---

## Deliberately out of scope

Decided before the build, restated so the reasoning survives to the writeup.

| Cut | Why |
|---|---|
| **Multi-gateway support** | The thesis is depth on one PSP's data model, not breadth. Correlation needs Razorpay's specific failure taxonomy and subscription lifecycle. |
| **Marketplace / Route splits** | Settlement ≠ single merchant changes the matching model substantially. Real work, wrong scope for the time available. |
| **Webhooks** | The production path — named by name in the writeup, not built. Batch reconciliation is the demonstrable loop. |
| **AI column mapping** | ReconPe does it well. It is also AI applied where determinism would do, which cuts against the AI-usage argument. |
| **B2B / TDS archetype** | Section 194-O TDS deduction is genuinely different arithmetic and would need its own correctness testing. |
| **Education / seasonal archetype** | Bursty timing stresses tolerance logic; interesting, not core to the claim. |
| **Production auth** | Test mode only. Multi-tenant auth proves nothing about the thesis. |
| **Any database beyond SQLite / flat files** | 50–5,000 rows. Postgres here would be infrastructure the problem doesn't have. |

---

## Known risks, carried

Identified in advance, actively mitigated. Not yet observed as failures.

| Risk | Mitigation | Status |
|---|---|---|
| Hardcoded fee rate wrong for UPI-heavy merchants | Rate card is config; `config` refuses to supply a default MDR; explicit payment-mix test | Mitigated by design, unverified |
| Correlation mis-attributes a gap | Planted deliberately on test day and documented | Planned |
| Timing tolerance breaks on bursty volume | Tolerance configurable, T+1/T+2/T+7 tested | Planned |
| Live API integration eats the clock | Hard 2h timebox, seeded fallback always ready | Not started |
| Not from a finance background | Every finance term in output is explained by the system or absent — a forcing function on our own understanding | Ongoing |

---

## Discovered during the build

Actual limits found while building. Empty entries are honest, not lazy.

### Phase 0 — foundations

**pandas 3.0.5 resolved rather than 2.x.** Copy-on-write is now mandatory and the default
string dtype changed. Judged low-risk (money is integer, no chained-assignment mutation)
and accepted rather than pre-emptively pinned. If Phase 1 surfaces dtype surprises, the
escape hatch is pinning `pandas>=2.2,<3` — one line. See ADR-005.

**Source planning documents arrived mojibake-encoded** (`â¹` for `₹`). Corrected on
write and verified. Recorded because the same text feeds LLM prompts and UI copy later,
where corrupted characters propagate silently.

### Phase 1 — engine

**The fee/tax convention is unresolved, and it is the number everything depends on.**
Razorpay's prose says `Net = Gross − MDR − GST on MDR`; its own documented example shows
`credit = amount − fee` with `tax: 0`. The two cannot both be literally true. The engine
therefore *derives* the convention per batch and raises on inconsistency (ADR-007) rather
than assuming — but the derivation currently runs against our own synthetic data, so it
proves internal consistency, not agreement with Razorpay. `finctl probe` reports
**UNDETERMINED** on the documented fixture, correctly, because every row there has
`tax: 0` and both identities hold.

*Resolution:* Day-2 live capture with non-zero tax. Until then this is an open assumption,
stated rather than hidden. If a judge asks "how do you know your fee math is right", the
honest answer today is: *the engine detects the convention rather than assuming one, and
refuses a batch where the identity fails — but we have not yet confirmed it against a
live response.*

**Fixtures are documented-shape, not live-captured.** No Razorpay test credentials were
available during Phase 1. Per ADR-006 this was not allowed to block the build. Every
fixture declares `live_capture: false` inline, and a test asserts that declaration exists,
so the distinction cannot be lost by reading a file alone.
