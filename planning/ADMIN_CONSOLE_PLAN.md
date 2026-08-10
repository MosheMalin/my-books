# The admin console (`app/admin/`) — plan

Written 2026-08-10, at the owner's instruction: P3.1 put *create a library* in
the main product's app bar, and that is the wrong home for it. Tenant
administration is a **different job for a different person**, even when today
that person is the same human — and putting it on the shelf-photographing
client means every household member's app carries controls they must never
press.

This document is the plan and the record of what was decided. It is written
before the code and updated after, in the house style.

## Hard constraints this was built under

1. **Nothing existing may be modified.** A concurrent session is improving the
   test suite; a change of ours in a shared file is a merge conflict at best
   and a corrupted measurement at worst. So: **new files only**, in a new
   directory. No edit to `app/main.py`, `app/api/*`, `app/web/*`,
   `.claude/launch.json`, `tools/*` or any test.
2. **The backend is fixed.** Phase 1 uses `/api/v1` exactly as it stands. Any
   admin capability with no endpoint behind it is **skipped**, not faked and
   not stubbed — a control that cannot work is worse than an absent one
   (the product's own *absent, not disabled* rule).
3. **Reachable from a phone.** The dev/preview server binds `0.0.0.0`, like
   `:8757` and `:5173` already do, for the same reason.

## What the API can and cannot support

Audited against the committed contract (`app/api/openapi.json`, 49 routes).

| The owner asked for | Endpoint | Verdict |
|---|---|---|
| create new libraries | `POST /libraries` | ✅ built |
| rename a library | `PATCH /libraries/{id}` | ✅ built (came free) |
| stats on libraries | `GET /books`, `/shelves`, `/duplicates` | ✅ built, derived |
| stats on books | `GET /books?status=…&limit=1` → `total` | ✅ built, derived |
| see all books in the system | `GET /books` per library, merged | ✅ built |
| moderate a book (approve / fix / delete) | `POST /books/{id}/approve`, `PATCH`, `DELETE` | ✅ built |
| **add users** | — | ❌ **SKIPPED — no API** |
| **assign users / change roles** | — | ❌ **SKIPPED — no API** |
| **stats on users** | partial: `GET /meta`, `GET /libraries` | ⚠️ only what one account can see |
| delete a library | — | ❌ no API (deliberately absent server-side) |

**On users, precisely.** There is no member listing, no invite, no role
change, and no login — `Principal` is built by the server
(`app/api/deps.py`), so the console literally cannot see a second account.
`GET /libraries` reports the role *this* account holds per library, and
`GET /meta` names the account. So the Access screen shows exactly that and
says plainly what is missing and why. It has **no disabled invite button** —
per the constraint above, and because a greyed-out control that never becomes
clickable reads as a bug.

**Counting is free, and that is what makes the dashboard cheap.**
`BookPageDTO` carries `total` alongside `items`, so `?limit=1` is a COUNT
query costing one row. A library's whole status breakdown is 4 such requests;
the dashboard is ~6 per library and a household has one to three.

## Architecture

```
app/admin/                 a SECOND client, sibling to app/web — not a tab in it
  package.json             own toolchain; own node_modules; Node >= 24.15
  vite.config.ts           port 5174, host: true, proxy /api -> 127.0.0.1:8757
  index.html
  src/
    api/client.ts          typed client; library is PER-CALL, never global
    api/schema.ts          type-only re-export of app/web's GENERATED schema
    lib/i18n.tsx           he/en + dir, Hebrew default
    lib/format.ts          dates, numbers, plurals
    lib/useAsync.ts        the one data-fetching primitive (request-id guarded)
    lib/stats.ts           the derivation: counts -> LibraryStats, PURE
    App.tsx                hash router + chrome
    dash/                  Dashboard: system totals + per-library table
    libraries/             list, create, rename, drill-in
    books/                 every book in the system, filtered/sorted/paged
    access/                account + memberships + what is missing
    styles/                tokens/base — its own, deliberately (see below)
  README.md                how to run it, including from a phone
```

### Decisions worth arguing about

**It is a separate Vite app, not a route in `app/web`.** Three reasons, in
order of weight: the constraint above forbids touching `app/web`; an admin
surface must be *deployable separately* from the household client (that is the
whole point of the split, and phase 2 will put a login in front of it); and
the two have opposite tenancy models — see next.

**The library reference is a PER-CALL argument here, never module state.**
`app/web/src/api/client.ts` keeps the selection in a module global and argues
for it well: one module instance is one person's tab, and the selection is as
global as the browser window. **That argument does not survive here.** Every
admin screen is *cross-library by nature* — the dashboard fans out over every
library at once — so a global "current library" would be a variable that is
wrong in the middle of every render. `admin/api/client.ts` therefore takes
`libraryId` on each call and has no setter at all.

**Types come from `app/web/src/api/schema.d.ts`, by a type-only import.**
Copying the generated file would create a second artefact that
`tools/api_contract.py --check` does not police, and it would go stale
silently — the exact failure mode this repo has already recorded twice (the
stale `:8757` build, the stale Vite module graph). A `import type` is erased
at build time, so there is no runtime coupling between the two clients: only
the compiler crosses the line, and only in the direction that keeps them
honest. If `app/admin` is ever extracted to its own repo, `npm run gen:api`
against `app/api/openapi.json` replaces the import in one line.

**Its own CSS tokens, rather than importing `app/web/src/styles`.** Not
duplication for its own sake: an admin console is a dense table surface where
the product is a reading surface, and the shared file would immediately need
to serve two intents. It keeps the same *idiom* (custom properties, both
colour schemes, `unicode-bidi: plaintext` + container-keyed `text-align` for
mixed Hebrew/Latin strings — UI_PLAN §7.2, which is a correctness rule, not a
theme).

**Hebrew default, English available.** Same reason `app/web` gives: the
English mode is not for English speakers, it is the only honest way to see
that the layout mirrors. Library names, book titles and author names are
Hebrew, so every user-generated string carries `.rtl-safe`.

**No delete of a library, and no cascade of any kind.** The server does not
offer it (`app/api/routers/libraries.py` says why at length), so neither does
this. Book deletion IS offered, behind a typed confirmation, because
`DELETE /books/{id}` exists and records a standing rejection — a real,
supported, reversible-by-restore act.

### The one honest compromise: cross-library paging

`GET /books` pages one library. There is no endpoint that pages across
libraries, and inventing one is a backend change. So the Books screen has two
modes:

- **one library selected** — true server-side search, sort and paging. The
  ranking is P1.5's measured Hebrew search, unaltered;
- **all libraries** — each library's books are fetched in pages of 200 up to a
  cap, merged, then sorted and paged in the browser. The screen says how many
  it loaded and whether the cap was hit, rather than implying it saw
  everything. Client-side ordering uses `localeCompare`, which is *not* the
  server's normalized key, so the merged order can differ slightly from a
  single library's — stated in the UI, not hidden.

This is the shape to revisit first when the backend can be touched: a
`GET /admin/books` that resolves across memberships would remove it entirely.

## Built and verified (2026-08-10)

43 client tests, typecheck and build all green. Two rules were mutation-checked
by reversing them and watching a *named* test fail: `unapproved` counting
anything but the `auto` rung, and the book panel losing its `key`.

Verified **live** against the real `work/product.db` (snapshotted before,
restored after — the routine this repo already follows for live writes; the
test library created during the pass is gone, 286 books and schema v12
intact):

- the dashboard fanned out over both real libraries — 286 books, 109 awaiting
  approval, 141 approved, 36 manual (they add up), with per-library rows;
- merged cross-library paging over 286 real Hebrew titles, 12 pages, both
  libraries labelled per row;
- server-side Hebrew search found 8 Asimov books across **two spellings** of
  his name, and the sort control went inert with its reason on screen;
- the detail panel offered *approve* on an `auto` record and **not** on an
  `approved` one; delete asked first;
- create and rename both wrote through and appeared without a refetch;
- every export link carried `?library=<id>` — the query-parameter transport,
  which is the half a header cannot do;
- English mode mirrored (`dir` ltr, `text-align` flipped, `unicode-bidi:
  plaintext` intact), and at a 375px viewport the page did not scroll
  sideways while the wide table scrolled inside its own box.

Two bugs were found and fixed in the process, both worth knowing:

⚠ **The rename cell held its own `editing` flag while the page held another.**
The page opened the editor; the cell, still `false`, rendered the read view, so
rename did nothing. Whoever renders a control owns the text in it; *who* is
editing is the table's business.

⚠⚠ **An effect that copies props into state can be silently defeated by an
effect above it.** The panel reset its form when the book changed, via an
effect. The focus/Escape effect above it depended on `onClose` — a fresh
closure every render — so it re-ran on every commit, and `.focus()` blurring
the edited input makes React fire a change for the controlled value, which
re-renders *during* the effect flush and leaves the reset effect comparing
against the very values it was meant to react to. **The reset never ran**, and
the ring's first version of the test passed anyway because it asserted through
the same stale render. Fixed twice over: the listener is installed once behind
a ref, and the reset is now a `key` on the panel — remounting needs no effect
ordering to be right.

⚠ The Browser pane did not composite frames this session (screenshot timed
out, as in P2.8/P2.10/P3.1), so the checks above are DOM structure, layout
geometry and API state — real verification of wiring, **not** of paint.
`getBoundingClientRect` still returns real numbers without compositing;
`getComputedStyle` readings taken here should be treated as unconfirmed.

**Not yet in CLAUDE.md** — this build could not touch existing files. Fold a
short `app/admin/` section in when the test-suite session lands.

## Phase 2 (needs backend work — not in this build)

Named so they read as deferred rather than forgotten:

- **member management**: list members of a library, invite, change role,
  remove. Needs P4.1's login to have anyone to invite and P4.3's invite flow;
- **an admin identity**: today the console sees one dev-trusted account and
  therefore one account's libraries. A real admin sees libraries it is not a
  member of, which is a new authorization axis, not a new screen;
- **delete a library**, with the six-aggregate cascade and P3.5's blob purge;
- **`GET /admin/books`** cross-library, to retire the compromise above;
- **storage/usage stats** (blob bytes per library) — nothing reports them.

*(Three of those five landed in revision 2, below — the admin identity, the
cross-tenant book listing, and the account listing that made "statistics about
the users" possible at all.)*

---

# Revision 2 (2026-08-10): system admin, not account admin

The owner read the first build and named the confusion it had inherited:

> there are 2 types of admins. System admin (the one I intended you to work on)
> and a single library admin. … the system admin can see everything, including
> statistics about the users. In parallel there is an admin per account (can be
> more than one) and that admin can add family members.

Revision 1 was the second thing. It could only ever add up the libraries the
operator happened to belong to and call the result "the system" — true for
exactly one account, quietly wrong for any other. This revision makes it the
first.

## Why it needed a backend

**`/api/v1` cannot answer a cross-tenant question, and no client can make it.**
Every product route resolves a library through `app/api/deps.py:current_library`,
which answers from the caller's MEMBERSHIPS. That is not an oversight to route
around — it is §4.2 ("a foreign record reads as ABSENT"), and the
tenant-isolation suite exists to keep it true. Loosening it to serve a console
would weaken the product's isolation for everyone.

So: **`app/staff_api/`, a second application**, on port 8758, prefix
`/api/staff/v1`, with its own credential. New files only — the "touch no
existing file" constraint from revision 1 still held.

- **read-only by construction.** Every statement is a `SELECT`, the connection
  sets `PRAGMA query_only`, and there is **no `migrate()` call anywhere**.
  CLAUDE.md records that merely importing `app.main` advances the real
  database's schema, so a console that opened the file the usual way would
  upgrade the owner's data as a side effect of being *looked at*. A test pins
  `user_version` across every query;
- **its own read model** (`queries.py`) rather than the stores: every port
  method leads with a `LibraryRef` by design, so "every library at once" through
  them would mean either loosening the ports or N queries per figure. The price
  is duplicated SCHEMA knowledge, paid up front by a `self_check()` that refuses
  to serve a database whose shape has moved — instead of surfacing a stale
  column as a plausible wrong number nobody double-checks;
- **no duplicated RULES.** The §5.1 status ladder is one SQL expression derived
  the way the entity derives it, and search imports `app.domain.search` —
  P1.5's measured Hebrew rules, verified live to agree with the product exactly.

## A system admin is not a Role

The most important structural call, and the tempting mistake it avoids:

> `app.domain.tenancy.Role` says who you are **within one library**. A system
> administrator is a member of nothing and must see tenants they were never
> invited to. Putting `SYSTEM_ADMIN` in that enum would make every membership
> row a place someone could grant themselves the world.

It belongs on the *operator*, orthogonal to memberships — today a shared token
on a separate service; later `Account.is_staff` or a `StaffGrant`, with its own
audit trail. The Access and Users screens name the two jobs apart in both
languages, because the confusion this revision fixes was verbal first.

## Reading is cross-tenant; writing is not

The console talks to both services, and the split is the useful one:

- **staff service** — everything the operator can SEE: every account, every
  library, every book, system totals;
- **product API** — everything they can CHANGE, which is only ever inside
  libraries they are themselves a member of.

So a library or a book outside those memberships shows its numbers and **says
it is read-only**, rather than offering a button that would 404 on click. That
is a deliberate limit: a system administrator silently rewriting a household's
book titles is a power this product has no reason to grant before it has a
login, an audit trail, or anyone to explain it to.

## The compromise revision 1 documented is gone

`GET /api/staff/v1/books` pages and ranks across every tenant server-side, so
the browser-side merge — and its "the order may differ slightly" apology — was
deleted along with `books/query.ts`. That was the one thing revision 1 named as
first to fix once the backend could be touched.

## Users: reported, not profiled

`GET /api/staff/v1/accounts` reports identity and membership and deliberately
**not** activity. "Statistics about the users" is a fair thing for an operator
to want; a per-person feed of what someone has been photographing and reading
in their own home is a different and much larger power, and this product has no
login, audit trail or consent story to justify it. Aggregate figures live on the
library rows, where they describe a collection rather than a person. A test
pins the absence.

## The credential

`BOOKSNAP_STAFF_TOKEN`, compared with `secrets.compare_digest`, accepted as
`X-Booksnap-Staff` or `Authorization: Bearer`. **Unset means the service still
serves and says so** (`authenticated: false`), which the console turns into a
banner: refusing to start would leave the owner with a console that cannot be
opened and no obvious reason, and silence would leave a cross-tenant surface
open on the LAN with nothing on screen to suggest it.

## Still deferred, and now for a sharper reason

Member management (invite / remove / re-role) is the **account admin's** job,
not this tool's — and it has no route in either service. It needs P4.1's login
to have anyone to invite and P4.3's flow to invite them with. Deleting a library
still needs P3.2's policy and P3.5's blob purge.

⚠ **A second composition root now exists** (`app/staff_api/main.py`).
`tests/test_layering.py` keeps `COMPOSITION_ROOTS` a one-element set precisely
so a second one is "a visible, argued-about diff rather than an accident", and
this build could not edit that file. The argument is written at the top of
`main.py`: the rule that exemption protects is `app/api -X-> app/adapters`, and
nothing here is under `app/api` — the staff service wires a read model that
imports no adapter at all, so the exemption is not needed yet. Add it to the
list the day it binds a real adapter.

⚠ `tests_staff/` exists because `tests/run_all.py` globs `tests/test_*.py`, and
adding a file there would change what the concurrent test-suite session runs.
It is a one-line rename once that lands.

## Verified live (revision 2)

Against the real `work/product.db` (snapshotted before, restored after; a
foreign tenant seeded through the real adapters to exercise the read/write
split, then removed with the snapshot — 286 books and schema v12 intact):

- **401** without a token, **401** with a wrong one, **200** with the right one,
  over real HTTP; the console's token gate replaced the whole app until one was
  entered, then let it through;
- the dashboard reported the real system: 1 account, 2 libraries, 2 memberships,
  286 books, 286 copies, 109 awaiting / 141 approved / 36 manual, 5 reads —
  from one request, not a per-library fan-out;
- staff search agreed with the product's **exactly** on four terms (8 / 0 / 2 / 0);
- the seeded foreign library appeared in the list with **no rename and no export
  links**, reading *"read-only — you are not a member"*, and its book's panel
  offered only *close*;
- Users listed both accounts with their roles — a screen `/api/v1` cannot
  produce.

51 client tests and 19 Python tests, typecheck and build green. Mutation-checked
in this revision: dropping the staff token from the transport, and ignoring
`writable` in the book panel, each fail named tests.

⚠ The Browser pane did not composite frames this session either, so these are
DOM- and API-level checks, not paint. (A coordinate click on the token form
also failed to register for the same reason and had to be driven through the
DOM — worth knowing before reading that as an app bug.)
