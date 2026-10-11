# Hosting the demo

No funding for compute as of 2026-10-05: the API runs in the cloud, but LLM
inference stays on a team laptop, reached back over a Tailscale Funnel. This
is the demo/POC architecture; a funded, laptop-independent setup (Ollama
running on the hosting platform itself) is a post-demo discussion if the
project is picked up. A full VM-hosted alternative was costed out (~$10-19/
month for a budget CPU VM at this traffic level) and logged in the project
doc for that future conversation, not pursued now.

**Operating model: the laptop and the tunnel are OFF by default.** The
hosted link is meant to work standalone, permanently, with nobody watching
it -- that is the actual handover deliverable. Run `bash scripts/tunnel_on.sh`
only for the live demo presentation itself (or a reviewer's live session),
so unscripted questions get real AI answers exactly when someone is
watching; run `bash scripts/tunnel_off.sh` afterward. The rest of the time,
the site still works perfectly for the three cached demo questions and all
retrieval/citations -- only a brand-new, unscripted question quietly gets
the templated fallback instead of live AI prose while the tunnel is off,
which is normal, not a failure.

## Architecture

```
 Visitor's browser
       |
       v
 Static web build (Flutter) ---- any free static host ----
       |
       | POST /query, /admin/*
       v
 rag.py API (Dockerfile.serve) ---- Render/Railway/Fly.io free tier ----
       |                    |
       | Cypher             | OLLAMA_URL = https://<tailscale-hostname>/api/generate
       |                    | + header X-Tunnel-Secret (OLLAMA_TUNNEL_SECRET)
       v                    v
   AuraDB (live)     Tailscale Funnel (public, laptop-side)
                            |
                            v
                     ollama_tunnel_proxy.py (checks the secret)
                            |
                            v
                     Ollama, loopback-only (127.0.0.1:11434)
```

Only the LLM-backed parts (live answer synthesis for anything not in
`data/demo_answer_cache.json`, and the admin confidence check) depend on the
laptop being on and the Funnel running. Retrieval, citations, and the three
cached demo answers all work with the laptop off -- that is the whole point
of the architecture.

**Why there's a proxy in the middle, not just Funnel -> Ollama directly:**
two problems, found by actually testing this live. (1) Ollama rejects any
request whose Host header isn't localhost -- a check that only runs when
Ollama is bound to loopback, which it needs to be anyway for its own
protection. (2) Funnel makes whatever it points at public to anyone who
finds the URL, and Ollama has no password of its own -- binding it wide
enough for Funnel to reach would remove its only defense. `ollama_tunnel_
proxy.py` solves both: it sits in front of Ollama, rewrites the Host header
on the way in, and refuses any request that doesn't carry the shared secret
(`OLLAMA_TUNNEL_SECRET`, header `X-Tunnel-Secret`) -- so Ollama can stay
loopback-only and protected, and only the hosted API (which knows the
secret) can actually reach it.

## What's already built (code side)

- `Dockerfile.serve` -- builds and runs the API in a container. Verified
  locally: `docker build -f Dockerfile.serve -t mandi-kg-api .` then
  `docker run --rm -p 8000:8000 --env-file .env -e PORT=8000 mandi-kg-api`.
- `rag.py`'s `resolve_port()` -- uses `$PORT` when `--port` is not given
  explicitly, which is how Render/Railway/Fly.io all tell a container which
  port to listen on.
- `llm_endpoint.py`'s `TRUSTED_LLM_HOST` -- pins exactly one external
  hostname (the Tailscale Funnel address) as trusted, narrower than
  `ALLOW_EXTERNAL_LLM=1` (which would accept any external host).
- `rag.py`'s `ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS = 10` -- a short
  connect timeout separate from the 90s generation timeout, so a question
  asked while the tunnel is off (the normal state) fails fast and falls
  back to the template in ~10s, not 90s. Verified live against a
  deliberately unreachable address.
- `flutter_application/lib/services/api_config.dart` -- `apiBaseUrl` reads
  `--dart-define=API_BASE_URL=...` at build time; falls back to loopback
  addresses for local development, unchanged from before.
- `ollama_tunnel_proxy.py` -- the authenticating proxy described above.
  Fails closed: refuses to start at all without `OLLAMA_TUNNEL_SECRET` set.
- `scripts/tunnel_on.sh` / `scripts/tunnel_off.sh` -- the actual on/off
  switch for live AI. `tunnel_on.sh` starts Ollama (if needed), starts the
  proxy, starts Funnel pointed at the proxy, and prints the public hostname.
  `tunnel_off.sh` stops Funnel and the proxy; Ollama is left running
  (harmless -- loopback-only, nothing public can reach it once the proxy
  and Funnel are down). Both verified live, including that `tunnel_off.sh`
  actually kills the proxy process (an earlier version used `pkill`, which
  silently does nothing against Windows-native processes from Git Bash --
  fixed to use PowerShell's process list instead).

## Environment variables the hosted API needs

Set these in the hosting platform's dashboard, never committed to git:

| Variable | Value |
|---|---|
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | From `.env` (the live AuraDB instance) |
| `OLLAMA_URL` | `https://<your-tailscale-funnel-hostname>/api/generate` |
| `OLLAMA_MODEL` | `mistral:7b` |
| `TRUSTED_LLM_HOST` | `<your-tailscale-funnel-hostname>` (no scheme, no path) |
| `CONFIDENCE_OLLAMA_URL` | `https://<your-tailscale-funnel-hostname>/api/chat` |
| `OLLAMA_TUNNEL_SECRET` | Same value as the local `.env`'s `OLLAMA_TUNNEL_SECRET` -- what lets the hosted API through `ollama_tunnel_proxy.py`'s gate. Without it, every request to the tunnel gets a 403, same as a stranger who found the URL. |
| `ADMIN_UPLOAD_SECRET` | A long random value -- generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Set it here AND type the same value into the admin UI's secret prompt. Never commit it. |

## Steps only a person can do

See the generated wizard for the interactive walkthrough: creating the
Tailscale account and enabling Funnel, creating the hosting-platform account
and deploying `Dockerfile.serve`, and building/deploying the static web app
with the right `--dart-define`.

## Building the web app for the hosted API

```bash
flutter build web --dart-define=API_BASE_URL=https://<your-hosted-api-url>
```

Deploy `build/web` to any static host (GitHub Pages, Render Static Site,
Cloudflare Pages). CORS is already wide open on the API side
(`Access-Control-Allow-Origin: *`), so the static site and the API do not
need to share a domain.

## Known tradeoffs of this architecture (say this at the demo if asked)

- While the tunnel IS on, the secret stops a stranger from USING your
  Ollama, but Funnel's public hostname is still, structurally, reachable by
  anyone on the internet who finds it -- they'd just get a 403 instead of
  an answer. Turning it off between sessions (`tunnel_off.sh`) rather than
  leaving it on permanently is still the real mitigation, not the secret
  alone.
- The laptop/Funnel being off is the NORMAL state, not a failure -- live LLM
  synthesis for anything outside the three cached demo questions falls back
  to the templated answer within ~10s (not 90s, since the connect-timeout
  fix), gracefully, not an error. Worth knowing before someone asks an
  off-script question outside a live-demo window.
- The admin confidence check also needs the laptop's Ollama reachable;
  `admin_ingest.py` already reports "Scoring didn't run" rather than a false
  rejection if it is not (see the confidence-framework bug writeup from
  earlier this session for the one place that protection does not yet
  reach: `confidence_framework.py`'s own `rejection_logs/` audit trail).
- Free hosting tiers commonly sleep an idle container; the first request
  after a period of inactivity may be slow to wake it.
