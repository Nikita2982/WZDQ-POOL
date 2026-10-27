#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
preview_port="${PREVIEW_PORT:-8090}"
venv/bin/python -m uvicorn share_preview:create_app --factory --host 127.0.0.1 --port "$preview_port" --no-proxy-headers &
preview_pid=$!
trap 'kill "$preview_pid" 2>/dev/null || true' EXIT
export WZDQ_PREVIEW_PORT="$preview_port"
venv/bin/python - <<'PY'
import os
import time
import urllib.request
port = os.environ['WZDQ_PREVIEW_PORT']
for _ in range(100):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as response:
            if b'public-ui-demo' in response.read():
                break
    except OSError:
        pass
    time.sleep(.05)
else:
    raise SystemExit('Не удалось запустить сервер демонстрации.')
PY
if ! kill -0 "$preview_pid" 2>/dev/null; then
  echo "Не удалось запустить демонстрацию: возможно, порт занят."
  exit 1
fi
# Isolate host keys and disable use of personal SSH identities.
ssh -T -o BatchMode=yes -o ConnectTimeout=15 -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile="${TMPDIR:-/tmp}/wzdq-share-known-hosts" \
  -o IdentityFile=none -o IdentityAgent=none \
  -R "80:127.0.0.1:$preview_port" nokey@localhost.run
