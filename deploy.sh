#!/usr/bin/env bash
# Deploy to the Hetzner server behind https://supplier.jilai.ai
# Usage: ./deploy.sh root@YOUR_SERVER_IP
set -euo pipefail

TARGET="${1:?usage: ./deploy.sh root@SERVER_IP}"
SRC="$(cd "$(dirname "$0")" && pwd)"

# 1. Sync code (never the venv, db, or generated reports)
rsync -av --delete \
  --exclude venv --exclude __pycache__ --exclude '*.pyc' \
  --exclude users.db --exclude reports --exclude .env --exclude .git \
  "$SRC"/ "$TARGET":/opt/agent_team/

# 2. Install deps (langgraph is now required), clear stale bytecode, restart
ssh "$TARGET" '
  set -e
  cd /opt/agent_team
  # Normalize permissions: rsync -a preserves the Mac-side modes, and files
  # edited by Cowork arrive as 600, which the service cannot read.
  find . -path ./venv -prune -o -type d -exec chmod 755 {} +
  find . -path ./venv -prune -o -type f -exec chmod 644 {} +
  chmod 755 run_proxy.sh deploy.sh 2>/dev/null || true
  chmod 600 .env 2>/dev/null || true
  # Hand everything to the user the service runs as (rsync leaves files
  # root-owned); it needs write access for users.db, SQLite journals, reports/.
  U=$(systemctl show agent-team -p User --value)
  [ -z "$U" ] && U=$(ps -o user= -p "$(systemctl show agent-team -p MainPID --value)" 2>/dev/null) || true
  [ -n "$U" ] && chown -R "$U": /opt/agent_team
  ./venv/bin/pip install -r requirements.txt
  find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
  systemctl restart agent-team
  # Slow box: wait up to 20s for uvicorn to come up before declaring failure.
  for i in $(seq 1 20); do
    code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/ || true)
    [ "$code" = "200" ] && break
    sleep 1
  done
  systemctl is-active agent-team
  echo "local backend: $code (after ${i}s)"
  [ "$code" = "200" ] || { journalctl -u agent-team -n 20 --no-pager; exit 1; }
'
echo "✓ deployed — check https://supplier.jilai.ai/"
