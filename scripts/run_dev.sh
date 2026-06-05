#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export APP_ENV_FILE="${APP_ENV_FILE:-.env.dev}"
exec venv/bin/python main.py
