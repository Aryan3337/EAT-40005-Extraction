#!/usr/bin/env bash
# Turns live AI answers ON for the hosted demo: starts Ollama (if not
# already running), starts the authenticating proxy in front of it
# (ollama_tunnel_proxy.py), then exposes the proxy publicly via Tailscale
# Funnel. Run this right before a live demo or review session.
#
# The hosted site works fine without this -- the three cached demo answers
# and all retrieval/citations don't need it. This only affects whether a
# brand-new, unscripted question gets real AI prose or the templated
# fallback.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

OLLAMA_EXE="$LOCALAPPDATA/Programs/Ollama/ollama.exe"
PROXY_PORT="$(grep -E '^FUNNEL_PROXY_PORT=' .env | tail -n1 | cut -d= -f2-)"
PROXY_PORT="${PROXY_PORT:-11435}"
SECRET="$(grep -E '^OLLAMA_TUNNEL_SECRET=' .env | tail -n1 | cut -d= -f2-)"

if [[ -z "$SECRET" ]]; then
  echo "OLLAMA_TUNNEL_SECRET is not set in .env -- run scripts/setup_hosting.sh first." >&2
  exit 1
fi

echo "1/3 Checking Ollama..."
if curl -s -m 5 -o /dev/null http://localhost:11434/api/tags; then
  echo "    already running"
else
  echo "    starting..."
  "$OLLAMA_EXE" serve > /tmp/ollama.log 2>&1 &
  disown
  sleep 3
fi

echo "2/3 Checking the authenticating proxy..."
if curl -s -m 5 -o /dev/null -w '' http://127.0.0.1:"$PROXY_PORT"/api/tags 2>/dev/null; then
  echo "    already running"
else
  echo "    starting..."
  OLLAMA_TUNNEL_SECRET="$SECRET" python -u ollama_tunnel_proxy.py --port "$PROXY_PORT" > /tmp/ollama_tunnel_proxy.log 2>&1 &
  disown
  sleep 2
fi

echo "3/3 Starting Tailscale Funnel..."
"/c/Program Files/Tailscale/tailscale.exe" funnel --bg "$PROXY_PORT"

echo
echo "Live AI is ON. Run scripts/tunnel_off.sh when you're done."
echo "Remember: the hosted site keeps working either way -- this only affects unscripted questions."
