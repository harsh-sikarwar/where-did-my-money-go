# Test baseline

Frozen "before" line — captured once at commit `04816ea`, 2026-09-05, so any later claim
of "still passing" or "still builds" has something concrete to diff against.

## Engine

```
$ cd engine && uv run pytest -q
........................................................................ [ 87%]
..............................s......................................... [ 95%]
........................................                                 [100%]
```
All green, 1 skipped (matches README's "903 passing, 1 skipped"). One deprecation
warning (`on_event` — FastAPI recommends `lifespan` instead; functional, not a failure).

```
$ cd engine && uv run ruff check .
All checks passed!
```

## API boot (deploy sanity check)

Verified the deployed-config boot path locally before trusting Render with it:

```
$ cd engine && PORT=8123 CORS_ALLOW_ORIGINS="https://example.vercel.app" \
    uv run uvicorn api.main:app --host 0.0.0.0 --port 8123 --app-dir ..
```

- `/health` → 200, reports `llm_credential_present`, `llm_enabled`, etc.
- `/api/batches` → 200, lists batches
- Startup hook seeds a `demo` batch when `DATA_ROOT` is empty (verified directly against
  an empty directory, since the local `data/` already had leftover batches from manual
  testing and never exercises the empty-disk branch).

## Web

```
$ cd web && npx tsc --noEmit
```
No output — clean.

```
$ cd web && npm run build
✓ Compiled successfully in 338ms
✓ Generating static pages using 15 workers (8/8)
```
All 13 routes compile (12 dashboard routes + Next's own `/_not-found`). This confirms
the Vercel deploy will succeed without a build-time surprise — it does not confirm every
route renders correctly against live data, which was verified only by manual click-through
during development, not by an automated route-smoke suite (deferred deliberately given the
same-day deadline and limited budget).

## Not run as part of this baseline

- No automated route-smoke tests, no API contract tests, no degradation-matrix tests
  (Tiers 1–3, 5 from the original test-hardening scope). Deferred deliberately given the
  same-day deadline and limited budget — `pytest` and the manual demo.sh walkthrough are
  the coverage this baseline actually has. Treat "12 routes render" as spot-checked, not
  proven.

## Final-stretch re-run (2026-09-05)

All four verification commands passed cleanly. Engine tests ran 903 passing with 1 skipped
(same as baseline); the same deprecation warning about `on_event` appeared, unrelated to
the re-run. Ruff checks passed. Web TypeScript type check produced no errors. Build
succeeded with all 13 routes compiling.

```
$ cd engine && uv run pytest -q
```
Passed — 903 passing, 1 skipped.

```
$ cd engine && uv run ruff check finctl/ tests/ ../api/
```
Passed — All checks passed!

```
$ cd web && npx tsc --noEmit
```
Passed — exit code 0.

```
$ cd web && npm run build
```
Passed — exit code 0, all 13 routes compiled, generated in 1033ms + 1381ms TypeScript + 255ms static pages.
