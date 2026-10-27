# Nectar deployment runbook

Builds the whole chatbot on one Nectar instance. Written to be followed by
someone who was not involved in the project. Decisions and their reasoning
are in `../../NECTAR_MIGRATION.md`.

Expect **40–60 minutes** end to end, most of it the model download.

---

## 1. Launch the instance

**Do step 2 first.** The launch wizard picks a security group and a key pair
from lists, so both have to exist before you start it. Follow this file in the
order **2 → the key pair below → 1 → 3 → 4 → 5 → 6**. The numbering is
left alone because `../../NECTAR_IMPLEMENTATION_PLAN.md`, `web/.gitkeep` and
the troubleshooting table below all cite these numbers.

**The key pair, before the wizard.** Generate it locally and import only the
public half, rather than letting the dashboard mint one and show you the
private key once in a browser:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/p85_nectar -C "p85-nectar"
cat ~/.ssh/p85_nectar.pub
```

Then **Compute -> Key Pairs -> Import Key Pair**: name `p85-nectar`, type
**SSH Key**, paste that single line. On Windows the path is
`$env:USERPROFILE\.ssh\p85_nectar` and `ssh-keygen` will not create the
directory for you — run
`New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh"` first. Keep the
private key out of OneDrive or any other synced folder. An empty passphrase is
reasonable here — the key opens a rebuildable demo VM, and the `scp` in step 6
would otherwise prompt repeatedly — the secrets worth protecting on this
instance live in `.env`.

Nectar dashboard -> **Compute -> Instances -> Launch Instance**.

| Tab | Value |
|---|---|
| **Details** | Instance name `p85-chatbot`; **Availability Zone `swinburne-01`** |
| **Source** | Boot from **Image**: `NeCTAR Ubuntu 22.04 LTS (Jammy) amd64 (with Docker)`. Create New Volume: **No** |
| **Flavour** | `m3.xlarge` — 16 VCPU, 32 GB RAM, 30 GB root, 0.457 SU/hr |
| **Networks** | `Classic Provider` — the project's only network, usually pre-allocated |
| **Security Groups** | `p85-chatbot` from step 2; deallocate `default` |
| **Key Pair** | `p85-nectar`, imported above |

**Set the availability zone explicitly. Leaving it on *Any* is how this
fails.** Measured 2026-10-27, a launch with no zone set died with:

```
Build of instance 6867d2d0-bccf-47dc-b91c-8e77f767837d aborted:
Failed to allocate the network(s), not rescheduling.
```

Nova placed the instance, then Neutron had no port to give it. This is a
**site allocation at Swinburne** — the allocation record reads
`Associated Site: Swinburne`, `National funded: no`, and its only storage line
is "Volume Service Storage Swinburne (VIC) 50 GB" — so `swinburne-01` is the
zone where the project has a network, and the volume in step 3 must be created
in that same zone or it cannot attach. That record is visible only to whoever
submitted the allocation (Afzal); every other tenant manager's "My Requests"
list is empty, so it is not something a deployer can look up.

An `Error` instance still holds quota. Delete it before relaunching rather
than leaving it beside the new one.

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
(quota is 50 GiB total), source **No source, empty volume**, Availability
Zone **`swinburne-01`** — the same zone as the instance, or it cannot
attach. Then **Manage Attachments** -> attach to `p85-chatbot`; the status
goes `Available` -> `In-use`.

20 GiB, not 30: the only things stored here are the Ollama model (~4.7 GB,
re-downloadable) and `uploads/`. 30 GiB spent 60% of the volume quota
holding a file that can be fetched again, and 20 still leaves room for a
second model.

The volume is what makes this instance rebuildable: the model and the
admin uploads survive destroying and recreating the VM.

SSH in and mount it. `/dev/vdb` is the usual device — confirm with `lsblk`
before formatting, and **only format a brand new volume**:

```bash
ssh -i ~/.ssh/p85_nectar ubuntu@<instance-ip>

lsblk                                   # confirm the device name first
sudo mkfs.ext4 /dev/vdb                 # NEW VOLUME ONLY - destroys data
sudo mkdir -p /mnt/data
sudo mount /dev/vdb /mnt/data

sudo blkid /dev/vdb                     # mkfs printed this UUID too
echo 'UUID=<uuid-from-above> /mnt/data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
cat /etc/fstab                          # the new entry must be on its own line

sudo mkdir -p /mnt/data/ollama /mnt/data/uploads
sudo chown -R ubuntu:ubuntu /mnt/data
```

`nofail` matters: without it a missing volume stops the instance booting, and
there is no console to fix it from.

**`UUID=`, not `/dev/vdb`** (this runbook said `/dev/vdb` until 2026-10-27).
Device names are assignment order, not identity: attach a second volume later
and today's `vdb` can come back as `vdc`, at which point the fstab line mounts
the wrong disk or nothing at all. A UUID follows the filesystem.

`cat /etc/fstab` is not ceremony either. `tee -a` appends, so if the file had
no trailing newline the new entry joins onto the end of the root entry and the
instance does not boot.

Both directories matter. `/mnt/data/uploads` is bind-mounted to
`/app/uploads` by `docker-compose.yml`, which is the only reason admitted
papers and `queue.jsonl` survive `docker compose down` -- `UPLOADS_DIR`
otherwise defaults to a path on the container's writable layer.

Then patch the OS, while nothing is being served yet. A fresh Jammy image is
~165 packages behind, ~140 of them security updates, and this box is about to
publish a login form:

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

**Answer the openssh-server prompt with "keep the local version currently
installed."** The Nectar image ships a modified `sshd_config`, and that
modification is what sets `passwordauthentication no` and `permitrootlogin
no`; the maintainer's version would overwrite both. SSH is the only way into
this instance. On the "daemons using outdated libraries" prompt accept the
defaults — the reboot restarts everything regardless.

Confirm before moving on. The reboot doubles as the fstab test, so run these
*after* reconnecting:

```bash
findmnt /mnt/data                                # /dev/vdb on /mnt/data, ext4
df -h /mnt/data                                  # ~20 GiB, ~1% used
ls -la /mnt/data                                 # ollama/ + uploads/, owned by ubuntu
docker --version                                 # Docker survived the upgrade
docker compose version                           # the v2 plugin step 5 uses
id -nG                                           # must include: docker
sudo sshd -T | grep -i passwordauthentication    # expect: no
```

**`id -nG` will not include `docker` on a fresh instance** (verified
2026-10-27 on this image), and without it every `docker compose` command in
step 5 fails on `/var/run/docker.sock`. Fix it here:

```bash
sudo usermod -aG docker ubuntu
```

Then log out and back in — group membership is read at login, so the
reconnect is what applies it — and check `docker ps` runs without `sudo`.

## 4. The public address (there is no floating IP)

**Nothing to do here but read the address.** `Classic Provider` assigns a
routable public IPv4 at boot: take it from the **IP Address** column on the
Instances page. Verified 2026-10-27 — `p85-chatbot` came up on
`136.186.108.232` with no floating IP involved, and the project has no other
network and no router. Floating IPs belong to projects running their own
self-service network, which this one does not have, so the **Associate
Floating IP** action this step used to describe does not apply.

That address goes in the Flutter build in step 6.

**It is instance-bound, which is a handover caveat rather than a detail.** A
classic-provider address belongs to the instance, so destroying and recreating
the VM yields a *different* address — invalidating both the `API_BASE_URL`
compiled into the Flutter web build (step 6) and any `<ip>.sslip.io`
certificate from `../../NECTAR_IMPLEMENTATION_PLAN.md` P1. The volume makes the
data survive a rebuild; nothing makes the URL survive one. So a rebuild also
means rebuilding the frontend, re-running certbot, and telling whoever holds
the link. If a stable address matters more than that, ask Afzal whether the
allocation can be given a router and a floating IP.

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

**Set `$SITE` first.** Once TLS is in place (step 7) port 80 is nothing
but a redirect, so a plain `curl localhost/...` returns **301**, not the
answer you were looking for -- and `-L` does not rescue it, because it
follows to `https://localhost/` where the certificate does not match.
Before TLS exists, use `SITE=http://localhost`.

```bash
SITE=https://$(ip -4 route get 1.1.1.1 | sed -n 's/.*src \([0-9.]*\).*/\1/p').sslip.io
echo $SITE          # https://<instance-ip>.sslip.io
```

```bash
docker compose ps                        # three containers, all Up
curl -s $SITE/health                     # through nginx
docker compose logs -f api               # expect "RAG API listening on ..."
```

A real question end to end, which also proves AuraDB is reachable and
Ollama has the model (expect 40s+ on CPU).

**`/query` requires a signed-in user.** Posting to it with no
`Authorization` header returns `401 {"error": "Sign in is required."}` in
well under a second, which is easy to misread as the API being broken when
it is in fact working. Register a throwaway account, use its token, and
delete the account afterwards:

```bash
# 1. Register. Returns {"token": ..., "email": ..., "role": "user"}.
TOKEN=$(curl -s -X POST $SITE/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"m2-verify@example.com","password":"m2-verify-pass-2026"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')

# 2. Ask. ~63s on m3.xlarge, measured 2026-10-27.
curl -s -X POST $SITE/query \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "What languages do the Garo speak?"}'
```

Expect an `answer`, an `evidence` block of triples each carrying a
`sentence_ref` and a page number, and `translations` for `en`/`hi`/`bn`. A
template fallback instead means retrieval found nothing — check the API log
for an AuraDB error.

Accounts live in **AuraDB**, not on the volume, so a throwaway account is a
write to the production graph and outlives the container. Delete it when
you are done — and note that sessions are held in API memory, so every
token is invalidated by `docker compose restart api` anyway:

```bash
docker compose exec -T api python -c "
from neo4j import GraphDatabase
from config import URI, USERNAME, PASSWORD
d = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
with d.session() as s:
    s.run('MATCH (u:User {email: \$e}) DETACH DELETE u', e='m2-verify@example.com').consume()
    print([r['email'] for r in s.run('MATCH (u:User) RETURN u.email AS email')])
d.close()"
```

## 6. Build and deploy the web frontend

On a machine with Flutter installed, **not** the instance:

```bash
cd flutter_application
flutter build web --release \
  --dart-define=API_BASE_URL=http://<instance-ip>
```

`API_BASE_URL` must be the real address. Left empty it falls back to
`http://127.0.0.1:8000`, which in a browser means the visitor's own
machine, not the server.

Copy the build up:

```bash
scp -i ~/.ssh/p85_nectar -r build/web/* \
  ubuntu@<instance-ip>:~/EAT-40005-Extraction/deploy/nectar/web/
```

Until this upload exists, `/` returns **403** and the nginx log says
`directory index of "/usr/share/nginx/html/" is forbidden`. That is the
signature of an empty `web/`, not a broken nginx.

Verify from the instance:

```bash
curl -s -o /dev/null -w '%{http_code}\n' $SITE/               # 200
curl -s -o /dev/null -w '%{size_download}\n' $SITE/main.dart.js  # ~2.9MB
```

**Do not upload dotfiles.** The `build/web/*` glob above is deliberate:
it skips them. A `tar`-based copy does not, and on 2026-10-27 that put a
complete `.git` directory into the web root, which nginx served to the
internet -- a scanner pulled `/.git/config` within the hour. That
particular repo held only public build artifacts, but a served `.git` is
a clonable copy of whatever history it has. `nginx.conf` now denies
dotfiles outright, but do not rely on that alone.

### Then open the site

**The URL is `https://<instance-ip>.sslip.io/`, not the bare IP.** Hand
that one out; it is the only address with a matching certificate.

A bare-IP URL does not work properly in a current Chrome, and the failure
is confusing in both directions:

- `http://<instance-ip>/` -- Chrome's HTTPS-First rewrites this to
  `https://` before the request leaves the browser, so nginx's own
  80 -> 443 redirect never runs.
- `https://<instance-ip>/` -- answered, but with a certificate issued for
  `<ip>.sslip.io`, so the browser shows a name-mismatch warning. It can be
  clicked through, unlike the pre-TLS state where the connection was
  refused outright with no bypass at all.

`curl` is not a good test of any of this: it has no HTTPS-First and will
happily report 200 from port 80 on a site no browser can open.


## 7. TLS

**Done 2026-10-27.** Certificate issued for `136.186.108.232.sslip.io`,
expiring 2027-01-25, renewing automatically. This section is what to do
on a REBUILT instance, where the IP -- and therefore the domain -- has
changed.

```bash
cd ~/EAT-40005-Extraction/deploy/nectar
./init-letsencrypt.sh                 # staging: proves the plumbing
STAGING=0 FORCE=1 LETSENCRYPT_EMAIL=s2026_eat40006_p85@outlook.com \
    ./init-letsencrypt.sh             # the real certificate
```

**To use a real domain instead**, point an A record at the instance and
pass the name as the first argument:

```bash
STAGING=0 FORCE=1 LETSENCRYPT_EMAIL=... ./init-letsencrypt.sh garochatbot.com
```

`nginx.conf` needs no change -- it has no domain in it. The Flutter bundle
does: rebuild it with `--dart-define=API_BASE_URL=https://garochatbot.com`
or the page will call the old origin. Whether to buy a domain at all is an
open handover question, not a technical one -- see H2 and H4 in
`../../NECTAR_IMPLEMENTATION_PLAN.md`.
The script derives the domain from the instance's own IP, so a rebuild
needs no edit to it or to `nginx.conf`. Read its header comment before
changing anything; the ordering in it is load-bearing.

**Always do the staging run first.** `sslip.io` is NOT on the Public
Suffix List, so Let's Encrypt counts every `*.sslip.io` certificate
issued anywhere on the internet against ONE shared registered-domain
limit. A misconfiguration retried against production burns a limit that
is not ours alone. Staging has its own generous limits and its
certificate is untrusted by design -- that is not the failure you are
looking for.

**Renewal** runs in the `certbot` container twice a day and acts only
inside the last 30 days of the 90-day certificate. `web` reloads nginx
every 6h so a renewed certificate is actually picked up -- nginx reads
certificates at start and reload only, so without that a renewal lands on
disk while the expired one keeps being served. Both containers are
`restart: unless-stopped`, so this survives a reboot.

Check it:

```bash
docker compose run --rm --entrypoint certbot certbot renew --dry-run
echo | openssl s_client -connect <ip>.sslip.io:443 \
  -servername <ip>.sslip.io 2>/dev/null | openssl x509 -noout -dates
```

The certificate lives at `/mnt/data/letsencrypt` -- on the volume, so
`docker compose down` does not throw it away and force a re-issue, and
under the cert name `p85` rather than the domain, so no path inside
`nginx.conf` contains the IP.
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

**After editing `nginx.conf`, recreate the container -- a reload is not
enough:**

```bash
docker compose up -d --force-recreate web
```

`nginx.conf` is a single-FILE bind mount, and almost everything that
writes a file replaces it rather than editing it in place -- `git pull`,
`tar -x`, `scp`, even `sed -i`. The replacement is a new inode, and the
running container stays bound to the old one. So `nginx -s reload` cheerfully
re-reads the file you thought you changed and reports success. Cost an
entirely avoidable debugging detour on 2026-10-27.

The certificate mounts are DIRECTORY mounts and do not have this problem,
which is why renewal pickup works with a plain reload.

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
| `POST /query` returns `401 Sign in is required.` | Not a fault. `/query` needs `Authorization: Bearer <token>` from `/auth/register` or `/auth/login`. See step 5 |
| Signed in fine, then every request 401s after a deploy | Sessions live in API memory, not AuraDB. `docker compose restart api` / `up -d --build` invalidates every token. Users sign in again; accounts themselves are safe in AuraDB |
| `/` returns 403, log says `directory index ... is forbidden` | `deploy/nectar/web/` is empty — the Flutter build in step 6 was never uploaded |
| Chrome shows a connection error on `http://<instance-ip>` while `curl` gets 200 | Chrome's HTTPS-First upgraded the bare IP to `https://` and nothing listens on 443. Not a server fault. Use the SSH local forward in step 6 until TLS lands |
| Edited `nginx.conf`, reloaded, nothing changed | Single-file bind mount: the editor wrote a new inode and the container still has the old one. `docker compose up -d --force-recreate web` |
| Browser warns the certificate name does not match | The bare IP was used. The certificate is for `<ip>.sslip.io`; hand out that URL |
| `init-letsencrypt.sh` fails at validation | Port 80 must be reachable from the internet for HTTP-01. Check the security group, and that the `/.well-known/acme-challenge/` block still precedes the redirect in `nginx.conf` |
| Certificate expired despite the certbot container running | nginx had not been reloaded since renewal. The 6h reload loop in `web`'s `command:` is what does that -- check it was not dropped |
| A path starting with a dot returns 404 | Deliberate. `nginx.conf` denies dotfiles after a `.git` directory was served from the web root on 2026-10-27. `/.well-known/` is exempt |

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
- **HTTPS.** Port 80 only *as deployed*. The reason given here used to be
  that TLS needs a DNS name the project does not have; that is no longer the
  blocker. `NECTAR_IMPLEMENTATION_PLAN.md` P1 uses `<instance-ip>.sslip.io`,
  which resolves to the IP with nothing to buy or register, and the security
  group already opens 443. P1 is on the critical path, not optional: the API
  serves `/auth/register` and `/auth/login`, which carry passwords, plus
  `ADMIN_UPLOAD_SECRET` in a request header — all cleartext on port 80.
- **GPU.** No usable GPU flavour exists on this allocation. See
  `../../NECTAR_MIGRATION.md`.
- **The Tailscale tunnel.** `ollama_tunnel_proxy.py`, the Funnel and
  `OLLAMA_TUNNEL_SECRET` are obsolete here: inference runs on the same
  Docker network as the API.
