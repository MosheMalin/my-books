# IMPLEMENTATION_PLAN.md — building the product around the engine

**Status:** proposal, drafted 2026-08-07, revised same day with the owner's
answers (location comes with the map; cost/BYO after login; phone capture
deferred; images on disk, not in the DB; tenant-aware clients and no
single-state backend; **React + Vite + TS from the start** — D3 reversed).
**Reads with:** `VISION.md` (what it's meant to become), `planning/UI_PLAN.md`
(the surface), `CLAUDE.md` (what exists and why it works that way).
**Purpose:** turn the vision + mock into a list of items that can be picked up
one at a time, each shipping with its own tests, without any of them being able
to damage the accuracy work.

Markers: **[DECIDED]** owner has chosen · **[OPEN]** still needs an answer ·
**[REC]** my recommendation · sizes are **S / M / L** relative effort,
deliberately not dates.

---

## 1. The pillars

The owner's proposal was: *books inventory → tenants → login → map*. That is a
sound spine and it matches `VISION.md` §14. Three parts of it are right for
non-obvious reasons and are worth stating so they don't get re-litigated:

- **inventory before schema-perfection** — the model's hard questions (author
  identity, duplicates, what a "book" is) become obvious the moment you render a
  browsable library; guessing first means migrating twice (§14);
- **tenants before login** — tenancy is a *schema and query* property, login is
  an *identity* property. Retrofitting `library_id` onto every table and query is
  the expensive one, so it goes first;
- **map last** — it is an enhancement layer, and a user who never draws one must
  still get a fully working catalog (§7).

### 1.1 Location: address comes with the map, identity does not **[DECIDED]**

**Owner's call:** a book's physical location is derived from the map. Until the
map exists those properties are null and simply not displayed.

That works, with one split that has to be explicit or pillar 2 collapses:

| | What it is | When |
|---|---|---|
| **Shelf identity** | an id, a free-text label the owner types ("living room case 2, third shelf"), `depth_count` | **pillar 2** |
| **Shelf address** | place → bookcase → `col` → `level`, geometry, the map highlight | **pillar 6 (map)** |

A capture must record *which shelf it is a photo of*, or a re-read has nothing
to diff against and §5.6 (a shelf's book list is durable state) cannot be built
at all. That needs an id and a label — not a map. **Depth also stays with
identity**: §5.7 is explicit that depth cannot be detected and must be declared,
so it is a property of the shelf, not of its position in a drawing. The
front-row-vs-whole-shelf bug (§5.7 #1) is therefore fixed in pillar 2, where it
belongs.

Interim location, before the map: the shelf's own label. Honest and enough. The
map later gives it structure and the "where is it" highlight.

**[DECIDED 2026-08-07]** The split above stands, and reconciliation stays in
pillar 2 — with one amendment: **shelf identity is FREE, so the label is
optional**. A shelf must exist and be re-findable, not be described. An unnamed
shelf is identified by the image it came from, which the owner recognises
without a caption; naming it and any other location information is optional,
and the real binding still waits for pillar 6.

So the interim-location row of the table above is weaker than it read: the
label is *an* answer to "where is it?" when someone bothers to type one, not
the mechanism that makes pillar 2 work. What makes pillar 2 work is that a
capture can name a shelf id at all.

Consequence for P2.2: a photo filed without a shelf must still get one, so the
intake path creates a shelf per capture by default.

**One image = one shelf is a placeholder, and MERGE is the exit (owner, 2026-08-07).**
Without the map there is nothing to bind several photos of one physical shelf
together, so each image gets its own shelf identity and that is honest. Once
the map exists (pillar 6), the owner must be able to **merge several shelf
identities into one physical shelf** — that is the gesture the map makes
natural, because on a drawing you can see that two of them are the same piece
of wood.

That is deferred work, but it constrains what may be built before it. The
constraint, stated so it is not discovered at pillar 6:

> **Nothing may treat a shelf id as a permanent, one-to-one handle on a
> physical shelf.** It is one *identity*, and identities merge.

Concretely, for pillars 2–5:

- `Copy.shelf_id` is a pointer that a merge REPOINTS. Fine, as long as nothing
  caches or derives from it in a way a repoint cannot reach;
- `Provenance.shelf_id` is history and must NOT be rewritten — a sighting
  happened against the shelf that existed then. So a merge needs an **alias**
  from the retired identity to the surviving one, not a mass update. Same shape
  as P7.1's alias table for shared book identity, and for the same reason:
  retrofitting identity onto records that assumed it was permanent is the
  expensive version;
- reconciliation (P2.3) diffs per `(shelf, depth)`. Its inputs must stay
  resolvable through an alias, or every read recorded before a merge becomes
  unreadable after it;
- **no automatic merging.** Two photos overlapping is not evidence they are one
  shelf — the same books can sit on two shelves, and §5.4 already refuses to
  guess at exactly this kind of ambiguity. A human merges, on the map.

Not built now. Pillar 6 owns the operation; pillars 2–5 owe it only the
property that a shelf id can be retired without losing what pointed at it.

### 1.2 Cost and BYO keys move after login **[DECIDED]**

Owner's call: testing is with family relatives on the owner's key, so metering
and BYO keys wait until after login (pillar 5). Accepted.

One cheap safeguard worth keeping in the earlier pillars anyway: a **per-library
run rate cap** — a single number, one item, no metering system. Family won't run
the bill up on purpose; a retry loop or a 400-photo upload will. Not insisted on.

### 1.3 What does *not* wait: tenant-aware clients and a backend with no global state **[owner-raised]**

The owner's technical point, made explicit because it is the real content of the
"tenants" pillar rather than a detail of it:

- **the client is tenant-aware** — a library reference travels on every request,
  the library switcher is real UI (`UI_PLAN` §1), and no screen assumes "the"
  library;
- **the backend holds no per-request global state.** Today a run is a thread
  plus a module-level `_set_job` / `_get_job` singleton (§11.1). That is correct
  for one user and simply wrong for two: two members starting a read would
  overwrite each other's job. So the **job queue and the removal of module
  globals are part of the tenants pillar**, not of a later operational one.

Object storage moves earlier for the same reason — images have to be keyed by
tenant before a second tenant exists (§3, D1 below).

### 1.4 Phone capture deferred **[DECIDED]**

Owner reports uploading from the phone's camera roll through the web page and
that the experience is already good. So no capture pillar; the responsive
upload path is maintained as part of pillars 1–2 and PWA/native capture is
deferred with the native clients. The one piece not deferred is the **measured
image size/compression policy** (§12.3 #12) — that is accuracy work, and it
belongs with accuracy work.

### 1.5 The store is a pillar item, not an assumption

`work/` today is JSON files with one implicit user, and `library.json` is a flat
dict keyed by `normalize(title)|normalize(author)` with a single `source` field.
The target model (§5.2) has copies, provenance *lists*, depth and lending.
Pillar 1 cannot be built on that store — and it also must not block on the
**[OPEN]** datastore decision (§12.1). Resolution: a **store port + contract
tests** in pillar 1, one adapter behind it, so the datastore question becomes a
swap a committed test suite proves.

Real data to migrate: **251 books** (141 approved, 110 auto), **19 runs**,
**22 images**, **155 decisions**.

### 1.6 Resulting order

| # | Pillar | Origin |
|---|---|---|
| **1** | **Books** — domain, store, migration, API, browse/search/edit/copies/lending | owner's pillar 1 |
| **2** | **Captures, shelf identity, reconciliation & review** — the run→shelf inversion | owner's pillar 1 (second half) |
| **3** | **Tenants** — accounts, libraries, memberships, roles, isolation, **job queue, no global state, tenant-keyed storage** | owner's pillar 2 + §1.3 |
| **4** | **Login** — sessions, magic link, OAuth, invites, onboarding, deploy + restore | owner's pillar 3 |
| **5** | **Cost** — metering, caps, BYO keys | vision §10 |
| **6** | **Map** — POC both, build the winner; **shelf addresses and "where is it"** | owner's pillar 4 + §1.1 |
| **7** | **Shared books DB**, covers, sampled correction corpus | vision §8, §9.2 |
| **—** | *Deferred:* PWA/offline capture, native clients | vision §14 ph. 5, 8 |

Accuracy work (vision phase 0) runs in parallel throughout and is **not** a
pillar that ends. The product is demoable to the family at the end of pillar 2,
usable by them at the end of pillar 4.

---

## 2. Horizontal rules

The "always true" constraints the request asked for. Each is enforced by
something mechanical, not by intention.

### H1 — Layering, one-way dependencies

```
booksnap/          recognition core. PURE. no HTTP, no DB, no user, no tenant.
                   unchanged by all of this. (vision §2: "what must survive")
app/domain/        entities + rules (Book, Copy, Shelf, reconcile, policy).
                   pure Python, no I/O, no framework imports.
app/ports/         Protocols: BookStore, ShelfStore, BlobStore, JobQueue,
                   Clock, IdGen, Principal.
app/adapters/      implementations (sqlite store, disk blobs, queue…)
app/api/           FastAPI routers under /api/v1 + DTOs. THIN — no rules.
app/web/           the client — React + Vite + TS (D3), talks only to /api/v1
tools/             sweep / spotcheck / probes — untouched
```

Arrows point **down only**. Enforced by `tests/test_layering.py`: an AST walk
over imports that fails if `booksnap/*` imports `app/*`, if `app/domain/*`
imports a framework or a driver, or if `app/api/*` imports an adapter directly
instead of a port.

Why a new `app/` package instead of growing `booksnap/server.py` (1021 lines,
run-centric, module-global job state): **strangle, don't refactor.** That server
is the accuracy-tuning surface — `explain()`, config snapshots, per-spine
scores, crops — and the vision keeps it, demoted to Settings → Technical log
(§5.5). Rewriting it into the product UI would put the tuning loop at risk for
no gain. It keeps running on `/api/*`; the product speaks `/api/v1/*`.

### H2 — Tenancy from the first write, statelessness from the first handler

Every persisted record carries `library_id` from pillar 1; every store method
takes a library reference; there is exactly **one** function resolving principal
→ library (a hardcoded dev library until pillar 3). And from the first handler:
**no module-level mutable state.** Request-scoped or store-backed only. A
stubbed resolver is nearly free; a missing tenant key or a global job dict is a
rewrite (§1.3).

### H3 — API discipline

`/api/v1` from the very first endpoint (§11.1). DTOs separate from domain
objects, so a model change is not automatically a breaking API change.
Resources are **books and shelves**; reads are a sub-resource of a shelf; there
is no run root. No server-rendered HTML — the API stays client-agnostic because
native clients are decided-later, not decided-against (§3).

### H4 — Four rings of tests, each with a distinct job

1. **Rule tests** (`app/domain`, no I/O, milliseconds). Every vision decision
   that can be silently reversed gets a *named* test — see H5.
2. **Store contract tests** — one suite, parametrized over every store
   implementation, including a **tenant-isolation** suite. This is what makes
   the datastore **[OPEN]** reversible instead of terrifying.
3. **API tests** — `TestClient` + in-memory store. Shapes, status codes,
   permission denials. Plus meta-tests: every route is under `/api/v1`; every
   route resolves its library from the principal; (from pillar 3) every route is
   policy-checked — a route with no policy declaration **fails** rather than
   defaulting to open.
4. **Accuracy gate** — `sweep --check` + `spotcheck`, unchanged, still enforced
   by the pre-commit hook. Product work must never require touching the baseline.

Plus one **end-to-end fixture test**: recorded read + recorded candidates →
claims → review decisions → shelf state → API response. No network, no
Tesseract, no Sonnet. It is the only test that catches a wiring error between
rings.

*What "effective" means here:* a test that fails if the decision is reversed —
not a coverage number. Don't unit-test DTO plumbing; do table-test the rules.
And explicitly: **the recognition core's test is the sweep** — don't add unit
tests to `match.py` for coverage's sake, add fixtures.

### H5 — The rule checklist (a named test each, in the pillar shown)

| Rule | Vision | Pillar |
|---|---|---|
| the matcher **never auto-creates a copy**; only a human action does | §5.1 | 1 |
| an **approved** book is never demoted by a worse re-read | §5.6 | 1 |
| *remove from shelf* ≠ *delete from library* | UI_PLAN §5 | 1 |
| **wishlist books excluded** from the default list and all counts | UI_PLAN §2 | 2 |
| a re-read **never auto-removes** a book from a shelf | §5.6 | 2 |
| a book the user **rejected** here is not re-added by a later run | §5.6 | 2 |
| capture-overlap dedup applies **within one depth only** | §5.7 #2 | 2 |
| "not seen in this read" is **scoped to the depth read** | §5.7 #1 | 2 |
| copy resolution fires **only** on genuine ambiguity; skipped ⇒ already-listed | §5.4 | 2 |
| skipped copy questions land in the **duplicates queue**, never lost | §5.4 | 2 |
| a blob path is **derived from a DB row**, never scanned, never client-supplied | — (D1) | 3 |
| cross-library access returns **404, not 403** | §4.2 | 3 |
| a key never appears in a log, a run snapshot or an error report | §10 | 5 |
| **column / level / depth** — three axes, three words, never "row" or "band" | §5.7, UI_PLAN §1.1 | 6 |

The last one gets a lint test over `app/` as soon as the words exist.

### H6 — Migrations are code, and tested

A versioned migration runner from the first schema. A committed
`fixtures/legacy/` sample of today's `work/` shapes, and a test asserting the
import produces the expected entities. The importer is a **required
deliverable** (§11.2) and doubles as the first real test of the schema.

### H7 — Secrets

`CLAUDE.md`'s credential hygiene extends to *other people's* keys (§10): write-
only from the UI, encrypted at rest, never logged, never in a run snapshot or an
error report. That last one gets an actual test (H5).

---

## 3. Decisions

**D1 — Datastore: SQLite behind the store port; images on disk, not in the DB.**
**[REC]** SQLite now (JSON columns for run/config snapshots), Postgres later.
Against the vision's own criteria (§12.1): memberships/roles/lending need
relational integrity — that is where a bug means someone sees a library they
shouldn't; run records are document-shaped; Hebrew search runs over the
*normalized* columns `normalize()` already produces and needs measuring either
way; zero ops, one file, portable, real SQL so the Postgres step is small. The
contract tests (H4 ring 2) are what keep this revisitable.

*Answering the owner's question directly:* **SQLite can store images** — a BLOB
column works, and for small blobs (tens of KB) it is genuinely competitive with
the filesystem. **Don't.** Shelf photos are multi-MB JPEGs; they would bloat the
DB file, make backup/restore expensive, and route every image read through the
DB process. So:

- blobs live on disk (later object storage), the DB holds metadata + a
  **storage key**;
- layout is tenant-first: `libraries/<library_id>/captures/<capture_id>/original.jpg`,
  crops under the capture that produced them;
- **a path is always derived from a DB row** — never scanned off disk, never
  taken from a client parameter. That single rule is what prevents cross-tenant
  path traversal, and it is in the H5 checklist;
- an **orphan reconciler** covers crashes mid-write (blob with no row, row with
  no blob). `server.py`'s existing `_reconcile_orphans` startup hook is the
  precedent;
- because it is a port, the move to object storage in pillar 3 changes one
  adapter and no rules.

**D2 — New `app/` package; `booksnap/server.py` survives as the audit surface.**
**[DECIDED — owner agreed]**, per H1.

**D3 — Client stack: React + Vite + TypeScript, from P1.0.**
**[DECIDED — owner's call, and I agree; this reverses my first recommendation.]**

The first draft argued for staying no-build through pillars 1–2 on the grounds
that the mock's code graduates directly. **That argument was weaker than I
stated it.** The mock runs off a synchronous fake `data.js`; against a real
paginated API with async loading, optimistic updates and error states, most of
that logic is rewritten regardless of stack. The mock was always going to be a
*reference*, not a donor.

What actually decides it:

- **pillars 1–2 are the bulk of the UI.** The books list, the two-mount book
  surface (drawer + full page, `UI_PLAN` §5), the shelf view and the review rows
  are the expensive screens. Building them hand-rolled and porting at pillar 6
  means writing the expensive part twice;
- **the manual-DOM tax is already being paid.** Commit `3df46cb` is
  *"anchored re-renders"* in the review UI — hand-managing scroll anchoring
  across a re-render, on a surface far simpler than P2.5's review + diff +
  alternatives + copy-resolution prompt. That is precisely what a component
  model removes;
- **"edit it anywhere, it changes everywhere"** (`UI_PLAN` §5) is a state
  problem, not a rendering problem. One book record, two mounts, a list behind
  it repainting — hand-rolled that is an event bus and a set of invalidation
  rules to get wrong.

Specifics, so this is one decision and not four:

- **TypeScript, with DTO types generated from the API's OpenAPI schema.** FastAPI
  emits the schema for free; generating client types from it makes a DTO change a
  *build* failure instead of a runtime surprise. Given H3 keeps DTOs separate
  from domain objects, this is the mechanism that keeps the two in step. A CI
  check regenerates and fails on drift;
- **Vitest + React Testing Library** for the client ring. Same standard as H4:
  test the components that encode *decisions* — the review row (tier badge,
  alternatives, the copy-resolution prompt and its stated default), the diff
  view, the mixed-script alignment rule (`UI_PLAN` §7.2) — not DTO plumbing and
  not layout. Rule tests stay in Python where the rules are;
- **`app/web/` is a Vite project.** Dev: Vite dev server proxying `/api/v1`.
  Prod: FastAPI serves the built assets. No CDN — bundled locally, consistent
  with the existing credential/offline posture;
- **`booksnap/static/index.html` is NOT migrated.** It stays a single-file
  vanilla page and remains the tuning/audit surface (H1, §5.5). `CLAUDE.md`'s
  "single-file vanilla-JS UI (no build step, no CDN)" line describes *that*
  surface and should be amended to say so, or it will read as a rule the new
  client is breaking.

Accepted costs, stated plainly: an npm dependency tree to keep current, a node
toolchain in dev and CI, and breaking majors on someone else's schedule. At this
project's scale that is small and worth it. *Alternative not taken:* Svelte is
less code and has no virtual DOM, but React was named, has the deepest ecosystem,
and is the better-supported target for assisted work.

**D4 — The mock is a design reference, not a donor.** **[DECIDED — owner agreed,
adjusted by D3]** `planning/mockup/` stays the reference until a tab reaches
parity in `app/web/`, then that tab's mock code is deleted. With D3 the port is a
rewrite against real data rather than a file move, so the reference matters more,
not less — and so does deleting it on parity. Two live implementations of one
screen drift, and the drift is invisible.

---

## 4. The items

### Pillar 1 — Books (single tenant, no login, no map)

| # | Item | Size |
|---|---|---|
| **P1.0** | **Scaffolding.** `app/` package per H1; `/api/v1` skeleton; the four test rings wired into pre-commit; `test_layering.py`. Plus the client toolchain (D3): `app/web/` as a Vite + React + TS project, Vitest + RTL running, OpenAPI→types generation with a CI drift check, dev proxy to `/api/v1`, prod static serving. No behaviour — one page, one typed call, one component test, all five checks green. | M |
| **P1.1** | **Book/Copy domain** (§5.2): entities, `normalize()`-derived search keys, status ladder (auto < approved < manual), **append-only provenance**, book-level vs copy-level fields. Pure. Rule tests: never-auto-create-copy, approval-outranks-auto. | M |
| **P1.2** | **Store port + SQLite adapter + contract tests** (D1). Every method library-scoped (H2). The isolation suite is written now, with one library — it is the suite pillar 3 inherits. | M |
| **P1.3** | **Legacy import** (H6, §11.2): `work/store.json`, `runs/*`, `library.json`, `decisions.json` → entities. Committed fixture + test. **Honest scope:** recovers 251 books, their statuses and one provenance entry each (manual adds are identifiable by their `owner-fb-…` spine ids). Location fields are null by design (§1.1) and hidden in the UI. | M |
| **P1.4** | **Books API v1**: list (sort: title / author / recently-added; paging), get, patch title/author → `manual`, delete from library, manual add, export CSV+JSON. | M |
| **P1.5** | **Hebrew search** — the one genuinely hard part (§6). Over normalized title+author: nikud stripped, final letters folded, geresh deleted in-word, leading ה/ו/ב/ל/מ/ש/כ tolerated, mixed-script. Ships with a **query fixture** (query → expected-hit pairs drawn from the real 251 books) asserted in tests, and a measured note on the mechanism chosen. Not "it should work". | M |
| **P1.6** | **Books UI** — `UI_PLAN` §2 and §5 built in `app/web/` against the real API (the mock is the reference, D4): list⇄grid, search, sort, status filters, author chip, book drawer + `#/book/<id>` full page, inline edit, *remove from shelf* vs *delete from library*, RTL/EN mirroring. Location blocks render only when non-null. | L |
| **P1.7** | **Copies & lending**: "I have another copy" (the only creation path), per-copy label/tags/condition, lend / mark-returned, "who has my books". Rule test: lending is per copy, never per book. | M |

**Done when:** the owner browses his real 251 books in the real UI, searches
them in Hebrew, fixes a title, and exports the library — with the tuning server
still running untouched alongside.

### Pillar 2 — Capture and detect (redefined 2026-08-07, owner)

**What this pillar is for.** At the end of it, the owner photographs a shelf in
the *product*, the engine reads it, and the books land in the library — for a
single user, with no tenants and no map. That is the product's core loop, and
everything in pillars 3–7 is an amplifier on top of it.

Two things the redefinition settles, because the earlier breakdown quietly
assumed both away:

- **the map is not a prerequisite for anything here.** Pillar 6 could be cut
  entirely and this would still be a viable product. Nothing in capture,
  reading or reconciliation may wait on it or depend on it;
- **capture belongs in pillar 2, not in "the client half of an item".** The
  earlier P2.2 assumed the product would keep borrowing the tuning server's
  upload-and-run path through pillars 1–2. That is what left the product with
  captures it had no photos for. Uploading, reading and reviewing are the
  pillar, so they are items.

**Strangle, don't refactor — literally (owner's call).** The tuning server on
`:8756` is the accuracy asset and stays untouched. The product does not import
it, extend it, or move its code: it gets its **own** upload/run/review path,
written against `booksnap`'s engine and *modelled on* `booksnap/server.py`
rather than carved out of it. Two copies of that flow is the intended cost —
H1's argument, and the reason the layering test exists.

| # | Item | Size | State |
|---|---|---|---|
| **P2.1** | **Shelf identity + capture domain** (§1.1): `Shelf{id, label, depth_count, virtual}`, `Capture{shelf, depth, order}`, `Copy` located at `(shelf, depth)`. No place/bookcase/col/level — pillar 6. Identity is FREE: the label is optional. | M | **done** |
| **P2.2** | **Capture intake**: `POST /captures` binds a photo to a shelf + depth, auto-creating an unnamed shelf when none is named. | M | **API done** |
| **P2.3** | **Images are real**: a `BlobStore` port + a local-disk adapter, `POST /captures` accepting the file, thumb/full serving, hash-based upload idempotency, and delete. Single-user layout now; P3.5 re-keys it per tenant, which is a path change and not a rewrite. **This is what P2.2 was missing.** | M | |
| **P2.4** | **Reading**: a `Reader` port + an adapter over `booksnap.Pipeline`, driven by an **in-process job runner with no module-level state** (the tuning server's global job dict is exactly what H2 forbids) — per-image progress, cooperative stop, and a `Read` persisted against `(shelf, depth)` with its claims, code version and config snapshot. Modes are the engine's own. | L | **done** |
| **P2.5** | **Reconciliation engine** (§5.6) — a **pure function** `(shelf state, claims, decisions) → diff` producing added / corrected / unchanged / not-seen, **scoped to the depth read**. Highest-risk logic in the product and fully offline-testable; every pillar-2 rule in H5 gets its named test here. | L | |
| **P2.6** | **Copy resolution** (§5.4): the fire / never-fire table as an explicit decision table + tests; three answers; default already-listed; the **duplicates queue** as a filter on Books; the two cheap wins (a lent-out book reappears → "is it back?"; several copies → pick which). | M | |
| **P2.7** | **The Capture tab**: drop zone → a row per photo with shelf + depth assigned inline (*Unassigned* = not yet named), add-a-row-behind surfaced even at `depth_count` 1 (§5.7 — most users won't know it exists), mode selector, run/stop, live progress, and inline review of each claim (crop, tier, diff badge, ✓/✕, alternatives, `why?`). | L | |
| **P2.8** | **Shelf view + read history**: books at a depth in physical order with the photo; the depth bar; the durable review on the shelf; history as diffs (`+3 added · 1 corrected · 12 unchanged · 1 not seen`); soft "not seen in the last 3 reads" badge. | L | |
| **P2.9** | **Complete the inversion**: `/api/v1` has no run root; reads are `/shelves/{id}/reads`; run detail is reachable only through the audit surface. Test: no `/api/v1` route takes a `run_id` as its primary key. | S | done |
| **P2.10** | **The image workspace** (§12.2 #10, owner 2026-08-09) — the Capture tab stops being a one-way pipeline. An image is a durable object: clicking it opens **its runs**, each run lists **its findings**, and each finding can be **approved / edited / removed**, the loop the engine POC already had. A processed photo is never re-read just to see what it found. | L | **done** |

**Done when:** the owner uploads a shelf photo in the product, presses read,
and the books appear in his library — then **opens that photo again and works
through what it found**, approving, editing and removing, without re-reading
it. Re-photographing the same shelf later produces a *diff*, not a second
result set, with nothing auto-removed.

⚠ **The tab is a workspace, not a pipeline** (§12.2 #10). The first build of
P2.7 read "capture" as drop → run → review-now, so a settled read had no route
back and the only visible action was *re-run on selected* — which costs money,
costs time, and invites re-deciding answered questions. P2.10 corrects it. The
shape to hold on to: **the image is the durable object**, runs hang off the
image, findings hang off the run.

**Explicitly NOT in this pillar**, so it cannot creep back in: tenants and
policy (pillar 3 — one library, dev-resolved, as today), login (4), metering
and BYO keys (5), the map and shelf addresses (6). The job runner is
in-process and single-user on purpose; P3.4 replaces it with a real queue, and
the port is what makes that a swap.

**Seams this pillar must create, because pillar 3 lands on them:**

- `BlobStore` — the product never reads `work/runs/`; the run archive is the
  tuning server's, not a shared filesystem. P3.5 changes the key layout only;
- `Reader` — so a test can read a shelf without cv2, tesseract or a paid API,
  and so P5's cost work has one place to meter;
- the job runner holds its state on an **instance**, never a module global.
  Two members starting a read is a pillar-3 problem, but a module global is a
  pillar-2 mistake.

### Pillar 3 — Tenants (and a backend that can hold two of them)

| # | Item | Size |
|---|---|---|
| **P3.1** | Account / Library / Membership entities; multiple libraries per account; the **library switcher** in the app bar; the client sends a library reference on every request (§1.3); the H2 resolver stops being hardcoded (still dev-trusted, no login yet). | M |
| **P3.2** | **Policy module**: §4.2's matrix as *data*, one enforcement point, table-driven test over every (role × capability) cell. Settle §12.2 #1 (may a Viewer see the photos?) and #3 (two members reviewing at once) here — both are policy, and guessing produces the wrong schema. | M |
| **P3.3** | **Isolation**: cross-library access returns **404, not 403** (don't leak existence); the store contract's isolation suite now runs with ≥2 libraries; the "every route is policy-checked" meta-test (H4). | M |
| **P3.4** | **Job queue, no global state** (§1.3): replaces the thread + `_set_job`/`_get_job` singleton. Per-tenant fairness, retry, progress, cooperative stop — today's `should_stop` polling maps straight onto it. Test: two concurrent reads in two libraries do not observe each other. | L |
| **P3.5** | **Tenant-keyed blob storage** (D1): the disk adapter behind the `BlobStore` port with the `libraries/<library_id>/…` layout, path-from-DB-row rule, orphan reconciler, retention + user purge (§3), hash-based upload idempotency (§12.3 #13). | M |
| **P3.6** | *Optional, cheap:* **per-library run rate cap** (§1.2) — one number, not a metering system. Guards against a retry loop, not against family. | S |

⚠ **A tenant is an ownership boundary, never a geography** (owner,
2026-08-10, settling the question P3.1's switcher surfaced — recorded in full
in VISION §4.1). One Library per account is the default; rooms and sites
within an account are pillar-6 Places, never Libraries; a second Library
under one account is the rare separate-collection case, and the normal way
to see a second Library is membership in someone else's (P4.3). The client
consequence landed with this decision: the switcher is a plain label until a
second Library genuinely exists, and the create form says what a Library is
for. P4.1's sign-up flow should create exactly ONE Library, named, per §4.3
— never offer a second during onboarding.

⚠ **Two "admins", one word — do not conflate them** (owner, 2026-08-10). The
Admin ROLE this pillar builds (§4.2) is an admin **inside a single account's
library** — the household's own owner, governing one collection. The **System
Admin console** (`app/admin/`, `app/staff_api/`, `planning/ADMIN_CONSOLE_PLAN.md`)
is a separate surface for the operator of the whole service, developed in its
own track; it authorizes on its own axis and never through §4.2's matrix.
Nothing in this pillar's policy work grants or checks operator powers, and
nothing in the console track should reuse `Role`/`POLICY` for staff.

### Pillar 4 — Login

| # | Item | Size |
|---|---|---|
| **P4.1** | Sessions + **email magic link** (§3): rate-limited, single-use, expiring. The resolver now reads a real session. | M |
| **P4.2** | **Google + Apple** sign-in (Apple is effectively mandatory if iOS ever ships). | M |
| **P4.3** | **Invites** (admin → membership) and the §4.3 onboarding path, with its stated target: sign-up to first correct book on screen in under five minutes, and a product that still works for someone who never invites anyone. | M |
| **P4.4** | **Deploy + restore rehearsal.** Not backup — *restore*. This is the item that gates handing a URL to a relative: their review decisions cannot be re-derived (§11.3). Settle §12.3 #10 (deployment target). | M |

### Pillar 5 — Cost

| # | Item | Size |
|---|---|---|
| **P5.1** | **Metering** per library: pages, engine calls, units, currency cost, visible to the admin (§10). | M |
| **P5.2** | **Hard caps** at the free-quota boundary, per-tenant rate limit, and **graceful degradation** to the free deterministic path instead of a hard stop. Settle §12.3 #11 (does the Tesseract path stay the free tier?) — the degradation story depends on the answer. | M |
| **P5.3** | **BYO keys**: encrypted at rest, write-only from the UI, validated at attach time, never logged or snapshotted (H7 + its test). Settle §12.3 #6 (which providers a user may bring). | M |

### Pillar 6 — The physical map (and shelf addresses)

| # | Item | Size |
|---|---|---|
| **P6.1** | **Address domain**: Place → Bookcase → `col` / `level`, shelves bound to addresses, `Copy` location rendered as `place · case · col · shelf · row` (§1.1). The naming lint (H5) lands here. Existing shelves keep their labels and gain addresses; nothing migrates twice because the fields were null, not absent. ⚠ Per the settled tenancy rule (§4.1, owner 2026-08-10): a **Place is any location within one tenant — a room AND a whole other site** (office, shelves at the parents') — so the Place level must comfortably hold "אצל ההורים" next to "סלון". P6.1 is also the exit for any room-or-site that was modelled as a second Library before Place existed: its shelves/books move back into the main Library under a Place, and the extra Library is retired. | M |
| **P6.1b** | **Shelf merge** (§1.1, owner 2026-08-07): several shelf identities → one physical shelf, by hand on the map, never automatically. Repoints `Copy.shelf_id`, leaves an **alias** for the retired identity so append-only provenance and pre-merge reads stay resolvable. This is the exit from pillar 2's placeholder "one image = one shelf". | M |
| **P6.2** | **POC A** — freehand sketch straightened into a clean orthogonal schematic (§7). The straightening is the whole bet; a wobbly canvas is not the target. | M |
| **P6.3** | **POC B** — bookcase photo → shelf levels proposed by `segment.py`'s existing band signal, confirmed by hand. Free, deterministic, already tuned. | S |
| **P6.4** | **Pick and build**, incl. the hybrid the vision anticipates (B feeds A: detect a case from its photo, drag the block onto the room plan); "where is it" highlight incl. back-row; stale-row surfacing. Explicitly **not** room-photo → floor plan: perspective, occlusion and scale make it unreliable and it is a paid call per attempt (`UI_PLAN` §3 flag). | L |

By this point the shelves, the depth data and the staleness signal all exist and
are tested. The map is a view and an editor over them — which is why it is safe
to be this late.

### Pillar 7 — Shared books DB, covers, correction corpus

| # | Item | Size |
|---|---|---|
| **P7.1** | Shared book identity **with dedup/merge from the start** (§8.4): `normalize(title)|normalize(author)` key, upsert-never-insert, distinct-*library* corroboration counter, `ngram_sim` candidate pairs into a **merge queue with an alias table** — no automatic merges. Retrofitting identity onto a polluted shared DB is the expensive version. | L |
| **P7.2** | Contribution rules (§8.2): approved-only, opt-out, removable from the retrieval chain for measurement. **Measure with `sweep --live --sources` before promoting it into the baseline chain** — it could plausibly *hurt* precision by adding near-miss neighbours. | M |
| **P7.3** | Covers, one instance per book globally; sourcing **[OPEN]** — the always-safe fallback is our own spine crop (§8.3). | M |
| **P7.4** | Sampled correction corpus (§9.2): two tiers (small committed gate fixture + large out-of-git extended corpus), sampling biased toward the informative, per-tenant caps, consent **[OPEN]**. Constraint: **the pre-commit gate must stay fast** — a slow gate gets bypassed, and that costs more accuracy than the fixtures buy. | L |

---

## 5. How to run it item by item

- one item = one branch = one reviewable change, with its tests, ending green on
  the pre-commit gate (`sweep --check` + `spotcheck` + the new rings);
- an item that uncovers a vision-level question **stops and adds it to §12 of
  `VISION.md`** rather than deciding it in code silently;
- accuracy work continues on its own branches against the untouched core; the
  layering test is what guarantees the two streams cannot collide;
- **suggested first slice** (a thin vertical, not a foundation-first sprint):
  P1.0 → minimal P1.1/P1.2 → P1.3 import → P1.4 + P1.5 → the Books tab of P1.6.
  That puts the real 251 books in a real, Hebrew-searchable UI early, which is
  where the vision's "highest motivation-per-hour" claim gets cashed.

## 6. Risks on record

1. **Two UIs, and now two capture paths.** The tuning server and the product
   coexist through pillar 2. Deliberate (H1), and the 2026-08-07 redefinition
   sharpens it: the product gets its **own** upload/run/review flow modelled on
   `booksnap/server.py` rather than carved out of it, so there are two
   implementations of "photograph a shelf and read it" until the tuning
   surface is retired. That duplication is the price of not putting the
   accuracy loop — the actual asset — through a refactor. The mitigation is
   that only the *engine* is shared, through a port: `booksnap.Pipeline` has
   one implementation, and it is the part where a divergence would cost
   accuracy.
2. **Null locations are honest but visible.** Migrated books have no location
   until the map (§1.1), so "where is it" is unanswerable for the whole
   collection through pillars 1–5. Pillar 2 softens this — a typed shelf label
   plus reconciliation means newly-read shelves *do* have a location — but the
   251 imported books stay unplaced unless their shelves are re-read. Worth
   knowing now rather than noticing at pillar 6.
3. **Hebrew search is the item most likely to be underestimated.** Listed
   separately (P1.5) with a measured fixture for exactly that reason.
4. **Reconciliation (P2.3) is where a silent data-loss bug would live.** It is
   pure and fully testable, which is the only reason I am comfortable calling it
   an item rather than a project.
5. **P3.4 is bigger than it looks.** Replacing in-process job state touches the
   run lifecycle, progress reporting and stop — the parts of the current server
   that work well today. It is also the item that cannot be skipped once a
   second person can press "read".
6. **The React decision front-loads cost into P1.0.** The first item now carries
   a toolchain (build, types, component tests, CI drift check) before a single
   book renders. That is the price of not writing pillars 1–2 twice, and it is
   the right trade — but P1.0 is no longer the trivial item it was, and it should
   not be judged by how little it appears to do.
7. **Sizes are relative, not estimates.** Pillars 1–2 are the bulk of the
   product; 3–4 are well-trodden; 6–7 are the ones whose scope can still change
   on evidence.
