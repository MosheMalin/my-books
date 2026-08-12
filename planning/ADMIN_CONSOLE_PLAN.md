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

⚠⚠ **NARROWED by revision 6 (2026-08-13).** What follows was the governing
rule and is now only half of it: the console no longer moderates a
household's CATALOGUE at all, member of it or not. It still writes tenancy
(create/rename a library). The split below described what may SUCCEED; the
rule now is whose job it is.

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

⚠ `tests_staff/` existed because `tests/run_all.py` globs `tests/test_*.py`, and
adding a file there would have changed what the concurrent test-suite session
ran. **Folded back in** once that branch merged: the suite is
`tests/test_staff_api.py`, and converting it from `unittest.TestCase` classes
to the runner's own module-level `test_*` convention is what actually made it
run — a class-based module is collected as *zero tests* and reports `ok`.

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

51 client tests and 20 Python tests, typecheck and build green. Mutation-checked
in this revision: dropping the staff token from the transport, and ignoring
`writable` in the book panel, each fail named tests.

⚠ The Browser pane did not composite frames this session either, so these are
DOM- and API-level checks, not paint. (A coordinate click on the token form
also failed to register for the same reason and had to be driven through the
DOM — worth knowing before reading that as an app bug.)

---

# Revision 3 (2026-08-10): the constraint is lifted

Everything above was built under *"nothing existing may be modified"*. The
owner ended it before pillar 4 — *"I want to put some order in the current
state"* — and four of this document's own recorded compromises went with it.
The full account is in CLAUDE.md, "Two applications, four packages"; what
matters HERE is which of this plan's notes are now obsolete:

- **the console no longer re-implements the product client.**
  `app/ui/` is the shared library, extracted mainly from `app/web` because
  that is the app the owner has actually used. The sort control was the
  owner's own example: this console had it as a bare `<select>` with a `↑/↓`
  button beside it, which read as two questions and dropped the reset-on-key-
  change rule. It now draws the product's, and the rule is declared per
  option so it cannot be forgotten;
- **"Its own CSS tokens" still holds — the argument was right.** A dense
  table surface is not a reading surface. What changed is that shared
  components draw from `--ui-*` and each app maps its palette onto them, so
  the console keeps its own colours without keeping its own copy of the
  controls. `.rtl-safe` moved to the shared sheet: §7.2 is a correctness rule
  about Hebrew, and the two copies had already drifted (`[dir=…]` here,
  `:root[dir=…]` there);
- **"Types come from `app/web/src/api/schema.d.ts`" is obsolete.** The
  generated contract lives in the shared package now, so neither client
  reaches into the other's source at all — and a test in each ring says so;
- **"the staff DTOs are hand-written, keep them in step" is obsolete.**
  `tools/api_contract.py` generates `app/staff_api/openapi.json` →
  `app/admin/src/api/staff-schema.d.ts` on the same committed-artefact rule
  as the product's. A renamed staff field is a compile error here rather than
  an `undefined` in a table;
- **`tests_staff/` is gone, and its tests run with the PRODUCT.** Two
  sessions answered this from opposite ends: one folded the suite into
  `tests/test_staff_api.py` (⚠ a `unittest.TestCase` module is collected as
  ZERO tests by `run_all.py` and still reports `ok` — the class-based suite
  was passing nothing), the other kept it separate with its own `--admin`
  gate. The fold wins, and a data-integrity review supplied the argument:
  this read model duplicates the product's SCHEMA, so what breaks it is a
  MIGRATION — made on the product side, where a console-keyed gate never
  runs. Reproduced by renaming `books.sort_author`. What was genuinely
  missing is that neither the staff suite nor this console's client tests
  were in any gate; `tools/check.py --admin` covers the client half now;
- **the second composition root is argued, not merely noted.**
  `tests/test_layering.py` holds the argument as a test: the staff service
  imports no adapter (so it needs no exemption *yet*), no product route, no
  migration, and never `app.main` — that last one because importing the
  product's composition root MIGRATES the owner's real database, which a
  read-only console must never do by being looked at. The day it binds an
  adapter, the test fails and someone adds it to `COMPOSITION_ROOTS`, which
  is the discussion that list exists to force.

Phase 2's list is unchanged: member management still needs P4.1's login,
deleting a library still needs the six-aggregate cascade and P3.5's purge.

---

# Revision 4 (2026-08-11): the console stops thinking in one library

The owner read revision 3 and named what is still wrong with it — not a bug,
a *frame*:

> unlike the user application, it should not think in terms of a single
> library or single account. when it comes to books info, it's either about
> aggregation or lists. … in the tab users. It should be account. … And indeed
> rather than Shelf, the images are images.

Revisions 1–3 built a system console out of the household client's nouns. Every
screen still answers *"…in which library?"*, because that is the question the
product is built to answer and the code was borrowed from it. An operator never
asks it. Their questions are **how many**, **across whom**, and **which of
them**. Three of the console's nouns are wrong for that reader, and this
revision replaces them.

## The three wrong nouns, and what replaces each

| today | the operator's question it fails | revision 4 |
|---|---|---|
| a book row belongs to ONE library | *"is this title common, or does one household have it?"* | a **work**: one row per `book_key`, "in N libraries", the instances behind a drawer |
| the **Users** tab lists people | *"who are my customers and how big are they?"* | an **Account**: created, admins, users, books, image storage — the people are a section inside it |
| the **Shelves** table | *"what has been photographed, how much space does it take, what did the engine make of it?"* | an **Image**: the photograph is the thing; the shelf it is filed at is a *binding* it shows, not its identity |

### 1. Books aggregate into works

A book row today is `(library_id, book id)` and the table carries a **Library**
column. That column is the frame the owner is naming: it makes the system-wide
book list a concatenation of household lists rather than a catalogue.

The aggregation key is **`app.domain.text.book_key`** —
`normalize(title)|normalize(author)`, the same function the product keys books
with and the same one `booksnap.library` uses. CLAUDE.md's rule is that two
normalizers drift; this is the third place that would have grown one. It is
computable in SQL without a new column, because `books.norm_title` and
`books.norm_author` are already stored and already written by that function.

What the row shows: title, author, the strongest status among its instances,
**how many libraries hold it**, total copies, and **when it was first added
anywhere**. What it does not show: a library, a shelf.

Three consequences worth stating, because each is a decision:

- **the displayed title is a choice, not a fact.** Two households may hold one
  work under two spellings that normalize alike (that is the whole point of the
  key). The rule is: prefer the strongest §5.1 status (`manual` outranks
  `approved` outranks `auto` — a human typed it), then the earliest `added_at`,
  then the id. Stated in the query and pinned by a test, so it cannot become
  "whatever SQLite returned first";
- **writing stays per instance.** Approve/edit/delete act on one household's
  book, through the product API, under revision 2's read-cross-tenant /
  write-your-own-memberships split. So the actions live in the drawer's
  per-library list, never on the aggregate row — there is no "approve
  everywhere" button, and there must not be one before there is an audit
  trail;
- **the library filter survives as a filter.** "Works present in library X" is
  a legitimate narrowing and it is how the account drawer links into this
  screen. What dies is the library as a *column* and as a book's *property*.

### 2. The Users tab becomes Accounts

The owner's list for a row — *when it was created, who are the admins, how
many users, how many books, images storage* — describes a **customer**, not a
person. A person has no admins and no users.

⚠⚠ **RETIRED by revision 5 (2026-08-13) — read this as history.** Everything
in this subsection was true when written and is not true now: the tenancy
boundary moved to the **Account** (VISION §4.1 [REVISED 2026-08-11]), P3.7b
made it a real record, and P3.7e made these screens say so. The paragraph
below is kept because it is *why* the boundary moved — a plan needing an
apology for its own vocabulary was the evidence the model was wrong.

⚠ **So the console's "account" is the tenant, and today the tenant record is a
`Library`.** This is a naming decision made deliberately, and it is the one
place this revision diverges from the domain's vocabulary:

- **the wire keeps `library`.** VISION §4.1 settled it twice — *Account is a
  person, one identity*; *Library is the isolation boundary*; *there is ONE
  tenancy layer, not two*. Renaming the entity would re-decide a settled thing
  and break the product client, the stores, and every `library_id` on every
  row;
- **the console says "account"**, because that is the operator's word for the
  thing they administer, and VISION itself writes *"an admin inside one
  account's library"* (§4.2) — the two words are already used as near
  synonyms at that level, and §4.1 records that **one library per account is
  the default and the normal case**;
- the drawer shows the **library id** under the account name, labelled as
  such, so the mapping is visible rather than hidden. Nothing is renamed in
  storage and the reversal cost is a tab label plus one page.

**The Libraries tab merges into it.** Two tabs listing the same entity under
two names is exactly the incoherence this revision is fixing; the old
Libraries table already carried most of the columns the owner asked for.
Create-library and rename stay on the merged screen, where they always were.

⚠ **A person with no membership would become invisible.** The Users tab was
the only screen that listed people directly; a tenant-shaped list cannot show
someone who belongs to no tenant. That is a real regression and it is
answered, not accepted: the Accounts screen carries an *unaffiliated accounts*
section, the mirror of the existing `orphan_libraries` warning (a library with
no member ↔ a member with no library), and `/overview` reports both.

**Reported, not profiled — still.** Revision 2's line holds: the drawer's
Users section shows identity, role and join date, never a per-person activity
feed. Aggregate figures describe the collection.

### 3. Shelves become images

> rather than Shelf, the images are images. they will later be bound to
> shelves/bookcase. but on their own they are images … the runs and result are
> bound to the image.

This is not a rename — it is the console dropping a placeholder it was
displaying as if it were furniture. VISION §4.1a is explicit: *"one image = one
shelf" is a PLACEHOLDER with a recorded exit* (P2.1), and intake mints a shelf
identity per image until pillar 6's map can say two photos are the same piece
of wood. So a console "shelves" table is mostly a list of photographs wearing a
noun they have not earned, and it will keep being one until P6.1b.

The image is the durable thing, and the data agrees: `claims.capture_id` binds
every engine finding to the photograph it came from, and `reads.capture_ids`
records which photographs a run consumed. So an Images screen can answer *what
was photographed, when, how big, what ran on it, and what it found* without
naming a shelf at all — and it shows the shelf/depth it is currently filed at
as a **binding**, secondary and labelled, the slot pillar 6 will replace.

⚠ **The staff service still serves no image BYTES.** Metadata crosses tenants;
photographs do not. An operator looking at a household's actual pictures is a
larger power than counting them, and revision 2's argument (no login, no audit
trail, nobody to explain it to) applies with more force to a photograph than to
a title. Thumbnails appear only for libraries the operator is a member of,
fetched from the product API exactly as the household client fetches them —
the same read/write asymmetry, one axis over.

### 4. Storage: where the bytes are counted

Nothing in the database knows how large a photograph is — `app/ports/blobs.py`
keeps bytes out of it on purpose (D1), and size lives in the on-disk sidecar
`DiskBlobStore` writes. The staff service may not import that adapter
(`tests/test_layering.py` pins it) so it reads the blob tree directly, in one
new file, and **knows the layout on purpose** — the identical trade
`queries.py` already makes with the schema, with the identical guard: a test
pins the staff reader's path against `DiskBlobStore`'s, so a layout change
fails a test instead of quietly reporting 0 MB.

Counted honestly: **every file under the library's blob dir**, thumbnails
included, because that is what the disk holds. Sidecar JSON is counted too and
is negligible; the number is "space this account occupies", not "sum of the
originals".

## The items

Each is one cycle, landed on `main` before the next. Reviewer sets follow
CLAUDE.md's table; `review-data-integrity` is standing on every server item
because every one of them is a cross-tenant read.

| # | item | reviewers | done when |
|---|---|---|---|
| **A1** | **Works in the read model** — `works()` / `work_instances()`, `GET /works`, `GET /works/instances?key=`, ranked search over the aggregate, the display-title rule | quality, data-integrity, security | staff ring green; the display-title rule and the "one row per `book_key` across tenants" rule each pinned by a mutation-checked test; contract regenerated |
| **A2** | **Images and storage in the read model** — `images()` (paged, cross-tenant, per-image reads/claims from `claims.capture_id` + `reads.capture_ids`), `storage.py` reading the blob tree, account-level figures (`admins` by name, `image_files`, `image_bytes`), `accounts_without_membership` on `/overview`; retire `/libraries/{id}/shelves` | quality, data-integrity, security | as above, plus the layout-drift test against `DiskBlobStore`, and a missing blob root reported as zero rather than a 500 |
| **A3** | **Console: Works** — the aggregate table, "in N libraries", the work drawer with its per-library instance list and per-instance actions, sort by spread | quality, ux | admin ring green; a book in a library the operator does not belong to still shows and still says read-only; browser-verified |
| **A4** | **Console: Images** — the cross-tenant image list, filters, the image drawer (metadata, binding, reads and what they found), thumbnails only where the operator is a member | quality, ux, security | admin ring green; no image bytes requested from `:8758` by any code path; browser-verified |
| **A5** | **Console: Accounts** — the merged tab (Libraries + Users), the account drawer with Users / Books / Images sections, `#/accounts`, redirects from `#/libraries` and `#/users`, unaffiliated accounts, dashboard restated in images + storage; retires `/libraries/{id}/shelves` with its last caller | quality, ux | admin ring green; verified in a real browser against the real database (snapshotted first); old routes still land somewhere sensible |

*Order amended while executing:* the Accounts screen links into Works and
Images, so it lands LAST — otherwise its drawer would carry a "see all images"
link to a tab that does not exist yet, which is the disabled-control shape this
project refuses. The owner's numbering (books, accounts, images) is a priority
order, not a build order, and books still land first.

### What this revision does NOT change

- the two services, their two credentials, and the read-cross-tenant /
  write-your-own-memberships split (revision 2) — every item above sits
  inside it;
- the domain, the schema, and the product client. **No migration.** Every
  figure here is a new `SELECT` over columns that already exist, or a
  `st_size` on a file that already exists;
- "a system admin is not a `Role`";
- member management, deleting a library, and metering — still Phase 2, still
  waiting on P4.1 / P3.2 / P3.5 / P5.1.

## Landed (2026-08-11)

All five items, each on `main` before the next, each with its reviewers.

| # | item | landed | reviewers | what they changed |
|---|---|---|---|---|
| A1 | works in the read model | ✅ | quality, data-integrity | three majors, all *wrong stated reasons* — see below |
| A2 | images + storage | ✅ | data-integrity, security | six majors, including a 13.6-second unauthenticated request |
| A3 | console: works | ✅ | quality | a real bug: the drawer lied about the spread it had just changed |
| A4 | console: images | ✅ | (folded with A2's) | — |
| A5 | console: accounts | ✅ | (folded with A3's) | — |

### What the reviews were actually for

Every major finding in this epic was a **stated reason that was wrong**, not a
behaviour that was wrong — which is the failure mode CLAUDE.md names ("a wrong
stated reason is what makes the next reader delete the guard"). Worth recording
as a pattern, because it recurred five times:

- `WORK_KEY_SQL` recomputed a key that `books.book_key` has stored since schema
  v1, under a comment claiming that avoided needing a new column;
- `WorkDTO.instances` documented a state `UNIQUE INDEX books_library_key`
  forbids — and was why three aggregates were mutually substitutable with no
  test noticing;
- the search `HAVING` was justified by "found by any household's spelling",
  which cannot happen because `search_text` derives from the same normalized
  pair as the key;
- `_walk`'s "symlinks are not followed" read as a guarantee about Windows
  directory junctions, which ARE followed;
- `onChanged`'s docstring said it kept the aggregate honest; it refetched the
  list and left the open drawer stale.

Two more that were behaviour, and both were measured rather than argued:

- **`/images` cost 13.6 seconds of CPU for one `?limit=200`** at 4000 reads —
  two correlated subqueries per row, each scanning every read in the system,
  on a service whose credential may be unset. Grouped pre-passes: 14ms;
- **the guard meta-test could not see a non-GET route or a `Mount`.** Both
  demonstrated green: an unguarded `POST /overview` served every tenant's
  totals, a `StaticFiles` mount served CLAUDE.md unauthenticated.

### Verified live (revision 4)

Against a copy of the owner's real database and blob tree — 286 books, 2
tenants, 36 files / 21.5 MB of photographs, taken with SQLite's backup API so
the live data was never opened:

- **286 books collapse to 283 works.** The three held by both households (a
  Maria V. Snyder trilogy) report *2 libraries · 2 copies* and list each
  household's own spelling underneath;
- **storage is read from the disk**: 21.5 MB total, 14.1 + 7.4 per account,
  matching an independent `os.walk`. With the blob root removed the console
  says *"we did not look"* rather than marking every photograph lost — the
  third state a review insisted on;
- **an image drawer** shows a real 4032×3024 `IMG_7849.jpeg`, 3 MB, filed at
  depth 1, with *1 run · 12 auto · 0 review · 14 unmatched*. Its thumbnail
  loads from `:8757` and never from `:8758`;
- **the read/write split, both ways**: with the product API down every
  household row reads *"not editable"*; with it up both offer edit and delete,
  and neither offers approve, because both copies are `manual` (§5.1);
- **the account drawer** carries users / books / images with the library id
  labelled beneath the account name;
- **Hebrew**: `dir=rtl`, every screen translated, the retired routes
  (`#/libraries`, `#/users`) landing on the accounts list.

⚠ The Browser pane did not composite frames — the third session in a row (see
revision 2) — so this is DOM- and network-level verification, not paint.

### Still deferred, unchanged

Member management (P4.1 login, P4.3 invites), deleting a library (P3.2 policy,
P3.5 purge), metering (P5.1). And two things this epic found and did not fix,
because neither belongs to it:

- **`filename` is uncapped on the WRITE path.** A review measured 40 MB per
  console page from unauthenticated LAN uploads with megabyte-long names. The
  console caps what it republishes at 200 characters; the real fix is at the
  port where the name enters, which is product-side;
- **`/works` costs two full group-sorts of `books` per request** — 8ms at 175
  books, 2.8s at 70k. Fine forever at this product's scale; the lever, when
  one is needed, is caching `total` or materialising the aggregate, NOT
  rewriting the correlated subqueries (measured at 11% of it).

---

# Revision 5 (2026-08-13): the gloss is retired — an account is an Account

Revision 4 made one naming decision under protest, wrote it down carefully,
and put the mapping on screen so nobody would be misled:

> ⚠ **So the console's "account" is the tenant, and today the tenant record is
> a `Library`.** … the drawer shows the **library id** under the account name,
> labelled as such, so the mapping is visible rather than hidden. Nothing is
> renamed in storage and the reversal cost is a tab label plus one page.

**That paragraph is now obsolete, and it is also what caused its own
obsolescence.** VISION §4.1 **[REVISED 2026-08-11]** cites it directly: a plan
that needs a paragraph explaining that the operator's word for a customer maps
to a different record than the domain carries is a model that is wrong, not a
plan that is unclear. The owner moved the tenancy boundary to the **Account**,
P3.7b made it a real record that a library belongs to, and P3.7e is where
these screens caught up. The full argument is in `docs/HISTORY.md`, "P3.7 —
the tenancy boundary moves from Library to Account"; the decomposition is
`planning/TENANCY_BOUNDARY_PLAN.md`.

The reversal cost was, as predicted, small — but not because the mapping was
harmless. It was small because it had been *written down*.

## What revision 4 said, and what is true now

| revision 4 | since P3.7e |
|---|---|
| the console's "account" is a `Library` record | it is an `Account` — a real row, with its own id, that libraries belong to |
| the wire keeps `library` | `/api/staff/v1/accounts` returns CUSTOMERS (P3.7d); `LibraryDTO.account_id` names the owner |
| the drawer shows the library id under the account name, labelled | **`t.acct_library_id` is DELETED, not relabelled.** The mapping is data now: the drawer lists the account's libraries, each row carrying its own id |
| a row is a tenant, and a tenant is a collection | a row is a customer; its collections are one level down, in the drawer |
| one library per account is the default and the normal case | still true, and still the guidance — but the console no longer *assumes* it. The owner's own database is one customer with two libraries, and revision 4's screens drew that as two customers |

## The three-way header split was a prerequisite, not a cleanup

`t.th_account` was rendered over **three different entities**: customers (the
accounts table, the dashboard), people (the unaffiliated list, the drawer's
members) and libraries (the images table and panel). One string over three
nouns is precisely the mechanism by which a console keeps saying "account"
about whatever happens to be in the row. It is `th_account` / `th_user` /
`th_library` now, and the split had to land *before* the screens could be
correct — not after them as tidying.

## What P3.7e changed, and the decisions inside it

- **rename and export left the accounts table.** They act on a library, and a
  row is no longer one; an account row carrying *rename* cannot say which
  collection it renames. They sit on the library rows in the drawer — **inside
  the name cell, stacked**, not in a trailing actions column: a drawer is
  capped at `min(720px, 100%)` and the column version measured 834px, putting
  rename and both exports outside the box and out of the accessibility tree
  until the table was scrolled sideways;
- **`LibraryDTO.members`/`admins` are never rendered on a library row.** Both
  mean *the owning account's people* since P3.7b, so printing them per
  collection shows one household once per shelf it keeps. The headcount
  appears exactly once, on the customer;
- **`#/accounts/<id>` carries an account id now and carried a library id
  before.** `parseHash` stays pure — an id is opaque and the parser cannot
  tell them apart without asking the server — so `AccountsPage` resolves:
  account first, then the account that OWNS the named library. An operator's
  stale bookmark lands on the customer it was about; an id naming neither says
  so rather than opening the list in silence;
- **the drawer's book/image previews fan out over the account's libraries and
  merge newest-first.** This is *not* revision 1's retired browser-side merge:
  that one paged and RANKED a catalogue with `localeCompare`, a different key
  from the server's normalized one, and the screen had to apologise for the
  order. This merges ≤5 rows per library on an ISO timestamp. What it cannot
  do is page, which is why the browse links stay per library;
- **absent and unknown are different states.** With `/users` failing, revision
  4's screens rendered every customer as *"no admin"* and every drawer as
  *"nobody can see or administer this account"* — states `new_account` and
  `NoAdminLeft` make unreachable — with no error anywhere. The alarms read the
  account row now, `peopleKnown` separates the two, and the error box is no
  longer gated on the table being empty.

## Phase 2, unchanged

Member management still needs P4.1's login and P4.3's invite flow; deleting a
library still needs P3.2's policy and P3.5's blob purge; metering still waits
on P5.1. And revision 4's two open items are still open: `filename` is uncapped
on the WRITE path (product-side), and `/works` costs two full group-sorts of
`books` per request (fine at this scale; the lever is caching `total` or
materialising the aggregate, NOT rewriting the correlated subqueries — measured
at 11% of it).

## Verified live (revision 5)

Against a **copy** of the owner's real database and blob tree, taken with
SQLite's backup API so the live data was never opened (1 account, 1 user, 2
libraries, 286 books — the figures were checked against the copy before
anything was believed):

- the Accounts screen shows **ONE row** with **2 libraries, 286 books, 1
  user** — the shape revision 4's console could not draw. The drawer lists
  both collections with their own ids (272 books and 14);
- the dashboard reads **1 account / 1 person / 2 libraries** as three separate
  tiles;
- the fan-out is one `/books?library_id=…&limit=5` and one
  `/images?library_id=…&limit=5` **per library** — four requests, no
  over-fetch — and the merged previews carry a library column plus an
  "across every library of this account" sub-line, so a preview dominated by
  one collection cannot be misread;
- every export link carries `?library=<id>`; both formats return 200 with
  per-library filenames;
- all four routes land correctly: an account id opens its drawer, a **stale
  library id** opens the owning account's, and `#/libraries` / `#/users` still
  reach the list;
- Hebrew mirrors: RTL→LTR moves the drawer `[0,720]`→`[560,1280]`, the header
  order reverses, and at 375px `document.body.scrollWidth === clientWidth` in
  both directions while the wide tables scroll inside their own boxes.

⚠ **Paint is UNVERIFIED, for the fourth session running** (see revisions 2 and
4). Screenshots timed out and synthetic mouse input was not delivered either —
demonstrated rather than assumed: a real click on the language toggle did
nothing while the same button responded to a programmatic DOM click. Everything
above is DOM, `getBoundingClientRect`, network and accessibility-tree level.
Colours and dark mode are not verified.

## Pre-existing, found while walking, NOT fixed here

Written down so the next reader adds them to an item instead of rediscovering
them: `StaffTokenForm` renders "a token is required" unconditionally, so an
authenticated Access page stacks three statements one of which is false;
`system.tsx` surfaces the raw `"Failed to fetch"` when `t.staff_unreachable`
exists and names the port; `img_depth_n`'s Hebrew is `שורה N` — literally
"row N", the noun CLAUDE.md forbids for depth; `img_count`/`books_count` have
no Hebrew singular ("1 תמונות"); `/overview` reports `image_files` 36 while
the per-library figures sum to 33 (both format to 21.5 MB today, so nothing
visibly disagrees, but they are not the same measurement); and `.rtl-safe`
sits on `<td>` elements whose text lives in child `<div>` blocks, where
`unicode-bidi` does not inherit — console-wide, and unverified because paint
was unavailable.

---

# Revision 6 (2026-08-13): the console reports, and a library names its account

Three corrections from the owner, after walking revision 5 against the real
database. Two of them retire rules this document argued for at length, which is
the reason to write them down rather than just change the code.

## 1. A library is never named alone

> In admin view, when I see a library: I want to see which account is belong
> to.

Obvious in hindsight and invisible from inside: every screen said `My library`
or `lib2` and left the operator to work out whose shelf that was. It was
tolerable while a library WAS the tenant; since P3.7b an account may own
several, so a collection name answers neither *whose?* nor *which one?*.

One `<LibraryName>` (`lib/ui.tsx`) prints the collection and the customer,
used everywhere outside an account's own drawer — the images table and panel,
the work panel's household cards, the access screen's memberships. The books
and images library filters are `<optgroup>`ed by customer for the same reason:
the grouping is real, not a label prefix.

⚠ Two elements, never one interpolated string. `.rtl-safe` is
`unicode-bidi: plaintext`, which resolves ONE direction per paragraph from its
first strong character, so `lib2 · משפחת מלין` would lay the Hebrew out in the
Latin name's direction and put the separator on the wrong side.

## 2. ⚠⚠ The console does not moderate a household's catalogue

> in the list of libraries — I should not be able to approve it or remove it
> or edit it. this is not mine to do so. I can only see info about it and
> about the libraries.

**This retires revision 2's read/write split as the governing rule**, and it is
worth being precise about what was wrong with it. Revision 2 said: read across
every tenant, write only where the operator is a member — enforced by the
product API, which 404s anything else. That answers *may this request
succeed?*. It is a true statement about permissions and the wrong question.

The right question is *whose job is it?* — and the two answers diverge exactly
where the operator holds a membership, which on the owner's own machine is
everywhere. A system console with no login and no audit trail retitling
somebody's books is not made acceptable by the operator happening to be in
that household's member list. Moderation belongs to the household's own app,
where the person doing it owns the shelf.

So `approve`, `edit` and `delete` are gone from the work panel, and gone
**structurally**: `api/client.ts` exports no book write at all, and
`boundaries.test.ts` fails if a book-mutating product route reappears anywhere
in the app — including one written straight into a component with `fetch`,
which is the shortcut a hidden-button rule would never catch. An unused export
is an invitation; a missing one is a decision.

⚠ **The console still writes TENANCY**: create a library, rename one. That is
the line — administering a customer's account is this tool's job, editing
their catalogue is not — and the guard is scoped to books so it cannot creep
into forbidding the writes that remain.

⚠ The removal is SAID, once, at the foot of the panel. "Absent, not disabled"
only works if the absence is explained; an operator who used to approve from
here must learn the capability moved, not wonder whether it failed to render.

## 3. ⚠⚠ A work has no status

> and in the main view - I should not be able to see status. after all, in 2
> libraries it can be different status. what to display? simply do not
> display.

Revision 4 introduced the works table with a status column showing the
strongest §5.1 claim across households, plus a "mixed" badge when they
disagreed. The reasoning was that an aggregate needs *some* status. The owner's
correction is that it needs none: §5.1 is a property of one COPY in one
library, and a single answer for a work held two ways is a fiction — one that
answers *"is anything out there still unapproved?"* with a confident no.

Removed from the list AND from the work panel's summary, which showed the same
aggregate one click away. It survives on each household card, where it is one
copy in one library and therefore true.

⚠ The status FILTER survives, and means something the column could not: works
with **at least one copy** in that state. That is the real version of the
question the aggregate was pretending to answer, and the screen now says so —
necessary once no row shows a status to infer it from.

## What this costs, stated

The console can no longer fix anything it finds. An operator who spots a
mis-read title in a household they administer must open the household app to
correct it. That is the intended trade: the alternative is a cross-tenant tool
that edits catalogues with no login, no audit trail and nobody to explain it
to. It becomes worth revisiting when P4.1 gives the operator an identity and
an audit trail gives the household a record — not before.

## Verified live (revision 6)

Against a backup-API copy of the owner's real database (1 account, 2
libraries, 286 books), served from a worktree so the originals were never
opened:

- the works table headers are *title · author · libraries · copies · first
  found* — **no status**; the drawer's summary likewise;
- the work drawer for a book held by BOTH collections shows two household
  cards, each reading `My library` / `חשבון ללא שם` with its own `ידני` badge,
  and its **only** button is *close*;
- the images list names the customer on every row;
- the library filter shows one `optgroup` per customer with both collections
  under it.

⚠ Paint still unverified (fifth session — see revisions 2, 4 and 5): the
Browser pane does not composite, so these are DOM- and network-level checks.
