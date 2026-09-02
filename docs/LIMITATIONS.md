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

### Phase 1b — generator

**The generator models a correct Razorpay using the engine's own fee code** (ADR-013).
This is deliberate and argued, but it has one real consequence: a bug inside
`expected_fee()` would make generator and classifier agree *wrongly*. Mitigated by testing
`expected_fee()` against the brief's worked example — external truth, not our own output —
rather than against generated data.

**The generator emits one fee convention per batch.** Real Razorpay data is assumed
internally consistent; a genuinely mixed batch is treated as an error (ADR-007). If
Razorpay ever mixes conventions within one recon report, our engine raises rather than
handling it. That is the intended behaviour, but it is an assumption, not a verified fact.

**Refunds are modelled as one-sided by omission.** The one-sided-refund defect is a refund
the merchant recorded that never reaches settlement. The reverse case — a settlement refund
the merchant never recorded — is not yet generated. Both should exist; only one does.

### Phase 1c — normalize / stage / match

**Our match rate is an exact-identifier rate, which is stricter than the industry
convention.** Many tools count fuzzy matches (amount + date proximity) toward their
headline number. We do not (ADR-015), so our figure is not directly comparable to a
published match rate unless that caveat is stated. It should be stated.

**Column aliases are a finite hand-written list.** A merchant whose CSV uses an unlisted
spelling gets a loud error naming the accepted spellings, not a guess. That is the intended
behaviour, but it does mean first-run friction on an unfamiliar export format. AI column
mapping (ReconPe's approach) would remove it and is deliberately out of scope.

**Duplicate detection is whole-file, by content hash.** The same file staged twice is
caught. A file containing *some* rows already staged in a previous batch is not — that
needs row-level dedup across batches, which is not built. The adversarial case "bank
statement arriving after the first run" is therefore only partially handled: re-running is
safe and non-corrupting, but overlapping rows would double-count.

### Phase 2a — API and UI

**The API has no authentication and permissive CORS.** It is a single-user local demo
tool. Production auth is explicitly out of scope (see the deliberate cuts above), and the
API binds to localhost. Batch names are validated against path traversal before touching
the filesystem, so the one real risk in a local tool is covered.

**Pipeline results are cached in a plain dict, keyed by batch name.** Regenerating a
batch requires `?refresh=true` or an API restart to see new data. Fine for a demo tool;
it would be wrong for anything multi-user. A cache library here would be infrastructure
the problem does not have.

**The UI renders one hardcoded batch (`demo`).** The batch-listing endpoint exists and
works, but there is no picker. The demo-data button and CSV upload path are Phase 2
items not yet built.

### Phase 2b — audit trail

**The audit log is held in memory during a run and written once at the end.** A crash
mid-run leaves no log. This is a deliberate trade — per-event fsync would make the audit
trail the throughput bottleneck rather than the matcher — but it means the log documents
completed runs only.

**`RECONCILED` rows are summarised, not enumerated** (ADR-022). Justified, tested against
reconstructibility, and stated here so the reading of "refuses to summarise" is visible
rather than assumed.

**The audit view reads at most 500 events.** The full log is on disk; the screen is a
reader, not the record. A 50,000-row batch would need pagination in the UI to be fully
browsable there.

### Phase 1c-ii — classify / correlate

**100% correlation gain is a property of our test data, not a general claim.** Every gap
the generator plants has a correlatable payment record behind it, because that is how the
generator creates gaps. Real data contains gaps with no payment record at all — bank
errors, month-boundary timing, data-entry mistakes — and those correctly remain
UNEXPLAINED. The refusal tests demonstrate the engine does not over-claim, but the headline
gain number should be reported with this caveat, not as evidence that correlation resolves
everything. Day 3's planted decoy exists to attack exactly this.

**Correlation depends on the payments feed being complete.** If a payment record is absent
for an order, the row stays UNEXPLAINED — correctly, but it means the differentiator's
reach is bounded by data availability rather than by logic. A merchant whose Razorpay
export omits failed payments would see the gain drop to near zero.

**Only timing has a tolerance wide enough to hide a whole defect.** `_is_below_tolerance`
handles the timing case only. If a future tolerance grows (a fee tolerance in basis points,
say), that function needs the new case — its absence would show as a sudden unexplained
drop in recall rather than a silent miscount, but it is a known sharp edge.

**REFUND is inferred from direction, not from a refund record.** The classifier labels a
negative amount gap as REFUND because that is the shape a one-sided refund makes. It does
not verify against an actual `type: "refund"` recon row, because in the one-sided case
there is none by definition. A negative gap with some other cause would be mislabelled.
This is a genuine soft spot and a good candidate for the Day 3 adversarial pass.

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

**Razorpay Subscriptions is not enabled on our test account.** `/v1/subscriptions` and
`/v1/plans` return `401` while every other endpoint returns `200` with the same key —
independently reproduced with `curl`, so it is product activation, not auth. The `halted`
subscription cluster is the demo centrepiece, so this is worth stating plainly: **our
subscription entity shape is derived from Razorpay's documentation, not verified against a
live response.** The lifecycle we model (`failed → pending → halted`, invoices generated
but charges not attempted) is documented Razorpay behaviour, not invented. See ADR-011.

**The test account has processed nothing.** Payments, orders, settlements, customers,
invoices and recon all return `count: 0`. The live probe therefore proves *reachability*
and nothing about *shape*. Combined with test mode not reliably generating settlements on
the T+2 schedule, **ADR-007 may not be answerable in test mode at all** — see ADR-012.
This is now enforced by a test that fails the moment a capture lands real rows, rather
than tracked as a note.

**Fixtures are documented-shape, not live-captured.** No Razorpay test credentials were
available during Phase 1. Per ADR-006 this was not allowed to block the build. Every
fixture declares `live_capture: false` inline, and a test asserts that declaration exists,
so the distinction cannot be lost by reading a file alone.
