# What this system does not do — handover summary

*Written 29 October 2026 for the handover on 30 October. A readable summary of
`KNOWN_LIMITATIONS.md`, which holds 31 entries with the full measurement and
the command that produced each one. Section references like "§31" point there.
Companion documents: [`SYSTEMS_AND_ACCOUNTS.md`](SYSTEMS_AND_ACCOUNTS.md),
[`SSH_ACCESS_SETUP.md`](SSH_ACCESS_SETUP.md).*

Every number here was measured on the live system, not estimated.

---

## The six things to say out loud

1. **The knowledge base is small — 112 verified facts from 11 papers (12
   processed) — and
   that is the system's main limitation.** Most reasonable questions about the
   Garo community are not in it, and the system will say so rather than guess.
2. **Refusing to answer is a designed behaviour, not a bug.** The project
   chose "an honest *I don't know*" over a confident wrong answer, at every
   stage. When a demo question gets refused, the first thing to check is
   whether the fact is actually in the graph.
3. **It is a list of facts, not a web of them.** 139 of 159 entities appear in
   exactly one fact, so the system cannot answer "what connects X to Y". It
   retrieves single facts; it does not reason across them.
4. **The first request after a quiet period fails, then works on retry.** The
   database connection goes stale while idle. A user meets this as "the site
   is broken" and then it is fine. A one-line fix is written and tested but
   not yet deployed (§31).
5. **Answers are slow: typically 15–60 seconds, up to ~5 minutes.** Every
   question is answered three times over — English, Hindi and Bangla — because
   Bangla is the deliverable for users in Bangladesh (§28).
6. **Bangla and Hindi answers have not been checked by a native speaker.**
   The engine was replaced on 28 Oct and is measurably much better, but
   "fit to review" is the honest claim, not "correct" (§29).

---

## A. What the system can and cannot answer

### A1. The knowledge base is small, and deliberately so — **HIGH impact**

**112 verified facts.** Twelve papers have been through the pipeline and
**eleven of them contributed at least one fact** — the twelfth, processed on
the live server as the end-to-end test of automatic extraction, produced
nothing usable. For the first three papers the figures are exact: **578 facts
were extracted, 45 survived the checks** — a 92% rejection rate.

Three automatic checks run on every extracted fact, with no AI involved:
*well-formedness* (is it a sensible statement?), *grounding* (do its words
actually appear in the sentence it quotes?) and *quote-genuineness* (does that
sentence really exist, word for word, on that page of the PDF?). A fact that
fails any one of them is **discarded, not queued for review**.

That is the intended trade. The graph feeds a chatbot with no human in the
loop, so a wrong fact reaches a user directly, while a missing one only means
the chatbot knows less. *(§1, confirmed as an owner decision: "never fabricate
a connection, even if that means more honest refusals".)*

**What this means in practice:** the system answers well on language use,
bilingualism, religion, livelihoods, medicinal plants and where the Garo
live. It will refuse most things outside that. **Verify any demo question
against the graph before relying on it.**

### A2. The facts do not connect to each other — **MEDIUM-HIGH, structural**

Of **159 distinct entities across the 112 facts, 139 appear exactly once.**
The biggest hub, `GaroCommunity`, touches 25 facts; the next is a
bibliography citation.

A knowledge graph earns its name from traversal — "what connects X to Y". This
shape cannot do that, so retrieval is **single-hop everywhere**: it finds
individual relevant facts and hands them to the model. There is nothing to
traverse. The graph is in 49 disconnected pieces. *(§4)*

Two causes, both fixable but both getting harder with every paper added:

- Nothing reconciles entities, so `GaroCommunity` and `Garo_People` are two
  separate things for the same people.
- Bibliography citations are extracted as if they were entities — `Pütz_1991`
  is a reference, not a thing in the world.

**Fix entity resolution before growing the corpus.**

### A3. Adding papers makes the vocabulary worse, not better — **MEDIUM, long-term**

**62 distinct relationship types across 112 facts, 45 of them used exactly
once.** Five different types describe language use and none of them match each
other. Each new paper adds roughly ten more single-use types.

Nothing constrains what the extraction model invents, so at 25 papers this
would be ~250 relationship types for ~350 facts, and no one can write a
reliable query against it. It also muddies search. The fix is a controlled
vocabulary in the extraction prompt (which only takes effect on re-extraction,
~1.2 h per paper) or a canonical mapping applied when facts are loaded. *(§5)*

### A4. One paper contributes almost nothing, and it is the PDF's fault — **LOW**

`garo_3`: **127 of 160 candidate facts failed the quote check — 79%**, against
32% and 35% for the other two papers. The PDF's text layer does not
reconstruct into readable sentences — most likely a two-column layout or a
scan. **This is a text-extraction problem, not a prompt problem**; do not try
to fix it by changing the model. *(§2)*

### A5. The one population figure in the data is not Garo-specific — **MEDIUM**

The number 1,650,159 is **all ethnic communities in Bangladesh combined**, not
the Garo. A direct "what is the Garo population?" is therefore **correctly
refused** — the figure simply is not in the corpus, which a database-wide
sweep confirmed. This was investigated as a suspected bug and closed as
correct behaviour. If anyone claims the system "won't answer an obvious
question", this is usually the one, and the answer is that it shouldn't. *(§27)*

### A6. Automatic checks cannot catch every kind of wrong — **MEDIUM-HIGH**

**21 facts added in one overnight batch passed all three automatic checks and
still had to be removed by hand.** Each was individually well-formed, genuinely
quoted and properly grounded — and still wrong: a paper's own research *aims*
extracted as if they were findings, relationships recorded backwards
(reading "Garo belongs to Lamdani" when Lamdani is a sub-group of the Garo),
and facts built from a sentence truncated mid-word (one fact has the subject
"E"). *(§1, §24)*

**A clean pass through the checks is not proof a fact is correct.** Someone
with subject knowledge needs to spot-check new facts, and that is especially
true of anything the community itself would notice.

---

## B. Reliability and operations

### B1. The first request after an idle period fails — **HIGH, fix written**

Measured 29 Oct, three identical requests in a row:

```
POST /auth/register  →  503   "Unable to retrieve routing information"
POST /auth/register  →  503   "Failed to read from defunct connection"
POST /auth/register  →  201   succeeded, ~3 seconds later
```

**What a user sees:** sign-in says "Authentication service unavailable", or a
question returns a bare error page — and then it works on retry. It has
probably been dismissed as flakiness for weeks.

**Cause, read out of the installed database driver rather than guessed:** the
connection pool never checks that a pooled connection is still alive before
handing it out, and will reuse a socket that has been idle for up to an hour.
The cloud database (or the network on the way out) drops idle connections well
inside that, so after any quiet period every connection in the pool is dead.
Nothing retries, because all 43 places the API talks to the database use the
unmanaged call style the driver does not retry.

**Status: fixed in code, tested, committed — and not deployed.** It ships with
the next deployment, and does not change anything else. *(§31, with the
driver's own source lines cited)*

**It is affecting people now.** The live API log on the evening of 29 Oct
shows a teammate signing in successfully and then getting a **502 on their
very next question**, with `SessionExpired: Failed to read from defunct
connection` underneath it — the exact fault above, on the current build,
hours before the handover.

> This is the item most likely to be reported as "the chatbot is broken".
> Deploying the fix is the cheapest reliability win available.

### B2. Every question is answered three times, so it is slow — **MEDIUM, accepted**

The API generates the English answer, then a Hindi translation, then a Bangla
one, **every time, in sequence**. Measured across eight benchmark questions on
29 Oct: **7, 15, 34, 40, 61, 62, 118 and 280 seconds** — 5 answered, 3
correctly refused, no errors.

This is a deliberate decision, taken 27 Oct and not to be re-litigated: users
will be in Bangladesh, so the **Bangla answer is the deliverable for the
primary audience**, not an optional extra. Generating it on demand would make
exactly those users wait twice.

Consequences accepted along with it: the web server's timeout had to be raised
to 620 seconds (the application's own worst case is 610s), and keeping
retrieved evidence short matters more, because there is less text to
translate. *(§28)*

### B3. Only one person can get into the server — **HIGH, fixed Friday**

One SSH key, on one laptop. No SSH password, no root login, and the dashboard
console password is not set. Six people hold Nectar dashboard access (three as
tenant managers), which can reboot the machine but **cannot change anything
inside it**.

A lockout is recoverable — but only by rebuilding the VM, which **changes the
public IP**, so the URL `136.186.108.232.sslip.io` dies and every link handed
to the team and the client breaks. See [`SSH_ACCESS_SETUP.md`](SSH_ACCESS_SETUP.md)
— this is being fixed in the handover session itself.

Related hazard: **"Rebuild" sits next to "Reboot"** in the dashboard and six
people can click it. Reboot is safe; rebuild destroys the URL, the
certificate, the SSH keys and the server's credentials file.

### B4. User accounts, feedback and chat history exist in one place only — **MEDIUM-HIGH**

The 112 facts are safely reproducible: they are committed as CSVs and can be
reloaded with one script. **But the four user accounts, all stored feedback
and all saved conversation history live only in the cloud database and are
backed up nowhere.** The server's credentials file (`deploy/nectar/.env`) also
exists as a single copy, on the disk a rebuild would wipe.

Two concrete actions, both in [`SYSTEMS_AND_ACCOUNTS.md`](SYSTEMS_AND_ACCOUNTS.md):
back up that file, and confirm which database tier the project is on — a free
tier can pause when idle and can eventually be reclaimed.

### B5. Deploying is manual, and the site can quietly run old code — **MEDIUM**

Pushing to GitHub does not update the live site; someone has to log into the
server and rebuild. The failure is silent, and it has happened: an audit found
the API current but the website image **three hours stale**, which meant a
feature was live in the back end with no interface able to reach it.

Verify what is actually deployed by hashing files inside the running container
against the checkout — the recipe is in `NECTAR_IMPLEMENTATION_PLAN.md`.
Also note **rebuilding the API signs every logged-in user out**, because
sessions are held in memory. *(§15 and the runbook)*

### B6. Nothing tests the system end to end — **LOW-MEDIUM**

**577 automated backend tests pass, plus 103 for the website, 0 failures.**
Not one of them crosses a boundary: nothing exercises the real database, the
HTTP API, or extraction into storage. Confirming the live system works still
needs a person to check it by hand after a change. *(§17)*

A warning worth repeating: for twelve days in October, the whole suite ran
**zero tests** because of an import-time error in one test file, and the
"passing" output looked normal. Read the collected-test count, not just the
colour of the result.

### B7. The project's automated checks do not run on push — **LOW**

The one CI workflow triggers on branches nobody uses and has never run the
test suite on any branch. Tests are run by hand before shipping. *(§16)*

---

## C. Answer quality

### C1. Bangla and Hindi answers are unverified by a native speaker — **HIGH until reviewed**

This was found, measured properly, and largely fixed in the space of a day —
the history matters because it shows how the fault was found.

**With the original engine (a general chat model doing the translating),
five of five substantive Bangla answers were materially wrong.** Not awkward —
wrong: one placed Assam inside Bangladesh, one **inverted a negation inside a
quoted source sentence** ("almost abolished" became "has begun"), one turned
asthma into the Bangla word for *faith* and vomiting into "courtyard from the
house", and added plant names that were in no source. All eight test responses
appended an unrequested transliteration, twice with **invented references** — a
Britannica URL and a journal citation that do not exist.

**Fixed 28 Oct by replacing the engine** with a dedicated translation model
(NLLB-200), now live. Measured on the same questions: no invented appendices,
the quoted sentence faithful, Assam back in India, and **2.6–7.8 seconds
instead of 30–80**. Three apparent faults in the new engine turned out to be
our own settings and were corrected too.

**What remains:** a native-speaker review (ordered, with a team member, not
yet returned). Until it comes back, the honest claim is that the Bangla output
is **fit to review**, not verified correct. Rolling back to the previous
engine is a one-line config change and a restart. *(§29)*

### C2. Off-topic evidence still reaches the model — **MEDIUM**

Retrieval was diluting its results with facts that merely mentioned "Garo".
A topic filter now runs on both retrieval paths, deployed and verified: for
one benchmark question the evidence went from ten facts to the one relevant
one, and the answer came back in 6 seconds instead of 23.

**But the filter is not a relevance judgement.** Off-topic evidence still
reaches the model on some questions — a question about religion was given a
fact about bamboo floors. The widely-quoted "27 off-topic facts down to 0"
figure measures *the two retrieval paths agreeing with each other*, not
relevance; say "the two retrieval paths now agree" and nothing more.
*(§20, §22, and the graph-precision notes)*

### C3. The safeguard against invented connections catches whole bad answers, not partly-bad ones — **MEDIUM**

A real failure prompted this: asked how the Garo trace lineage and
inheritance, the system produced a fluent answer that **welded together two
unrelated facts and attributed the claim to a named academic source that never
made it**.

The model is now required to state, as its first line, whether its evidence
genuinely answers the question — and the surrounding program **discards the
draft in code** if the answer is no, rather than trusting the model to stop.
Two earlier attempts that merely *asked* the model to be careful were tested
and did not work.

The remaining gap: if even one supplied fact is on-topic, the model may still
write an answer using the whole set — so a mostly-good answer that weaves in
one unrelated fact is not caught. Judging each fact individually was scoped as
follow-up work. *(§23)*

### C4. The sources panel shows more than the answer used — **LOW**

Every answer comes with an expandable list of the facts and page numbers
behind it, which is one of the project's better features. It is capped to what
the model actually saw, but is not narrowed to what the answer actually
*cited* — and it is still shown underneath an honest "not enough evidence"
message, where it reads oddly. *(§22)*

---

## D. Security, governance and data

### D1. Login is real now; the gaps are elsewhere — **MEDIUM**

Superseding what older documents say about "two hardcoded demo logins": the
system now has genuine server-side accounts — registration and login against
the database, passwords stored as salted PBKDF2-SHA256 hashes (310,000
rounds), four live accounts, two of them admin.

What is still missing: no rate limiting on login, no password reset, no email
verification, and **session tokens are held in memory**, so every restart
signs everyone out. Registration also still collects a phone number and
**silently throws it away** without telling the person. *(§8, §25)*

### D2. The admin upload secret is the only real access control — **MEDIUM**

Every `/admin/*` route is gated by one shared secret in the server's
environment. That matters because paper upload triggers AI work on the
machine: an open endpoint would be an invitation to burn the allocation.
Treat that value as the project's most operationally sensitive secret after
the database password.

### D3. The old hosting is still live, and unauthenticated — **HIGH, open action**

The project's previous host still serves an old build, and
**`POST /query` there answers with no authentication at all**, where the
current site correctly requires it. Re-verified 29 Oct. Deleting those two
services needs the dashboard owner and is on the Friday list — with one
caution: **do not revoke the database credential as part of it**, because it
is the same credential the live site uses. *(§11 in
[`SYSTEMS_AND_ACCOUNTS.md`](SYSTEMS_AND_ACCOUNTS.md))*

### D4. Credentials have been committed to git three times — **MEDIUM, process**

A real password reached `.env`, an example file, and a local file. All three
database instances have since been deleted, so the leaked values are dead —
this is a process finding rather than a live incident, and the history was
deliberately not rewritten because a coordinated rewrite across the team was
judged riskier than dead credentials warranted. **The lesson is the point:**
keep real values out of the repository. *(§13)*

### D5. Nothing checks the project is allowed to use a paper — **MEDIUM, by omission**

The upload screen scores each paper for credibility, relevance and ethical
handling — but the "ethical handling" score asks whether **the paper's own
authors** documented consent from **their** participants. It says nothing
about whether this project has permission to use the paper. **There is no
licence, copyright, embargo or paywall check anywhere in the code**, and what
such a check should test needs agreeing before it can be built. These two are
routinely confused; keep them apart. *(§10)*

### D6. There is no path for community-collected material — **MEDIUM-HIGH, governance**

The project committed to two things: that paper content goes only to a local
model, and that human-collected material (workshop transcripts, interviews)
would too. The first is enforced in code. **For the second, no pipeline
exists and no such data has been through the system** — and the upload screen
has no concept of a data class, so a transcript dropped into it would take
exactly the same route as a published paper.

This compounds with a governance point worth raising explicitly: **the cloud
allocation was applied for on the written basis that the data holds no
personal information.** If community-sourced material containing names is
loaded later, that declaration no longer holds. It was raised verbally and
waved off; the written declaration still says no personal data. **Give the
upload path a data class, with human-collected material pinned to the local
model, before accepting any.** *(§11, §12, and the allocation record)*

### D7. The database stores verbatim quotes from the papers — **MEDIUM, by design**

Exact sentences from academic papers about an Indigenous community are stored
in the cloud database, and the same text is in the repository as CSVs. This
was a deliberate, supervisor-approved choice — the quotes are what make the
fact-checking possible — but anyone continuing the work should know what is
stored and why. *(§13, and `data/production_graph/README.md`)*

---

## E. Engineering debt worth knowing about

| Item | Where it stands |
|---|---|
| **`main` and `dev` have diverged in both directions** | ~269 files differ, and **neither branch is the whole system**. `dev` is the working branch; anyone cloning the default branch gets the pipeline *without* the fact-checking gates. Reconciling them is unfinished. *(§14)* |
| **Paper-admission scoring is unstable** | Scoring the *same* paper 11 times produced results from **5 to 80 out of 100** — spanning "reject" to "approve". It can tell an irrelevant paper from a relevant one; it cannot be trusted as a verdict on a single run. Treat the number as a prompt for human judgement. *(§9)* |
| **Automatic extraction works and yields almost nothing** | Approving a paper now triggers extraction automatically, proven end to end on the live server. One real run produced **1 usable-looking fact from 98 candidates — and that one was wrong.** The machinery is sound; the yield is the problem. *(§18)* |
| **The pruner is built but not connected** | Code exists to review facts already in the database and remove ones later found wrong. It is not wired to the live system. |
| **Two files sit outside the local-model guard** | Both are currently unused, but would bypass the guard if wired up. *(§12)* |
| **Database reads are a full scan with no index** | Free at 112 facts, fine into the low thousands. A few tens of thousands of facts would need a full-text index and a different query shape. A hard cap bounds the worst case. *(§6)* |

---

## F. What is *not* a limitation, though it gets reported as one

| Reported as | Actually |
|---|---|
| "It refuses questions it should answer" | Usually correct behaviour. The most common example — the Garo population — is genuinely not in the corpus (A5). Check the graph before calling it a bug |
| "The answer is a flat list rather than natural writing" | The templated fallback, used when the model is unreachable. Accurate, just not fluent |
| "It's broken" after a quiet period | B1. It works on retry; the fix is written and awaiting deployment |
| "The number of sources doesn't match the answer" | C4. Known, cosmetic, deliberately deferred |
| "It only answers in English" | Wrong, and worth correcting: a **Bangla question works**, provided the app sends its language — which it does. The old "you must ask in English" advice came from a hand-made test request that omitted the language field |

---

## G. If one week of work were available, in order

1. **Deploy the idle-connection fix** (B1). Written, tested, not deployed —
   the cheapest reliability win in the list.
2. **Finish the access handover**: second SSH key, console password, back up
   the credentials file, confirm the database tier (B3, B4).
3. **Delete the old unauthenticated host** (D3).
4. **Get the native-speaker review of the Bangla answers back** (C1). It
   decides whether the primary audience's deliverable is trustworthy, and it
   costs us nothing but a reply.
5. **Grow the corpus — but fix entity resolution and pin the relationship
   vocabulary first** (A2, A3). Both get harder with every paper added, and
   corpus size is the system's binding limitation.
6. **Give the upload path a data class** before any community-collected
   material is accepted (D6).

---

*Full evidence for every item, including the commands that produced each
measurement, is in `KNOWN_LIMITATIONS.md` on the `dev` branch.*
