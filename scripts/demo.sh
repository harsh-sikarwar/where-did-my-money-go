#!/usr/bin/env bash
# One command: seed data, start both services, land on the verdict.
#
# From docs: "never a seven-step manual ritual". Judges will not debug a startup
# sequence during a two-minute demo, and neither will you at 11pm.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cleanup() {
  echo ""
  echo "stopping..."
  # Kill the whole process group so uvicorn's reloader children go too.
  [[ -n "${API_PID:-}" ]] && kill -- -"$API_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill -- -"$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "→ seeding demo batch"
(cd engine && uv run finctl generate --volume 200 --out data/demo >/dev/null)

echo "→ verifying the checkpoint"
(cd engine && uv run finctl checkpoint --data data/demo 2>&1 | sed -n '3,9p')

echo ""
echo "→ starting engine API on :8000"
(cd engine && setsid uv run uvicorn api.main:app --port 8000 --app-dir .. >/tmp/finctl-api.log 2>&1) &
API_PID=$!

# Wait for it to answer rather than sleeping a guessed number of seconds.
for _ in $(seq 1 40); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then break; fi
  sleep 0.25
done
if ! curl -sf http://localhost:8000/health >/dev/null 2>&1; then
  echo "API failed to start. Log:" >&2
  tail -20 /tmp/finctl-api.log >&2
  exit 1
fi
echo "  ready"

echo "→ starting web on :3000"
(cd web && setsid npm run dev >/tmp/finctl-web.log 2>&1) &
WEB_PID=$!

for _ in $(seq 1 80); do
  if curl -sf http://localhost:3000 >/dev/null 2>&1; then break; fi
  sleep 0.25
done

echo ""
echo "   ┌─────────────────────────────────────────┐"
echo "   │  http://localhost:3000                  │"
echo "   │  Where did my money go?                 │"
echo "   └─────────────────────────────────────────┘"
echo ""
echo "   API docs: http://localhost:8000/docs"
echo "   Ctrl-C to stop both."
echo ""
wait
