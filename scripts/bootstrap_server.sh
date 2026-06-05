#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/opt/WZDQ-POOL}"

sudo mkdir -p "$APP_DIR"
sudo chown -R "$(whoami)":"$(whoami)" "$APP_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "Git repository not found in $APP_DIR"
  echo "Clone the repository first:"
  echo "  git clone https://github.com/Nikita2982/WZDQ-POOL.git $APP_DIR"
  exit 1
fi

cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo
echo "Bootstrap complete."
echo "Next steps:"
echo "1. Copy .env.example to .env and fill real production values."
echo "2. Copy deploy/systemd/wzdq-bot.service to /etc/systemd/system/."
echo "3. Update User= and WorkingDirectory= in the service file if needed."
echo "4. Run: sudo systemctl daemon-reload"
echo "5. Run: sudo systemctl enable --now wzdq-bot"
