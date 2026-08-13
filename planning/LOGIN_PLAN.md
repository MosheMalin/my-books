# Pillar 4 — Login

**Status: APPROVED (owner, 2026-08-13).** Decisions taken with the approval:
**P4.0c is DROPPED for now** — "staff token should not fail for the time
being" (owner); the staff service keeps its honesty-based fail-open model,
and the deployment posture (P4.4) simply sets the token. All other
recommendations accepted as given: deployment target VPS + Docker Compose,
libraries-per-account cap = **5**, mail provider picked at P4.4 behind the
`Mailer` port, sessions are opaque server-side ids in HttpOnly cookies with
a **90-day rolling** lifetime. This document is the progress tracker: items
gain a ✅ as they land on `main`.

Produced by re-reading the standing decomposition
(`IMPLEMENTATION_PLAN.md` "Pillar 4 — Login", VISION §3 / §4.1 / §4.2 / §4.3 /
§10 / §11 / §12, `TENANCY_BOUNDARY_PLAN.md` "Found on the way") against a
code-level audit of what actually landed. Open questions for the owner are
batched in §7 — nothing starts until they are answered and the item list has
a nod.

## 1. What this pillar is

Sessions and sign-in (email magic link, then Google/Apple), invites and the
§4.3 onboarding path, and the deploy + **restore** rehearsal that gates
handing a URL to a relative. It is also, deliberately, the pillar where the
unauthenticated-LAN trade recorded in CLAUDE.md ("a known single-household
trade until pillar 4") is paid off.

## 2. Corrections against the standing decomposition

Re-reading the plan against the code found one stale claim and two scope
facts worth stating before itemizing:

- **P3.2 landed; roles ARE enforced.** A prior session note claimed "roles
  are reported, never enforced — decide whether P3.2 lands before or inside
  P4.1". That is stale: the matrix is data
  (`app/domain/policy.py:POLICY`), the one enforcement point is
  `app/api/policy.py:require`, and the table-driven cell test
  (`test_the_policy_matrix_is_vision_4_2_cell_for_cell`) plus the per-route
  meta-test (`test_every_api_route_declares_exactly_one_policy_capability`)
  both exist and are mutation-checked. What is fake is the **principal**
  feeding that enforcement — a process-wide `DevPrincipal`
  (`app/main.py:202`) with a fallback that upgrades a missing membership to
  ADMIN. So the P3.2 question dissolves into P4.1's first act: kill the
  fallback, keep the matrix.
- **There are THREE dev-trusted fallbacks, not two, and they die together**
  (audit, 2026-08-13): `app/api/deps.py:129-130` (`current_library` serves
  the principal's default library with no store lookup),
  `app/api/policy.py:87-88` (`_role` upgrades a missing membership to ADMIN
  for the default library), and `app/api/deps.py:203-204` (`owning_account`
  invents an account key from the library id — the key the rate cap and job
  fairness use). Alongside them die `app/main.py:_bootstrap_dev_user` and
  the two "P4.1 replaces this" helpers `_user`/`_account` in
  `app/api/routers/libraries.py`.
- **`MANAGE_MEMBERS` already has a policy row and no routes** — reserved for
  P4.3 ("an invite with no login to accept it is not a feature",
  `app/api/routers/libraries.py:36-37`). The matrix does not change in this
  pillar; it gains its first consumer routes.

## 3. Ground truth the items build on (audited 2026-08-13)

- **No session, token, password or mail concept exists anywhere in `app/`.**
  `User.email` is optional, unused, and already carries a partial unique
  index (`users_by_email`). `requirements.txt` has no mail/JWT/OAuth/crypto
  library. There is no `.env.example`; two hand-rolled `_load_dotenv` copies
  exist (`app/main.py`, `app/staff_api/main.py`).
- **The migration runner has three recorded holes**
  (`TENANCY_BOUNDARY_PLAN.md` → "Found on the way"): string steps are not
  atomic (`executescript` autocommits, so `with conn:` wraps nothing); no
  guard when the file is NEWER than the code (silent skip, later raw
  `no such table`); no cross-process mutual exclusion (N test workers each
  replay the chain on a fresh file). Schema is at v14; every P4 schema step
  inherits all three unless they are fixed first.
- **All five services bind 0.0.0.0** (`:8756` tuning, `:8757` API, `:5173`
  web, `:5174` admin, `:8758` staff). `:8757` has no auth at all; `:8758`
  with `BOOKSNAP_STAFF_TOKEN` unset serves every tenant to anyone on the LAN
  (`app/staff_api/app.py:349-364` — unset ⇒ `require_staff` returns).
- **`filename` is uncapped on the write path** (`POST /api/v1/images` →
  `disk_blobs.put` → sidecar, all four hops confirmed). Only the staff
  console caps what it republishes (`app/staff_api/storage.py:MAX_FILENAME
  = 200`, read-side). Measured earlier: ~40 MB per console page from
  megabyte-long names.
- **`owner_membership` has a known timing oracle** (`app/api/deps.py:155-171`,
  its own docstring): 40/40 ids classified by response time. It "matters
  most after P4.1" — fix is one wasted lookup, and it belongs in this pillar.
- The rate cap (30 reads/hr) and job fairness key off `owning_account`, so
  auth work touches them only through that one function.

## 4. The items

Sizes are relative (S/M/L). Every item: branch in place or worktree per
CLAUDE.md rule 1, `review-security` standing (this is the pillar where
credentials arrive), `review-migration` BEFORE any commit that adds a schema
step, snapshot `work/product.db` via SQLite's backup API before every merge
to `main` (importing `app.main` migrates it; there is no down step).

### ✅ P4.0a — fix the migration runner (S/M) — landed 2026-08-13

One deviation from the text below, argued in `migrations.py`'s docstring and
pinned by `test_a_failure_late_in_a_fresh_chain_rolls_back_every_earlier_
step`: ONE transaction wraps the whole pending chain (not per-step) — the
race is closed by the re-read under the lock, and the single transaction
means a file is never left between versions.

The three recorded holes, closed in the runner so all future steps inherit
the guards:

- **atomicity**: run each string step inside an explicit transaction
  (`BEGIN` … `COMMIT`, statements executed individually or the script
  wrapped), so a crash mid-step leaves a file that rolls back to the OLD
  version instead of a half-upgraded file at the old `user_version`;
- **newer-than-code guard**: `migrate()` raises a named error stating both
  numbers when `user_version > SCHEMA_VERSION`, instead of skipping quietly;
- **cross-process exclusion**: take a write lock (`BEGIN IMMEDIATE`) before
  reading `user_version`, so concurrent fresh-file opens serialize instead
  of racing (`duplicate column name: lent_out`).

Tests: a step that fails mid-way leaves the file openable at the old
version; a newer file raises the named error; a concurrency test over a
fresh file. No schema version change of its own — but `review-migration`
reviews it anyway (it changes how every step behaves), plus
`review-quality`. Done: gate green, the three holes' entries in
`TENANCY_BOUNDARY_PLAN.md` annotated as closed here.

### ✅ P4.0b — cap `filename` at the write port (S) — landed 2026-08-13

As specified below: `MAX_FILENAME = 200` on the port, truncation in
`DiskBlobStore.put`, staff keeps its read-side copy (it imports nothing
from `app`) with a test pinning the two equal.

Cap at the port where the name enters (`app/api/routers/images.py` +
`app/adapters/disk_blobs.py`), aligned with the staff console's 200.
Recommendation: truncate rather than reject — the name is display metadata,
not identity, and a phone's genuine long name should not fail an upload.
Tests: an over-long name stores truncated; the staff read model note in
`storage.py:58-66` updated to say the write path now caps. Reviewers:
`review-security`, `review-data-integrity`. (Small, standalone, unblocks
nothing — but it is the recorded "real fix is unowned" debt, and this pillar
touches the file anyway.)

### P4.0c — ~~staff token fails CLOSED~~ DROPPED (owner, 2026-08-13)

"Staff token should not fail for the time being." The fail-open,
honest-on-screen model stays. P4.4's deployment posture sets the token in
the deployed environment; the local-dev behaviour is unchanged.

### P4.1 — sessions + email magic link (L; split a/b/c like P3.7)

The riskiest item of the pillar; staged so each stage lands green on `main`.

✅ **P4.1a landed 2026-08-13.** Numbers decided in code, each with a stated
reason there: token life 15 min, refresh threshold 60 days remaining (one
write/month/device), link rate 5/hr per (address × source) pair and 15/hr
per source — the pair form replaced address-alone after the security review
measured a stranger locking the owner out through it. Post-landing reviews
(security, data-integrity, quality) all folded; the identity anchor
(`BOOKSNAP_OWNER_EMAIL`) is linked on the real database.

**P4.1a — session machinery, additive (M).** New schema steps (v15+): a
`sessions` table (opaque random id, `user_id`, `created_at`, `expires_at`,
`revoked_at`) and a `login_tokens` table (token stored HASHED, single-use,
short expiry, `email`, `consumed_at`). A `Mailer` PORT in `app/ports/` (the
credential-preflight precedent: capability lives on the port, never
`os.environ` in a route) with a dev adapter that logs the link; the real
adapter arrives with P4.4's deployment. Routes: request-a-link (rate-limited
per email AND per IP — §3's "rate-limited, single-use, expiring" is the
decided spec), redeem-a-link (mints a session, sets an HttpOnly SameSite
cookie), logout (revokes). The dev principal still resolves requests — this
stage is additive and cannot break the household's flow. Session transport
recommendation: opaque server-side session id in an HttpOnly cookie, NOT a
JWT — revocation is trivial, scale is a household, and it adds no
dependency. Reviewers: `review-migration` (before each schema commit),
`review-security`, `review-data-integrity`, `review-quality`.

⚠ **P4.1b prerequisite, recorded at P4.1a (migration review): the owner's
real user row must carry his email BEFORE the dev identity dies.** v15 makes
`users.email` the whole identity resolution (`user_by_email` at redeem), and
the owner's row predates email. P4.1a's bootstrap fills it from
`BOOKSNAP_OWNER_EMAIL` (set in `.env`) on server start — verify
`users.email` is populated on the real database before starting P4.1b, and
P4.1b's cutover carries a test that a v14-shaped file with an email-less
user survives (signs in to the RIGHT user, never a freshly-minted twin).

✅ **P4.1b landed 2026-08-13.** All three fallbacks, the bootstrap, the dev
principal and `routers/libraries.py`'s `_user`/`_account` deleted; the
`Principal` port is identity-only and `current_library` resolves the
no-header default through the store. "Operating as" for `POST /libraries`
is the request's own library header; a multi-account caller naming nothing
is refused with instructions. The web client gained the login screen, the
401→login mechanism (`SIGNED_OUT_EVENT` out of the one place all five
request helpers fail through), the redeem route, and sign-out. The
`owner_membership` timing-oracle fix turned out to have landed WITH P3.7b
(both lookups already run on every path — the plan text below overstated
the debt). Admin-console note: its tenancy writes ride the operator's
product session (cookies are host-scoped, not port-scoped), so the
operator signs into the product once in the same browser.

**P4.1b — the resolver reads the session; the fallbacks DIE (M/L).** The
first real act of authentication, not a cleanup afterwards: delete all three
fallbacks together (`deps.current_library` branch 2, `policy._role`'s ADMIN
upgrade, `deps.owning_account`'s id-as-account), delete
`_bootstrap_dev_user` and `routers/libraries.py:_user`/`_account`, and
resolve the principal from the session cookie. An unauthenticated request to
any `/api/v1` route is 401 with a clear body; the web client gains a login
screen and 401 handling (fetch layer → login). Local dev logs in via the dev
mailer's printed link — the `BOOKSNAP_DEV_PRINCIPAL` env identity is
deleted, not preserved behind a flag (a flag that restores an
authentication bypass is the landmine we are removing). Fix the
`owner_membership` timing oracle in the same item (one wasted lookup). This
closes the `:8757` unauthenticated-LAN trade: the phone still reaches the
API on the LAN, but logs in first. ⚠ The test-impact list in §8 is large
and known in advance; the named fallback test
(`test_a_membership_row_on_your_own_library_outranks_the_dev_trusted_fallback`)
is DELETED, not edited, and the API-ring harness (`StubPrincipal`) becomes a
session-minting helper. Reviewers: `review-security`,
`review-data-integrity`, `review-quality`, `review-ux` (the login flow is
user-visible, phone-first, Hebrew/RTL).

✅ **P4.1c landed 2026-08-13.** The sign-up act is `POST /libraries` from a
caller with no account and no header: account + first library minted
together, domain objects first (a blank name refuses before any write),
ADMIN by construction. The cap (5, pinned by number in a test like a
policy cell) binds existing accounts, never the first library. The client
gained the first-library screen — a signed-in user with no library names
their collection instead of seeing tabs that can only 404, and the nav is
absent (not disabled) until it exists.

**P4.1c — sign-up mints the world (M).** A new email's first login creates
User + Account + its FIRST Library in one flow (VISION §4.3 steps 1–2: an
account with no library is a customer with nowhere to put a book — the
state is unreachable). Exactly ONE library, never a second offered during
onboarding (§4.1 revision). The libraries-per-account cap lands here: a
policy number checked at create time on the account, never a second scope
on the data (number is §7 Q2). Naming the library is part of the flow
(label mandatory — existing domain rule). Reviewers: `review-security`,
`review-data-integrity`, `review-ux`.

✅ **P4.2 landed 2026-08-13** (schema v18), last, as the plan
recommended — Apple needs a real HTTPS domain, which P4.4 settled.
Authorization-code flow with PKCE (S256), one `IdentityProvider` port with
Google and Apple adapters over stdlib HTTP. The ID Token's signature is
deliberately not verified and the reason is written where it can be
argued with (OIDC Core §3.1.3.7: the token arrives over a TLS connection
we opened to a pinned endpoint) — every CLAIM is still checked by one
domain checklist: issuer, audience, nonce, and the verified-email flag
that stops anyone typing your address into their own provider account.
Identity links on the verified email, so Google and the magic link land on
the SAME user. The state is server-side (v18) because Apple's callback is
a cross-site POST that no SameSite=Lax cookie accompanies, and it is
single-use — that is the CSRF guard for a route anyone can aim a browser
at. The login screen offers exactly the configured providers and none
otherwise. Apple's client secret is a real ES256 JWT signed with
`cryptography` (already a dependency), verified against its public half in
a test. **What only the owner can supply:** the Google OAuth client and
the Apple Services ID + .p8 key — `.env.example` documents both, and with
neither set the product signs in by link exactly as before.

### P4.2 — Google + Apple sign-in (M) — recommend landing AFTER P4.4

OIDC code flow for both; identity linked to the User by **verified email**
(the magic-link anchor), so one person is one User regardless of sign-in
method. No passwords, ever. Constraints discovered in planning: Apple
sign-in requires a paid Apple Developer account and a real HTTPS domain for
redirect URLs; Google can develop against localhost. Hence the
recommendation to run this item after P4.4 settles the domain (§7 Q3) —
Apple against a domain that exists, once. Reviewers: `review-security`,
`review-quality`, `review-ux`.

### P4.3 — invites and the onboarding path (M/L)

`MANAGE_MEMBERS` gets its routes: an admin issues an invite (single-use,
expiring token carrying account + role), the recipient signs in (magic link
or OAuth) and accepts — joining the ACCOUNT, per §4.1 ("invite once").
This is the item that makes a user belonging to several accounts REACHABLE
(it has been representable since P3.7b — correct state, not a gap). The
switcher's multi-account behaviour becomes real; revoking an invite and
removing a member (NoAdminLeft already enforced domain-side) get routes and
UI. Onboarding polish to §4.3's target — sign-up to first correct book in
under five minutes: guided first capture, run on the free quota, review one
shelf. Steps 5–6 of §4.3 stay skippable; the product works for someone who
never invites anyone. Reviewers: `review-security`,
`review-data-integrity`, `review-ux`, `review-quality`.

✅ **P4.3 landed 2026-08-13** (schema v16). An invite is a SHARE-LINK, not
a mail: the admin mints one (raw token in the response, once — stores hold
the hash), hands it over their own channel, and the invitee joins the
ACCOUNT at the carried role. Member management (§4.2's MANAGE_MEMBERS row
finally consuming routes): list/role-change/remove with NoAdminLeft as
409, open invites with revoke. The client: an account menu in the app bar
(members panel for admins; sign-out moved behind it after the UX review
measured the bare buttons 77px past an iPhone width), the invite-accept
route that survives the sign-in detour via a stash, `absorb()` on the
library provider so the joined account's libraries appear and select
without a reload. The P4.1 review fleet's findings folded in the same
landing — see the commit message for the list.

✅ **P4.4 landed 2026-08-13** (schema v17 rode with it). Deployment is
VPS + Compose: one image serving the API and the built client (same origin,
so the session cookie needs no CORS), Caddy terminating TLS as the only
published port, the staff service reachable by SSH tunnel alone, and a
backup service that takes a backup daily AND drills it. `tools/backup.py`
copies through SQLite's backup API + the blob tree + a manifest written
LAST; `tools/restore.py --drill` restores into a temp directory and reads it
back through the real stores — proven on the owner's 286 books, and a gate
(`tests/test_backup_restore.py`) covers the round trip, an older-schema
backup, an interrupted one, a corrupted one, and the move-aside rule. The
production `SmtpMailer` and the per-deployment `Secure` cookie flag are the
two things TLS turns on. `DEPLOY.md` is the runbook.

### P4.4 — deploy + RESTORE rehearsal (L)

**Additions from the P4.1/P4.3 reviews (2026-08-13):**
- a request-body size limit at uvicorn or the proxy (the pre-auth routes
  buffer an unbounded body before validation — measured 100 MB in memory);
- run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy>` or the
  per-source rate door collapses to a whole-service cap behind TLS
  (measured: 15 requests lock everyone out) — never an unconditional
  X-Forwarded-For read;
- the interactive docs page is OFF by default since P4.1b's review (an
  unpinned CDN script on the origin that holds the session cookie;
  `BOOKSNAP_DOCS=1` opts a dev machine in) — vendor swagger-ui into the
  build or leave it off in production;
- `BOOKSNAP_PUBLIC_URL` must be the deployed domain (the dev default now
  guesses the LAN address so a phone can open the link; `.env.example`
  documents it — created early, at the review's insistence);
- the production Mailer implements `delivery` (the 202 carries how the
  link travels; the login screen renders the server-log hint in dev).

Not backup — restore: review decisions cannot be re-derived (§11.3), and
this item gates handing a URL to a relative.

- settle §12.3 #10 (deployment target — §7 Q3) and stand up staging before
  anyone outside the family (§11.3);
- backups: `work/product.db` via SQLite's backup API + the blob tree;
  restore is REHEARSED — a documented, scripted drill onto a fresh
  environment, verified by the gate and a real browse;
- the production `Mailer` adapter (provider per §7 Q3), TLS/domain, and the
  deployment posture for the staff service (token set, not LAN-open);
- `.env.example` finally exists: one documented home for
  `BOOKSNAP_STAFF_TOKEN`, session secret, mail transport, OAuth client ids
  — and the two `_load_dotenv` copies are reconciled if touched;
- rate limiting / abuse controls at the door re-checked for an
  internet-facing deployment (§12.3 #14) — invite-only, but the login and
  magic-link endpoints are public by nature.

Reviewers: `review-security` (standing), `review-quality`; `review-ux` for
anything user-visible in the deployed flow.

## 5. Standing rules for the pillar

- ⚠ **A system admin is NEVER a `Role`.** No `SYSTEM_ADMIN` enum value,
  ever — a membership row must not be a place someone grants themselves the
  world. Operator identity stays the staff token; later `Account.is_staff`
  or a `StaffGrant` with its own audit trail. (CLAUDE.md; restated here
  because auth work is exactly where the temptation appears.)
- **Sessions authenticate a User; roles stay per Account** (§4.1). Nothing
  in P4 adds a second scope to data rows; `library_id` remains the one
  physical scope, the account checked at the door.
- **Tokens are stored hashed, never logged, never in run snapshots** —
  CLAUDE.md's credential hygiene, now applied to tokens we MINT, not only
  keys we hold.
- **The console's removed moderation stays removed.** Revisit only once
  P4.1 gives the operator an identity AND an audit trail gives the
  household a record (ADMIN_CONSOLE_PLAN revision 6) — neither is a P4
  deliverable; P4.1 merely makes the revisit possible later.
- Every schema step: NEW step, never an edit in place; `review-migration`
  BEFORE the commit; the runner guards from P4.0a already in force.
- Reviewers get one detached worktree EACH (`git worktree add --detach
  D:/tmp/<name> <sha>`), removed after; three sharing one tree contaminated
  each other's mutation checks once already.

## 6. Sequencing

```
P4.0a runner ──► P4.1a sessions ──► P4.1b fallbacks die ──► P4.1c sign-up
P4.0b filename ─┘ (any time before P4.1b)                        │
P4.0c staff 401 ─ (on owner's word, any time)                    ▼
                                              P4.3 invites ──► P4.4 deploy ──► P4.2 OAuth
```

The only hard edges: P4.0a before the first auth schema step; P4.1a → b → c
in order; P4.3 needs P4.1c (an invite needs a login to accept it); P4.2
after P4.4 is a recommendation (Apple's domain requirement), not a hard
edge — Google alone could land earlier if wanted.

## 7. Open questions — ANSWERED (owner, 2026-08-13)

Q1 VPS + Docker Compose · Q2 cap = 5 · Q3 provider picked at P4.4, behind
the port · Q4 staff token stays fail-open (P4.0c dropped) · Q5 90-day
rolling sessions. The original questions with their reasoning:

1. **Deployment target (§12.3 #10).** The stack is SQLite + disk blobs +
   two FastAPI services + static builds — recommendation: a small VPS with
   Docker Compose (portable, cheap, keeps SQLite/disk storage exactly as
   built, restore drill is scp + backup API). A managed PaaS fights the
   disk-state model; managed cloud services replace parts that already
   work. Decide: VPS+Compose / PaaS / other?
2. **Libraries-per-account cap** — the `[OPEN]` policy number checked at
   account level on create (VISION §4.1). Recommendation: **5** (generous
   for real second-collection cases, still a retry-loop guard like the run
   rate cap). Any number works; it is one constant with a stated reason.
3. **Mail provider** for magic links (couples to Q1's target).
   Recommendation: a transactional-mail service with a free tier and a
   plain HTTP API (e.g. Resend/Postmark/SES — final pick with Q1), behind
   the `Mailer` port either way; dev adapter logs the link, so nothing else
   depends on the choice.
4. **Staff token fail-closed (P4.0c)** — today's unset-token = open-to-LAN
   model was a deliberate honesty-based decision; confirm switching it to
   401-at-the-door with an explicit dev escape env, or leave as is until
   deployment (P4.4)?
5. **Session lifetime** — recommendation: 90-day rolling sessions,
   revocable server-side (a household app on personal phones; short
   lifetimes punish the phone-capture flow). Object if you want shorter.

## 8. Appendix — known test impact at P4.1b (from the 2026-08-13 audit)

Deleted with the fallbacks: `test_a_membership_row_on_your_own_library_outranks_the_dev_trusted_fallback`.
Change meaning (dev-trusted branch → session semantics):
`test_a_request_with_no_library_header_still_gets_the_default_one`,
`test_a_library_goes_under_an_account_you_belong_to_never_your_defaults`,
`test_the_library_meta_resolves_is_always_one_the_switcher_lists` (pins the
bootstrap that dies), `test_a_library_goes_under_the_account_you_are_operating_as`
(written FOR the post-P4 world — becomes fully true). Harness changes:
`StubPrincipal`, `_tenancy()`, `_second_library()`,
`_viewer_of_second_library()` become session-minting helpers; the
`_USER_SCOPED` exemption list is re-audited. Structural constraints that
survive and must keep passing unchanged:
`test_library_resolution_has_exactly_one_implementation` (constrains where
session code may live in `deps.py`),
`test_every_api_route_resolves_its_library_from_the_principal`,
`test_every_api_route_declares_exactly_one_policy_capability`,
`test_a_role_says_who_you_are_and_never_what_you_may_do` (bans policy words
in `tenancy.py` — constrains where any session→role helper is written), and
`test_a_library_is_not_a_place` (pins `Library`'s exact field set — invite
or session state must not grow on tenancy entities it does not belong to).
