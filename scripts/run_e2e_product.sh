#!/usr/bin/env bash
# Product E2E: build frontend, start uvicorn on PORT, run scripts/e2e_product.py (real HTTP/WS).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export IRP_E2E_REPLAY_NO_OSRM=1

PORT="${PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"

if command -v lsof >/dev/null 2>&1 && lsof -i ":${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port ${PORT} is already in use. Set PORT=8001 or free the port." >&2
  exit 1
fi

echo "== Frontend: npm run build =="
(cd frontend && npm run build)

PREVIEW_PORT="${PREVIEW_PORT:-5174}"
echo "== Frontend: vite preview :${PREVIEW_PORT} (smoke) =="
(cd frontend && npx vite preview --host 127.0.0.1 --port "${PREVIEW_PORT}" --strictPort) &
PREVIEW_PID=$!
trap 'kill "${PREVIEW_PID}" 2>/dev/null || true; kill "${UV_PID}" 2>/dev/null || true' EXIT
sleep 2
curl -sf "http://127.0.0.1:${PREVIEW_PORT}/" >/dev/null
echo "preview OK"

echo "== Backend: uvicorn :${PORT} =="
uvicorn backend.main:app --host 127.0.0.1 --port "${PORT}" &
UV_PID=$!
for _ in $(seq 1 40); do
  if curl -sf "${BASE}/health" >/dev/null; then
    break
  fi
  sleep 0.25
done
curl -sf "${BASE}/health" >/dev/null

echo "== API + WS E2E =="
python3 scripts/e2e_product.py --base-url "${BASE}"

echo "== All product E2E steps passed =="
