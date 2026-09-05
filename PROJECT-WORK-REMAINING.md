# Work Remaining: Tasks, Effort, and Completion %

**As of 2026-09-05**

This is the full breakdown of what's left to ship. Every task is estimated in hours/minutes,
ranked by criticality, and tagged with current completion %. The goal: ship by 2026-09-06.

---

## Summary

| Category | Effort | Completion | Status |
|----------|--------|------------|--------|
| **Engine & API** | ~0h | 100% | ✅ Done |
| **Dashboard UI** | ~4h | 80% | 🔄 In Progress |
| **Credibility Reports** | ~1h | 100% | ✅ Done (just added) |
| **Demo & Testing** | ~2h | 0% | ⏳ Not Started |
| **Final Polish** | ~1h | 0% | ⏳ Not Started |
| **Total** | **~8h** | **70%** | |

---

## Work in Progress (Blocking)

### 1. Dashboard Route Implementation & Testing
**Effort:** 4 hours | **Completion:** 80% | **Criticality:** BLOCKING

All 12 routes are built but not yet tested end-to-end. Need to verify each route works
with real API calls, handles loading states, and gracefully degrades on errors.

#### 1.1 Overview Route (`/`)
**Effort:** 30 min | **Completion:** 80%
- [ ] Render verdict screen with all fields (gap, lines, verdict)
- [ ] Chart rendering (correlation before/after)
- [ ] Link to detail pages on click
- **Test:** Load demo batch, verify all numbers match expected

#### 1.2 Runs List (`/runs`)
**Effort:** 20 min | **Completion:** 75%
- [ ] Fetch batch list from API
- [ ] Display as filterable table
- [ ] Click → navigate to `/analysis/[batch]`
- **Test:** Create 2+ batches, verify list accuracy

#### 1.3 New Run Wizard (`/new-run`)
**Effort:** 45 min | **Completion:** 70%
- [ ] Upload CSV/XLSX file picker
- [ ] Generation form (volume, archetype, payment mix)
- [ ] Progress bar during reconciliation
- [ ] Redirect to analysis on complete
- **Test:** Upload real CSV, generate batch, verify roundtrip

#### 1.4 Analysis Breakdown (`/analysis/[batch]`)
**Effort:** 1h | **Completion:** 75%
- [ ] Render Summary tab (gap, lines, verdict)
- [ ] Render Line Items tab (drill-down on each classification)
- [ ] Render Evidence tab (source rows in audit log)
- [ ] Chart: daily breakdown (settlement timing)
- [ ] Chart: correlation before/after
- **Test:** Verify numbers match verdict API response, links to order detail work

#### 1.5 Exceptions Queue (`/exceptions/[batch]`)
**Effort:** 30 min | **Completion:** 70%
- [ ] Fetch actionable findings
- [ ] Display with severity (green/amber/red)
- [ ] Mark as reviewed / dismissed
- [ ] Filter by status
- **Test:** Verify actionability logic matches expected output

#### 1.6 Order Detail (`/orders/[batch]/[orderId]`)
**Effort:** 30 min | **Completion:** 75%
- [ ] Render order trace (path through pipeline)
- [ ] Show matching status (matched/missing/duplicate)
- [ ] Timeline view (settlement date, received date, etc.)
- [ ] Related classification + correlation info
- **Test:** Click from analysis, verify trace reconstruction

#### 1.7 Audit Log (`/audit/[batch]`)
**Effort:** 20 min | **Completion:** 70%
- [ ] Fetch audit events (last 500)
- [ ] Group by day
- [ ] Expandable rows for details
- [ ] Pagination/load-more
- **Test:** Verify event count and grouping matches API

#### 1.8 Data Sources (`/sources/[batch]`)
**Effort:** 20 min | **Completion:** 60%
- [ ] List uploaded files (with hash, size, row count)
- [ ] Show missing sources (expected but not found)
- [ ] Re-upload capability
- **Test:** Upload, verify file tracking

#### 1.9 Settings (`/settings`)
**Effort:** 20 min | **Completion:** 75%
- [ ] Display current rate card
- [ ] Edit + save rate card (persisted to localStorage)
- [ ] Show read-only sections (tolerances, etc.)
- **Test:** Edit rate, verify persistence across page reloads

#### 1.10 Rules (`/rules`)
**Effort:** 15 min | **Completion:** 80%
- [ ] Read-only display of tolerances, rate card, defect taxonomy
- [ ] No save capability
- [ ] Expandable sections for detail
- **Test:** Verify data matches API `/api/rules`

#### 1.11 Reports (`/reports/[batch]`)
**Effort:** 30 min | **Completion:** 70%
- [ ] Compose from verdict + actions + audit
- [ ] Export to PDF / CSV
- [ ] Print-friendly layout
- **Test:** Generate report, verify completeness

#### 1.12 Copilot Chat (`/copilot/[batch]`)
**Effort:** 45 min | **Completion:** 75%
- [ ] Message input + send
- [ ] Display chat history
- [ ] Stream responses (or show loading state)
- [ ] Guard against numerals in model responses
- [ ] Error handling (API timeout, bad response)
- **Test:** Send test questions, verify guard works, no numerals in output

#### 1.13 Copilot Drawer (Docked)
**Effort:** 20 min | **Completion:** 60%
- [ ] Dockable panel on right side of any screen
- [ ] Minimize/maximize/close
- [ ] Persist state in localStorage
- **Test:** Open from 3+ routes, verify state persists

---

### 2. Demo Uptime & Fallback Handling
**Effort:** 1h 30 min | **Completion:** 10% | **Criticality:** HIGH (Judges' first impression)

#### 2.1 Run full demo pipeline
**Effort:** 30 min | **Completion:** 0%
- [ ] Execute `./scripts/demo.sh`
- [ ] Measure cold-start time for API
- [ ] Verify all screens load without errors
- [ ] Navigate through all 12 routes
- [ ] Verify numbers match expected breakdown
- **Success criteria:** <10s cold start, all routes load, numbers correct

#### 2.2 Add visible loading state for slow API
**Effort:** 20 min | **Completion:** 0%
- [ ] Add "Waking up the engine…" message if API takes >2s to respond
- [ ] Hard timeout after 10s with fallback message
- [ ] Spinners on every data-fetching action
- **Test:** Simulate slow API, verify UX graceful

#### 2.3 Verify hosting doesn't cold-start on judging day
**Effort:** 20 min | **Completion:** 0%
- [ ] Check Vercel/hosting setup (free tier sleeps after 15 min)
- [ ] If needed: pin to paid tier or pre-warm
- [ ] Ensure demo.sh doesn't require authentication
- **Test:** Let API sleep 20 min, then run demo.sh, verify <5s response

#### 2.4 Test fallback without API key
**Effort:** 20 min | **Completion:** 0%
- [ ] Remove GROQ_API_KEY from env
- [ ] Run demo, verify explanation uses deterministic template
- [ ] Verify chat endpoint returns template prose, not model response
- **Test:** Run with `GROQ_API_KEY=""`, verify no errors

---

## Work Queued (After Routes)

### 3. API Enhancement — Health Endpoint
**Effort:** 30 min | **Completion:** 0% | **Criticality:** MEDIUM

#### 3.1 Enhance `/health` endpoint
**Effort:** 30 min | **Completion:** 0%
- [ ] Add field: `llm_credential_loaded` (boolean)
- [ ] Add field: `llm_actively_used_this_run` (boolean)
- [ ] Add field: `summary_source` (string: "groq" | "template")
- [ ] Add field: `engine_version` (string)
- [ ] Add field: `timestamp` (ISO 8601)
- **Test:** Call `/health`, verify all fields present

---

### 4. Metrics Hash — Determinism Proof
**Effort:** 45 min | **Completion:** 0% | **Criticality:** MEDIUM

#### 4.1 Add `--hash` flag to checkpoint/matrix
**Effort:** 45 min | **Completion:** 0%
- [ ] Compute SHA256 of sorted JSON output
- [ ] Print as one-line: `metrics_hash: <40-char-hash>`
- [ ] Document in README: "Judges can reproduce: `uv run finctl checkpoint --hash`"
- [ ] Verify determinism: run twice, same hash both times
- **Test:** `uv run finctl checkpoint --hash && uv run finctl checkpoint --hash` →
  identical hashes

---

### 5. Expose Offline-First Mode
**Effort:** 20 min | **Completion:** 0% | **Criticality:** LOW

#### 5.1 Make `--no-llm` flag explicit
**Effort:** 20 min | **Completion:** 0%
- [ ] Add CLI flag: `uv run finctl reconcile --no-llm`
- [ ] Or confirm it's the default and update README to say so clearly
- [ ] Update README table: "Summary source: Deterministic (no LLM)" as option 1
- **Test:** `uv run finctl reconcile --no-llm`, verify no API calls, deterministic output

---

## Testing & Validation (After Routes)

### 6. Final Integration Test
**Effort:** 1h | **Completion:** 0% | **Criticality:** BLOCKING

#### 6.1 End-to-end test scenario
**Effort:** 1h | **Completion:** 0%
- [ ] Generate demo batch
- [ ] Upload real CSV (or use generated data)
- [ ] Reconcile with all 12 routes active
- [ ] Verify verdict matches expected breakdown
- [ ] Verify audit log reconstructs every figure
- [ ] Export report + verify completeness
- [ ] Run blind test if time: `finctl blind new && finctl blind run && finctl blind score`

---

### 7. Regression Checks
**Effort:** 30 min | **Completion:** 50% | **Criticality:** MEDIUM

- [ ] Run all 903 tests (1 skipped): `uv run pytest`
- [ ] Update golden files: `uv run finctl golden --update`
- [ ] Verify no new lint errors: `ruff check .`
- [ ] Verify no TypeScript errors in web/: `npm run type-check`
- [ ] Verify all documentation links are valid

---

## Final Polish (Before Submission)

### 8. README & Docs Sync
**Effort:** 45 min | **Completion:** 70% | **Criticality:** HIGH

- [ ] Verify README test count matches actual (903 passing, 1 skipped) (DONE)
- [ ] Add link to BROKE-FIXED.md (DONE)
- [ ] Add link to HOW-WE-KNOW.md (DONE)
- [ ] Add credibility section (DONE)
- [ ] Remove any outdated ADR references
- [ ] Verify all code links are correct (build-spec, JOURNAL, LIMITATIONS)
- [ ] Proofread for typos and clarity

---

### 9. Environment Verification
**Effort:** 20 min | **Completion:** 20% | **Criticality:** MEDIUM

- [ ] `.env` is in `.gitignore` (verify with `git check-ignore`)
- [ ] `.env.example` has all required keys
- [ ] No secrets in code or docs (grep for `GROQ_API_KEY`, `sk-`, etc.)
- [ ] Verify secrets can't be accidentally committed

---

### 10. Demo Script Cleanup
**Effort:** 15 min | **Completion:** 0% | **Criticality:** MEDIUM

- [ ] Verify `./scripts/demo.sh` runs without manual intervention
- [ ] Verify it doesn't require authentication or live API
- [ ] Verify it opens browser at correct URL (localhost:3000)
- [ ] Verify it lands on verdict screen, not login

---

## Priority Order to Ship

### Must Do (Blocking)
1. **Complete all 12 routes** (4 hours)
   - Test each route loads, calls correct endpoint, shows data
   - Handle errors gracefully (no crashes)
   - Fix any UI rendering bugs

2. **Test demo end-to-end** (1 hour)
   - Run `./scripts/demo.sh`
   - Verify cold start + uptime
   - Verify fallback behavior (no API key)

3. **Verify all tests pass** (30 min)
   - `uv run pytest`
   - `npm run type-check`
   - No lint errors

### Should Do (High Signal)
4. **Enhance `/health` endpoint** (30 min)
5. **Add metrics hash** (45 min)
6. **Final documentation sync** (30 min)

### Nice to Have (Low ROI if time short)
7. **Expose `--no-llm` flag** (20 min)
8. **Copilot drawer optimization** (20 min)

---

## Effort Breakdown by Tier

| Tier | Hours | What It Includes |
|------|-------|-----------------|
| **Minimum viable** | 5.5h | Routes (4h) + demo testing (1h) + tests pass (30 min) |
| **Strong submission** | 7h | Minimum + health endpoint + metrics hash |
| **Full polish** | 8h | Strong + docs sync + env check + demo cleanup |

---

## Timeline to Submission (2026-09-06)

### Day 1 (Today, ~6 hours available)
- [ ] Complete 4-6 highest-effort routes (analysis, new-run, analysis)
- [ ] Run demo.sh, verify no crashes
- [ ] Commit & test (30 min)
- [ ] Estimate remaining work

### Day 2 (Tomorrow, ~8 hours available)
- [ ] Complete remaining 7 routes (20 min each, mostly state management)
- [ ] End-to-end integration test (1 hour)
- [ ] Health endpoint + metrics hash (1 hour)
- [ ] Final tests + polish (1 hour)
- [ ] Submit

---

## Success Criteria for Submission

- [ ] All 12 routes load without errors
- [ ] Demo runs end-to-end: generate → analyze → export
- [ ] 903 tests pass, 1 skipped
- [ ] No TypeScript errors
- [ ] No lint errors
- [ ] README links are accurate
- [ ] All documentation files exist and are linked
- [ ] No secrets in repo
- [ ] Fallback mode works (no API key required)
- [ ] Copilot chat doesn't emit numerals from model
- [ ] Metrics file reproducible (hash matches)

---

## Known Risks & Mitigation

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| API cold-start too slow | Medium | Pre-warm or move to paid tier |
| TypeScript compilation errors in web/ | Medium | Run type-check early, fix incrementally |
| Route API integration mismatches | High | Test each endpoint call as you build |
| Chat guard allows numerals through | Low | Unit test guard logic, manual spot-check |
| Demo.sh doesn't run unattended | Low | Remove any auth prompts, test without user input |

---

## What NOT to do (Save time)

- ❌ Don't rebuild UI from scratch — routes are already built
- ❌ Don't add new features — submission is feature-complete
- ❌ Don't refactor engine code — it's working and tested
- ❌ Don't pursue disputes/withholding matrix — it's unit-tested, not critical
- ❌ Don't chase live API integration — fallback is good enough
- ❌ Don't optimize performance — 63K rows/sec is fine
- ❌ Don't add real merchant auth — test mode is intentional

---

## Current Blockers

**None.** Code is written, tests pass, routes exist. Work is purely verification + UI
integration testing.

Next step: Run `./scripts/demo.sh` right now. Measure cold start time, list any UI errors,
and that's your scope for the next 4 hours.
