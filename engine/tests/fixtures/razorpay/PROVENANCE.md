# Fixture Provenance

**These fixtures are the contract our synthetic data is held to.** A test asserts that
generator output is field-compatible with them. If Razorpay's shape and ours diverge, the
test suite says so — rather than a judge saying so.

See `docs/DECISIONS.md` ADR-006: *real API = verification, not foundation.*

---

## Source and status

| Fixture | Source | Status |
|---|---|---|
| `settlement_recon.json` | razorpay.com/docs/api/settlements/fetch-recon | **documented shape** — transcribed from published docs |
| `payment_failed.json` | razorpay.com/docs/api/payments/fetch-all-payments + error-code docs | **documented shape** — constructed from documented fields |
| `subscription_halted.json` | Razorpay Subscriptions docs | **documented shape** |
| `settlement_recon_live.json` | `GET /v1/settlements/recon/combined?year=…&month=…` | **live capture** — empty collection |
| `payment_failed_live.json` | `GET /v1/payments?count=100` | **live capture** — empty collection |

Every file carries a `_provenance` key stating its status inline, so the distinction
cannot be lost by reading the file alone.

## Live probe run — 2026-09-02

`finctl probe --live` was run against real test-mode credentials. Findings:

- **The test account is empty.** `/v1/payments`, `/v1/orders`, `/v1/settlements`,
  `/v1/customers`, `/v1/invoices` and `/v1/settlements/recon/combined` all authenticate
  and return `200` with `count: 0`. The account has never processed a payment.
- **`/v1/subscriptions` and `/v1/plans` return `401 Unauthorized`** while every other
  endpoint on the same key returns `200`. This is not an auth failure — it is the
  Subscriptions product not being enabled on the account. No live subscription shape
  could be captured.
- **The documented-shape fixtures were deliberately NOT overwritten.** An empty
  collection carries no item shape; replacing a documented fixture with one would delete
  the contract the test suite relies on and put nothing in its place. Live captures land
  beside them as `*_live.json`.
- **ADR-007 remains UNDETERMINED**, and honestly so. Settling it needs settled payment
  rows with **non-zero tax**; the account has no rows at all. Rows with `tax == 0`
  satisfy both identities and prove nothing, so no amount of re-running helps until the
  account has real settled data.

### What would be needed to answer ADR-007

Settlements are what carry `fee`/`tax`/`credit`, and they only exist downstream of a
captured payment. In test mode that means: create an order, pay it with a test card,
capture it, and wait for test-mode settlement to run. Note that test-mode settlements
are not guaranteed to be generated on the usual T+2 schedule, so the fee convention may
only be answerable against a real (live-mode) merchant account — in which case ADR-007
stays open and `LIMITATIONS.md` continues to carry it.

## What still must happen

The probe ran; the account had nothing to capture. Still open:

1. **Get data into the test account** (see above), then re-run `finctl probe --live`.
   The empty-account guard means a re-run with real data will overwrite the documented
   fixtures automatically, and diff them against the documented shape as it does.
2. **Resolve ADR-007** — is `fee` GST-inclusive or MDR-only? Still unanswered. It is the
   single number the whole verdict depends on, and only rows with non-zero tax settle it.
3. **Capture a live subscription shape** — blocked on Subscriptions being enabled for
   the account.

Until then, `LIMITATIONS.md` carries ADR-007 as an open, unverified assumption.

## Safe to commit

Test-mode entity shapes contain no credentials and no real customer data. The ids in the
documented-shape files are Razorpay's own documentation examples.

Live captures are additionally run through unconditional PII redaction before being
written: `email`, `contact`, `vpa` and related identity fields are replaced with fixed
placeholders (`redacted@example.com`, `+910000000000`, `redacted@upi`), whether or not
the response contained any. Nulls are preserved as null, because nullability is part of
the shape being captured. Each live file records `pii_redacted: true` in `_provenance`.
