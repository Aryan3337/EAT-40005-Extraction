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

**The allocation record itself, read 2026-10-27.** It is visible only to
whoever submitted the allocation — every other tenant manager's
"My Requests" list is empty — so ask Afzal rather than going looking:

| Field | Value |
|---|---|
| State | Approved, `Provisioned: yes` |
| **Window** | **19 Oct 2026 → 19 Oct 2027** (12 months) |
| Contact | `achowdhary@swin.edu.au` |
| Approver | `pwolynec@swin.edu.au` |
| Project ID | `39543965fbe54d1ca3794f8b4a184806` |
| **Associated Site** | **Swinburne**; `National funded: no` |
| Current Resources | `Bundle: Standard`, plus "Volume Service Storage Swinburne (VIC) 50 GB" |

That closes open item 2 below: **the allocation expires 19 Oct 2027** and
Afzal is the contact of record for renewing it. Two further things follow.

**The availability zone is `swinburne-01`.** A site allocation has a network
in its own site's zone and nowhere else, which is why launching with
Availability Zone = *Any* fails with `Failed to allocate the network(s), not
rescheduling` — measured 2026-10-27 on instance
`6867d2d0-bccf-47dc-b91c-8e77f767837d`, which had to be deleted and
relaunched with the zone pinned. The volume must be created in the same zone
or it cannot attach. `deploy/nectar/README.md` step 1 now says so; nothing in
this repo did before, and the zone is not discoverable from the dashboard
quota views a deployer can see.

**The quota table above is the dashboard's bundle-derived view, not an
approved per-zone grant.** `Current Resources` lists only the Standard bundle
and the 50 GB volume: there is no compute line and no per-AZ vCPU/RAM
breakdown. The 64 vCPU / 128 GB figures are what the launch wizard reports as
available, and that is the right thing to measure `m3.xlarge` (16 / 32)
against, so D1 is unaffected. But do not read that table as "Nectar approved
64 vCPUs" when discussing headroom with Afzal or a successor.

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

### D5 — Neo4j (AuraDB) is the retrieval backend

**Reversed 2026-10-26.** An earlier draft of this decision dropped Neo4j for
CSV mode. Neo4j is required, so the deployment reads the existing managed
AuraDB instance and `--neo4j` stays as `Dockerfile.serve`'s CMD already has
it. No edit to that CMD and no `command:` override in `docker-compose.yml`.

**The two paths are mutually exclusive**, which is easy to miss. `rag.py:2820`:

```python
skeleton = Neo4jRAGSkeleton() if use_neo4j else RAGSkeleton(kg_path, approach=approach)
```

`--neo4j` wins outright and every `--kg` flag is dead. A draft of
`docker-compose.yml` passed twelve of them alongside `--neo4j`; they did
nothing. `data/production_graph/` still ships in the image (`COPY data/`) for
`load_production_graph.py` and as the clean reference corpus, but it is not
the read path.

**AuraDB over a self-hosted container.** Zero infrastructure work, no fourth
service, no volume budget, and it matches what Render serves today. The cost
is a cloud dependency and a credential set that must survive the handover —
recorded under open items, not resolved here.

**Two consequences worth writing down.**

*The graph path is behind the CSV path on precision.* Both share
`question_keywords`, `keyword_weights`, `score_triple_weighted` and
`dedupe_triples`. Only `ConceptRetriever.retrieve` has:

| Behaviour | CSV | Neo4j |
|---|---|---|
| `filter_community_periods` (time-aware narrowing) | yes | no |
| Drops zero-scoring triples (`score > 0`) | yes | no |
| `matches_topic` — community identity alone is not topic relevance | yes | no |
| `group_responses` (community attribution) | yes | no |

Without `matches_topic`, a question about languages retrieves anything that
merely mentions "Garo"; without the score cut, zero-scoring triples reach
synthesis as evidence. Both push in the wrong direction for a project that
accepts low recall to avoid confident wrong answers. **Investigation and a
plan are owed before any code changes here** — `Neo4jRAGSkeleton.query` is
also what Render serves, so this is not a Nectar-local edit.

*The data no longer differs.* **Superseded 2026-10-27.** This paragraph used
to say AuraDB held 697 nodes / 715 relationships with 670 carrying no current
`run_id` — leftover ungated loads, per `docs/ICSE_SEIS_EVIDENCE_REPORT.md` —
so that deploying on `--neo4j` served a messier superset of the 112-triple CSV
export, and that whether to clean it first was an open question.

It has been cleaned. Measured against the live instance 2026-10-27: **195
nodes, 124 relationships**, of which **112 are `Entity`->`Entity` and all 112
carry both a `run_id` and a `sentence_ref`** — matching the 112 rows across
`data/production_graph/*_kg_refined.csv` exactly. The two run ids present are
`2026-10-08-overnight-batch` (67) and `20261005T021421Z-cab24022` (45). The
remaining 12 relationships are the auth and chat-history graph (`User`,
`Conversation`, `ChatMessage`).

So the graph path and the CSV path now read the same corpus, and the open
question above is closed. What remains different between the two paths is the
code, not the data: the four missing precision filters described above.

### D5a — `Dockerfile.serve` copied five modules and needed twelve

Found 2026-10-26 while checking D5, and it blocked the deploy outright in
*either* retrieval mode.

`Dockerfile.serve` was last edited 5 Oct (`971132a`). Since then `auth_store`
(13 Oct), `local_tts` (13 Oct), `source_provenance` (15 Oct),
`community_time` and `community_attribution` (16 Oct), plus
`local_translation` and `prompt_evidence`, all became unguarded module-level
imports in `rag.py`. None were in the `COPY`. The container dies at
`rag.py:42`:

```
ModuleNotFoundError: No module named 'auth_store'
```

Verified by assembling a directory holding exactly the files the image would
hold and importing `rag`: it fails as above, and succeeds once those seven are
added. The `COPY` now names all twelve, and nothing enforces that — if
`rag.py` gains a local import, it has to be added by hand.

**This implies the live Render deployment has been serving a pre-13-Oct image
or failing to build since.** Not investigated here; worth checking before the
demo.

**torch and transformers stay out.** `local_tts.py` and
`local_translation.py` are the only users and both import them lazily inside
functions, so the image starts and English retrieval works without them.
Shipping them would add multi-GB wheels plus model files that
`local_files_only=True` will not download at runtime anyway. The cost:
backend TTS is unavailable (it refuses cleanly unless `TTS_ENABLED=1`), and
`TRANSLATION_PROVIDER` must be set to `llm`, because `rag.py:1068` defaults
it to `local`, which would route a Bangla or Hindi question into
`import torch` and raise. English questions never touch that path.

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
2. ~~**Allocation end date and renewal owner.**~~ **ANSWERED 2026-10-27** from
   the allocation record above: the window is **19 Oct 2026 → 19 Oct 2027** and
   `achowdhary@swin.edu.au` is the contact. Still open is who renews it once the
   students' accounts deactivate — which is item 1, not this one. If it lapses
   mid-assessment the assessors get a dead link.
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
- **No `command:` override in compose.** `Dockerfile.serve`'s CMD is
  already `python -u rag.py --serve --neo4j --host 0.0.0.0`, which is what
  the AuraDB path needs — see D5. An override existed only while CSV mode
  was the plan.
- **`NEO4J_USERNAME`, not `NEO4J_USER`.** `config.py` reads the former; the
  latter fails as "Neo4j configuration is incomplete", which reads like a
  missing credential rather than a misspelt variable.
- **The username is not `neo4j`.** Added 2026-10-27. On this instance the
  working username is the 8-hex-character string that is also the instance id
  in `NEO4J_URI`; `neo4j` fails with
  `Neo.ClientError.Security.Unauthorized`. `deploy/nectar/.env.example` and
  the runbook both used to say `neo4j`, and both are corrected. Not unique to
  this instance either — `PRUNER_README.md:93` carries the same
  instance-id-as-username shape for a different database.

Verification status, 2026-10-26:

- The compose file parses, declares three services, publishes only port 80,
  and carries no `command:` override. (The security group opens 443 as well,
  ahead of the TLS work; nothing publishes it yet.)
- The exact 12-file set `Dockerfile.serve` copies imports `rag` cleanly,
  checked by assembling that file set and importing it.
- `resolve_neo4j_uri` confirmed on four inputs: a bare Aura hostname gains
  `neo4j+s://`, an explicit `neo4j+s://` passes through, `neo4j://` to a
  remote host raises `InsecureNeo4jURI`, and `neo4j://neo4j:7687` is allowed
  as a private host.
- **`nginx.conf` has not been runtime-tested** — the local Docker daemon was
  not running. Check `docker compose logs web` first on the instance. Still
  true as of 2026-10-27.

Updated 2026-10-27:

- **The AuraDB credentials now work, and one of them was wrong in the docs.**
  A connection was made from a development machine using the `.env` values and
  the `neo4j` Python driver: it authenticates, and the schema and node counts
  above were read over it. This found that `NEO4J_USERNAME` is not `neo4j` —
  see the bullet above.
- **Be precise about what that does and does not settle.** It proves the URI,
  username and password are correct and the instance is reachable. It does
  **not** exercise `config.py`'s `resolve_neo4j_uri` (the `.env` URI already
  carries an explicit `neo4j+s://`, so the prepend branch was never taken),
  and it does not test the connection from inside the container or from the
  Nectar instance's network. The first `docker compose up` is still the first
  test of those.

## Notes for whoever picks this up

- **`p3.*` flavours are almost certainly preemptible.** They are 4–6x cheaper
  than `m3.*` at identical specs and, unlike every `t3`/`c3`/`m3`/`r3` flavour,
  show no `CPU Shares` quota line at all. Unconfirmed — verify before running
  anything long-lived on one.
- **`t3.*` flavours have a 10 GB root disk** where all others have 30 GB.
- Shutting an instance off is not the same as shelving it. `openstack server
  shelve` releases resources; a shut-off instance may keep accruing SU. Confirm
  with Nectar support before relying on either.
