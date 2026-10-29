# Giving Afzal SSH access to the P85 server

*Written 29 October 2026, for the handover session on Friday 30 October.
Companion documents: [`SYSTEMS_AND_ACCOUNTS.md`](SYSTEMS_AND_ACCOUNTS.md) and
[`LIMITATIONS_SUMMARY.md`](LIMITATIONS_SUMMARY.md). The full deployment
runbook is `deploy/nectar/README.md`.*

---

## What this is, and why it has to happen live

The chatbot runs on one Nectar virtual machine:

```
https://136.186.108.232.sslip.io/     the site visitors use
ubuntu@136.186.108.232                the machine itself, SSH only
```

The machine accepts **public-key SSH and nothing else**. There is no SSH
password, no root login, and (as at 29 Oct) no console password. **One key
exists, on one laptop.** Until a second key is added, exactly one person can
change anything on the server.

| Door | State as at 29 Oct 2026 |
|---|---|
| SSH password | `PasswordAuthentication no` |
| Root over SSH | `PermitRootLogin no` |
| Nectar dashboard console | `ubuntu` password **locked** — nothing to type |
| SSH key | the only route in |

**This cannot be done from the Nectar dashboard.** Importing a key pair there
does nothing to a machine that is already running — OpenStack injects key
pairs at launch only. The only way to grant access to a live instance is to
edit `~/.ssh/authorized_keys` on it, which means someone who already has
access has to do it. That is why it is a live step in the handover session
and not something that could be prepared last week.

Time needed: **about 15 minutes**, including the verification.

---

## Before the session — two things to check (Marcus, 5 minutes)

### 1. Port 22 is open to Marcus's home IP only, and that will block Afzal

This is the step most likely to make the session fail, because the key will
look correct and the connection will still hang.

The security group `p85-chatbot` was created with:

| Rule | Port | Source |
|---|---|---|
| SSH | 22 | A single `/32` — one person's home connection, as set 27 Oct 2026. Read the current value from the dashboard; it is deliberately not written down here |
| HTTP | 80 | `0.0.0.0/0` |
| HTTPS | 443 | `0.0.0.0/0` |

So **Afzal's key will work and his connection will still time out**, from
his own machine, from campus, or from anywhere that is not that one address.

Fix it in the dashboard before or during the session:

> **Network → Security Groups → `p85-chatbot` → Manage Rules → Add Rule**
> Rule `SSH`, Remote `CIDR`, CIDR = Afzal's public IP with `/32`
> (he can read it off <https://ifconfig.me> in a browser).

Decide which of these you want, and say which in the session:

| Option | Trade-off |
|---|---|
| One `/32` per person (current pattern) | Tightest. Breaks whenever anyone's home IP changes, which it will |
| A Swinburne network range, if IT publishes one | Durable and still narrow. **Ask IT for the CIDR — do not guess one** |
| `0.0.0.0/0` on port 22 | Always works, never needs maintenance. Exposes sshd to the internet; acceptable only because password auth is off and keys are the only credential. If you choose this, say so out loud as a decision rather than letting it happen by accident |

Marcus's own IP is also just a home address — **if it changes, he loses
access too**, which is a second reason not to leave this as the only rule.

### 2. Set the break-glass console password

Still outstanding as at 29 Oct. It takes one command and it is the single
highest-value thing available before the handover, because it turns the six
existing Nectar dashboard logins into six real recovery paths that need no
SSH key at all.

```bash
sudo passwd ubuntu                                  # Marcus types it; nobody else sees it
sudo passwd -S ubuntu                               # expect P (usable), not L (locked)
sudo sshd -T | grep -i '^passwordauthentication'    # must still say "no"
```

It is usable **only** from the dashboard's console (*Instances → p85-chatbot →
Console*), which already requires a Nectar/AAF login — so it does not weaken
SSH. **Test it once from that console**, then store it wherever the team keeps
shared credentials. An untested break-glass is not a break-glass, and it must
never go in this repository.

---

## Step 1 — Afzal generates a key pair (on his own machine)

He runs this himself. **The private key never leaves his machine and is never
sent to anyone, including Marcus.**

**Windows** (PowerShell, built in since Windows 10):

```powershell
ssh-keygen -t ed25519 -C "achowdhary@swin.edu.au"
# Accept the default path:  C:\Users\<name>\.ssh\id_ed25519
# A passphrase is recommended — it protects the key if the laptop is lost
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

**macOS / Linux:**

```bash
ssh-keygen -t ed25519 -C "achowdhary@swin.edu.au"
cat ~/.ssh/id_ed25519.pub
```

He sends **only the output of that last command**. It is one line and looks
like this:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... achowdhary@swin.edu.au
```

> **If what arrives begins `-----BEGIN OPENSSH PRIVATE KEY-----`, stop.**
> That is the private key, pasted by mistake. Do not add it. Tell him to
> treat that key as compromised, delete the pair, generate a new one, and
> send the `.pub` file's contents only. The helper script in Step 2 refuses
> a private key for exactly this reason, but catch it before it is on a
> shared screen.

Already has a key (`~/.ssh/id_ed25519.pub` exists)? Then he skips the
generate step and just sends that file's contents.

---

## Step 2 — Marcus adds the key (on the instance)

A helper script is already staged on the server at `~/add_ssh_key.sh`
(source: `scripts/add_ssh_key.sh`, commit `b1815f3`). Use it rather than
editing the file by hand — a single `>` instead of `>>` wipes the only key on
the box, and a malformed key line is **silently ignored** by sshd with no
error at all.

```bash
# From Marcus's machine
ssh -i ~/.ssh/p85_nectar ubuntu@136.186.108.232

# See who has access right now
~/add_ssh_key.sh

# Add Afzal's key — the whole key in single quotes, on one line
~/add_ssh_key.sh 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... achowdhary@swin.edu.au'
```

The script validates the key with `ssh-keygen` *before* writing it, refuses a
private key, appends only, takes a timestamped backup, forces mode 600,
strips blank lines, and is idempotent by fingerprint (re-running it says
"already authorised"). On success it prints:

```
Added:   256 SHA256:xxxxxxxx... achowdhary@swin.edu.au (ED25519)
Keys:    1 -> 2
Backup:  /home/ubuntu/.ssh/authorized_keys.bak-20261030T...Z
```

**Keep this SSH session open.** Do not close it until Step 3 passes.

---

## Step 3 — Afzal verifies it, from his own machine

This is the step that is easy to skip and the only one that proves anything.
With Marcus's session still open, Afzal runs:

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@136.186.108.232 'echo OK; whoami; hostname'
```

Expected:

```
OK
ubuntu
p85-chatbot
```

On Windows, `ssh` in PowerShell works the same way; the key path is
`$env:USERPROFILE\.ssh\id_ed25519`.

**If it fails, read the error — the two failures mean opposite things:**

| What he sees | Cause | Fix |
|---|---|---|
| Hangs, then `Connection timed out` | **Security group.** The key is fine; his IP is not allowed on port 22 | Add his `/32` (see "Before the session") |
| `Permission denied (publickey)` | The key did not land, or landed malformed | Re-run `~/add_ssh_key.sh` with no argument and check the fingerprint count went up; compare against the fingerprint he gets from `ssh-keygen -lf ~/.ssh/id_ed25519.pub` |
| `Host key verification failed` | His machine has a different cached key for that IP | Only expected if the instance was rebuilt. Remove the stale line it names from `~/.ssh/known_hosts` |
| `Bad permissions` / `UNPROTECTED PRIVATE KEY` | His private key file is too readable | `chmod 600 ~/.ssh/id_ed25519` (macOS/Linux); on Windows, remove inherited permissions on the file |

Marcus's session is still open, so the recovery is always available:

```bash
cp /home/ubuntu/.ssh/authorized_keys.bak-<timestamp> /home/ubuntu/.ssh/authorized_keys
```

Only once Afzal has seen `OK / ubuntu` should Marcus close his session.

---

## Step 4 — Add a second holder, not just Afzal

One key holder is the state we are leaving; two is the minimum worth
handing over. Repeat Steps 1–3 for one more person, chosen deliberately:

- **Five of the six Nectar project members are `@student.swin.edu.au`
  accounts, which lapse at graduation.** `achowdhary@swin.edu.au` is the only
  staff account on the project — the durable anchor, and the reason Afzal
  himself should hold a key rather than only a student.
- The second holder should be whoever will still be here in six months.
- Everyone logs in as the same `ubuntu` user. That is deliberate — every
  runbook command says `ubuntu@` — but it means the keys, not the accounts,
  are what you revoke.

---

## Step 5 — What Afzal does once he is in

Worth walking through together while the session is live, so the first time
is not alone:

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@136.186.108.232
cd ~/EAT-40005-Extraction/deploy/nectar

docker compose ps                    # expect 4 services Up: api, web, ollama, certbot
docker compose logs -f --tail=50 api # live API log; Ctrl-C to stop
cat .env                             # the only copy of the AuraDB credentials
```

`ubuntu` has `NOPASSWD:ALL`, so **anyone holding a key is effectively root.**
There is no safety rail between a key and the whole machine.

Deploying a change — note the two forms are not interchangeable:

```bash
cd ~/EAT-40005-Extraction
git pull
cd deploy/nectar

docker compose up -d --build api     # code change in the Python API
docker compose up -d --build web     # change to the Flutter app or API_BASE_URL
docker compose restart api           # config-only change to .env — no rebuild
```

> `docker compose up -d --build` with **no service named** rebuilds the
> Flutter web image too (both `api` and `web` have `build:` stanzas), which
> takes far longer and is not what you want for an API change. A teammate got
> the wrong command from an earlier version of the runbook; it is corrected
> now, but the habit is worth stating.
>
> **Every API rebuild signs every logged-in teammate out** — sessions are
> held in memory, not in the database. Harmless, but tell people first.

---

## Removing someone's access

Per-key revocation is the whole reason to add individual keys rather than
pass one private key around.

```bash
nano ~/.ssh/authorized_keys          # delete that person's line
~/add_ssh_key.sh                     # re-check: the fingerprint count should drop
```

The script never removes a key, deliberately. If someone leaves and their key
had root, also consider rotating `ADMIN_UPLOAD_SECRET` and the AuraDB password
(see `SYSTEMS_AND_ACCOUNTS.md` for how, and for what else has to change in
the same window).

---

## The two things that must not happen

### Do not click "Rebuild" in the Nectar dashboard

It sits directly beside *Reboot* in the instance action menu and it is the one
button that cannot be undone. Rebuild re-images the root disk:

- the public IP changes — there is **no floating IP** on this allocation;
- `136.186.108.232.sslip.io` stops pointing at us, so **every link handed to
  the team and the client breaks**;
- the TLS certificate no longer matches the name and must be reissued
  **staging-first** (all of `*.sslip.io` shares one Let's Encrypt rate limit);
- `API_BASE_URL` is compiled into the Flutter bundle, so the web image must be
  rebuilt with the new name;
- `~/.ssh/authorized_keys` resets to the launch key pair, undoing everything
  in this document;
- `deploy/nectar/.env` is on the root disk and is gone, taking the AuraDB
  credentials with it.

**Reboot is safe.** Docker is enabled at boot and all four services are
`restart: unless-stopped`, so the stack comes back by itself — verified.

### Do not lose every key with no console password set

If that happens, a rebuild is the only way back in, and the costs above are
what it costs. The 20 GiB volume at `/mnt/data` survives a rebuild and carries
the Ollama models, the NLLB translation weights, `uploads/` (admitted papers
and the review queue), extraction output and the Let's Encrypt certificates —
detach and reattach it. `deploy/nectar/.env` is the only irreplaceable thing
*not* on the volume, and it is reissuable from the Aura console.

So a lockout is recoverable, and what it actually costs is the URL.

---

## Facts worth keeping

- A key added this way **survives reboots**. cloud-init's `config_ssh` and
  `config_users_groups` carry per-instance semaphores that are already
  satisfied, so they re-run only when the instance-id changes — a rebuild,
  not a reboot. Verified 29 Oct 2026.
- A malformed key line produces **no error anywhere** — not in the file, not
  in the sshd log. It simply never authenticates. This is why Step 3 exists.
- `~/.ssh/authorized_keys` must be mode 600 and `~/.ssh` mode 700, or sshd
  ignores the file entirely. The helper script enforces both.
- Dashboard access and server access are different credentials: the dashboard
  can reboot, resize, open the console and rebuild, but **cannot change
  anything inside the box**. See `SYSTEMS_AND_ACCOUNTS.md`.

---

## Session checklist

- [ ] Afzal's public IP added to the `p85-chatbot` security group on port 22 (or a decision taken on a wider CIDR)
- [ ] Console password set with `sudo passwd ubuntu`, checked with `passwd -S`, and **tested once from the dashboard console**
- [ ] Console password stored where the team keeps shared credentials — not in this repo
- [ ] Afzal has generated a key pair and sent the `.pub` line only
- [ ] Key added with `~/add_ssh_key.sh`, fingerprint count went up
- [ ] **Afzal has logged in himself and seen `OK / ubuntu`**, while Marcus's session was still open
- [ ] A second holder's key added and verified the same way
- [ ] `~/add_ssh_key.sh` with no argument run at the end, and the final list of fingerprints agreed and recorded
- [ ] Afzal has run `docker compose ps` and seen the four services, and knows which deploy command to use
- [ ] Everyone in the room knows not to click **Rebuild**
