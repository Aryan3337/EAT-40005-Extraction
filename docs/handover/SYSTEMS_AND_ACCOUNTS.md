# Systems and accounts — P85 Mandi/Garo chatbot handover

*Written 29 October 2026 for the handover on 30 October 2026. Every system
this project depends on, who holds it today, and what has to change hands.
Companion documents: [`SSH_ACCESS_SETUP.md`](SSH_ACCESS_SETUP.md) and
[`LIMITATIONS_SUMMARY.md`](LIMITATIONS_SUMMARY.md).*

---

> ## ⚠ Read before filling this in
>
> **This file contains no secrets and must stay that way.** It is tracked in
> git, and this project has already committed live credentials three times
> (`KNOWN_LIMITATIONS.md` §13). Do not make it four.
>
> To record the real values, **copy this file out of the repository first**:
>
> ```
> docs/handover/SYSTEMS_AND_ACCOUNTS.filled.md     ← already gitignored, local only
> ```
>
> Better still, put the values in whatever password manager the team or
> Swinburne already uses and keep this document as the *map* of what exists
> and where it lives. A list of secrets in a Markdown file is a one-time
> convenience and a permanent liability.
>
> Placeholders below are written as `__________`. Leave them empty in the
> tracked copy.

---

## 1. The short version — what must change hands

| # | System | Who holds it today | Must be held by | Blocking? |
|---|---|---|---|---|
| 1 | **Server SSH access** (the VM) | Marcus only — one key | Afzal + 1 backup | **Yes — do it live Friday** |
| 2 | **Console break-glass password** | Nobody — not set | The team's shared store | **Yes — one command, Marcus** |
| 3 | **Neo4j AuraDB console** | Personal account | Shared project account | **Yes — the graph lives here** |
| 4 | **Nectar dashboard** | 6 people, 3 tenant managers | Already fine | No |
| 5 | **GitHub repository** | `Aryan3337` (personal account) | Afzal must have admin | **Yes** |
| 6 | **Shared project account** (`s2026_eat40006_p85@outlook.com`) | Created, password on the server | Afzal | **Yes** |
| 7 | **Site admin login** (the chatbot's own admin) | `mandiadmin` + the shared account | Afzal | Yes |
| 8 | **`deploy/nectar/.env`** — all server secrets | On the VM only, one copy | Backed up off the VM | **Yes** |
| 9 | **Render.com** (old hosting, still live) | Marcus | Delete it | Yes — see §11 |
| 10 | Tailscale (legacy LLM tunnel) | Marcus | Nobody — retire it | No |
| 11 | Let's Encrypt / sslip.io | No account needed | — | No |
| 12 | Jira / project board | Team | Afzal | No |

---

## 2. Neo4j AuraDB — the knowledge graph

**This is the single most important credential in the project.** The graph —
112 verified facts and the verbatim source sentences behind them, plus every
registered user account and all stored feedback — lives here, not on the
server. The server is replaceable; this is not.

```
Console URL:    https://console.neo4j.io/
Console login:  __________________________________   (email)
Console pass:   __________________________________
Account owner:  __________________________________   ← see warning below
Instance name:  __________________________________
Instance tier:  __________________________________   ← CHECK THIS, see below
Region:         __________________________________

Connection values, as they appear in deploy/nectar/.env:
  NEO4J_URI       6ba8a37e.databases.neo4j.io        (instance id is 6ba8a37e)
  NEO4J_USERNAME  6ba8a37e                           ← NOT "neo4j". See below
  NEO4J_PASSWORD  __________________________________
```

### Three things that are easy to get wrong here

**`NEO4J_USERNAME` is `6ba8a37e`, not `neo4j`.** It is the same 8-hex string
as the instance id. It reads exactly like a copy-paste mistake and it is not
one — verified against the live database on 27 Oct 2026: `neo4j` fails with
`Neo.ClientError.Security.Unauthorized`. **Do not "correct" it.**

**Do not rotate or revoke this password casually.** AuraDB gives this product
one single built-in database user — that *is* `6ba8a37e`, and it is the same
credential the live site uses. Rotating it takes **production down** unless
`deploy/nectar/.env` is updated and the `api` container restarted in the same
window:

```bash
ssh -i <key> ubuntu@136.186.108.232
cd ~/EAT-40005-Extraction/deploy/nectar
nano .env                    # paste the new NEO4J_PASSWORD
docker compose restart api   # no rebuild needed for a config-only change
curl -s -o /dev/null -w '%{http_code}\n' https://136.186.108.232.sslip.io/
```

**Check which Aura tier this instance is on, and write it above.** It decides
whether the database can pause or be deleted on you. If it is a free tier,
Neo4j's own policy pauses an idle instance after a few days and deletes it
after extended inactivity — which over a quiet summer would mean losing the
graph. The CSVs in `data/production_graph/` are a complete, re-loadable copy
of the 112 facts (`load_production_graph.py`), so the *facts* are safe in git
— **but user accounts and feedback exist only in AuraDB and have no backup
anywhere.** If the tier can pause, either move to a paid tier or add a
periodic export; see `LIMITATIONS_SUMMARY.md` §A3.

### Ownership

`.env.example` and `KNOWN_LIMITATIONS.md` §13 both record the decision that
this account should be the shared project account rather than a personal one,
*so that access outlives the handover*. **That migration was decided on
27 Oct and has not been done.** It is on the Friday list.

---

## 3. The shared project account — the "service account"

```
Address:   s2026_eat40006_p85@outlook.com
Password:  __________________________________
MFA / recovery method and where its codes live:
           __________________________________
```

Created so that no system the project depends on hangs off a student's
personal login. **It exists and is in partial use.** Where it is already
used:

| Used for | State |
|---|---|
| Let's Encrypt registration email (TLS certificate notices) | **Done** — see §7 |
| A `role: 'admin'` `:User` node on the chatbot itself | **Done** 28 Oct — password was generated on the server and written to `/mnt/data/admin_pw.txt` (mode 600). **Replace it with one you choose.** |
| The AuraDB console login | **Not done** — §2 |
| GitHub repository ownership | **Not done** — §5 |

Three different things are called "admin" on this project and conflating them
wastes real time, so to be explicit:

1. **The site's admin** — a `:User` node in Neo4j with `role: 'admin'`. Logs
   into the chatbot and can upload/review papers. (§6)
2. **The AuraDB console login** — where the three `NEO4J_*` values are read
   and rotated. (§2)
3. **`NEO4J_USERNAME` = `6ba8a37e`** — a *database* credential. Grants no
   privilege in the application at all. (§2)

---

## 4. Nectar Research Cloud — the hosting

No credential to hand over: login is **Swinburne/AAF single sign-on**, and
access is project membership rather than a shared password.

```
Dashboard:        https://dashboard.rc.nectar.org.au/
Project name:     P85 2026 Mandi knowledge chatbot
Project ID:       39543965fbe54d1ca3794f8b4a184806
Allocation:       19 Oct 2026  →  19 Oct 2027     ← renewal is a diary item
Allocation contact / owner:  achowdhary@swin.edu.au
Approver:         pwolynec@swin.edu.au
Budget:           4000 SU   (m3.xlarge burns 0.457 SU/hr ≈ 1 year at 24/7)
```

**Instance, as built:**

```
Name:             p85-chatbot
Flavour:          m3.xlarge   (16 vCPU / 32 GB)
Image:            NeCTAR Ubuntu 22.04 LTS (Jammy) amd64 (with Docker)
Availability zone: swinburne-01          ← a launch with AZ=Any FAILS
Public IP:        136.186.108.232        (no floating IP — instance-bound)
Public URL:       https://136.186.108.232.sslip.io/
Security group:   p85-chatbot  — 22 from one /32, 80 and 443 from anywhere
Volume:           p85-data, 20 GiB, ext4, mounted at /mnt/data
                  UUID 65154101-0e0f-484d-87d4-0f0189148892
```

**Membership: six people, three of them tenant managers.** Read the current
list from *Identity → Projects → Members* rather than trusting a copy —
members change and a copy goes stale. Deliberately not written here: the
individual addresses are personal data.

Two things about that membership that matter for handover:

- **Five of six are `@student.swin.edu.au`** and lapse at graduation.
  `achowdhary@swin.edu.au` is the only staff account — the durable anchor.
- Six people can click **Rebuild**, which sits beside *Reboot* and destroys
  the URL, the certificate, the SSH keys and `.env`. Everyone with dashboard
  access needs to know this. Reboot is safe; rebuild is not.
  ([`SSH_ACCESS_SETUP.md`](SSH_ACCESS_SETUP.md) has the full list of what it
  costs.)

---

## 5. GitHub — the code and its history

```
Repository:  https://github.com/Aryan3337/EAT-40005-Extraction
Owner:       Aryan3337    ← a personal student account, not an organisation
Default branch: main      ← NOT the working branch, see below
Working branch: dev
Afzal's GitHub username:  __________________________________
Admin/owner access after handover:  __________________________________
```

**Two risks here, both worth raising in the room:**

1. **The repository lives under one student's personal account.** When that
   account goes, so does the project's canonical copy and every permission
   grant on it. The durable fix is a Swinburne-owned GitHub organisation (or
   at minimum transferring ownership to the shared project account), with
   Afzal as an owner. Decide this on Friday even if it is actioned later.
2. **`main` is not the working branch.** `main` and `dev` have diverged in
   both directions (`KNOWN_LIMITATIONS.md` §14); anyone cloning the default
   branch gets the *pre-verification* pipeline, with no fact-checking gates.
   **Clone `dev`:**

   ```bash
   git clone -b dev https://github.com/Aryan3337/EAT-40005-Extraction.git
   ```

   The runbook's deploy step says `-b dev` for the same reason.

Current state of `dev` as handed over: local, `origin/dev` and the **running
server are all on `1692bc8`**, suite **577 passed / 0 failed** plus **103
Flutter tests**. There is no split to reconcile — a condition worth
re-checking rather than assuming, because it has been untrue twice in this
project's history and both times something looked deployed that was not:

```bash
# on the server
cd ~/EAT-40005-Extraction && git rev-parse --short HEAD
docker exec p85_api sha256sum /app/rag.py && sha256sum rag.py   # must match
```

The second line is the one that matters. The first only tells you what is on
the server's disk; a container keeps running the image it was built from, so
a `git pull` with no rebuild leaves the two disagreeing silently.

---

## 6. The chatbot's own accounts (stored in Neo4j)

Real server-side accounts now: `POST /auth/register`, salted PBKDF2-SHA256
password hashes (310,000 rounds) as `:User` nodes in AuraDB, opaque in-memory
session tokens. **Five live accounts as at 29 Oct 2026, 21:00: two admins
and three teammates' own logins.**

Only the two admin accounts below are part of the handover. The teammate
logins are deliberately not listed here — they are personal data, they
change without warning (one disappeared and two appeared in the 24 hours
before handover), and nobody needs to inherit them. **Read the current
list live** from the admin dashboard (*Users*, or `GET /admin/users`);
never treat a list in a document as current.

| Admin account | Note |
|---|---|
| `mandiadmin` | Legacy. Not an email address — written by hand in Cypher, predates the validator. **To be retired** once the shared account is confirmed working |
| `s2026_eat40006_p85@outlook.com` | Created 28 Oct. Password in `/mnt/data/admin_pw.txt` (mode 600) — replace it |

Before pruning any `user` account, ask the team who it belongs to.
Deleting one destroys that person's saved conversations and feedback,
and at least one current login is a bare-looking address that could
easily be mistaken for a test account but has not been confirmed as one.

```
Admin login to hand over:  s2026_eat40006_p85@outlook.com
Password:                  __________________________________
```

Reset or create an admin without putting anything in a file or a chat log:

```bash
python bootstrap_admin.py       # interactive; writes a salted hash to Neo4j
```

Anyone can self-register as a normal user from the site — teammates and the
client do not need accounts issued to them.

> **Session tokens are in memory**, so any API restart or rebuild signs
> everyone out. Expected, not a fault — but warn people before a deploy.

---

## 7. Server-side secrets — `deploy/nectar/.env`

**One copy exists, on the VM's root disk, and it is the only irreplaceable
thing not on the persistent volume.** A dashboard *Rebuild* destroys it.
Template and the reasoning for each value: `deploy/nectar/.env.example`.

```
Location:  /home/ubuntu/EAT-40005-Extraction/deploy/nectar/.env
Backup:    __________________________________   ← there is none today. Make one.
```

| Variable | What it is | Value |
|---|---|---|
| `NEO4J_URI` | Aura hostname; `neo4j+s://` is prepended automatically. An unencrypted URI to a remote host is **refused** — the graph holds verbatim paper text | `6ba8a37e.databases.neo4j.io` |
| `NEO4J_USERNAME` | `6ba8a37e` — not `neo4j` (§2) | `6ba8a37e` |
| `NEO4J_PASSWORD` | From the Aura console | `__________` |
| `ADMIN_UPLOAD_SECRET` | Gates every `/admin/*` route. **The only real access control on paper upload.** Must also be typed into the admin UI's secret prompt | `__________` |
| `TRANSLATION_PROVIDER` | `local` = NLLB-200-600M on this box (the correct setting). `llm` = mistral:7b, the no-rebuild fallback. `online` would send paper-derived text to a third party — **do not** | `local` |
| `API_BASE_URL` | **Build-time**, compiled into the Flutter bundle. Changing it needs `docker compose up -d --build web`. An *empty* value is worse than a missing one | `https://136.186.108.232.sslip.io` |

Generate a new shared secret when you need one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Back this file up on Friday.** Copy it to the persistent volume *and* to
wherever the team keeps shared credentials:

```bash
sudo cp /home/ubuntu/EAT-40005-Extraction/deploy/nectar/.env /mnt/data/env.backup
sudo chmod 600 /mnt/data/env.backup
```

A pre-translation-switch copy already exists beside it as
`.env.backup-pre-nllb`.

---

## 8. TLS certificate and the site's address

**No account and no credential — and nothing is bought or owned.**
`sslip.io` is a free public DNS service that resolves any `<ip>.sslip.io` to
that IP; it was chosen so the project would not have to buy a domain.

```
Site:              https://136.186.108.232.sslip.io/
Certificate:       Let's Encrypt, --cert-name p85, expires 2027-01-25
Renewal:           automatic (certbot container, restart: unless-stopped)
Registration email: s2026_eat40006_p85@outlook.com
Certificates live on the volume, so they survive a rebuild.
```

Two consequences to state at handover:

- **The URL embeds the IP**, so a rebuilt VM gets a different address and
  every link breaks. There is no floating IP on this allocation.
- **If a certificate ever has to be reissued, run `init-letsencrypt.sh`
  staging-first.** `sslip.io` is not on the Public Suffix List, so every
  `*.sslip.io` name in the world shares one Let's Encrypt rate limit — a
  careless retry loop can lock the project out of issuance for a week.

A real domain (`garochatbot.com` or similar) is about 30 minutes of work and
was deliberately left to the client: the question is not the ~AU$15/yr, it is
who holds the registration in five years.

```
Decision on a permanent domain:  __________________________________
```

---

## 9. Local development machine (only for extraction work)

Nothing to hand over as a credential, but nothing works without it. Running
the extraction pipeline, or the test suite, needs:

```
Python 3.x + requirements.txt
Ollama, locally installed, with the models pulled:
    mistral:7b        (chat/synthesis and the fallback translator)
    deepseek-r1:7b    (extraction)
```

**This is a hard project constraint, not a preference.** The project
committed to its supervisor that paper content and human-collected material
go to a **local** model only, never to a third-party provider.
`llm_endpoint.py` enforces it by refusing an endpoint outside our own
network. `ALLOW_EXTERNAL_LLM=1` overrides it — that override is a governance
decision, not a configuration detail.

Extraction costs roughly **1.2 hours of local model time per paper**, and
re-extracting the whole corpus is about 3.4 hours.

---

## 10. Tailscale (legacy — retire it)

The hosted site used to reach a model running on Marcus's laptop through a
Tailscale Funnel, guarded by `OLLAMA_TUNNEL_SECRET`. **The Nectar deployment
replaced this** — Ollama and NLLB both run on the VM now, and neither
`TRUSTED_LLM_HOST` nor `OLLAMA_TUNNEL_SECRET` appears in the server's `.env`.

```
Tailscale account:  Marcus's personal account
Action:             nothing to hand over; retire the account from the project
```

`scripts/tunnel_on.sh` / `tunnel_off.sh` and the `HOSTING.md` instructions
remain in the repo for local development only. `HOSTING.md` carries a
SUPERSEDED banner.

---

## 11. Render.com — old hosting, STILL LIVE, must be deleted

**This is an open action, not history.** It was decided on 28 Oct to take
Render down. The repository half is done — nothing in git recreates the
services and no document tells the inheritor that hosting is Render. **The
dashboard half needs Marcus's Render account and has not been done.**

Re-verified **29 Oct 2026**: the old API still answers, and
`POST /query` returns **200 with no authentication at all**, where Nectar
correctly returns 401 for the same request. It is serving a build from before
answer translation existed.

```
Render account:  Marcus's personal account
Services to delete:
    eat-40005-extraction      (API)   https://eat-40005-extraction.onrender.com
    eat-40005-extraction-1    (site)  https://eat-40005-extraction-1.onrender.com
```

Steps:

1. Delete both services in the Render dashboard.
2. Confirm both URLs stop answering.
3. **Remove any GitHub deploy hook**, so a future push cannot silently
   resurrect it. (Verified 29 Oct that the last push did *not* redeploy it —
   its `/query` still returns the old response keys — so no hook appears to
   be firing, but check and remove it anyway.)

> **Do not revoke the AuraDB credential as part of this.** The earlier plan
> assumed Render had its own database user. It does not — `6ba8a37e` is the
> single built-in user that the live Nectar site also uses, so revoking it
> takes **production** down (§2).

---

## 12. Project tracking and documentation

```
Jira / board URL:       __________________________________
    (the team's SCRUM project; `jira_import.csv` and `jira_import_nectar.csv`
     in the repo are importable backlogs of the remaining work)
Google Drive / Teams folder:  __________________________________
Client / community contact (sign-off):  __________________________________
Supervisor:             Afzal Azeem Chowdhary  <achowdhary@swin.edu.au>
```

The authoritative documentation is in the repository, on `dev`:

| Document | What it is for |
|---|---|
| `HANDOVER.md` | The plain-English project overview, written for a non-technical reader. **Owned by a teammate** — it was last substantively written 8 Oct, so some figures in it are superseded by the ones here |
| `docs/handover/SYSTEMS_AND_ACCOUNTS.md` | This file |
| `docs/handover/SSH_ACCESS_SETUP.md` | Granting server access |
| `docs/handover/LIMITATIONS_SUMMARY.md` | The limitations, summarised for a handover conversation |
| `KNOWN_LIMITATIONS.md` | The long technical version — 31 entries, each with the measurement and the command that produced it |
| `deploy/nectar/README.md` | The deployment runbook: launch, volume, deploy, TLS, access, troubleshooting |
| `NECTAR_IMPLEMENTATION_PLAN.md` | Migration and handover work, with what is done and what is not |
| `NECTAR_BACKLOG.md` | Feature work, no deadline attached |
| `NECTAR_MIGRATION.md` | Why Nectar, why m3.xlarge, why AuraDB — the decision record |
| `README.md`, `PRUNER_README.md`, `LOCAL_TRANSLATION_SETUP.md` | Component-level detail |

---

## 13. Friday checklist, in the order that de-risks fastest

- [ ] **Set the console password** (`sudo passwd ubuntu`), check `passwd -S` says `P`, test it once from the dashboard console, store it in the shared store. *One command, needs nobody else.*
- [ ] **Add Afzal's SSH key, and a second holder's**, and have each of them log in themselves — [`SSH_ACCESS_SETUP.md`](SSH_ACCESS_SETUP.md). Remember port 22 is open to one `/32` today.
- [ ] **Back up `deploy/nectar/.env`** to `/mnt/data/` and to the shared credential store. It is the only irreplaceable thing on the root disk.
- [ ] **Hand over the shared project account** (`s2026_eat40006_p85@outlook.com`) with its password and recovery method.
- [ ] **Migrate the AuraDB console login** to that account, and record the tier.
- [ ] **Give Afzal admin on the GitHub repository**, and agree where the repo should permanently live.
- [ ] **Replace the generated site-admin password** in `/mnt/data/admin_pw.txt` with one Marcus chooses, confirm login, then retire `mandiadmin`.
- [ ] **Delete the two Render services** and any deploy hook. Do *not* touch the AuraDB credential.
- [ ] Record the Jira/board URL and the client contact above.
- [ ] Agree who diarises the **allocation renewal on 19 Oct 2027** and the certificate's auto-renewal check.
- [ ] Walk the three unpushed commits (`9301fc2`, `b1815f3`, `1943bcc`) to `origin/dev` so nothing of the handover work exists only on one laptop.

---

*No real passwords, keys or secret values belong in this document, in the
code, or anywhere else that gets published.*
