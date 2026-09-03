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
| Hardcoded fee rate wrong for UPI-heavy merchants | Rate card is config; `config` refuses a default MDR | **Occurred.** The mechanism worked; the shipped *value* was wrong — UPI billed at 0 when the ~2% platform fee applies. Found by reading Razorpay's pricing page, not by the suite. Fixed in ADR-035 |
| Correlation mis-attributes a gap | Planted deliberately on test day and documented | **Run.** 2,246 decoys across 22 matrix runs, 0 claimed, false-attribution rate 0.0000 (ADR-042). The decoy is a failed payment on a *healthy* subscription — same shape as the halted centrepiece, differing in `status`/`auth_attempts`. Limit: we designed the confusion, so it does not prove resistance to one we did not imagine |
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

**Refunds are modelled as one-sided by omission.** ~~The one-sided-refund defect is a refund
the merchant recorded that never reaches settlement. The reverse case — a settlement refund
the merchant never recorded — is not yet generated. Both should exist; only one does.~~
**Closed 2026-09-03 (ADR-039).** The reverse case is now generated and classified as
`UNRECORDED_REFUND`. Razorpay's own sample export contained one, and it revealed something
worse than a missing defect type: those rows carry a blank `order_id`, and the matcher
dropped every row without one. Money left the merchant's account and no stage of the
engine ever saw it.

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

### Blind testing — what it establishes, and what it does not

`finctl blind` runs the engine against a batch whose configuration and answers it has
never seen. The first run **passed** (0 missed, 0 false positives) and **found a real
bug**: the classifier judged every batch against the configured T+2 rather than the cycle
the batch was actually settled on (ADR-030).

**What this establishes.** The engine is not tuned to one specific batch. It handles
unseen volumes, mixes, archetypes and cycles.

**A hand-edited run found a bug nothing else could.** Deleting two ledger rows with `sed`
left ₹16,992.29 unaccounted for: `decompose()` handled orphan bank rows but not orphan
settlements (ADR-031). No generated case could have found it — the generator writes the
ledger first and derives settlements from it, so settled money with no ledger row behind
it is structurally unreachable. Three edits found what 22 matrix runs and 500+ tests could
not.

**What it does not establish.** The generator still produces Razorpay-shaped data with
defect types we designed. A blind test rules out *"tuned to one batch"*; it does not rule
out *"tuned to the failure modes we imagined"*. Closing that gap needs data we did not
generate — either hand-edited CSVs, or a real merchant export. The strongest available
version is hand-editing, and it is documented in `docs/BLIND-TEST.md`.

**On public benchmarks.** We examined BenchRec, the ICAIF 2023 reconciliation benchmark
(real Tier 1 bank data, held-out solution file). It is a *fuzzy matching* task — predict
which GL allocation a bank line belongs to — with no order ids, no settlement layer, no
fees, and no subscriptions. Our engine matches on exact identifiers and explicitly refuses
fuzzy matching (ADR-015), so running it there would score near zero and prove nothing
about correctness. Worth citing for one number though: **34% of that bank's
reconciliation was done manually**, which is a far better baseline for "this is hard" than
the VLOOKUP comparison.

### Composition audit — what it found, and what it did not cover

Two further bugs, both found by *running* adversarial cases rather than reasoning about
code: duplicated ledger rows left ₹7,305.71 unattributed (ADR-025), and an empty batch
raised instead of answering "nothing to reconcile" (ADR-026). Both fixed and asserted.

**Not covered by this audit:** one order split across two settlements, and a refund
issued before its original settled. Both are listed in `build-spec.md` §6e and neither is
exercised by the generator yet, so the engine's behaviour on them is *unverified* rather
than known-good. They belong in the Day 3 adversarial block.

### Phase 2b — a composition bug the test suite could not see

**The verdict screen's lines did not sum to its gap** — ₹99,421.65 of lines against a
₹38,372.30 gap. Fixed (ADR-024), and now asserted on every run and across every
configuration. Recorded here rather than only in the journal because the *class* of
failure is the useful part:

Every individual number was correct and independently tested. The bug was in the
*relationship between* correct numbers, which component tests cannot see by construction.
A suite can be thorough about parts and silent about the whole — and for a product whose
claim is "every rupee accounted for", the arithmetic of the headline was the thing most
needing an invariant and the thing that lacked one.

It was found by a human reading the screen, not by any test. That is worth saying out
loud in the submission: it is a real instance of criterion 4, and the fix is an
invariant that raises rather than a patch that happens to work.

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

**Partially addressed (ADR-039), and stated precisely.** Where a real refund row *does*
exist, the engine now reads it rather than inferring: `UNRECORDED_REFUND` fires on the
row itself, carrying its `entity_id`, `arn` and reason. The direction inference remains
for the genuinely one-sided case — where by definition there is no row to check — so the
soft spot is narrowed, not closed. Two confidence levels now exist where there was one,
which is the honest position rather than a claim to have solved it.

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

### Review — external checks against published pricing and prior art

**A UPI-labelled row can carry two different rates, and we cannot always tell which.**
`method: upi` covers both a bank-to-bank UPI payment (~2% platform fee) and a RuPay
*credit card* paid through a UPI app (2.15% + GST) — a credit-card transaction wearing a
UPI mask. The rate card prices both (`upi`, `upi_rupay_credit`), but if a batch labels the
masked case as plain `upi` with no distinguishing field, we will check it against the
wrong rate and report a small FEE discrepancy on a transaction that was billed correctly.
The 15 bps gap is under most rounding tolerances at single-transaction scale and becomes
visible in aggregate. We do not currently detect the ambiguity, and cannot without a field
that separates them. See ADR-035.

**No fuzzy matching, by choice — and it costs recall.** ADR-015 refuses approximate
matching on identifiers. A comparable open-source implementation (Sashank2006) matches on
`order_id + amount + date window` with numeric tolerance, arguing that nobody misspells an
order id so the tolerance is on the *numbers*, not the string. That is a reasonable
position and it will match rows we leave unmatched. We chose the opposite failure: we
would rather report "unmatched, look at it" than assert a pairing we cannot prove. This is
a real recall cost on messy merchant data, not a claim of superiority.

**No composite hypotheses.** When two line items together explain a gap that neither
explains alone, we go to UNEXPLAINED. The same prior implementation attempts a composite
path. Compound faults are common in real data, so this is a genuine coverage gap; the
residual absorbs it honestly rather than guessing, but it does absorb it.

**Bank-leg aggregation is N:1 and depends on it.** A settlement consolidates many payments
into one bank credit under one UTR, so pass 2 aggregates per UTR rather than comparing row
to row. This is the same cardinality Hyperswitch documents for its second leg. It is
tested and it holds — noted here because a row-to-row comparison would appear to work on
small batches and fail on any batch with real consolidation.

**We refuse to guess a column mapping; Cointab lets the user draw one.** A commercial
implementation of this same reconciliation accepts CSV/XLS/XLSX and has the user map
columns in a UI. We raise on an unrecognised header instead. Defensible for an engine that
must never silently misread a money column, but it is the friction point on a real
merchant's file, and "raise" is not a substitute for the mapping step a product would need.

### Real-data phase — what Razorpay's own sample files falsified

We obtained Razorpay's twelve official sample report exports to build the upload path
against real headers. Four assumptions did not survive contact with them.

**A date format we could not read, that failed silently.** The recon export carries Excel
serial dates (`44658.44689814815`) and `DD/MM/YYYY HH:MM:SS` **in the same column**. Our
parser read the bare-integer form as epoch seconds and returned **1970-01-01**. It raised
nothing. Every affected order would have looked ~52 years late and been filed as TIMING —
the benign bucket — while also corrupting the observed settlement cycle for the whole
batch. Fixed in ADR-037. That this survived 547 tests is the point: the generator emits
epoch seconds, so no batch it produced could reach the branch.

**The exports are `.xlsx`, not CSV.** ~~The normalizer is `csv.DictReader` only.~~
**Closed 2026-09-03 (ADR-043).** Both formats now read through one function, and a test
asserts an `.xlsx` batch produces the same gap, headline and score as the identical
`.csv` batch — a separate xlsx path would be a second implementation of the engine
rather than a second door into it. "Real CSV upload" was the wrong framing of the
feature: Razorpay's dashboard hands a merchant an Excel file.

**Our recon type discriminator had the wrong name.** `matcher.py` branched on
`row["type"]`; the real column is `transaction_entity`. The *values* match (`payment`,
`refund`) but the key did not, so on a real export every recon row was dropped and every
order reported as MISSING. ADR-008 committed to Razorpay's own field names precisely so a
live-data swap would be a source change rather than a schema change — this is one place
that promise had drifted, and no test could catch it because both sides of the test used
our name. Fixed in ADR-038 via an accessor that reads either spelling; both remain
supported, since the live API and the dashboard export genuinely differ.

**Amounts are rupee decimals, not paise.** `amount: 1.0` means one rupee. Our JSON
ingest path (`load_collection`) assumes canonical integer paise. The CSV/xlsx path parses
rupee strings correctly, so this is a live hazard only where the two paths meet.

**What these files do and do not establish.** They are authoritative for **schema and
format**, which is what we most needed. They are *not* a real merchant's data: 10 recon
rows, one payment method (`bank_transfer`), `sample utr` as a literal string, and no
populated disputes. So they close the "am I reading the right columns" question and
leave the "are my accuracy numbers self-graded" question open. The accuracy figures in
METRICS.md are still measured against generator-produced ground truth, and obtaining
these files does not change that.

### The actionable list is at its cap

The verdict's actionable list is now **5 lines** — `UNRECORDED_REFUND`, `DISPUTED`,
`HALTED_SUBSCRIPTION`, `PAYMENT_FAILED`, `ON_HOLD` — and `test_rank.py` caps it at 5.

That cap has been raised twice, each time because the engine learned to name a cause it
previously left in UNEXPLAINED (ON_HOLD in ADR-036, UNRECORDED_REFUND in ADR-039,
DISPUTED in ADR-041). Each raise was the right call in isolation: money moved out of a
silent bucket onto a line with an owner.

It is not repeatable. The product promise is that a merchant reads this list in one
glance on a Monday morning, and a sixth line starts making it a dashboard — the thing
this project argues against from the README down. The next classification added forces a
real decision (grouping related causes, or a "more" affordance), not another cap raise.
Stated here so that decision is made deliberately rather than by a test edit.

### Upload exists; the mapping picker does not

`POST /api/upload` accepts a merchant's own files and reconciles them (ADR-044). Two
things it does not yet do:

**~~An unfamiliar column name is a dead end in the browser.~~ Closed 2026-09-03
(ADR-045).** The 422 now carries structured data — which fields are unmapped and every
column available to choose from — `POST /api/inspect` returns headers plus three real
sample rows, and `POST /api/mappings` records the choice against a fingerprint of the
file's shape. Asked once, then never again for that shape, including next month's export
with the columns reordered. **The picker screen now exists** (ADR-047): the 422
becomes a set of buttons, one per unclaimed column, offered in file order and unranked so
the UI does not reintroduce the guess the engine refuses to make.

**~~The rate card is still ours, not theirs.~~ Closed 2026-09-03 (ADR-046).** A merchant
can now supply their contracted rates, layered over the shipped card so they state only
what they negotiated. On the demo batch a contracted 1.75% turns 30 fee findings worth
₹595 into 189 worth ₹3,552 — same data, different contract, and the proof quotes their
number. **The form now exists** (ADR-047), taking
percentages rather than basis points — the API takes bps because integers keep money
arithmetic exact, but no merchant thinks in bps and asking them to would invite the exact
unit error the API refuses.

### What still has no screen

~~The **action list** is the gap that matters now.~~ **Built 2026-09-03 (ADR-048).** The
verdict's "those 6 customers" now resolves to six named rows with amounts, reasons and a
next step, available in the CLI, the API and the UI, with a CSV export. Two residual
gaps: `REFUND` and `UNRECORDED_REFUND` rows have an empty "why" column, because nothing
upstream attaches a reason to them; and the customer column shows an id rather than an
email, because our generator has no contact fields — Razorpay's real payments export
does, and the code reads them when present, but that path is unexercised by our data.

**Correlation still has one mechanism.** Halted subscriptions, plus failed payments.
Disputes and on-hold settlements are now *classified* (ADR-036, ADR-041) but are not
correlator inputs, so the "correlation layer" claim rests on one join.

