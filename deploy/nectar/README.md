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

`.env` needs **five** values before `docker compose up` will work.
Retrieval reads AuraDB, so the three `NEO4J_*` ones are not optional:

| Variable | Where it comes from |
|---|---|
| `NEO4J_URI` | Aura console. The bare `<id>.databases.neo4j.io` is fine — `config.py` prepends `neo4j+s://` |
| `NEO4J_USERNAME` | **Not `neo4j`** on the P85 instance, and not `NEO4J_USER` either. Verified 2026-10-27: `neo4j` fails with `Neo.ClientError.Security.Unauthorized`; the working value is the same 8-hex string as the instance id in `NEO4J_URI`. Copy it from the Aura console verbatim |
| `NEO4J_PASSWORD` | Shown once when the Aura instance was created |
| `ADMIN_UPLOAD_SECRET` | The `token_urlsafe` value you just generated |
| `API_BASE_URL` | The origin visitors will type, e.g. `https://136.186.108.232.sslip.io`. Compiled into the frontend at build time, so it is needed by `up --build`, not just at runtime. Before TLS exists (step 7), `http://<instance-ip>` builds a working site; rebuild the `web` service after step 7 to move it to the `sslip.io` name |

Missing any of the three Neo4j values and the container exits at startup
with `Neo4j configuration is incomplete.` Missing `API_BASE_URL` and compose
refuses to build at all, naming the variable -- deliberately, because an
empty one produces a site that loads and cannot reach its own API.

```bash
docker compose up -d --build
docker compose exec ollama ollama pull mistral:7b     # ~4.7GB, several minutes
```

The first `--build` compiles the Flutter frontend inside the `web` image and
fetches a ~1.5GB SDK to do it, so expect a few minutes before anything
answers on port 80. That is the whole of the old "build and upload the
frontend" step; section 6 covers rebuilding it.

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

**There is no separate step any more.** `docker compose up -d --build` in
section 5 built the frontend as part of the `web` service. This section is
what to know when it goes wrong or needs rebuilding.

`deploy/nectar/Dockerfile.web` compiles the Flutter app inside the image: a
pinned, checksummed Flutter 3.47.6 SDK from Google's release bucket, then
`flutter build web --release`, then an `nginx:alpine` stage that holds the
compiled site and `nginx.conf`. The document root is image content; nothing
is uploaded.

Rebuild just the frontend after a source or `API_BASE_URL` change:

```bash
cd ~/EAT-40005-Extraction/deploy/nectar
docker compose up -d --build web
```

A cold build fetches ~1.5GB of SDK and takes a few minutes; afterwards the
SDK and the resolved dependencies are cached layers, so a source-only change
rebuilds in well under a minute and a change to `nginx.conf` alone takes
seconds.

**`API_BASE_URL` is a build-time value, set in `.env`.** It is compiled into
`main.dart.js` by `--dart-define`; the frontend cannot be pointed somewhere
else at runtime. Set it to the origin visitors type -- the `sslip.io` name,
not the bare IP, and not the API container -- because nginx proxies the API
routes on that same origin. Compose refuses to start without it and the
Dockerfile checks again, so the old failure mode (empty value, site loads,
every request quietly goes to the visitor's own machine) can no longer
happen silently.

Verify from the instance:

```bash
curl -s -o /dev/null -w '%{http_code}
' $SITE/                 # 200
curl -s -o /dev/null -w '%{size_download}
' $SITE/main.dart.js  # ~2.9MB
docker compose exec web grep -rl sslip.io /usr/share/nginx/html   # main.dart.js
```

That last command is the one worth running: it proves the bundle being
served was compiled with the real origin rather than the loopback fallback.

**What this replaced, and why.** Until 2026-10-28 the site came from
`flutter build web` on a laptop plus `scp` into `deploy/nectar/web/`. No file
in the repository performed that step, so rebuilding the instance from a
clean clone produced a **403** with `directory index of
"/usr/share/nginx/html/" is forbidden` -- the signature of an empty document
root, not a broken nginx. It also meant the live bundle's provenance was
whatever happened to be on someone's laptop. Two incidents came from that
arrangement: a `tar`-based copy carried a complete `.git` directory into the
web root, which nginx served to the internet until a deny rule went in (a
scanner pulled `/.git/config` within the hour), and `nginx.conf` as a
single-file bind mount was edited in place and reloaded with no effect,
because a replaced single-file mount needs a force-recreate rather than
`nginx -s reload`. Both are structurally impossible now: the web root and the
config are both built into the image.

`deploy/nectar/web/` no longer exists. If an old instance still has one, it
is inert -- nothing mounts it -- and can be deleted.


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
docker compose build api             # rebuild ONLY the backend
docker compose up -d api             # and swap it in
```

**Updating after a code change.** `api` and `web` BOTH have a `build:`
stanza, so `docker compose up -d --build` rebuilds the Flutter web image as
well -- a full toolchain build for what is usually a backend-only change.
Build the service you actually changed:

```bash
cd ~/EAT-40005-Extraction
git fetch origin && git checkout -B dev origin/dev   # the instance tracks dev
cd deploy/nectar

docker compose build api && docker compose up -d api   # backend change
docker compose build web && docker compose up -d web   # flutter_application/ change
```

Three things that have each cost a debugging session here:

- **Rebuilding `api` does not rebuild `web`,** or the reverse. On
  2026-10-28 the API was current while the web bundle was three hours
  stale, so a finished backend feature had no UI able to reach it.
- **Verify what actually deployed** rather than trusting the build:
  `docker exec p85_api sha256sum /app/rag.py` against `sha256sum rag.py`
  in the checkout.
- **Every API rebuild signs every teammate out** -- sessions are held in
  memory, not in the database.

**After editing `nginx.conf`, rebuild the `web` image -- neither a reload
nor a recreate is enough:**

```bash
docker compose up -d --build web
```

`nginx.conf` is baked into the image by `Dockerfile.web` as of `62b1378`,
and nothing mounts it any more. So editing the file on disk changes nothing
in the running container until the image is rebuilt -- `nginx -s reload` and
`--force-recreate` will both report success and both serve the old config.

A rebuild of `web` recompiles the Flutter bundle, which takes several
minutes. That is the whole cost: `web` holds no sessions, so rebuilding it
does **not** sign anyone out. Only an `api` rebuild does that.

The certificate mounts are DIRECTORY mounts, so renewal pickup still works
with a plain reload and needs no rebuild.

**Watching credit burn:** `m3.xlarge` costs 0.457 SU/hr, so the 4000 SU
budget is about a year of continuous uptime. Check consumption under
**Allocations** in the dashboard.

Shutting an instance off is not the same as shelving it —
`openstack server shelve` releases the resources, while a shut-off instance
may keep accruing SU. Confirm with Nectar support before relying on either.

## Access: who can get into the box

**Read this before the handover, not after.** Audited 2026-10-29.

The instance accepts **public-key SSH only**, as one user:

```
ssh -i ~/.ssh/p85_nectar ubuntu@136.186.108.232
```

Everything else is shut, and that is deliberate -- but it means there is no
second way in:

| Door | State |
|---|---|
| SSH password | `PasswordAuthentication no` |
| Root over SSH | `PermitRootLogin no` |
| Nectar dashboard VNC console | `ubuntu` password **locked** -- nothing to type |
| SSH key | the only route |

`ubuntu` has `NOPASSWD:ALL`, so anyone holding a key has full root.

**Adding a keypair in the Nectar dashboard does nothing to a running
instance.** OpenStack injects a keypair at launch only. Editing
`~/.ssh/authorized_keys` is the only way to grant access to a box that is
already up.

### Adding someone's key

Get their **public** key (`ssh-ed25519 AAAA... name@host`, one line, from
`~/.ssh/id_ed25519.pub`). If what you were sent begins `-----BEGIN`, that is
a *private* key -- stop, tell them, and ask for the `.pub`.

```bash
# On the instance. APPEND -- a single > wipes the only key you have.
echo 'ssh-ed25519 AAAA... alice@laptop' >> ~/.ssh/authorized_keys

chmod 600 ~/.ssh/authorized_keys        # sshd ignores the file if it is group/world readable
ssh-keygen -l -f ~/.ssh/authorized_keys # one fingerprint per key: check the count went up
```

**Then verify from a second terminal, with the first one still open.**

```bash
ssh -i ~/.ssh/<their-key> ubuntu@136.186.108.232 'echo OK; whoami'
```

If that prints `OK` and `ubuntu`, the key works. Only then close the original
session. If you close it first and the key is malformed, nobody can get back
in -- a malformed line is silently ignored, it does not raise an error.

A key added this way **survives reboots**: cloud-init's `config_ssh` and
`config_users_groups` carry per-instance semaphores that are already
satisfied, so they re-run only if the instance-id changes -- a rebuild, not a
reboot. Verified 2026-10-29.

### Removing someone's key

Delete their line from `~/.ssh/authorized_keys` and re-check the fingerprint
count. Revocation is per-key, which is the whole reason to add individual
keys rather than pass one private key around.

### Break-glass: the console password

Because SSH password auth is off, a password on `ubuntu` is usable **only**
from the Nectar dashboard's console, which already requires a Nectar/AAF
login. That makes it the one recovery path that does **not** change the
instance's IP.

```bash
sudo passwd ubuntu          # set it
sudo passwd -S ubuntu       # expect P (usable), not L (locked)
sudo sshd -T | grep -i '^passwordauthentication'   # must still say "no"
```

**Then actually test it from the dashboard console, once.** An untested
break-glass is not a break-glass. Store the password wherever the team keeps
shared credentials -- never in this repo.

### Dashboard access is not server access

They are different credentials and it is worth being precise about it:

- **Nectar dashboard** (AAF / Swinburne login) — lets you reboot, shelve,
  resize, open the console, and **rebuild**. As of 2026-10-29 six people
  hold it on this project, three of them `tenantmanager`. Check
  *Identity -> Projects -> Members* for the current list rather than
  trusting a copy written here.
- **SSH key** — lets you actually change anything *inside* the box: deploy,
  read logs, restart a container, edit `.env`. Dashboard access grants none
  of this.

So the dashboard is the backstop, not the day job. It is also why the
console password above matters more than it first appears: it is the switch
that turns everyone's existing dashboard access into a real recovery path,
without anyone needing a key.

> **DO NOT CLICK "REBUILD" IN THE DASHBOARD.**
>
> It sits directly beside *Reboot* in the instance's action menu, and it is
> the one button that cannot be undone. Rebuild re-images the root disk:
> the IP changes, `136.186.108.232.sslip.io` stops resolving to us, the
> certificate no longer matches, `~/.ssh/authorized_keys` is reset to the
> launch keypair, and `deploy/nectar/.env` — with the AuraDB credentials —
> is gone. *Reboot* is safe and the stack comes back on its own (docker is
> enabled, all four services are `restart: unless-stopped`).
>
> If the site is misbehaving, reboot or restart a container. Never rebuild
> without reading the next section first.

### What a lockout actually costs

If every key is lost and there is no console password, the only option is a
dashboard **rebuild**:

- **The IP changes.** There is no floating IP (section 4), so
  `136.186.108.232.sslip.io` stops working, every link handed to teammates
  and the client breaks, and the certificate must be reissued for the new
  name -- staging-first, because sslip.io shares one Let's Encrypt rate
  limit (section 7).
- **`deploy/nectar/.env` is on the root disk and goes with it**, taking the
  AuraDB credentials. Recoverable from the Aura console; it is the only
  irreplaceable thing not on the volume.
- **The 20 GiB volume survives** and carries what matters: ollama models,
  the NLLB weights, `uploads/` (admitted papers and the review queue),
  extraction output, and the Let's Encrypt certificates. Detach and reattach
  it.

So a lockout is recoverable, and what it costs is the URL. Keep more than one
person holding a key.

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
| Site loads, every request fails | `API_BASE_URL` was wrong when the `web` image was built. Fix it in `.env` and `docker compose up -d --build web`. Empty can no longer cause this -- compose and the Dockerfile both refuse -- but a *wrong* value still can |
| Ollama "model not found" | The `ollama pull` in step 5 did not run, or ran before the volume was mounted |
| API exits at startup, `Neo.ClientError.Security.Unauthorized` | `NEO4J_USERNAME` was set to `neo4j`. On the P85 instance the username is the instance id, not `neo4j` — see the credentials table in step 5 |
| Admitted papers and the review queue vanish after a restart | `/mnt/data/uploads` was not created in step 3, or `UPLOADS_DIR=/app/uploads` was removed from `docker-compose.yml`. Without both, uploads sit on the container's writable layer and `docker compose down` deletes them |
| `POST /query` returns `401 Sign in is required.` | Not a fault. `/query` needs `Authorization: Bearer <token>` from `/auth/register` or `/auth/login`. See step 5 |
| Signed in fine, then every request 401s after a deploy | Sessions live in API memory, not AuraDB. `docker compose restart api` / `up -d --build` invalidates every token. Users sign in again; accounts themselves are safe in AuraDB |
| `/` returns 403, log says `directory index ... is forbidden` | Was the empty `deploy/nectar/web/` mount, which no longer exists. If it happens now the `web` image was built from a context missing `flutter_application/` -- check the build ran with `context: ../..` |
| Chrome shows a connection error on `http://<instance-ip>` while `curl` gets 200 | Chrome's HTTPS-First upgraded the bare IP to `https://` and nothing listens on 443. Not a server fault. Resolved by step 7; use the `sslip.io` URL |
| Edited `nginx.conf`, reloaded, nothing changed | It is baked into the `web` image as of 2026-10-28, so an edit on disk changes nothing until `docker compose up -d --build web`. (Before that it was a single-file bind mount, where the editor wrote a new inode and the container kept the old one -- the same symptom, a different cause.) |
| Browser warns the certificate name does not match | The bare IP was used. The certificate is for `<ip>.sslip.io`; hand out that URL |
| `init-letsencrypt.sh` fails at validation | Port 80 must be reachable from the internet for HTTP-01. Check the security group, and that the `/.well-known/acme-challenge/` block still precedes the redirect in `nginx.conf` |
| Certificate expired despite the certbot container running | nginx had not been reloaded since renewal. The 6h reload loop in `web`'s `command:` is what does that -- check it was not dropped |
| `web` image build fails on `sha256sum -c` | The pinned Flutter SDK archive did not match `FLUTTER_SHA256` in `Dockerfile.web`. Either the download was truncated (retry) or the pin is wrong for the version -- both values come from `releases_linux.json` and must change together |
| `web` image build fails, `API_BASE_URL build arg is empty` | Working as intended. Set `API_BASE_URL` in `.env` |
| Ollama pegged at ~1600% CPU with nothing in the API log | A `docker exec` that drove Ollama was killed from the HOST. That kills the exec *client*; the process inside the container keeps running and keeps sending generations. `pkill` on the host does nothing and `docker exec ... ps` is not installed. Find it with `docker top p85_api` and `sudo kill -9 <pid>` -- the PID is in the host namespace. Restarting `ollama` alone does not help: the orphan simply issues the next request |
| An extraction shows no progress for its whole run | Expected today. `extract_jobs.run_extraction` captures the subprocess output and writes `uploads/logs/<paper>.log` only when it exits, so the file is absent mid-run. `docker top p85_api` confirms `main.py` is alive. Streaming the log instead is a known follow-up |
| A paper is stuck on `extracting` and every other paper is refused with 409 | The API restarted mid-run. `reap_stale_extractions()` clears this at startup for runs older than 3h; before that it clears nothing, so wait it out or append an `extraction_failed` entry to `queue.jsonl` by hand |
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
- **Two of the four CSV-path precision filters.** `Neo4jRAGSkeleton.query`
  gained the topic filter and the `score > 0` cut in G1 on 2026-10-28, which
  took off-topic evidence from 27 to 0 over the eight benchmark questions. It
  still lacks `filter_community_periods` and `group_responses`. Tracked in
  `../../NECTAR_MIGRATION.md`. **The deployed image predates G1** until the
  API is rebuilt.
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
