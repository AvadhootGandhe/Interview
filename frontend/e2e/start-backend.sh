#!/usr/bin/env bash
# Starts the real FastAPI backend for the Playwright run: FAKE_LLM=1 (offline DemoLLM) on a throwaway
# SQLite DB ingested from data/sample_questions.json. Needs no key, model or the 958 MB dataset.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$HERE/../../backend"
PORT="${E2E_API_PORT:-8100}"
WEB_ORIGIN="${E2E_WEB_ORIGIN:-http://localhost:3100}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PY="${E2E_PYTHON:-$BACKEND/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"

cd "$BACKEND"
export DATABASE_URL="sqlite:///$TMP/e2e.db"
export FAKE_LLM=1
export FOLLOWUP_LOG_PATH="$TMP/followups.jsonl"
export CORS_ORIGINS="[\"$WEB_ORIGIN\"]"

"$PY" -m scripts.ingest --source ../data/sample_questions.json --db "$DATABASE_URL"
exec "$PY" -m uvicorn app.main:app --port "$PORT" --log-level warning
