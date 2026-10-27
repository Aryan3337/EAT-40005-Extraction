# Nectar migration plan

Move P85 off Render + a laptop-hosted Ollama and onto one ARDC Nectar
instance, then hand it over.

**Deadline: ~9 Nov 2026.** Written 2026-10-26.

- **Why each architectural choice is what it is:** `NECTAR_MIGRATION.md`
- **How to launch and operate the box:** `deploy/nectar/README.md`
- **What this replaces:** `HOSTING.md`
- **Feature work deliberately NOT in this plan:** `NECTAR_BACKLOG.md`
- **Known gaps:** `KNOWN_LIMITATIONS.md`

---

## Scope

**This is a migration, not a rebuild.** No application code has to change.
Verified: every mention of Render, Tailscale or the tunnel under
`deploy/nectar/` is a comment explaining why it is *not* needed.

| | |
|---|---|
| Ollama | Moves from a laptop onto the box. The Funnel, `ollama_tunnel_proxy.py` and `OLLAMA_TUNNEL_SECRET` are **deleted, not ported** |
| AuraDB | Does not move. Same instance, same credentials |
| API | Same image, same `Dockerfile.serve` |
| Frontend | Same `flutter build web`, served by nginx instead of Render |
| Config | `is_private_host()` already accepts `ollama`, so no `TRUSTED_LLM_HOST`. `PORT=8000` replaces Render's injected `$PORT` |

One genuine blocker existed and is already fixed: `Dockerfile.serve` copied 5
of the 12 local modules `rag.py` imports, so the container died at
`rag.py:42` with `ModuleNotFoundError: No module named 'auth_store'`. Fixed
and pushed in `3bd363c`.

**What is NOT in this plan**, and why — both live in `NECTAR_BACKLOG.md`:

- **Extraction wired to the admin UI.** Has never worked on any deployment.
  New feature, not a migration step.
- **Entity canonicalisation and graph traversal.** Have never existed. New
  features.

Bundling those in made a day-and-a-half migration look like a fortnight of
risk. They are real work and worth doing — they are not worth blocking the
deployment on.

```
M1 ──> M2 ──┬──> M3
            ├──> P1
            ├──> P2
            └──> O1
   M2, P1, P2 ──> H1
```

Sizes are rough person-days for someone who knows this repo.

---

# Track M — Migrate

Owner: one person, needs Nectar dashboard access and the AuraDB credentials.
**~1.5 days.** This is the whole migration.

## M1 — Provision the instance

**Blocks:** everything · **Size:** 0.5 day · **Needs:** Nectar dashboard

**DONE 2026-10-27.** `p85-chatbot` is live: `m3.xlarge` in availability zone
**`swinburne-01`**, public IP **136.186.108.232**, key pair `p85-nectar`,
security group `p85-chatbot` (22 from one `/32`, 80 and 443 open), 20 GiB
volume `p85-data` mounted at `/mnt/data` by UUID with `ollama/` and
`uploads/`, OS fully patched, verified across a reboot. Three findings from
the real run are now in the runbook; re-read step 1 rather than this summary
if you are rebuilding.

Follow `deploy/nectar/README.md` steps 1–4, but **not in that numeric
order** — the wizard in step 1 selects a security group and a key pair, so it is
**2 → key pair → 1 → 3 → 4**. The numbers were kept so this file, `web/.gitkeep`
and the runbook's own troubleshooting table keep pointing at the right places.

**Three things the first real run established, all now in the runbook:**

| Finding | Why it matters |
|---|---|
| **Availability Zone must be `swinburne-01`**, set explicitly | With AZ = *Any* the launch dies: `Failed to allocate the network(s), not rescheduling`. This is a site allocation at Swinburne (`Associated Site: Swinburne`, `National funded: no`), so only that zone has a network. The volume must be in the same zone to attach |
| **There is no floating IP** | `Classic Provider` hands out the public IP at boot. The project has no router and no self-service network, so "Associate Floating IP" is not a step. The address is instance-bound: a rebuild changes it, invalidating the Flutter build's `API_BASE_URL` and P1's `<ip>.sslip.io` certificate |
| **`ubuntu` is not in the `docker` group** on this image | Every `docker compose` command in M2 fails on `/var/run/docker.sock` until `sudo usermod -aG docker ubuntu` and a reconnect. Compose itself is present as the v2 plugin |

**The three deviations this block used to list are landed in the repo**
(`d7c6851`, pushed 2026-10-27) — do not apply them by hand, and do not
"restore" what looks like a wrong figure:

| Was a deviation | Now |
|---|---|
| Volume 20 GiB, not 30 | Runbook step 3 says 20 GiB, with the reasoning inline |
| Open 443 as well as 80 | Runbook step 2's rule table has three rows |
| Mount `uploads/` onto the volume | `docker-compose.yml` carries both `UPLOADS_DIR=/app/uploads` and the `/mnt/data/uploads:/app/uploads` bind mount |

They moved into the repo because M2 deploys by `git clone -b dev`: a
correction a deployer has to remember under time pressure is a correction
that gets missed. The third was a real data-loss defect, not a precaution —
`rag.py:2206` defaults `UPLOADS_DIR` to a *relative* `"uploads"`, which under
`Dockerfile.serve`'s `WORKDIR /app` lands on the container's writable layer,
so `docker compose down` destroyed every admitted paper and the review queue.
Fixing it needed both halves plus a `/mnt/data/uploads` the runbook never
created alongside `/mnt/data/ollama`.

A companion walkthrough of these four steps, for whoever is at the dashboard:
https://claude.ai/artifact/6so53xdFn4z6kjJRP78prm

**Done when:** `ssh ubuntu@<instance-ip>` works, `findmnt /mnt/data` shows the
volume still mounted *after a reboot*, `/etc/fstab` has the `nofail` entry,
`df -h /mnt/data` shows 20 GiB, `/mnt/data` contains both `ollama/` and
`uploads/` owned by `ubuntu`, and `id -nG` includes `docker`. All verified
2026-10-27.

## M2 — Deploy against AuraDB

**Blocked by:** M1 · **Blocks:** M3, P1, P2, O1, H1 · **Size:** 0.5 day, plus
however long first-contact debugging takes

**DONE 2026-10-27.** All three containers Up, `mistral:7b` pulled onto the
volume, AuraDB reachable, the Flutter frontend built and uploaded, and
`http://136.186.108.232/` serving the app. The gate query returned real
triples with `sentence_ref`s and page numbers in **63s**, against a ~130s
budget. Every finding below is already written into
`deploy/nectar/README.md` -- re-read the runbook rather than this summary.

| Finding | Why it matters |
|---|---|
| **The verification `curl` in this plan and in the runbook was wrong** -- `/query` returns `401 Sign in is required.` without a bearer token | It fails in under a second, which reads like a broken API rather than a missing header. Register via `/auth/register` and pass `Authorization: Bearer <token>`. Both documents now carry the working sequence |
| **Chrome will not open `http://<instance-ip>`** | HTTPS-First upgrades the bare IP to `https://`, nothing listens on 443, and the visitor gets a connection error with no bypass to click through. `curl` gets 200 from the same address. This moves **P1 from parity work to whether the site is reachable at all** |
| **Accounts live in AuraDB; sessions live in API memory** | Accounts survive `docker compose down` and an instance rebuild with no volume involved. Tokens do not -- a rebuild signs everyone out. A test account is also a write to the production graph, so delete it afterwards |
| **`nginx.conf` works as written** | This was the plan's single largest untested item. It proxies `/health`, `/query` and the static bundle correctly on first run. No change needed |
| **An empty `web/` presents as a 403**, `directory index ... is forbidden` | Reads like an nginx permissions fault; it is only the missing frontend upload |

```bash
git clone -b dev https://github.com/Aryan3337/EAT-40005-Extraction.git
cd EAT-40005-Extraction/deploy/nectar
cp .env.example .env && nano .env     # four values, see below
docker compose up -d --build
docker compose exec ollama ollama pull mistral:7b
```

`.env` needs `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` and
`ADMIN_UPLOAD_SECRET`. The username variable is `NEO4J_USERNAME` —
`NEO4J_USER` fails as "Neo4j configuration is incomplete", which reads like a
missing credential rather than a misspelt variable name.

Then copy the frontend up per runbook step 6 — `flutter build web --release
--dart-define=API_BASE_URL=http://<instance-ip>` on a machine with Flutter,
then `scp` to `deploy/nectar/web/`. Manual for now; P2 fixes that. Left empty,
`API_BASE_URL` falls back to `http://127.0.0.1:8000`, which in a visitor's
browser means *their* machine.

**The two things this block called untested have now both been run, and
both worked unmodified:**

1. **`nginx.conf`** had been written against a Docker daemon that was down.
   It serves the static bundle and proxies `/health` and `/query` correctly
   on first run.
2. **AuraDB from this configuration.** The credentials and `config.py`'s TLS
   rule both work. Note the `.env` URI carries an explicit `neo4j+s://`, so
   `resolve_neo4j_uri`'s prepend branch is still unexercised.

**Done when** all three containers are `Up`, the site loads, and a query
returns real triples rather than a template fallback, in under ~130s. The
`/query` call needs a bearer token -- the runbook's step 5 has the register
-> query -> delete-the-account sequence. Expect 40s+ on CPU; the first call
also loads the model into RAM. **All verified 2026-10-27, at 63s.**

## M3 — Decommission Render

**Blocked by:** M2 (ideally P1) · **Size:** 0.5 day

**Redeploy Render once before killing it.** `3bd363c` fixed
`Dockerfile.serve`, which Render builds from — it had been copying 5 of 12
modules since 13 Oct, so Render has been serving a stale image or failing to
build. Its next build will change behaviour. Watch that deliberately rather
than discovering it as a surprise.

Then: delete the services, revoke any AuraDB credentials that existed only for
Render, remove the Render URLs from `README.md` and `HOSTING.md`, and leave one
line in `HOSTING.md` saying the architecture it documents has been replaced,
pointing at `NECTAR_MIGRATION.md`.

**Done when:** no Render service is live, and no doc in the repo points a
reader at a dead URL.

---

# Track P — Parity

Two capabilities Render provided for free that Nectar does not. These are
**regressions caused by the move**, which is why they are here and not in the
backlog. **~2 days.**

## P1 — TLS

**Blocked by:** M2 · **Size:** 0.5-1 day · **DONE 2026-10-27**

**The site is live and openable at https://136.186.108.232.sslip.io/.**
Certificate issued for that name, expiring 2027-01-25, renewing
automatically. All three gates below pass: a trusted chain with no
`-k`, `http://` redirecting, and `certbot renew --dry-run` succeeding.
Verified end to end in Chrome -- register, ask a question, grounded
answer with sources -- not just by `curl`.

What was built: a `listen 443 ssl;` block in `nginx.conf` with the
`location` blocks unchanged, an ACME-challenge block on 80 ahead of the
redirect, a `certbot` service renewing twice daily, a 6h nginx reload
loop so renewals are picked up, and `init-letsencrypt.sh` to break the
chicken-and-egg (nginx will not start without the certificate file that
nginx must be running to obtain).

| Decision | Why |
|---|---|
| **Staging run first, always** | `sslip.io` is **not** on the Public Suffix List, so Let's Encrypt counts every `*.sslip.io` certificate on the internet against ONE shared registered-domain limit. Retrying a misconfiguration against production burns a limit that is not ours alone. Staging proved the plumbing first; production then succeeded first try |
| **`--cert-name p85`, not the domain** | Puts the certificate at `live/p85/` instead of `live/<ip>.sslip.io/`. The IP is instance-bound, so otherwise a rebuild would change a path inside `nginx.conf`. Now a rebuild needs `init-letsencrypt.sh` re-run and nothing edited |
| **Domain derived from the instance's own IP** | Classic Provider puts the public address directly on `eth0` -- no NAT, no floating IP -- so `ip route get` yields it. One less thing to remember after a rebuild |
| **Certificates on `/mnt/data`** | Survive `docker compose down`, so a restart does not re-issue and walk into the shared rate limit |
| **No HSTS** | It is cached for its max-age and cannot be withdrawn, and this hostname derives from an IP a rebuild changes. Pinning a demo URL to https in every visitor's browser is a trap for whoever inherits this |

**The bare IP is still imperfect and that is now permanent.**
`https://<ip>/` is answered but with a name-mismatch warning, because the
certificate is for the sslip.io name. It is at least *clickable*, unlike
the pre-TLS refused connection. **Hand out the sslip.io URL.**

**Two findings worth more than the TLS work itself:**

1. **A `.git` directory was being served from the web root.** It rode
   along in a `tar`-based upload of the Flutter build -- the runbook's
   `scp build/web/*` glob skips dotfiles, a tar does not -- and a scanner
   pulled `/.git/config` within the hour. That repo turned out to hold one
   commit of public build artifacts, no source and no credentials, so the
   actual exposure was nil. It was removed, and `nginx.conf` now denies
   dotfiles with `/.well-known` exempted so renewal still works. Worth
   remembering that this repo's history has carried AuraDB credentials
   three times (`KNOWN_LIMITATIONS` 13) -- the same mistake with the main
   repo would not have been harmless.
2. **`nginx.conf` is a single-file bind mount, so editing it and
   reloading does nothing.** Any write that replaces the file -- `git
   pull`, `tar -x`, `scp`, `sed -i` -- creates a new inode while the
   container stays bound to the old one, and `nginx -s reload` reports
   success having re-read the unchanged file. Use `docker compose up -d
   --force-recreate web`. The certificate mounts are directory mounts and
   are unaffected, which is why renewal pickup works on a plain reload.

Render terminated TLS. Nectar does not, and the API serves `/auth/register`
and `/auth/login`, which accept passwords, plus `ADMIN_UPLOAD_SECRET` in a
request header. On port 80 all of that crosses the network in cleartext,
including over university wifi.

Use `sslip.io` so no DNS purchase is needed — `<instance-ip>.sslip.io` resolves
to the IP automatically. Then certbot in the `web` container, or an
`nginx:alpine` + certbot sidecar writing to a shared volume.

- Add a `listen 443 ssl;` server block to `deploy/nectar/nginx.conf`, keep the
  `location` blocks identical, redirect 80 → 443.
- Renewal must survive a reboot. A cert that expires 90 days after everyone
  graduates is worse than no cert, because the site breaks rather than degrades.
- `API_BASE_URL` becomes `https://<ip>.sslip.io`, so the frontend needs
  rebuilding after this lands.

**Bail-out:** if this fights you for more than a day, disable the auth
endpoints instead and ship without accounts. Shipping a login form over
cleartext is worse than shipping no login form. Record whichever you chose in
`HANDOVER.md`.

**Done when:** `curl https://<ip>.sslip.io/health` succeeds with a valid chain,
`http://` redirects, and `certbot renew --dry-run` passes. **All three verified
2026-10-27**, plus a full sign-in and question answered in Chrome.

## P2 — Reproducible frontend build

**Blocked by:** M2 · **Size:** 1 day · **DONE 2026-10-28**

Render built the frontend on push. On Nectar nothing does: `deploy/nectar/web/`
holds a `.gitkeep`, and the real artifact comes from `flutter build web` on a
laptop plus `scp`. A successor who rebuilds the instance gets an empty site.

Create `deploy/nectar/Dockerfile.web`: a Flutter SDK stage running
`flutter build web --release --dart-define=API_BASE_URL=$API_BASE_URL`, then
copy `build/web` into an `nginx:alpine` stage alongside `nginx.conf`. Replace
the `web` service's `image:` and bind mounts with a `build:` block passing
`API_BASE_URL` as an `args:` value.

This is the only option where the instance IP stops being something a human
has to remember to pass correctly.

**Done when:** `docker compose up -d --build` from a clean clone produces a
working site with no manual copy step, and the built JS contains the real
origin (`grep -r "sslip.io"` over the build output finds it).

**Done 2026-10-28, `62b1378`.** `deploy/nectar/Dockerfile.web` builds the
frontend from a pinned, sha256-checked Flutter 3.47.6 SDK taken from Google's
release bucket -- not a third-party SDK image, since
`ghcr.io/cirruslabs/flutter` has no 3.47.6 tag. `deploy/nectar/web/` is gone
and both bind mounts are off the `web` service: `nginx.conf` is baked in too,
which also retires the single-file-mount trap where an edit plus
`nginx -s reload` silently did nothing.

Evidence: the image built on the instance first try (SDK checksum passed,
`flutter build web` 52.5s), `grep -rl sslip.io /usr/share/nginx/html` inside
the running container finds `main.dart.js`, and the served bundle is
**2,957,851 bytes** -- the same size as the laptop build it replaces.
`API_BASE_URL` now lives in `.env`; compose refuses to start without it and
the Dockerfile checks again, because an *empty* value is the dangerous one
(the site loads and silently calls the visitor's own machine).

A cold build fetches ~1.5GB of SDK; a source-only rebuild reuses that layer,
and a change to `nginx.conf` alone takes seconds because its COPY is in the
final stage.

**What it does not solve.** The instance's IP is still a value a human has to
keep in step -- in `.env` and in the certificate name -- because there is no
floating IP on this allocation. The build removes the *upload*, not the
address. Pointing the frontend at its own origin at runtime (making
`API_BASE_URL` unnecessary) would, and is in `NECTAR_BACKLOG.md` territory,
not here.

---

# Track O — Optional

## O1 — CSV fallback override

**Blocked by:** M2 · **Size:** 0.5 day · **Cut this first if time is short**

Honest framing: this is an **addition**, not a migration step or a parity fix.
Render runs `--neo4j` too, so CSV mode was never live anywhere — it was a
locally rehearsed fallback. It earns its place only because
`KNOWN_LIMITATIONS.md` §20 calls `ConceptRetriever` "the rehearsed fallback for
when AuraDB is unavailable", and under `--neo4j` that fallback currently needs
a compose edit and a rebuild to reach.

Create `deploy/nectar/docker-compose.csv.yml` overriding only the `api`
service's `command:` — `--serve --host 0.0.0.0` plus `--kg` for **all twelve**
`data/production_graph/*_kg_refined.csv` files. Seven files load 72 of 112
triples; the other five landed 8 Oct in `35a61eb`/`f2fb3bb`.

```bash
docker compose -f docker-compose.yml -f docker-compose.csv.yml up -d
```

**Document the limitation plainly:** this answers questions. It does not log
anyone in. Users, feedback and conversation history all live in AuraDB
(`auth_store.py`), so auth, `/feedback` and `/history` are dead in CSV mode.
A degraded read-only mode, not a hot spare.

**Done when:** the command above serves a real answer with AuraDB credentials
removed from `.env`, and the startup log says `Loaded 112 triples`.

---

# Track H — Handover

The actual deliverable, and the reason the project exists in this form.
**~4 days. Write these as the other tracks land**, not at the end — a handover
written in the final two days is a list of things someone half-remembers.

## H1 — Reconcile the runbook with reality

**Blocked by:** M2, P1, P2 · **Size:** 1 day

Every surprise found during M2 goes into `deploy/nectar/README.md`'s
troubleshooting table. Delete anything the deployment no longer does.

**Done already, 2026-10-27** — a docs pass ahead of M1 cleared most of this
block, so what is left is genuinely only what M2 teaches:

- Runbook's 30 GiB figure corrected to 20, with the reasoning inline.
- `NECTAR_MIGRATION.md`'s verification section updated: the AuraDB credentials
  are confirmed working, and the stale 697/715/670 graph figures are replaced
  everywhere they appeared (`NECTAR_MIGRATION.md`, `NECTAR_BACKLOG.md`,
  `deploy/nectar/README.md`).
- `NEO4J_USERNAME` corrected in `.env.example`, the runbook, the main
  `README.md` and the troubleshooting table — it is **not** `neo4j`.
- The runbook's "HTTPS needs a DNS name" line corrected; P1's `sslip.io`
  approach needs none.
- Test baseline corrected from a figure that never ran to 473/9/0.

**Closed by M2, 2026-10-27:** `nginx.conf` has now been runtime-tested and
works unmodified -- it proxies `/health`, `/query` and the static bundle on
first run. The deployment's largest untested item is gone.

**Still open:** nothing exercises `config.py`'s `resolve_neo4j_uri` prepend
branch, because the `.env` URI already carries an explicit `neo4j+s://`.

**Added by M2**, already written into the runbook and listed here so H1
does not rediscover them: the `/query` bearer-token requirement, Chrome's
HTTPS-First refusal of the bare IP, the in-memory session lifetime, and
the empty-`web/` 403.

**Have someone who did not do Track M follow the runbook on a fresh instance.**
It is the only real test of a runbook, it is cheap against 4000 SU, and it is
the difference between a document that reads correctly and one that works.

## H2 — The handover document

**Size:** 1.5 days · Extends the existing `HANDOVER.md`

- **Credentials inventory:** every secret the system needs, where it lives, who
  holds it, how to rotate it. `KNOWN_LIMITATIONS.md` §13 records that AuraDB
  credentials have been committed three times. Do not make it four.
- **Accounts the system depends on.** §13 already says these should belong to a
  shared team account rather than a personal one, so access outlives the
  handover.

  **Decided 2026-10-27, not yet done:** that shared account is
  `s2026_eat40006_p85@outlook.com`. It serves two separate purposes that are
  easy to conflate, so name both in the inventory:

  1. **The site's admin account** — the `:User` node with `role: 'admin'`.
     Today that node's `email` property is the literal string `mandiadmin`,
     which is not an address and cannot have come from `register()`: both the
     current and the pre-2026-10-27 validator reject a value with no `@`, so it
     was written by hand in Cypher. Migrating it to the real address is a
     property rename on one node plus a fresh password hash. The address is a
     valid email, so `_normalise_email` accepts it and nothing else has to
     change.
  2. **The login for the AuraDB console**, which is where `NEO4J_URI`,
     `NEO4J_USERNAME` and `NEO4J_PASSWORD` are read and rotated.

  Distinct from both: `NEO4J_USERNAME` is the **database** credential
  (`6ba8a37e`, the instance id — see `deploy/nectar/.env.example`). It grants
  no privilege in the application. Three different things called "admin" and
  no reader should have to work out which is which.
- **The site's address, and who can change it.** The site is served at
  `https://136.186.108.232.sslip.io/`. That name is not bought, owned or
  configured by anyone: `sslip.io` is a public service that resolves any
  `<ip>.sslip.io` to that IP, chosen during P1 specifically so the project
  would not have to buy DNS. It works, and it is free, and it is ugly, and
  **it embeds the instance's IP address**, so rebuilding the VM changes the
  URL.

  **Raised 2026-10-27 and deliberately left to the client.** A real name
  (`garochatbot.com` or similar) is roughly 30 minutes of work -- see H4 --
  but it is an ongoing cost and an ongoing renewal obligation, and the
  question is not the ~AU$15/yr, it is who holds it in five years. A domain
  registered to a student's personal account expires once that student has
  graduated, which is §13's failure mode with a new coat of paint. Two
  routes, and they are not equivalent:

  | Route | Owner | Cost | Who can start it |
  |---|---|---|---|
  | **Subdomain of `swin.edu.au`** | Swinburne, institutionally | free | **Only Swinburne IT.** A student cannot self-assign one. Fold it into the H3 conversation about an SSH CIDR -- one request, two answers |
  | **Public domain, e.g. `garochatbot.com`** | whoever registers it | ~AU$15-20/yr | Anyone with a card. Not gated by the university -- the reason to go slowly is ownership, not access. Register to the shared project account, never a personal one |

  `garochatbot.com`, `.org`, `.net` and `mandichatbot.com` all had no DNS
  records on 2026-10-27, so they were almost certainly unregistered.

  **Until this is decided the sslip.io URL is the real address and the
  handover must say so plainly**, rather than leaving a successor to
  wonder whether a domain was lost.
- **SU economics:** 0.457 SU/hr, ~1 year on 4000 SU, where to check
  consumption, and that shelving is the only thing that actually stops the
  burn. The shelve-vs-shutoff question is still open with Nectar support —
  **put it to them in writing this week**; the answer belongs in this document,
  not in an expiry notice next March.
- **What is deliberately not built**, with reasons: no HTTPS if P1 bailed out,
  no streaming, no GPU, single-hop retrieval, extraction CLI-only, TTS and
  local translation unavailable in the serve image. Point at
  `NECTAR_BACKLOG.md`.
- **An operational runbook for staff**, who will not be developers: how to
  restart, where logs live, what a failure looks like, who to contact.

## H3 — SSH and access

**Size:** 0.5 day

`deploy/nectar/README.md` says port 22 from "your IP /32". Correct security,
dead end for a handover — nobody else can get in, and the IP changes.

One `/32` rule per team member, each with their own key pair, or the Swinburne
VPN range as a single CIDR if IT publishes one — **ask IT, do not guess a
range.** Then confirm at least two people besides the original owner can
actually SSH in, verified by them doing it rather than by the rule existing.

A key pair that exists only on one laptop is the same failure mode as a
password only one person knows.

## H4 — Specs for the work not being done

**Size:** 1 day

Written specs, not aspirations, so a successor can pick any of them up cold.
The measurements that justify them are in `NECTAR_BACKLOG.md` — H4 is the
reader-facing summary, the backlog is the detail.

**Give the site a real domain.** Smallest item here by a distance, and the
only one a non-developer can mostly action. P1 was built so this is a
configuration change rather than a code change: `nginx.conf` contains no
domain at all (`server_name _`, certificate at `live/p85/` via
`--cert-name`), and `init-letsencrypt.sh` takes the domain as its first
argument, falling back to deriving `<ip>.sslip.io` only when none is given.

Once the name exists and an **A record points it at the instance's IP**:

```bash
cd ~/EAT-40005-Extraction/deploy/nectar
STAGING=0 FORCE=1 LETSENCRYPT_EMAIL=s2026_eat40006_p85@outlook.com \
    ./init-letsencrypt.sh garochatbot.com

# then, on a machine with Flutter:
cd flutter_application
flutter build web --release --dart-define=API_BASE_URL=https://garochatbot.com
scp -i ~/.ssh/p85_nectar -r build/web/* \
  ubuntu@<instance-ip>:~/EAT-40005-Extraction/deploy/nectar/web/
```

The Flutter rebuild is **not optional**: `API_BASE_URL` is compiled into
the bundle, so a page served from the new domain would otherwise still
call the old origin and every request would fail.

**The real argument for this is not cosmetic.** The current URL contains
the instance's IP, and that IP is instance-bound -- Nectar's Classic
Provider assigns it at boot and there is no floating IP to reattach (M1).
So today, rebuilding the VM changes the site's address, invalidates the
certificate and forces a frontend rebuild. With a real domain, a rebuild
is one DNS record edit. It converts the most fragile thing about this
deployment into a routine operation.
**Rank streaming first.** Every Ollama call sets `"stream": False`
(`rag.py:405`, `:1585`, `:1713`, and `confidence_framework.py:303`) and
`nginx.conf` sets `proxy_buffering on`, so a 40s answer is 40s of blank screen.
Streaming makes the same generation start producing text in about two seconds.
It is a contained three-surface change — `rag.py`'s synthesis call, the nginx
buffering config, the Flutter client — with the largest perceived-quality
payoff available, and it costs nothing in compute. If a successor builds one
thing, this is it.

---

## Sizing and parallelism

| Track | Size | Can start | Needs |
|---|---|---|---|
| M — Migrate | ~0.5 d left | M1+M2 **done**; only M3 remains | Nectar dashboard, Render access |
| P — Parity | ~1 d left | P1 **done**; only P2 remains | Flutter, Docker |
| O — Optional | 0.5 d | after M2 | — |
| H — Handover | ~4 d | alongside | whoever did the work |

**~8 person-days against a ~14-day calendar.** That fits for two people, and
comfortably for three. The natural split:

- **One person on M, then H1 and H3.** Must be whoever has dashboard access.
- **One person on P**, starting the day M2 lands. P1 and P2 are independent of
  each other and can be split again if someone is free.
- **H2 and H4 are writing, not coding** — the best fit for whoever is least
  comfortable in the codebase, provided they interview the people who did each
  track rather than guessing.
- **Anyone with spare capacity goes to `NECTAR_BACKLOG.md`**, starting with
  G1 (the `matches_topic` port), which is the only backlog item that improves
  answer quality for users and needs no instance access.

**If it does not all fit, cut in this order:** O1, then P2 (manual `scp` per
runbook step 6 still works), then P1's TLS **only** by also disabling the auth
endpoints. **Never cut Track H.** A deployed system nobody can operate is not a
handover.

---

## Verification gates

Before anything is called done:

- `python -m pytest tests/ -q` — **473 pass / 9 fail / 0 collection errors**
  is the known-good baseline as of 2026-10-27. The 9 are all
  `tests/test_rag_languages.py`, pre-existing. A tenth failure is a
  regression, not noise.

  This figure replaces the **451 / 9 / 2** recorded when this plan was
  written, and the old one was not measurable: `test_auth_store.py`'s
  collection error aborted collection for the whole suite, so the documented
  command ran **zero tests** and exited 1. Reading it through `| tail` hid
  the exit code and it looked like a pass. Fixed in `tests/test_auth_store.py`
  — the file had been asserting a registration feature reverted on 15 Oct.
  `test_insert.py` no longer errors either; it does not need live Neo4j.

  **No migration block in this plan changes Python code**, so this baseline
  should not move for M, P or O work.
- A real `/query` through nginx returns graph-backed triples, not a template.
- The runbook followed end to end on a fresh instance by someone who did not
  write it.
