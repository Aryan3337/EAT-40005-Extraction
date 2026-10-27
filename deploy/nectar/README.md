# Nectar deployment runbook

Builds the whole chatbot on one Nectar instance. Written to be followed by
someone who was not involved in the project. Decisions and their reasoning
are in `../../NECTAR_MIGRATION.md`.

Expect **40–60 minutes** end to end, most of it the model download.

---

## 1. Launch the instance

Nectar dashboard -> **Compute -> Instances -> Launch Instance**.

| Tab | Value |
|---|---|
| **Details** | Instance name `p85-chatbot` |
| **Source** | Boot from **Image**: `NeCTAR Ubuntu 22.04 LTS (Jammy) amd64 (with Docker)`. Create New Volume: **No** |
| **Flavour** | `m3.xlarge` — 16 VCPU, 32 GB RAM, 30 GB root, 0.457 SU/hr |
| **Networks** | The project's default network |
| **Security Groups** | See step 2 |
| **Key Pair** | Create or select one. **Download the private key now** — it is shown once |

Not the `AI Ready` images: they are 15–19 GB of CUDA and PyTorch that a
CPU-only deployment cannot use, and they would fill the 30 GB root disk.

## 2. Security group

**Network -> Security Groups -> Create Security Group**, name it
`p85-chatbot`, then add three ingress rules:

| Rule | Port | CIDR | Why |
|---|---|---|---|
| SSH | 22 | **your IP /32**, not `0.0.0.0/0` | Admin access |
| HTTP | 80 | `0.0.0.0/0` | The public site |
| HTTPS | 443 | `0.0.0.0/0` | TLS. Open it now; nothing listens on it until the TLS work lands, and a closed 443 blocks certbot's HTTP-01 redirect flow later |

Do **not** open 8000 or 11434. The API and Ollama are reachable only on the
internal Docker network; publishing them would expose an unauthenticated
Ollama to the internet.

## 3. Volume for the model and data

**Volumes -> Volumes -> Create Volume**: name `p85-data`, size **20 GiB**
(quota is 50 GiB total). Then **Manage Attachments** -> attach to
`p85-chatbot`.

20 GiB, not 30: the only things stored here are the Ollama model (~4.7 GB,
re-downloadable) and `uploads/`. 30 GiB spent 60% of the volume quota
holding a file that can be fetched again, and 20 still leaves room for a
second model.

The volume is what makes this instance rebuildable: the model and the
admin uploads survive destroying and recreating the VM.

SSH in and mount it. `/dev/vdb` is the usual device — confirm with `lsblk`
before formatting, and **only format a brand new volume**:

```bash
ssh -i <your-key>.pem ubuntu@<floating-ip>

lsblk                                   # confirm the device name first
sudo mkfs.ext4 /dev/vdb                 # NEW VOLUME ONLY - destroys data
sudo mkdir -p /mnt/data
sudo mount /dev/vdb /mnt/data
echo '/dev/vdb /mnt/data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mkdir -p /mnt/data/ollama /mnt/data/uploads
sudo chown -R ubuntu:ubuntu /mnt/data
```

`nofail` matters: without it, a missing volume stops the instance booting.

Both directories matter. `/mnt/data/uploads` is bind-mounted to
`/app/uploads` by `docker-compose.yml`, which is the only reason admitted
papers and `queue.jsonl` survive `docker compose down` -- `UPLOADS_DIR`
otherwise defaults to a path on the container's writable layer.

Confirm before moving on: `lsblk` shows the volume mounted at
`/mnt/data`, `df -h /mnt/data` reports ~20 GiB, and `/etc/fstab` has the
`nofail` line.

## 4. Associate a floating IP

**Compute -> Instances -> Associate Floating IP** on `p85-chatbot`. Note
the address — it goes in the Flutter build in step 6.

## 5. Deploy

```bash
# -b dev is required: the default branch is main, which does not have
# deploy/nectar/ or the merged retrieval work.
git clone -b dev https://github.com/Aryan3337/EAT-40005-Extraction.git
cd EAT-40005-Extraction/deploy/nectar

cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # paste into ADMIN_UPLOAD_SECRET
nano .env
```

`.env` needs **four** values before the API will start. Retrieval reads
AuraDB, so the three `NEO4J_*` ones are not optional:

| Variable | Where it comes from |
|---|---|
| `NEO4J_URI` | Aura console. The bare `<id>.databases.neo4j.io` is fine — `config.py` prepends `neo4j+s://` |
| `NEO4J_USERNAME` | **Not `neo4j`** on the P85 instance, and not `NEO4J_USER` either. Verified 2026-10-27: `neo4j` fails with `Neo.ClientError.Security.Unauthorized`; the working value is the same 8-hex string as the instance id in `NEO4J_URI`. Copy it from the Aura console verbatim |
| `NEO4J_PASSWORD` | Shown once when the Aura instance was created |
| `ADMIN_UPLOAD_SECRET` | The `token_urlsafe` value you just generated |

Missing any of the three Neo4j values and the container exits at startup
with `Neo4j configuration is incomplete.`

```bash
docker compose up -d --build
docker compose exec ollama ollama pull mistral:7b     # ~4.7GB, several minutes
```

Check it:

```bash
docker compose ps                        # three containers, all Up
curl -s localhost/health                 # through nginx
docker compose logs -f api               # expect "RAG API listening on ..."
```

A real question end to end, which also proves AuraDB is reachable and
Ollama has the model (expect 40s+ on CPU):

```bash
curl -s -X POST localhost/query -H 'Content-Type: application/json'   -d '{"query": "What languages do the Garo speak?"}'
```

## 6. Build and deploy the web frontend

On a machine with Flutter installed, **not** the instance:

```bash
cd flutter_application
flutter build web --release \
  --dart-define=API_BASE_URL=http://<floating-ip>
```

`API_BASE_URL` must be the real address. Left empty it falls back to
`http://127.0.0.1:8000`, which in a browser means the visitor's own
machine, not the server.

Copy the build up:

```bash
scp -i <your-key>.pem -r build/web/* \
  ubuntu@<floating-ip>:~/EAT-40005-Extraction/deploy/nectar/web/
```

Then open `http://<floating-ip>` in a browser.

---

## Operating it

```bash
cd ~/EAT-40005-Extraction/deploy/nectar

docker compose ps                    # what is running
docker compose logs -f api           # follow API logs
docker compose restart api           # restart just the API
docker compose down                  # stop everything
docker compose up -d --build         # rebuild after a git pull
```

**Updating after a code change:**

```bash
cd ~/EAT-40005-Extraction && git pull
cd deploy/nectar && docker compose up -d --build
```

**Watching credit burn:** `m3.xlarge` costs 0.457 SU/hr, so the 4000 SU
budget is about a year of continuous uptime. Check consumption under
**Allocations** in the dashboard.

Shutting an instance off is not the same as shelving it —
`openstack server shelve` releases the resources, while a shut-off instance
may keep accruing SU. Confirm with Nectar support before relying on either.

## Troubleshooting

| Symptom | Cause |
|---|---|
| 504 after ~60s on `/query` | `proxy_read_timeout` in `nginx.conf` dropped below rag.py's 130s synthesis timeout |
| Answers work but are slow | Expected on CPU. First call after startup also loads the model into RAM |
| `/admin/*` returns 403 | `ADMIN_UPLOAD_SECRET` missing from `.env`, or the admin UI's prompt has a different value |
| API exits at startup, `Neo4j configuration is incomplete` | One of `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` is missing from `.env`. Note it is `NEO4J_USERNAME`, not `NEO4J_USER` |
| API exits at startup, `Refusing an unencrypted Neo4j connection` | `NEO4J_URI` has a `neo4j://` scheme pointing at a remote host. Drop the scheme and let `config.py` add `neo4j+s://` |
| API exits at startup, `ModuleNotFoundError` | A local module `rag.py` imports is not in `Dockerfile.serve`'s `COPY`. This happened once already — the five-file list went stale on 13 Oct |
| A Bangla or Hindi question 500s | `TRANSLATION_PROVIDER` is unset or `local`, which needs torch. Set it to `llm` |
| `/tts` refuses | Expected. Backend speech needs torch, which this image does not carry |
| Site loads, every request fails | `API_BASE_URL` was wrong or empty at Flutter build time. Rebuild and re-upload |
| Ollama "model not found" | The `ollama pull` in step 5 did not run, or ran before the volume was mounted |
| API exits at startup, `Neo.ClientError.Security.Unauthorized` | `NEO4J_USERNAME` was set to `neo4j`. On the P85 instance the username is the instance id, not `neo4j` — see the credentials table in step 5 |
| Admitted papers and the review queue vanish after a restart | `/mnt/data/uploads` was not created in step 3, or `UPLOADS_DIR=/app/uploads` was removed from `docker-compose.yml`. Without both, uploads sit on the container's writable layer and `docker compose down` deletes them |

## What this deployment deliberately does not include

- **A self-hosted Neo4j.** Retrieval reads the existing managed AuraDB
  instance. The handover therefore includes AuraDB credentials and depends
  on that account surviving. The CSVs ship in the image but are not the
  read path — see `docker-compose.yml`.

  **Corrected 2026-10-27.** This section used to warn that the live graph
  was a messier superset of the clean export — 697 nodes / 715
  relationships, 670 of them carrying no current `run_id`. That is no
  longer true. Measured against the live instance: 195 nodes, 124
  relationships, of which **112 are `Entity`->`Entity` and all 112 carry
  both a `run_id` and a `sentence_ref`**, matching the 112 rows across
  `data/production_graph/*_kg_refined.csv` exactly. The unattributed
  relationships are gone. The remaining 12 relationships are the auth and
  chat-history graph (`User`, `Conversation`, `ChatMessage`).
- **The four CSV-path precision filters.** `Neo4jRAGSkeleton.query` lacks
  `filter_community_periods`, the `score > 0` cut, `matches_topic` and
  `group_responses`, all of which `ConceptRetriever.retrieve` applies. The
  deployed graph path is measurably less precise than the CSV path. Tracked
  in `../../NECTAR_MIGRATION.md`.
- **Backend TTS and local translation.** Both need torch and multi-GB model
  files. `TTS_ENABLED` stays unset and `TRANSLATION_PROVIDER=llm`.
- **HTTPS.** Port 80 only. Adding TLS needs a DNS name, which the project
  does not currently have.
- **GPU.** No usable GPU flavour exists on this allocation. See
  `../../NECTAR_MIGRATION.md`.
- **The Tailscale tunnel.** `ollama_tunnel_proxy.py`, the Funnel and
  `OLLAMA_TUNNEL_SECRET` are obsolete here: inference runs on the same
  Docker network as the API.
