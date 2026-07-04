# Deploying Marketing Agent Team to Hetzner Cloud

## 1. Create the server (~2 min)

1. Sign up / log in at https://console.hetzner.cloud → **New Project** → **Add Server**
2. Location: **Nuremberg/Falkenstein** (cheapest) or **Singapore** (lower latency from Asia)
3. Image: **Ubuntu 24.04**
4. Type: **Shared vCPU → CX22** (2 vCPU / 4 GB / 40 GB) — enough for this app
5. Networking: enable **Public IPv4**
6. SSH key: paste your public key (`cat ~/.ssh/id_ed25519.pub`; generate with `ssh-keygen` if none)
7. Create & note the server IP.

## 2. First login + base setup

```bash
ssh root@YOUR_SERVER_IP

# System + deps: Python, Node 20 (needed by the Claude Agent SDK CLI), Caddy (HTTPS)
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git ufw
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt install -y nodejs
npm install -g @anthropic-ai/claude-code

# Firewall: SSH + web only
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

## 3. Upload the app

Option A — from your machine:
```bash
rsync -av --exclude venv --exclude __pycache__ --exclude users.db \
  ~/Claude/Projects/agent_team/  root@YOUR_SERVER_IP:/opt/agent_team/
```
Option B — via git if the project is in a repo: `git clone <repo> /opt/agent_team`

## 4. Python env + secrets

```bash
cd /opt/agent_team
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install langgraph          # for the LangGraph engine

cat > .env <<'ENV'
ANTHROPIC_API_KEY=sk-ant-...
# optional providers:
# DEEPSEEK_API_KEY=...
# GROQ_API_KEY=...
# email verification (optional):
# SMTP_HOST=... SMTP_USER=... SMTP_PASS=...
ENV
chmod 600 .env
```

Quick test: `./venv/bin/python -m product_researcher.server` → visit `http://YOUR_SERVER_IP:8000` (temporarily `ufw allow 8000`, remove afterwards).

## 5. Run as a systemd service

```bash
cat > /etc/systemd/system/agent-team.service <<'UNIT'
[Unit]
Description=Marketing Agent Team dashboard
After=network.target

[Service]
WorkingDirectory=/opt/agent_team
ExecStart=/opt/agent_team/venv/bin/python -m product_researcher.server
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now agent-team
systemctl status agent-team        # should be "active (running)"
```

## 6. HTTPS reverse proxy with Caddy

Point a DNS A-record (e.g. `agents.yourdomain.com`) at the server IP first.

```bash
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy

cat > /etc/caddy/Caddyfile <<'CADDY'
agents.yourdomain.com {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1     # important: don't buffer SSE streams
    }
}
CADDY
systemctl restart caddy
```

Caddy fetches the TLS certificate automatically. Open `https://agents.yourdomain.com`, sign up, run a pipeline.

No domain? Use the IP with plain HTTP: `caddy` config `:80 { reverse_proxy 127.0.0.1:8000 { flush_interval -1 } }` — but the session cookie then travels unencrypted; get a domain for real use.

## 7. Updates & maintenance

```bash
# redeploy after changes
rsync -av --exclude venv --exclude users.db ... root@IP:/opt/agent_team/
systemctl restart agent-team

# logs
journalctl -u agent-team -f

# backup the database (users + search history)
cp /opt/agent_team/users.db /root/backup/users-$(date +%F).db
```

## Notes

- SQLite (`users.db`) and `reports/` live on the server's disk — included in Hetzner's
  optional snapshot/backup feature (~20% of server price) if you want automatic backups.
- The LiteLLM proxy (`./run_proxy.sh`, for Groq/Gemini fallback) can run as a second
  systemd unit the same way if you use those providers.
- Set `REQUIRE_VERIFICATION=1` in `.env` only if SMTP is configured.
