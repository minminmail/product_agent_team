# Free real LLM calls via Gemini + LiteLLM proxy

Your app is built on the Claude Agent SDK, which only speaks Anthropic's API
format. This setup runs a small **LiteLLM proxy** that exposes an
Anthropic-compatible `/v1/messages` endpoint and forwards every request to
**Google Gemini's free tier** — so you get real LLM output with no Anthropic
credits.

```
 App (Claude Agent SDK)  ──/v1/messages──▶  LiteLLM proxy  ──▶  Gemini (free)
   ANTHROPIC_BASE_URL=http://localhost:4000
```

> Just testing the UI / pipeline / statuses? You don't need any of this — tick
> **🧪 Mock** in the dashboard (or `--mock` on the CLI). Mock runs fully offline.

## 1. Get a free Gemini API key

Go to https://aistudio.google.com/apikey and create a key. No credit card. Free
tier is roughly ~1,500 requests/day on Gemini Flash (limits change — check the
page).

## 2. Install LiteLLM

```bash
pip install "litellm[proxy]"
```

> Security: do **not** use LiteLLM **1.82.7** or **1.82.8** — those PyPI
> releases shipped credential-stealing malware. Install a newer version and, if
> you ever had those, rotate your keys.

## 3. Start the proxy

```bash
export GEMINI_API_KEY="your-gemini-key"
export LITELLM_MASTER_KEY="sk-local-test"   # any local secret
./run_proxy.sh
```

This serves `http://localhost:4000` and routes all models to
`gemini/gemini-2.0-flash` (see `litellm_gemini.yaml`). Quick check:

```bash
curl http://localhost:4000/health/liveliness   # → "I'm alive!"  (proxy is up)
```

Use `/health/liveliness` (or `/health/readiness`) to check the proxy — **not**
plain `/health`, which actively calls Gemini and will error if your
`GEMINI_API_KEY` is missing/invalid (it must start with `AIza`).

The local proxy runs **without auth** — the run script `unset`s
`LITELLM_MASTER_KEY` (LiteLLM auto-reads that env var as a master key) and the
config has no `master_key`. This avoids LiteLLM's misleading **"400 No connected
db"** error, which is actually an auth-key mismatch (it tries to validate the
key against a database that doesn't exist). The app still sends an auth header;
the proxy simply ignores it.

## 4. Choose how the app uses the proxy

There are two modes. Pick one in `.env`.

### Mode A — auto-fallback (recommended)

Use Anthropic normally; only when a run hits **"credit balance too low"** does it
auto-retry via Gemini. Keep your **real** Anthropic key and add the two Gemini
lines — **do not** set `ANTHROPIC_BASE_URL` (that would force the primary path
through the proxy too):

```
ANTHROPIC_API_KEY=sk-ant-...your real key...
GEMINI_API_KEY=AIza-...your gemini key...
LITELLM_MASTER_KEY=sk-local-test        # proxy auth; any secret
```

The fallback authenticates to the proxy with `LITELLM_MASTER_KEY`, so your real
`ANTHROPIC_API_KEY` is used only for Anthropic and never sent to the proxy.

### Mode B — always Gemini

Route every run through the proxy (no Anthropic key needed):

```
GEMINI_API_KEY=AIza-...your gemini key...
LITELLM_MASTER_KEY=sk-local-test
ANTHROPIC_BASE_URL=http://localhost:4000
ANTHROPIC_API_KEY=sk-local-test         # must equal LITELLM_MASTER_KEY
```

Either way, start the app and run with **Mock OFF** (Live). When routed to
Gemini, the "Lead model" dropdown is ignored — everything goes to Gemini Flash.

## Automatic fallback (Anthropic credit too low → Gemini)

If you run **Live on Anthropic** and a run hits a fatal API error — most
commonly **"credit balance is too low"** (also rate-limit / quota / auth) — the
app automatically **retries the same run via this Gemini proxy**, with no manual
switch. You'll see a `🔄` line in the timeline and a `FALLBACK` entry in the log.

Requirements for the fallback to trigger (Mode A):

- `GEMINI_API_KEY` is set in `.env` (this is the on/off switch — the app reads it
  from `.env` directly, so no restart is needed after adding it), and
- `LITELLM_MASTER_KEY` is set in `.env` (the proxy auth token), and
- the proxy is running (`./run_proxy.sh`).

Optional: set `GEMINI_FALLBACK_BASE_URL` if your proxy isn't at
`http://localhost:4000`. The fallback authenticates with `LITELLM_MASTER_KEY`
(and only falls back to `ANTHROPIC_API_KEY` if you didn't set one — so always set
`LITELLM_MASTER_KEY` to keep your real Anthropic key off the proxy). If
`GEMINI_API_KEY` is not set, a credit error simply shows as **failed**, and the
reason note will say the Gemini fallback isn't active (click the status pill).

## Notes & caveats

- Swap the model by editing `litellm_gemini.yaml` (e.g.
  `gemini/gemini-2.5-flash`). Run `litellm --config litellm_gemini.yaml` again.
- This is **best-effort**: the Agent SDK leans on Anthropic-specific behaviour
  (tool use, token counting, sub-agents). Most runs work, but quality and tool
  fidelity will be lower than real Claude, and some edge calls may error. For
  verifying app behaviour, Mock mode is the reliable path.
- The proxy must be running before you start a Live run, and `ANTHROPIC_BASE_URL`
  is read once at process start — restart the app after changing `.env`.
