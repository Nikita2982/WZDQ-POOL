#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/opt/WZDQ-POOL}"
SERVICE_NAME="${2:-wzdq-bot}"
BRANCH="${3:-main}"

cd "$APP_DIR"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

source venv/bin/activate
pip install -r requirements.txt

sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager --lines=20
