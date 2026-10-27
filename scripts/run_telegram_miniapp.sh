#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV_FILE="${APP_ENV_FILE:-.env}"
exec venv/bin/python -u scripts/run_telegram_miniapp.py
