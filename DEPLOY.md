# Deploying booksnap, and the restore drill (P4.4)

**Settled 2026-08-13 (owner):** VPS + Docker Compose (VISION §12.3 #10).
The stack is SQLite plus a disk blob tree, so a managed PaaS fights the
storage model and managed cloud services would replace parts that already
work and are measured. A VPS keeps the whole restore story to *one file and
one directory*, which is exactly what the drill rehearses.

⚠ **The item is RESTORE, not backup** (VISION §11.3). This is what gates
handing a URL to a relative: an accuracy regression on someone else's
library is not recoverable by re-running, because their **review decisions**
cannot be re-derived. The engine can read a shelf again; nobody can
reconstruct which findings a human approved, corrected or rejected.

---

## What runs

| service | what it is | reachable from |
|---|---|---|
| `caddy` | TLS, the only public door | the internet, :80/:443 |
| `api` | the product — API **and** the built client, one origin | Caddy only |
| `staff` | the operator's cross-tenant read model | **nothing** — SSH tunnel |
| `backup` | takes a backup daily **and proves it restores** | nothing |

One origin for the client and the API is deliberate: the session cookie is
`HttpOnly` and same-origin, so there is no CORS surface and no header to get
wrong. One uvicorn worker is also deliberate — the job runner's state lives
on the app instance (§1.3), and a second worker is a second queue with its
own idea of what is running.

## First deploy

```bash
git clone <repo> booksnap && cd booksnap
cp .env.example .env      # then fill it in — see below
docker compose up -d --build
```

`.env` must carry, at minimum:

```
BOOKSNAP_DOMAIN=books.example.com
BOOKSNAP_PUBLIC_URL=https://books.example.com
BOOKSNAP_STAFF_TOKEN=<a long random string>
BOOKSNAP_SMTP_HOST=…   BOOKSNAP_SMTP_USER=…   BOOKSNAP_SMTP_PASSWORD=…
BOOKSNAP_MAIL_FROM=booksnap@example.com
ANTHROPIC_API_KEY=…
```

Three of those refuse to start without a value, on purpose:

- **`BOOKSNAP_SMTP_HOST`** — without it the composition root binds the DEV
  mailer, which prints sign-in links to the container log. A live
  credential readable by anyone with `docker compose logs` is a worse
  threat model than the mailbox it replaces, so both compose and
  `app/main.py` refuse it in a TLS posture.

- **`BOOKSNAP_STAFF_TOKEN`** — unset, the staff service serves every tenant
  to anyone who can reach it (the owner's deliberate local-dev posture,
  2026-08-13). That posture must not reach the internet, so compose refuses.
- **`BOOKSNAP_PUBLIC_URL` / `BOOKSNAP_DOMAIN`** — the emailed sign-in link
  points at this. `localhost` on the recipient's phone is the recipient's
  phone; P4.1b's UX review measured that exact dead end.

**There is no bootstrap and no first user.** A fresh database is empty by
construction (P4.1b deleted the dev principal). The first person to request
a sign-in link and follow it becomes a `User`; naming their first library
mints the Account (P4.1c). Everyone else arrives through an invite link
(P4.3).

## Reaching the operator console

The staff service is **not** routed publicly. It answers cross-tenant
questions behind a single shared token — a password with no rate limit and
no rotation story, which is not a thing to expose:

```bash
ssh -L 8758:localhost:8758 you@vps     # then point the console at it
```

That works because the staff service publishes on the VPS's **loopback**
(`127.0.0.1:8758:8758`), reachable by the tunnel and by nothing else. ⚠ If
it ever seems unreachable, the fix is not `ports: - "8758:8758"` — that
publishes cross-tenant read access, behind one shared token, to the
internet.

The console's own writes (create/rename a library) ride the operator's
**product** session; cookies are host-scoped, so sign into the product once
in the same browser.

## Backups

The `backup` service takes one daily into the `state` volume under
`/data/backups/<UTC timestamp>/`, and **immediately drills it**. A backup
directory holds:

```
product.db      copied through SQLite's backup API — never copy2, because
                a live file's WAL sidecars are a second and third instant
blobs/          every photograph, crop and sidecar
manifest.json   written LAST, with a checksum and the row counts
```

The manifest going last is the integrity rule: a backup interrupted halfway
has none, and `restore.py` refuses it rather than restoring a half-copy over
a working system.

Copy them off the box — a backup that lives only on the machine it protects
is not one:

```bash
rsync -a --delete you@vps:/var/lib/docker/volumes/booksnap_state/_data/backups/ ./offsite/
```

## The restore drill

**Run it. That is the whole item.** It restores into a temporary directory,
opens the result through the product's own store adapters, and checks the
numbers against the manifest — it never touches the live paths, so it is
safe while the server is up:

```bash
docker compose exec api python tools/restore.py --drill
```

```
DRILL PASSED for /data/backups/20260813T094911Z
  ok  integrity ok, 0 broken references
  ok  schema v17 opened as v17
  ok  286 books, matching the manifest
  ok  1 review decisions, matching
  ok  36 blob files, matching
    My library: 272 books
    lib2: 14 books
```

The drill is also a **test** (`tests/test_backup_restore.py`), so the gate
runs it on every commit — including the case that matters at 3am: a backup
written by *yesterday's* code, which today's stores must migrate forward.

### The real restore

```bash
docker compose stop api staff
docker compose run --rm api python tools/restore.py \
    --from /data/backups/20260813T094911Z \
    --to-db /data/work/product.db --to-blobs /data/blobs --i-mean-it
docker compose start api staff
docker compose exec api python tools/restore.py --drill   # prove it again
```

Without `--i-mean-it` it runs the drill instead of writing — and whatever is
already at the destination is **moved aside**, never deleted. The moment you
restore the wrong backup is the moment you can least afford to lose what was
there.

## Upgrading

```bash
git pull && docker compose up -d --build
```

The schema migrates on the first store construction, inside one
`BEGIN IMMEDIATE` (P4.0a): it lands whole or not at all, concurrent workers
serialize, and a database **newer** than the code is refused at the door
naming both versions. **Take a backup first anyway** — there is no down
step, and a rollback of the code past a schema change means restoring, which
is the drill above.

## Under a path prefix — malinvishne.com/booksnap

The owner's domain already hosts the family's site at its root, so the
product lives on a **path**, and one setting carries that everywhere:

```
BOOKSNAP_BASE_PATH=/booksnap
BOOKSNAP_PUBLIC_URL=https://malinvishne.com/booksnap
BOOKSNAP_DOMAIN=booksnap.malinvishne.com     # the VPS's own hostname (Caddy's cert)
```

What the prefix does, and where — because it lives in two places that
cannot read each other:

- **Build time.** Compose hands it to the image build as an `ARG`, Vite
  bakes it into `index.html` as the asset URLs (`/booksnap/assets/…`), and
  the client prepends it to every request it makes and every URL it hands
  the browser (`app/web/src/api/client.ts:apiUrl` — one function, every
  funnel; `basePath()` reads Vite's `BASE_URL`).
- **Run time.** The server gets the same variable as FastAPI's `root_path`.
  Starlette strips the prefix from a path that carries it and leaves one
  that does not alone, so the proxy passes the path through **untouched**
  and a request that reaches the origin directly still routes. The two
  paths the server BUILDS — the OAuth redirects and the OAuth binding
  cookie's `Path` — read it back off the request (`auth.py:_root`); at a
  domain root the cookie was scoped to `/api/v1/auth/oauth`, which a
  browser at `/booksnap/api/v1/…` never sends back, and every genuine
  provider sign-in would have been refused as a forgery.
- **The check.** `app/main.py:check_web_base` reads the page it is about
  to serve and refuses to start when its asset URLs were built for another
  prefix, naming both values. Built for `/` and served under `/booksnap`,
  the page loads, asks for `/assets/…` at the domain root and renders
  nothing — with no request ever reaching this server to log.

The emailed sign-in link and the OAuth `redirect_uri`s are built from
`BOOKSNAP_PUBLIC_URL` — a THIRD spelling of the prefix, and the one the
domain gets typed into. `app/main.py:public_url` refuses to build the
app when its path is not the served prefix (`https://malinvishne.com`
beside `BOOKSNAP_BASE_PATH=/booksnap` would mail every sign-in link to the
family's site and hand Google a callback at the domain root, with no
error anywhere). The Google OAuth client must list
`https://malinvishne.com/booksnap/api/v1/auth/oauth/google/callback`.

The mismatch refusals fire at **start-up** (`Application startup failed`
in the container log), not at import — `tools/api_contract.py` and the
pre-commit hook import `app.main`, and a prefixed build left in
`app/web/dist` must not lock a developer out of committing.

**Cloudflare** does the path routing. The apex record stays where it is;
two things are added to the zone:

1. a DNS-only `A` record `booksnap.malinvishne.com` → the VPS, which is
   what Caddy obtains its certificate for, exactly as at a domain root;
2. a Worker (`deploy/cloudflare-worker.js`) on the route
   `malinvishne.com/booksnap*`, with the variable
   `BOOKSNAP_ORIGIN=booksnap.malinvishne.com`. It forwards the request to
   the origin with the prefix intact, answers the bare `/booksnap` itself,
   rewrites a redirect that names the origin host, and drops the origin's
   HSTS header (that decision belongs to the zone, not to one path).

3. **HSTS at the zone** (SSL/TLS → Edge Certificates → HSTS): the Worker
   deliberately drops the origin's `Strict-Transport-Security`, so unless
   the zone sets its own, `http://malinvishne.com/booksnap` is a plaintext
   first hop until Cloudflare's redirect (security review).

What sharing a domain MEANS, stated plainly (security review):

- **The family's site is inside this product's trust boundary.** The
  session cookie is scoped to `Path=/booksnap/` so it no longer rides
  along on every request to the apex and into that host's logs — but a
  path is not a boundary for writes: anything served anywhere on
  `malinvishne.com` can set a cookie for this path or fetch this API with
  credentials. If the apex is ever hosted somewhere the owner does not
  control, that sentence is the decision.
- **The origin is a second front door.** `booksnap.malinvishne.com` is a
  public record with a public certificate (Certificate Transparency keeps
  it), and the product answers there at both `/booksnap/` and `/`. Same
  app, same auth, same body cap — not a hole today, but anything
  protective placed at the Cloudflare layer is skipped by addressing the
  origin directly; the day that layer gains a WAF rule or rate limit, the
  origin needs Authenticated Origin Pulls or a shared-secret header.
- **The sign-in rate door.** Behind the Worker every request reaches
  Caddy from a Cloudflare address, so the per-source window (15 links an
  hour) would be one bucket for everyone. The Worker stamps the visitor's
  address in `X-Booksnap-Visitor`, Caddy deletes that header from any
  request not arriving from Cloudflare's published ranges, and compose
  binds its name (`BOOKSNAP_VISITOR_HEADER`) so the api keys the window
  on it. Three pieces; `tests/test_integrations.py` asserts all three are
  present, and the deploy measures the effect (two addresses, two windows).
  Cloudflare's ranges are in the Caddyfile by value — re-check them against
  https://www.cloudflare.com/ips when a deploy is years old.

⚠ Rebuilding with a different prefix is `docker compose up -d --build`
with the new `.env` — a `--build` is what re-bakes the page. Building the
client by hand on Windows from Git Bash needs `MSYS_NO_PATHCONV=1`, or
`/booksnap` arrives as `/C:/Program Files/Git/booksnap` (measured).

## What is verified, and what is not

Verified, on the owner's real data and by the gate:

- the backup/restore round trip, the drill, and every refusal
  (`tests/test_backup_restore.py`), including a backup written on an older
  schema coming forward — measured on a v16 copy of the real 286 books,
  opened as v17;
- `docker compose config` parses this file, and the `:?` guards refuse to
  start without a domain and a staff token;
- the properties this file turns on are asserted structurally
  (`tests/test_integrations.py`): only the proxy publishes a port, the image
  keeps the free reading path, one worker, and this runbook's commands exist.

- **the image builds and RUNS** (2026-08-13). `deploy/smoke.py` drives the
  real ASGI app inside the built container and proved, in order: no cookie
  → 401, a link requested and printed, redeemed for a session cookie, a
  fresh database EMPTY, sign-up minting account + first library with the
  caller as admin, the books route resolving afterwards, the built client
  served from `/`, `/api/v1/docs` off, and a backup + drill finding the
  library that was just signed up.

```bash
docker build -t booksnap .
docker run --rm -v "$PWD/deploy/smoke.py:/smoke.py:ro" -e PYTHONPATH=/app     -e BOOKSNAP_PUBLIC_URL=https://books.example.com booksnap python /smoke.py
```

**Not verified:** Caddy actually obtaining a certificate, and the SMTP
mailer against a real provider — both need a public domain and credentials
that only exist on the VPS. They are the two things to watch on the first
deploy.

## Known posture, stated plainly

- **The staff service fails OPEN without its token** (owner, 2026-08-13:
  "staff token should not fail for the time being"). Compose refuses to
  start it unset, which is the deployment's answer; local dev keeps the
  honest on-screen warning.
- **`/api/v1/docs` is off** unless `BOOKSNAP_DOCS=1`. It loads swagger-ui
  from a CDN, unpinned, on the origin that holds a 90-day session cookie.
- **The blob GC under-deletes on purpose** (24h age floor). Run
  `tools/blob_gc.py` deliberately, never on a timer.
