#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV_FILE="${APP_ENV_FILE:-.env}"
export MINIAPP_LOCAL=true
export DATABASE_URL="sqlite+aiosqlite:///dj_ai_bot_miniapp.db"
venv/bin/python scripts/prepare_miniapp_db.py
exec venv/bin/python -m uvicorn api.miniapp_app:create_app --factory --host 127.0.0.1 --port "${MINIAPP_PORT:-8080}" --no-proxy-headers
