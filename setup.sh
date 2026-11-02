#!/usr/bin/env bash
# One-time setup for the Telegram assistant on an Ubuntu server (e.g. a DigitalOcean Droplet).
# Run as root:  bash /opt/assistant-bot/setup.sh
set -e
cd "$(dirname "$0")"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a

echo "==> Installing system packages (can take a minute on a new server)..."
for i in $(seq 1 30); do
  apt-get -o DPkg::Lock::Timeout=300 update -q && break
  echo "    Server is still busy with automatic updates, retrying in 10s..."
  sleep 10
done
apt-get -o DPkg::Lock::Timeout=300 install -y -q python3-venv

echo "==> Creating Python environment and installing libraries..."
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

echo "==> Installing the background service..."
sed "s|/opt/assistant-bot|$(pwd)|g" assistant.service > /etc/systemd/system/assistant.service
systemctl daemon-reload

echo ""
echo "All set! Next step: create your settings file with:"
echo "    cd $(pwd) && nano .env"
