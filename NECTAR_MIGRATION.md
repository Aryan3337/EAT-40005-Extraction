# Nectar migration — decisions and status

As of **26 October 2026**. Companion to `HOSTING.md` (the current Render +
Tailscale architecture this migration replaces) and `HANDOVER.md`.

## Why this exists

Afzal Azeem Chowdhary (supervisor) submitted an ARDC Nectar allocation for P85
live in the weekly meeting on **19 October 2026**. Three deliverables followed,
in his words: use the 4000 credits so we can test properly, deploy the chatbot,
and prepare a systematic handover covering every system a successor would need.

**Deadline: two weeks from 26 October 2026**, so roughly **9 November 2026**.
That date drives most of the decisions below.

## What we are migrating away from

```
 Visitor's browser
       |
       v
 Flutter web (static)  ----------------------------- Render
       |
       | POST /query, /admin/*
       v
 rag.py API (Dockerfile.serve) ---------------------- Render
       |                    |
       | Cypher             | OLLAMA_URL
       v                    v
   Neo4j AuraDB      Tailscale Funnel -> laptop -> Ollama
```

Live answer synthesis currently depends on a team member's laptop being awake
with the Funnel running. Only the cached demo answers survive the laptop being
off. **Removing that dependency is the entire point of the migration** — it was
recorded as the funded post-demo ask long before Nectar appeared.

`llm_endpoint.py` already routes every LLM call through `resolve_llm_endpoint()`
with a `TRUSTED_LLM_HOST` pin, so repointing inference at a Nectar VM is a
config change. `ollama_tunnel_proxy.py`, the Funnel and `OLLAMA_TUNNEL_SECRET`
all get **deleted rather than migrated**. A Nectar VM is infrastructure the team
controls, so the local-models-only commitment documented in `llm_endpoint.py`
holds more straightforwardly than it did over a tunnel.

## The allocation

Project identifier: **"P85 2026 Mandi knowledge chatbot"**. All six students
were made tenant managers. Quota as shown in the dashboard on 26 Oct 2026:

| Resource | Limit |
|---|---|
| Instances | 40 |
| VCPUs | 64 |
| RAM | 131072 MB (128 GB) |
| Volumes | 50 |
| **Volume storage** | **50 GiB** |
| Budget | 4000 SU |

Afzal requested 16 CPUs, 2 GPUs, 128 GB RAM, 4 routers, 8 load balancers, and a
managed database (16 GB RAM / 100 GB storage). RAM and volume storage match the
request exactly; vCPUs came in higher than asked.

**Volume storage (50 GiB) is the binding constraint, not compute or SU.**

## Decisions

### D1 — Instance: `m3.xlarge` (16 vCPU, 32 GB RAM), 0.457 SU/hr

Roughly **one year of continuous uptime** on 4000 SU.

SU bills on **uptime, not utilisation** — an idle instance costs exactly what a
busy one does, so expected traffic is irrelevant to the bill and runway is the
dominant criterion. `c3.xlarge` has identical specs at 0.694 SU/hr; the premium
buys 4x CPU shares, which only matters under *host* contention, and costs four
months of runway. Not worth it for a low-traffic demo that has to outlive the
team.

`m3.large` (8 vCPU / 16 GB, 0.228 SU/hr, ~2 years) is the conservative
alternative and still runs `mistral:7b` adequately.

### D2 — CPU only. Do not wait for GPU.

The only GPU flavour visible to the project is `qld-multi-gpu` — 196 vCPU,
625 GB RAM, blank SU/hour. It overruns the quota by 3x on CPU and 4.9x on RAM,
so it cannot be launched. Nectar gates GPU and huge-RAM behind a Blazar
**reservation** on top of allocation approval.

All 29 available flavours were enumerated; there is **no right-sized GPU
flavour**. With two weeks on the clock, a reservation with unknowable lead time
cannot sit on the critical path. `mistral:7b` runs on CPU — slower, not blocked,
and already faster than the laptop it replaces. GPU is documented as future work
and is a config change if a reservation later lands.

### D3 — Image: `NeCTAR Ubuntu 22.04 LTS (Jammy) amd64 (with Docker)` (1.56 GB)

Not the `AI Ready` images (15–19 GB). Those exist to ship CUDA and PyTorch,
which are dead weight without a GPU, and they would consume most of a 30 GB root
disk. Using the plain Docker image reclaims roughly 17 GB.

### D4 — One VM, not several

The repo already carries `docker-compose.yml`, `Dockerfile` and
`Dockerfile.serve`. For a graph of 45–350 triples, splitting across machines
triples the handover surface for no benefit. One box means one set of
credentials, one runbook, one thing to restart.

### D5 — CSV retrieval mode; Neo4j is optional

`data/production_graph/` is **23 KB across 7 CSV files**. `rag.py --kg <csv>`
reads them directly via `ConceptRetriever`, which is where all recent work
(topic filter, community attribution, multi-CSV support) has landed. Neo4j is a
parallel path, not a dependency.

Dropping it for the initial deploy removes AuraDB credentials, network egress
and an entire service from the handover.

**Known edit required:** `Dockerfile.serve`'s CMD hardcodes `--neo4j`. For CSV
mode it becomes `--kg data/production_graph/<file>.csv`, repeatable per file
since the `sangeetha-multiple-csv-retrieval` merge.

### D6 — Attach a volume for persistence

Not required to run — the 30 GB root disk holds the OS, the ~4.7 GB Ollama model
and the containers with room spare. It is required for a *good handover*: models
and graph data on a volume survive an instance rebuild, so a successor can
destroy and recreate the VM from the runbook without losing state.

## Minimum to run the chatbot

Three processes on one box:

| Component | Footprint |
|---|---|
| Ollama + `mistral:7b` | ~4.7 GB disk, ~6 GB RAM resident |
| `rag.py` API via `Dockerfile.serve` | python:3.11-slim + 6 pip packages, ~200 MB |
| Flutter web build (static files) | a few MB |

Absolute floor is `m3.medium` (4 vCPU / 8 GB); honest floor for a demo is
`m3.large`. No GPU, no volume and no Neo4j are needed to get it running.

## Open — blocked on Afzal

A message covering item 3 was drafted on 26 Oct 2026.

1. **Who owns the Nectar project after the team leaves?** All six students are
   tenant managers. When Swinburne accounts deactivate the project is orphaned
   and nobody can restart a stopped instance or renew the allocation. Afzal or
   Tanjila must be added as a tenant manager before handover. *Highest risk item
   on this list.*
2. **Allocation end date and renewal owner.** If it lapses mid-assessment the
   assessors get a dead link.
3. **Were the 2 GPUs actually approved, does use require a reservation, and what
   is the SU/hour for `qld-multi-gpu`?** A 196-vCPU node could burn 4000 SU in
   days.
4. **Data governance.** The allocation was submitted stating the data holds no
   personal information. On the call Marcus flagged that Tanjila's
   community-sourced material, which he believes contains confidential names,
   may be loaded later; Afzal resolved it verbally as "tacit knowledge is
   publicly accessible domain". That needs to be in writing — successors inherit
   the obligation without having heard the conversation.
5. **Storage: 500 GB vs 50 GiB.** Afzal read out "500 gigs of storage" but the
   project shows 50 GiB of volume storage. The call separately settled volumes
   at 50 GB so this is probably fine; worth confirming nothing is missing.

Afzal also stated the handover requires **client sign-off from Tanjila** plus a
client consent/CAPEX form.

## Workstreams

| | Workstream | Depends on | Status |
|---|---|---|---|
| W1 | Nectar foundation — instance, volume, security groups, keys | — | **Runbook written**; nothing launched yet |
| W2 | Ollama onto Nectar, retire the tunnel | W1 | **Configured** in `deploy/nectar/docker-compose.yml`; not deployed |
| W3 | API + Flutter off Render onto Nectar | W1 | **Configured** (nginx + build steps); not deployed |
| W4 | Neo4j: AuraDB stays, or self-host | W1 | Deferred by D5 |
| W5 | Handover pack | partly none | This document + `deploy/nectar/README.md` |

## What is built

`deploy/nectar/` holds everything needed to stand the instance up. Nothing
has been launched on Nectar yet — every file below is written and committed
but unexercised against a real VM.

| File | Purpose |
|---|---|
| `docker-compose.yml` | Ollama + `rag.py` API + nginx. Only port 80 published |
| `nginx.conf` | Serves the Flutter build, reverse-proxies the API |
| `.env.example` | `ADMIN_UPLOAD_SECRET` plus optional translation vars |
| `README.md` | Full runbook: launch parameters through to troubleshooting |

Three details in that configuration worth not rediscovering:

- **No `TRUSTED_LLM_HOST` is needed.** `llm_endpoint.is_private_host()`
  accepts any single-label hostname, so `http://ollama:11434` passes. The
  Tailscale tunnel, `ollama_tunnel_proxy.py` and `OLLAMA_TUNNEL_SECRET` are
  obsolete here rather than migrated — inference runs beside the API.
- **nginx `proxy_read_timeout` is 180s.** The 60s default would cut off
  every real synthesis call (rag.py allows 130s) and surface it as a 504
  that looks like a broken API rather than a slow one.
- **Neo4j is overridden out in compose, not by editing `Dockerfile.serve`.**
  That keeps the existing Render deployment working during the transition.

Verification status: `docker compose config` parses and all seven `--kg`
paths resolve. **`nginx.conf` has not been runtime-tested** — the local
Docker daemon was not running. Check `docker compose logs web` first on the
instance.

## Notes for whoever picks this up

- **`p3.*` flavours are almost certainly preemptible.** They are 4–6x cheaper
  than `m3.*` at identical specs and, unlike every `t3`/`c3`/`m3`/`r3` flavour,
  show no `CPU Shares` quota line at all. Unconfirmed — verify before running
  anything long-lived on one.
- **`t3.*` flavours have a 10 GB root disk** where all others have 30 GB.
- Shutting an instance off is not the same as shelving it. `openstack server
  shelve` releases resources; a shut-off instance may keep accruing SU. Confirm
  with Nectar support before relying on either.
