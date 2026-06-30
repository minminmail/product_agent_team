#!/usr/bin/env bash
# Start a LiteLLM proxy that serves the Anthropic /v1/messages API and forwards
# to Google Gemini's free tier. See LITELLM_GEMINI_SETUP.md for full steps.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

# Load provider keys from .env if not already in the env.
read_env () { grep -E "^$1=" "$DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2- ; }
if [ -f "$DIR/.env" ]; then
  [ -z "${GROQ_API_KEY:-}" ]     && GROQ_API_KEY=$(read_env GROQ_API_KEY)         || true
  [ -z "${DEEPSEEK_API_KEY:-}" ] && DEEPSEEK_API_KEY=$(read_env DEEPSEEK_API_KEY) || true
  [ -z "${GEMINI_API_KEY:-}" ]   && GEMINI_API_KEY=$(read_env GEMINI_API_KEY)     || true
  export GROQ_API_KEY DEEPSEEK_API_KEY GEMINI_API_KEY
fi

# One unified config serves every backend whose key is set; the app selects one
# per request by model name (groq / deepseek / gemini).
CONFIG="$DIR/litellm_proxy.yaml"
avail=""
[ -n "${GROQ_API_KEY:-}" ]     && avail="$avail Groq"
[ -n "${DEEPSEEK_API_KEY:-}" ] && avail="$avail DeepSeek"
[ -n "${GEMINI_API_KEY:-}" ]   && avail="$avail Gemini"
if [ -z "$avail" ]; then
  echo "ERROR: set at least one of GROQ_API_KEY / DEEPSEEK_API_KEY / GEMINI_API_KEY in .env" >&2
  exit 1
fi

# CRITICAL: LiteLLM auto-reads LITELLM_MASTER_KEY from the ENVIRONMENT and
# enforces it even though our config has no master_key — a mismatch then throws
# the misleading "400 No connected db". Unset it so the local proxy is auth-free.
unset LITELLM_MASTER_KEY

PORT="${PORT:-4000}"

echo "Starting LiteLLM proxy on http://localhost:${PORT}  (local, NO auth)"
echo "  → backends available:${avail}  (selected per request: groq / deepseek / gemini)"
echo "  Is it up?   curl http://localhost:${PORT}/health/liveliness"
echo

# Avoid the known-compromised 1.82.7 / 1.82.8 releases (see setup doc).
exec litellm --config "$CONFIG" --port "${PORT}"
