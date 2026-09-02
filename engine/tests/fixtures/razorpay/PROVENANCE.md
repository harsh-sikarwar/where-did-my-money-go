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

**None of these are live-captured yet.** No test credentials were available at Phase 1.
Every file carries a `_provenance` key stating this inline, so the distinction cannot be
lost by reading the file alone.

## What must happen on Day 2

Re-run `finctl probe --live` with real test-mode credentials and **overwrite** these
files with genuine captures. Then:

1. Diff documented shape vs live shape. Any difference is a finding worth recording in
   `JOURNAL.md` — docs and reality diverging is exactly what the probe exists to catch.
2. Resolve **ADR-007** definitively: is `fee` GST-inclusive or MDR-only? The live data
   answers this, and it is the single number the whole verdict depends on.
3. Update the `status` column above from *documented shape* to *live capture*.

Until step 3 happens, `LIMITATIONS.md` carries this as an open, unverified assumption.

## Safe to commit

Test-mode entity shapes contain no credentials and no real customer data. The ids here
are Razorpay's own documentation examples.
