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
it -- that is the actual handover deliverable. Turn the laptop's Ollama and
`tailscale funnel 11434` on only for the live demo presentation itself (or a
reviewer's live session), so unscripted questions get real AI answers
exactly when someone is watching; turn it back off afterward. The rest of
the time, the site still works perfectly for the three cached demo
questions and all retrieval/citations -- only a brand-new, unscripted
question quietly gets the templated fallback instead of live AI prose
while the tunnel is off, which is normal, not a failure.

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
       v                    v
   AuraDB (live)     Team laptop's Ollama, via Tailscale Funnel
```

Only the LLM-backed parts (live answer synthesis for anything not in
`data/demo_answer_cache.json`, and the admin confidence check) depend on the
laptop being on and the Funnel running. Retrieval, citations, and the three
cached demo answers all work with the laptop off -- that is the whole point
of the architecture.

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

## Environment variables the hosted API needs

Set these in the hosting platform's dashboard, never committed to git:

| Variable | Value |
|---|---|
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | From `.env` (the live AuraDB instance) |
| `OLLAMA_URL` | `https://<your-tailscale-funnel-hostname>/api/generate` |
| `OLLAMA_MODEL` | `mistral:7b` |
| `TRUSTED_LLM_HOST` | `<your-tailscale-funnel-hostname>` (no scheme, no path) |
| `CONFIDENCE_OLLAMA_URL` | `https://<your-tailscale-funnel-hostname>/api/chat` |
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
