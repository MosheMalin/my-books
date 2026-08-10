# VISION.md — booksnap product vision & requirements

**Status:** living document, first drafted 2026-08-06, revised same day
(book copies, copy resolution, shared-DB deduplication, sampled correction
corpus, clients confirmed, runs demoted from the UX, shelf depth).
**Purpose:** capture where this is going, so day-to-day accuracy work doesn't
paint the architecture into a corner. `CLAUDE.md` describes *what exists and
why it works that way*; this file describes *what it is meant to become*.

Markers used throughout:
**[DECIDED]** owner has chosen — don't re-litigate without new information.
**[OPEN]** deliberately unresolved; listed in §12 with what would settle it.
**[FLAG]** a decision whose cost I want on record, taken anyway.

---

## 1. The product in one paragraph

A person photographs the shelves of their home library. The system reads the
spines and builds a real, browsable catalog of the books they own — searchable
by title and author, correctable by hand, and mapped back onto the physical
furniture so "where is my copy of X" has an answer. Families share a library
with different permission levels. Books can be marked as lent out and to whom.
Recognition is deterministic-first and cheap by design; the paid engine is a
fallback, and users eventually bring their own key so inference cost doesn't
scale with the user base.

The heart of the system is **detection accuracy**. Everything else is a shell
around a correct list of books. That ordering is not negotiable — a beautiful
library UI over a catalog full of phantom books is worse than useless, because
a phantom silently rots in the collection while a missing book gets noticed.

---

## 2. Where we are today (honest baseline)

Working, measured, single-user, local:

- pipeline: segment → read (Tesseract spines / LLM page) → retrieve → match,
  with evidence gates and tiering (AUTO / REVIEW / unmatched);
- run archive with config snapshots, per-spine records, crops, and replayable
  retrieval recordings (`work/runs/<id>/`);
- a confirmed **library** (`library.py`) — AUTO claims absorbed automatically,
  REVIEW claims decided by hand, decisions kept separately so runs stay
  immutable; also serves as a retrieval source (`ConfirmedCatalog`);
- offline measurement: `tools/sweep.py` + `tools/spotcheck.py`, enforced by a
  pre-commit hook against a committed baseline;
- a single-file vanilla-JS UI over ~915 lines of FastAPI in `server.py`;
- storage is JSON files under `work/`; there is exactly one user, implicitly;
- **the UI and API are organised around runs** (list runs → books in a run).
  That is a developer's model, correct for tuning and wrong for the product —
  §5.5/§5.6 invert it.

Baseline accuracy (8 labelled shelves, run-16 fixes):
AUTO mean P 0.94 / R 0.78 / F1 0.85; A+R P 0.94 / R 0.83 / F1 0.88.

**What must survive every future refactor:** the matching core
(`segment/ocr/llmreader/match/scoring/replay`) stays a pure library with no
knowledge of users, tenants, HTTP, or a database. The sweep harness runs it
offline against committed fixtures; that property is the reason accuracy work
is measurable at all. Web/tenancy code depends on the core, never the reverse.

---

## 3. Decisions taken (2026-08-06 session)

| Area | Decision | Notes |
|---|---|---|
| Hosting | **[DECIDED]** Hosted multi-tenant, **invite-only** initially | Multi-tenant machinery from day one; billing/ToS/abuse deferred, not designed away |
| Inference cost | **[DECIDED]** Free quota on our key → then BYO key | New user sees real results immediately; metering + per-tenant caps required |
| Clients | **[DECIDED, confirmed]** API strictly client-agnostic now; web UI is the near-term surface; **cross-platform native later** | No server-rendered HTML; versioned JSON API from day one |
| Shared books DB | **[DECIDED]** Approved books only, **opt-out** (on by default) | Bibliographic data only. Never photos, never who owns what |
| Shared-DB identity | **[DECIDED]** A book appears **once**; contributions upsert, never insert | Dedup + merge design in §8.4 |
| Correction data | **[DECIDED]** **Sampled** user corrections as an ever-growing rule anchor, later phase; owner's manual labelling continues near-term | Not all shelves — cost and gate speed forbid it. §9.2 |
| Book identity | **[DECIDED]** One book record per title+author; **user-created copies**, no ISBN/edition modelling | Lending is per copy. §5.1 |
| Duplicate resolution | **[DECIDED]** A known book detected on another shelf asks: *another copy* / *already-listed copy* / *wrong book* | At review time, with the crop visible. Default = already-listed. §5.4 |
| Shelf depth | **[DECIDED]** A shelf may hold 2–3 rows of books front-to-back; depth is a declared attribute of location | Photographed one row at a time. Scopes the diff, the dedup and the "not seen" rule. §5.7 |
| Runs in the UX | **[DECIDED]** Runs stay first-class **internally**, but are **not a user-facing concept**. No global run list | Users see books and shelves; a shelf has a read history. Full run detail lives in an audit view. §5.5 |
| Re-reading a shelf | **[DECIDED]** Reconciles the shelf's book list; never re-adds, never auto-removes | A shelf's books are durable state, not a run's output. §5.6 |
| Physical map | **[DECIDED]** Freehand sketch **and** bookcase-photo detection; **POC both** | Sketch must be straightened into a clean schematic. Users have **multiple physical libraries** |
| Photo retention | **[DECIDED]** Keep originals + crops, **user-purgeable** | Re-running old shelves with better code is core to the tune-and-measure loop |
| Auth | **[DECIDED]** Email magic link + Google/Apple sign-in | Apple sign-in effectively mandatory if an iOS app ever ships |
| Metadata | **[DECIDED]** Iterative, in this order | 1) publisher/year/language/pages → 2) user fields (tags, rating, notes, read status) → 3) covers → 4) summaries, review links |
| Covers | **[DECIDED]** Stored **once per book globally**, never per customer | Blob size is the reason; ties covers to the shared books DB |
| Datastore | **[OPEN]** — research and decide later | Criteria in §12.1 |
| First build after accuracy | **[DECIDED]** The **library experience** (browse/search/authors) | Also sharpens the data model before it's frozen into a multi-tenant schema |

---

## 4. Users, tenancy and permissions

### 4.1 Entities

```
Account (a person, one identity)
  └─ membership in one or more Libraries (role-scoped)

Library  (a household's collection — the tenancy boundary)
  ├─ Members: Account × Role
  ├─ Places (1..n)   ← a user may have several: home, office, parents'
  │    └─ Bookcases → Shelves
  ├─ Shelves ── (0..n) Captures (photos)  ← one shelf may span several photos
  ├─ Runs (immutable archive, as today)
  └─ Books (confirmed catalog — the deliverable)
```

Note the distinction: **Library** is the permission/tenancy unit ("the Malin
family collection"); **Place** is a physical location within it — a room, or
a whole site. A user having several places was called out explicitly and must
not be collapsed into a single implicit root.

*Naming, settled 2026-08-10 before H5's lint lands at P6.1:* the noun is
**Place**; *PhysicalLibrary* is its retired synonym and must not appear in
code — it contains the very word it exists to be distinguished from, which is
how "the living-room library" gets typed.

**[SETTLED 2026-08-10, owner] What makes something a TENANT.** The
discriminator is **ownership, never geography**: a different tenant is a
different account's/household's collection. Within one account, multiple
physical libraries — the living room, the child's room, and equally a whole
other SITE (the office, shelves standing at the parents') — are **locations
of one Library**, never Libraries of their own. Consequences:

- **one Library per account is the default and the normal case.** A second
  Library under your own account is a rare, deliberate act (a genuinely
  separate collection you administer — a shop's stock, a classroom set), not
  an organizational tool. The way an account normally comes to see a second
  Library is MEMBERSHIP in someone else's (P4.3 invites);
- the "home, office, parents'" example above is about MY books stored in
  three places — all one tenant. My parents' OWN collection is THEIR
  Library, which I may join as a member. Whose books, not whose roof;
- splitting one collection across two Libraries has a real, silent cost:
  search, dedup and §5.4's duplicate question are all tenant-scoped, so a
  second copy of a book you already own would never be flagged. This is why
  the boundary must not be used for rooms;
- the client must not ADVERTISE multi-library to an account that has one —
  the switcher renders as a plain label until a second Library genuinely
  exists, and creating one carries guidance saying what a Library is for.
  Rooms get their proper noun (Place) with the map, pillar 6.

### 4.2 Roles **[DECIDED — matrix settled at P3.2, 2026-08-10]**

The matrix lives as DATA in `app/domain/policy.py:POLICY`, with one
enforcement point (`app/api/policy.py:require`) and a table-driven test over
every (role × capability) cell. Changing a cell is a one-line edit made in
two places (the table and its test) — that is deliberate: a cell change is a
decision, and the test is where it gets written down twice.

| Capability | Viewer | Editor | Admin |
|---|:--:|:--:|:--:|
| Browse/search books, see shelves | ✓ | ✓ | ✓ |
| See lending state | ✓ | ✓ | ✓ |
| See the original shelf photos (§12.2 #1) | | ✓ | ✓ |
| Upload photos, start a run | | ✓ | ✓ |
| Approve/reject/replace matches | | ✓ | ✓ |
| Add/remove books manually | | ✓ | ✓ |
| Mark lent / returned | | ✓ | ✓ |
| Edit physical map | | ✓ | ✓ |
| Invite/remove members, change roles | | | ✓ |
| Attach BYO API key, see usage/quota | | | ✓ |
| Rename the library | | | ✓ |
| Delete photos, delete the library | | | ✓ |

⚠ **Admin here is an admin inside one account's library** (owner,
2026-08-10): the role governs a single household's collection. It is NOT the
system operator — that is the separate staff console (`app/admin` /
`app/staff_api`, its own plan), which authorizes on its own axis and never
through this matrix.

Remaining open sub-question: a role between Viewer and Editor that may mark
lending but not edit the catalog. Nothing forecloses it — it would be a new
`Role` plus one column in the table — and it stays open because nobody has
asked for it yet.

### 4.3 Onboarding **[OPEN in detail]**

Target: from sign-up to *first correct book on screen* in under five minutes,
without the user creating any API account. The free-quota decision exists
precisely to make this possible. Sketch:

1. sign in (magic link / Google / Apple);
2. create a Library, name it; optionally name a first Place;
3. guided first capture — one shelf, with framing/lighting guidance;
4. run on our key (free quota), show results;
5. walk them through approving/correcting one shelf, so the review model is
   learned on a small set;
6. only then: invite family, attach a key, map the physical library.

Steps 5 and 6 are the ones most likely to be skipped by real users; the
product should work acceptably for someone who never does either.

---

## 5. Data model

### 5.1 Books and copies **[DECIDED]**

A **Book** is identified by `{title, author}` within a library — no ISBN, no
edition, no printing. **Copies are supported, but they are created by the
user**, not inferred: an owner who has two of something presses *"I have
another copy"* and gets a second Copy record to tag, locate and lend
independently.

The reasoning is sound and worth preserving: an ISBN or printing simply is not
legible from a spine photo in the general case. Building edition modelling
around data the reader can't supply would be effort spent on a field that
stays empty. Copies exist because *lending* needs them; identity resolution
does not.

Consequences this design deliberately accepts:

- **The matcher must never auto-create a copy.** Two spines claiming the same
  book on one shelf is overwhelmingly a mis-assignment, not a genuine
  duplicate — which is exactly what today's `dup_drop_frac` (0.70) rule
  encodes when it *drops* a weak rival rather than demoting it. That rule
  stays correct and must not be "fixed" later on the theory that it blocks
  legitimate duplicates. Duplicates enter through human action only.
- **Authors remain strings, not entities.** "Click an author → see their
  books" is a grouping over normalized strings. `normalize()` already folds
  nikud, final letters and geresh, so this mostly works — but it will visibly
  fail on transliteration variance: `ג'ראלד דארל` / `ג'רלד דורל` /
  `Gerald Durrell` are one author and three strings. An author-merge/alias
  tool will become necessary. Note that §8.4 has to solve this *anyway* at
  global scale, and solving it there once benefits every tenant.

### 5.2 Book and Copy records (target shape)

```
Book                              ← one per {title, author} per library
  id, library_id
  title, author
  normalized_title, normalized_author    ← search keys, from normalize()
  shared_book_id → SharedBook (nullable) ← publisher, year, language, pages, cover
  work_fields: { rating, notes, read_status }     ← about the book, not the object
  copies: [ Copy, ... ]                            ← at least one

Copy                              ← one per physical object
  id, book_id
  label                           ← optional, user-set ("paperback", "Dad's")
  status: auto | approved | manual
  provenance: [ {run_id, spine_id, shelf_id, captured_at}, ... ]  ← append-only
  shelf_id (nullable)             ← where this object lives
  copy_fields: { tags[], condition, acquired_at }
  lending: { lent_to, lent_at, due_at, returned_at } | null
```

Three splits are doing work here:

1. **bibliographic vs user-owned** — publisher/year/cover live once, globally
   (§8); ratings and tags live per library. This is what makes the
   one-cover-per-book decision implementable.
2. **book-level vs copy-level user fields** — a rating, a note and a
   read-status describe the *book* (you don't rate your second copy
   differently); tags, condition, acquisition, location and lending describe
   the *object*. Small **[OPEN]**: if tags turn out to feel book-level in use,
   move them — it's a one-way door only if provenance was lost, and it isn't.
3. **provenance sits on the Copy** — which is where it belonged all along.
   `library.py` already records `source: {run_id, spine_id}`; that field is
   precisely a copy's evidence. **Requirement: append provenance, never
   overwrite.** A book seen on two shelves across two runs produces two
   provenance entries, and the user decides whether that's one copy that moved
   or two copies they own.

Default is exactly one copy per book, so a user who never thinks about copies
never sees the concept — the list view shows books, and the copy count appears
only when it exceeds one.

### 5.3 Shelves, captures and the multi-image case

A **Shelf** is the durable thing users think about ("living room, case 2,
third shelf"). A **Capture** is one photo of part of it. Requirements:

- one shelf may have several captures **[DECIDED — called out explicitly]**;
  they are *ordered* (left-to-right / right-to-left per the shelf's reading
  direction) so a shelf's book list has a sensible order;
- a shelf may also be **several rows deep** (§5.7), photographed one row at a
  time; captures are therefore keyed by `(shelf, depth, order)`;
- overlapping captures will produce the same book twice — de-duplication
  across captures of one shelf **at the same depth** is a required feature,
  not a nicety;
- re-photographing a shelf later produces a *new* run against the *same*
  shelf: the UI must show "shelf as of run N", and a diff ("3 books added, 1
  gone") is a natural and valuable view;
- a book removed from a physical shelf should be *removable* from that shelf
  without deleting it from the library (it may have moved).

### 5.4 Copy resolution — when a known book appears again **[DECIDED]**

When a run claims a book whose normalized `{title, author}` is **already in
this library**, the review UI offers the choice explicitly, with the crop
visible:

- **"Already listed copy"** — the same physical object. Relink: the existing
  copy's `shelf_id` becomes the new shelf, and a provenance entry is appended.
  Nothing is created.
- **"Another copy"** — a second object. Creates Copy #2 on the new shelf, with
  its own tags, lending state and label.
- **"Wrong book"** — falls through to the normal reject / replace-from-
  alternatives flow.

That third option is not optional. A claim colliding with a book you already
own is a *plausible* mis-match — the confirmed library sits at the head of the
retrieval chain (`ConfirmedCatalog`), so previously-confirmed books are
exactly the entries most available to be wrongly claimed. Without a "wrong
book" path the user is forced to choose between two answers that are both
false, and the library silently gains a bad record either way.

**This prompt must fire rarely, or it becomes review fatigue and gets
click-through-approved** — which is worse than not having it. It fires only on
genuine ambiguity:

| Situation | Behaviour |
|---|---|
| Two spines, same shelf, same run | **Never ask.** This is a mis-assignment, and `dup_drop_frac` already drops it. Unchanged. |
| Same shelf **and same depth**, re-photographed in a later run | **Never ask.** Same copy: append provenance, update last-seen. |
| Overlapping captures of one shelf at the same depth (§5.3) | **Never ask.** Resolved by capture-overlap dedup. |
| A different shelf, **a different row of the same shelf** (§5.7), or a different physical library | **Ask.** This is the real case. |

**Default when the question is skipped or the run is never reviewed:
"already listed copy"** — one copy, relinked. The asymmetry is the same one
that governs everything else here: a missed duplicate means you own two and
the catalog says one, which is mildly wrong and trivially fixed later by *"I
have another copy"*. An invented duplicate is a phantom, and phantoms rot
silently. Never create a copy without a human saying so.

Two cheap wins that fall out of this:

- if the existing copy is marked **lent out** and now shows up on a shelf,
  ask the better question: *"you lent this to Dana — is it back?"*;
- if the library already holds **several** copies, the user picks which one
  this is; default to the copy that has no shelf assigned, or the
  least-recently-seen.

Skipped questions accumulate in a **"duplicates to resolve"** queue rather
than being lost, so the answer can come later without re-running anything.

### 5.5 Runs: first-class internally, absent from the UX **[DECIDED]**

Two statements that must both hold, and that today's system conflates:

**Internally, the run archive is preserved exactly as it is.** Runs record
`run_no`, `code_version` + dirty flag, the full config snapshot, catalog
identity, and per-image/per-spine detail; decisions live outside the run so
runs stay immutable. This is what makes "run 3 was better" a meaningful
sentence, and it is the foundation of every accuracy claim in the project. It
must not be sacrificed to schema tidiness *or* to UI simplification.

**Externally, "run" is not a concept the user meets.** Today the UI is
organised around runs — a list of runs, books within a run — and that is a
developer's model leaking into the product. The user's model is:

> **my books**, and **my shelves**. A shelf can be re-read. That's it.

Concretely:

- primary navigation is **Library** (books, authors, search) and **Shelves**
  (with the physical map, §7). There is **no global list of runs**;
- a shelf shows its **read history** — dates, and what each read *changed*
  ("+3 books, 1 corrected, 12 unchanged"). That history is the only place a
  run surfaces in normal use, and it surfaces as an *event on a shelf*, not as
  an entity with a number;
- full run detail — config snapshot, code version, per-spine tiers, scores,
  crops, `explain()` — lives in an **audit/log view**, reachable but not on
  the main path. Useful for the owner and for support; irrelevant to a family
  member cataloguing their shelves;
- `run_no` and "v3: wider gates"-style labels stay, but as *developer* handles
  in the audit view and the experiments ledger, not as user-facing names.

**Consequence for the API** (§11.1): resources are shelf- and book-centric,
with runs as a sub-resource of a shelf (`/shelves/{id}/reads`), not the root
organising principle they are today (`/api/results?run_id=`).

### 5.6 A shelf's book list is durable state, not a run's output **[DECIDED]**

This is the inversion that makes §5.5 work, and it is the single biggest
change from how the system behaves today. Right now, results *are* the run.
Going forward:

> A shelf **has** books. A read is an **event that updates** that list.

Re-reading a shelf must therefore *reconcile*, never *replace* — and above all
never re-add. Reconciliation rules for each claim in a new read:

| Claim | Behaviour |
|---|---|
| Book already listed **on this shelf** | Same copy. Append provenance, update last-seen. **No new record, no review prompt.** |
| Book in the library but **on another shelf** | The §5.4 prompt: another copy / already-listed / wrong book. |
| Book not in the library | New book, normal AUTO / REVIEW flow. |
| Book the user **previously rejected** here | **Not re-added.** `library.py::absorb_auto_claims` already enforces this — a human decision must not be overridden by re-running. Preserved. |
| Book the user **approved**, now read worse (e.g. REVIEW instead of AUTO) | Approval stands. `add_book` already encodes "a human decision outranks an auto one". A re-read must never demote or re-question a confirmed book. |

**The hard case: a book that was on the shelf and this read did not find.**
It must **never** be auto-removed. Measured recall on the labelled shelves is
0.78–0.83, so absence from a single read is weak evidence — auto-removal would
silently delete roughly a fifth of a shelf every time it was re-read, and
deleting a confirmed book is precisely the destructive direction. Options, in
order of preference:

1. do nothing; keep the book, record that this read didn't see it;
2. after it goes unseen across **several** reads, surface it softly —
   *"not seen in the last 3 reads of this shelf — still there?"*;
3. never anything automatic.

Removing a book from a shelf stays a deliberate user action (and §12.2 #4 —
whether it leaves the library or just the shelf — is still open).

**What the user sees after a re-read** is therefore a *diff*, not a new result
set: what was added, what changed, what's unchanged, what wasn't seen this
time. That view is also the natural home for the shelf history in §5.5.
(Scoped by depth — see §5.7.)

### 5.7 Shelf depth: double- and triple-stacked shelves **[DECIDED]**

A shelf commonly holds **more than one row of books front-to-back**. The
capture flow is necessarily physical: photograph the front row, take those
books off the shelf, photograph the row behind, and so on.

**Model: depth is an attribute of location, not a new kind of shelf.**

```
Shelf
  depth_count: 1 | 2 | 3 | ...        ← user-declared
Capture   → { shelf_id, depth, order }
Copy      → located at { shelf_id, depth }
```

The alternative — making "shelf 3, back row" its own Shelf record — is
tempting because it needs no new concept, but it doubles or triples the shelf
list, breaks the map (two shelves occupying one physical slot), and loses the
fact that they are one piece of furniture. Depth as an attribute keeps the
physical truth.

**Depth cannot be detected; it must be declared.** Nothing in the image says
"this is the row behind" — the front books are simply absent. The UI needs an
explicit *"add a row behind this one"* action on the shelf, and the capture
flow must ask which row is being photographed. Most users won't know the
feature exists, so the shelf view should surface it rather than hide it in a
menu.

**Zero impact on the recognition core.** Depth is location metadata;
`segment`/`ocr`/`match` never see it. The core stays pure (§2).

⚠️ **Naming collision to avoid:** `segment.py` already uses **band** for the
horizontal shelf rows detected *within one photo*, and `Spine.band` is in the
stored record format. That is a vertical concept. This one is front-to-back.
Call it **depth** — never "row" or "band" in code — or the two will be
conflated by someone reading `spine_id = IMG_1234_b0_s07` and reasonably
guessing wrong.

**Three interactions that are bugs if left implicit:**

1. **The "not seen in this read" rule (§5.6) must be scoped to the depth that
   was read.** If a shelf has three rows and the user re-reads only the front
   one, the middle and back rows were not photographed at all. Comparing the
   read against the whole shelf would flag two-thirds of its books as possibly
   missing on every single re-read. Same for the diff view: a diff is
   per-depth, or it is nonsense.
2. **Capture-overlap dedup (§5.3) must not merge across depths.** Two captures
   of one shelf at different depths are not two views of the same scene — the
   scene physically changed between them. Overlap dedup applies *within* a
   depth only.
3. **§5.4's copy-resolution prompt should fire across depths.** Same shelf,
   different row is a different physical location, so the same title appearing
   at depth 1 and depth 2 is exactly the *another copy / already-listed /
   wrong book* question. Added to the firing table there.

**Two things this buys, beyond correctness:**

- *"Where is my book"* gets materially more useful: **"living room, case 2,
  shelf 3, back row"** tells you that retrieving it means moving the front row
  first. That is the difference between an answer and a useful answer;
- the system can notice **stale rows** — *"this shelf has 3 rows; the back two
  haven't been read since March"* — which is honest prompting rather than a
  silently incomplete catalog.

**[OPEN]** Whether a partially-read shelf should be visibly marked incomplete
in the library ("2 of 3 rows read") or left quiet. Marking is more honest;
it also nags.

---

## 6. The library experience (first build target)

This is what turns runs into a product. Scope for the first pass:

**Must**
- all books, with sort (title / author / recently added / shelf) and paging;
- search across title and author using the *normalized* forms, so a query
  typed without nikud, with a prefix (ה/ו/ב/ל/מ/ש/כ), or with a final-letter
  variant still hits. Hebrew search is the one genuinely hard part here;
- author view: click an author → their books in this library;
- book detail: the spine crop, which shelf it's on, when it was last seen, and
  a "why?" explanation (the existing `explain()`). Tier, score, run and config
  detail belong in the audit view (§5.5), not here;
- shelf view: books on this shelf in physical order, with the photo, **split
  by row where the shelf is stacked front-to-back** (§5.7), plus **read
  history and diffs** (§5.6) — what each re-read added, changed, or didn't
  see. This replaces the run list as the way history is exposed;
- edit: fix title/author by hand, or replace from ranked alternatives;
- filter by status (auto / approved / manual) and by shelf.

**Should**
- user fields — rating, notes, read status on the book; tags on the copy
  **[DECIDED, phase 2]**;
- **"I have another copy"** — the only way a second copy is ever created
  (§5.1), with per-copy label, shelf and tags;
- lending state per copy, visible in list and detail, plus a "who has my
  books" view;
- **copy resolution at review time** (§5.4) — a known book detected on another
  shelf asks *another copy / already-listed copy / wrong book*, plus the
  "duplicates to resolve" queue for skipped ones;
- CSV/JSON export of the whole library (also the honest answer to lock-in).

**Later**
- covers **[DECIDED, phase 3]**, sourced globally (§8.3);
- summaries and review links **[DECIDED, phase 4]**;
- series awareness ("you have books 1 and 3").

**Design constraint:** RTL-first, since the collection is Hebrew, but the
library is *not* Hebrew-only (an English book already appears in the sample
shelves). Mixed-script titles, mixed-direction lists, and search across both
scripts are baseline requirements, not internationalisation polish.

---

## 7. Physical library mapping

**[DECIDED]** Build POCs for **both** approaches and pick on evidence of which
is simpler in practice:

**A — Freehand sketch, straightened.** The user draws their room: rough
rectangles for bookcases, rough lines for shelves. The system snaps the
hand-drawn strokes into a clean orthogonal schematic (line straightening,
angle snapping, alignment, edge merging). This was the owner's preference,
conditional on the straightening working — a wobbly hand-drawn canvas is not
the target, a clean schematic derived from a wobbly sketch is.

**B — Bookcase photo, shelves auto-detected.** Reuse the existing horizontal
shelf-band detection (`segment.py`) on a wide photo of a bookcase to propose
shelf rows; the user confirms or adjusts. Elegant reuse of code that already
exists and is already tuned for exactly this signal.

They are not exclusive — B is a good *input* to A (detect the bookcase's
shelves from a photo, place the resulting block on the sketch). The POC should
answer: which produces a usable map faster, on a phone, for a non-technical
user with four bookcases in three rooms?

Requirements common to both:
- **multiple physical libraries per Library** **[DECIDED — explicit]**;
- each Shelf in the map binds to zero or more Captures;
- given a book, the UI can answer "where is it" by highlighting the shelf on
  the map — **including which row front-to-back** (§5.7), since a back-row
  book means moving the front row to reach it;
- a shelf on the map carries its declared depth, so "3 rows, back two not read
  since March" is answerable from the map;
- the map must be editable after the fact (furniture moves);
- a user who never draws a map still gets a fully working catalog — the map is
  an enhancement layer, never a prerequisite.

---

## 8. The shared books database

**[DECIDED]** Approved books flow into a global DB, **opt-out** (on by
default, disclosed at onboarding). Only bibliographic data — never photos,
never crops, never ownership, never who confirmed it.

### 8.1 Why it exists

Not "a bigger list matches better" — `CLAUDE.md` already corrects that
overstatement. The real value is threefold:

1. **Free retrieval.** A book confirmed by any user becomes an instant,
   offline, zero-cost candidate for every other user. Hebrew popular fiction
   has enormous overlap between home libraries; the second user to own
   `משחקי הכס` should not cost an NLI round-trip.
2. **Cover and metadata hosting, once.** **[DECIDED]** One cover per book
   globally, not per customer — this is what makes covers affordable at all.
3. **Coverage of what NLI misses.** Editions, popular translations, and
   spine-title variants that a formal catalog records differently from how the
   book is actually printed on the spine.

### 8.2 Safety rules (non-negotiable)

- **Only human-approved books enter.** AUTO claims do not, ever. Feeding
  unverified claims into shared retrieval lets phantoms self-reinforce across
  every user — the same reasoning `library.py` already applies within one
  tenant, and the blast radius here is global.
- A shared entry needs corroboration before it outranks a formal catalog:
  confirmed by ≥N distinct libraries, or matched to an NLI record.
- The shared DB must be **removable from the retrieval chain** for measurement
  — the sweep must be able to run without it, exactly as the confirmed library
  is excluded from sweep catalogs today.
- **[OPEN]** Its influence on accuracy must be measured before it is trusted:
  it could plausibly *hurt* precision by adding near-miss neighbours. Run a
  `--live --sources` comparison before promoting it into the baseline chain,
  per the existing rule for any new source.

### 8.3 Covers **[DECIDED, later phase]**

One instance per book, globally. Sourcing is unresolved **[OPEN]** —
publisher cover art is copyrighted and NLI/Simania image reuse terms are
unclear. The always-safe fallback is **the spine crop we already produce**:
it's ours, it's authentic to the user's actual copy, and a shelf of real spine
crops is arguably a nicer browse experience than stock cover art.

### 8.4 One book, one record **[DECIDED]**

A book must appear in the shared DB **once**. Contribution is an *upsert with
a corroboration counter*, never an insert. Without this the shared DB
degenerates into exactly the thing `CLAUDE.md` warns about — a bigger flat
list with more chances for garbled OCR to hit the wrong neighbour — and the
one-cover-per-book decision becomes unenforceable.

**Identity key.** With no ISBN available (§5.1), the key is
`normalize(title) | normalize(author)` — the same function the matcher and
`ConfirmedCatalog` already use, which is the right choice because it means a
shared record is keyed identically to how it will be retrieved.

**Near-duplicate merging.** Exact-key matching will not catch everything:
translation and transliteration variance (`ג'ראלד דארל` vs `ג'רלד דורל`),
subtitle presence, series-volume phrasing. Detection should reuse what already
exists and is already tuned — `ngram_sim`, which was built precisely because
`token_set_ratio` scores a short subset title a perfect 100. Candidate pairs
above a threshold go to a **merge queue with an alias table**, not to an
automatic merge.

**The asymmetry that sets the threshold:** a wrong merge corrupts retrieval
for *every* user and is hard to notice; a missed merge leaves a duplicate,
which is mild noise. So the automatic path must be conservative and the
review queue must be where the recall comes from. This is the same principle
as the matcher's gates — say "I don't know" rather than guess — applied one
level up.

**Corroboration, not just presence.** Each shared record carries a count of
*distinct libraries* that confirmed it, plus whether it matched a formal
catalog record (NLI/Simania). §8.2 already requires corroboration before a
shared entry outranks a formal catalog; the counter is what implements it, and
it also gives the merge queue a priority order (merge the popular ones first).

Counts must be **distinct-library**, not distinct-copy — otherwise one user
duplicating a book (§5.1) inflates its global standing.

---

## 9. Accuracy in a multi-user world

### 9.1 Near term

The owner's hand-labelled shelves remain the fixture source, and GT coverage
stays **curated, not automatic** — a processed shelf joins the fixture when
the owner chooses to label it. That existing rule is unchanged.

### 9.2 Sampled correction corpus **[DECIDED in principle, phase 7]**

User corrections become an ever-growing anchor for the rules — but by
**sampling, not exhaustively**. That instinct is right, and for a sharper
reason than volume: the fixture's value is **diversity, not size**. A shelf
where every claim was AUTO and every AUTO was approved teaches the gates
almost nothing. A shelf with three rejects and a replace is gold.

**What the real costs actually are** — worth naming precisely, because
"storage" is the intuitive answer and it's the wrong one. A correction sample
is *text*: the stored read, the stored candidate recording, and the human's
verdict. No photos, no crops. The 8-shelf fixture is ~1MB. The binding costs
are:

1. **Gate runtime.** `sweep --check` runs on every accuracy-relevant commit
   and currently finishes in seconds. At hundreds of shelves it would not, and
   **a slow pre-commit gate gets bypassed** — which would cost more accuracy
   than the extra fixtures buy.
2. **Repo size.** The gate's inputs are *committed* (`fixtures/sweep/`) so a
   fresh clone reproduces the baseline. That property is worth keeping, and it
   caps how large the committed set can sensibly get.
3. **Curation.** One user's careless "approve" becomes a permanently wrong
   label. An unreviewed corpus is a corrupted ruler, and `CLAUDE.md`'s second
   hard-won rule is that a bad ruler invents work.
4. **Consent surface** — **[OPEN]**: opt-in or opt-out? Raw reads can catch
   incidental non-book text, which argues for opt-in and a different
   disclosure from the books DB's opt-out.

**Proposed shape — two tiers:**

- **Core gate fixture** — small (tens of shelves), curated, committed,
  reproducible, fast. This is what the pre-commit hook and the baseline use.
  Growth here is deliberate and human-approved.
- **Extended corpus** — large, sampled from users, stored outside git, run on
  demand and on a schedule rather than per commit. Its job is to catch
  regressions the small set can't see, and to *nominate* candidates for
  promotion into the core fixture.

**Sampling should prefer the informative:** shelves where the human disagreed
with the machine (reject / replace / manual add), spines that landed in
REVIEW, titles and authors not yet represented, and varied capture conditions
(stylised typography, thin spines, poor light) — the failure modes
`CLAUDE.md` already documents as the hard core. Cap per-tenant contribution so
one heavy user's shelves don't dominate the corpus.

### 9.3 Required regardless

- **per-tenant accuracy telemetry** — approve/reject/replace rates per run are
  a live precision proxy that needs no ground truth at all. A tenant whose
  reject rate spikes is a signal worth having;
- **the sweep and spotcheck harnesses keep working offline** against committed
  fixtures, with no DB and no tenant context. Non-negotiable (§2);
- **the pre-commit gate stays enforced** through the whole rewrite. A
  multi-user refactor is exactly when an accuracy regression would slip in
  unnoticed;
- **re-running an old shelf with new code must stay possible** — this is why
  photos are retained, and it's the multi-user version of "would my change
  have fixed this spine?".

---

## 10. Cost, keys, and quota

**[DECIDED]** Free quota on our key → then BYO.

Requirements:

- **metering** per Library: pages processed, engine calls, tokens/units,
  currency cost. Visible to the Library's admin, not hidden;
- **hard caps** at the free-quota boundary, plus a per-tenant rate limit. A
  single user must not be able to run our bill up by uploading 400 photos;
- **BYO key storage**: encrypted at rest, write-only from the UI (never
  displayed back), never logged, never included in run snapshots or error
  reports. `CLAUDE.md`'s credential-hygiene rule extends here — and the
  exposure is now *other people's* keys, which raises the stakes considerably;
- **key validation** at attach time — a user must learn immediately that their
  key is wrong, not on their next run;
- **graceful degradation**: quota exhausted with no key attached should still
  allow the free deterministic path (Tesseract spines mode) rather than a hard
  stop. The whole architecture is built around the paid engine being optional;
- **[OPEN]** which providers a user may bring: Anthropic only, or Google Vision
  too? Two key types means two validation paths and two cost models.

The deterministic-first philosophy from `CLAUDE.md` is not just an aesthetic
preference here — it *is* the cost model. Every spine resolved by free local
code is a spine nobody pays for.

---

## 11. Architecture and deployment (proposed)

### 11.1 Shape

```
 clients ──── versioned JSON API ──── API service (FastAPI)
   web (now)                             │
   native (later)                        ├── auth / tenancy / permissions
                                         ├── library, search, review, lending
                                         └── enqueues jobs
                                              │
                                    job queue │
                                              ▼
                                        Worker(s)
                                          └── booksnap core  (pure library:
                                              segment / read / retrieve / match)
                                              ▲
        object storage (photos, crops) ───────┘
        database (entities + run records)
        shared books DB  ── retrieval source, opt-out contributions
```

Key points:

- **`booksnap` core stays a pure library.** The worker imports it; it imports
  nothing about users, HTTP, or the DB. This is what keeps `sweep.py` alive.
- **Runs become background jobs, not in-process threads.** Today's server runs
  a job on a thread with a module-level `_set_job`/`_get_job` singleton — that
  is correct for one user and wrong for many. A real queue is required:
  per-tenant fairness, retry, cooperative stop (the existing `should_stop`
  polling maps directly onto it), and progress reporting.
- **Photos and crops move to object storage**, not the DB and not local disk.
  Retention and user-purge (§3) become storage-lifecycle operations.
- **Versioned API from the start** (`/api/v1/...`). Cheap now; the alternative
  is breaking a shipped native client later.
- **Resources are books and shelves, not runs** (§5.5). Reads become a
  sub-resource — `/libraries/{id}/shelves/{id}/reads` — and the run archive is
  exposed through an audit endpoint. Today's `/api/results?run_id=` shape is
  the developer model and does not survive the rewrite. The archive itself
  does, unchanged.
- **Self-hosting is not a goal** given the hosted decision, but nothing should
  gratuitously prevent it. Prefer portable components over managed-cloud-only
  primitives where the cost is zero.

### 11.2 Migration from today

The owner's existing `work/` data — runs, decisions, the confirmed library,
crops — is real, hard-won data and must migrate, not be abandoned. A one-shot
importer that reads `work/store.json`, `work/runs/*`, `library.json` and
`decisions.json` into the new store is a required deliverable of the
persistence phase, not an afterthought. It doubles as the first real test of
the schema.

### 11.3 Environments

Dev == server was already a design goal (`config.py`, paths via env vars).
Keep it: one config surface, environment-driven. Add a staging environment
before inviting anyone outside the family — an accuracy regression on someone
else's library is not recoverable by re-running, because their *review
decisions* are the expensive artifact.

---

## 12. Open questions

### 12.1 Datastore **[OPEN — research and decide later, owner's instruction]**

Decide against these criteria rather than by preference:

- relational integrity for memberships, roles, shelves, lending — the parts
  where a bug means someone sees a library they shouldn't;
- document-shaped storage for run records and config snapshots, which are
  deeply nested and schema-fluid by design;
- **Hebrew search quality** — the hardest requirement. Postgres full-text has
  no Hebrew configuration; `pg_trgm` over the *normalized* forms that
  `normalize()` already produces is likely sufficient and would avoid a third
  moving part, but this needs measuring, not assuming;
- blob handling for photos/crops — almost certainly object storage regardless
  of the DB choice;
- operational cost and backup story at invite-only scale.

Candidates on the table: Postgres (+JSONB), Postgres + dedicated search
engine, MongoDB, SQLite-per-tenant. `library.py`'s comment anticipating Mongo
predates the permissions and lending requirements and should not be treated as
a decision.

### 12.2 Product/UX questions to settle

1. **[SETTLED 2026-08-10, P3.2]** May a **Viewer** see the original shelf
   photos? **No.** The photos show the inside of a home, and "viewer" may
   mean a friend browsing what you own; the catalog — titles, authors,
   lending state — is what a Viewer is for. `VIEW_PHOTOS` is its own row in
   §4.2's matrix, Editor+, so reversing this is a one-cell edit. The
   privacy-preserving cell is also the cheap-to-reverse one: loosening later
   shows photos to people who could not see them; tightening later cannot
   un-show them.
2. Can one **Account** belong to several Libraries, and how does it switch?
   (Assumed yes above; P3.1 built exactly this.)
3. **[SETTLED 2026-08-10, P3.2]** What happens when two members review the
   **same run** simultaneously? **Optimistic concurrency — no locking, no
   per-spine claim, and no new schema.** The write paths already have the
   right semantics: every apply recomputes against CURRENT library state and
   is idempotent by sighting (`Provenance.sighting`, P2.7/P2.9), so two
   people confirming the same finding produce one book, one copy, one
   sighting; and an answer to a question someone else just closed gets a 409
   from the duplicates router's own re-derivation rather than a duplicate
   write. Locking would trade that for a held-lock UX problem (§5.4's whole
   design is that these prompts are rare); a per-spine claim is coordination
   machinery for a household of two reviewers. Revisit only if real
   simultaneous review produces a measured conflict this does not absorb.
4. Does a book **removed from a shelf** stay in the library by default?
5. Is there a **wishlist / "want to read"** concept, or is the library strictly
   what you physically own?
6. Should the system support **manual book entry** without a photo at all
   (typing, or an ISBN)? Cheap and often the fastest path for a book the
   camera can't read.
7. Is **offline capture** required — photograph shelves now, upload when
   there's signal? Materially affects the client architecture.
8. **Notifications** at all (loan due, run finished)? Push implies native or
   web-push infrastructure.
9. Is a **borrower** a free-text name, or optionally an Account? An Account
   borrower could see "books I'm holding" in their own app and be reminded
   automatically — genuinely useful, and it also covers lending *within* a
   family library, where borrower and member are the same person.
10. **[SETTLED 2026-08-09, owner]** §5.5 says "there is no global list of runs"
    and a run surfaces only as an event on a shelf. That is right for the
    *Library* mental model and **wrong for the Capture tab**, where the owner
    is doing the cataloguing and the unit of work is the photograph:

    > *"The heart of this tab are the images and the analysis. In Books we see
    > the list and act on books. In Map we arrange the physical aspects. But
    > here, in Capture and Read, we focus on the images."*

    So the resolution is a **split by surface, not a reversal**: an image is a
    durable object with a history, clicking it opens that image's **runs**, and
    each run lists its **findings** with approve / edit / remove — the review
    loop the engine POC already had. Books and Map stay run-free exactly as
    §5.5 requires; the run-shaped view lives where the work is, which is also
    what §5.5's own "audit view, reachable but not on the main path" allows.

    What this rules out is the reading that produced the current tab: a
    one-way pipeline (drop → run → the result scrolls away) with **no route
    back to a finished analysis**. Re-running a photo you have already
    processed is not a substitute for looking at what it found — it costs
    money, it costs time, and it invites re-deciding questions already
    answered.

11. **[SETTLED 2026-08-09, owner]** **Nothing enters the library until a human
    approves it.** §5.6's table let an AUTO-tier claim for an unknown book
    enter on its own, mirroring `booksnap/library.py::absorb_auto_claims`; the
    owner watched one photo file fourteen books he was never asked about:

    > *"until I do not manually approve, the books should not be added to the
    > local library."*

    So a read now produces **findings**, and a finding becomes a Book only
    through an explicit ✓ (individually, or via *approve all*). Two
    consequences worth stating, because both are visible and neither is a bug:

    - **tier stops deciding entry** and decides only presentation. An AUTO and
      a REVIEW finding are the same state — waiting — which is why they carry
      the same controls (the owner's own follow-up: *"a review book should
      have the same available controls as an auto book"*);
    - **a read's archived diff summary leads with its pending count**, because
      "+0 added" is what an honest engine read now produces. The finding list
      under it still shows what each finding IS today; that disagreement is
      §5.5/§5.6's snapshot-vs-live distinction, not drift.

    The exception is a book the owner **types in** onto a photo (*"the engine
    missed this one"*): it enters at once, at `manual`. There is nobody left
    to ask, and demanding approval of what someone just typed is exactly the
    ceremony §5.4 warns trains people to click through prompts.

    UI_PLAN §6 already lists *auto-approve AUTO* as a Settings toggle. Until
    that setting exists its value is OFF; when it ships, this is the rule it
    turns back on.

12. **[SETTLED 2026-08-09, owner]** **The Capture tab carries no shelf
    plumbing.** *"Open the shelf →"* and *"add a row behind"* are both gone
    from it: a photo is a shelf, or part of one, and binding it to a place in
    the house — including how many rows deep that furniture is — is the **Map**
    tab's job. §5.7's argument that nobody discovers depth unless it is offered
    early stands; it just does not get to be answered here. The depth PICKER
    stays, because an already-stacked shelf still has to say which row a photo
    shows.

### 12.3 Technical questions to settle

10. Deployment target — VPS + Docker Compose, a managed PaaS, or a cloud
   provider's managed services? Affects cost, ops burden, and portability.
11. Do we keep the Tesseract spines path as the free tier, given it costs
    ~20s/spine and llmpage is the default mode now? If yes it needs to stay
    maintained and measured; if no, the "graceful degradation" story in §10
    needs a different answer.
12. Image size/compression policy on upload — accuracy depends on resolution,
    storage and transfer costs depend on it too. Needs measuring, not guessing.
13. Idempotency on re-upload of the same photo (hash-based dedupe?).
14. Rate limiting and abuse controls, even invite-only.
15. Terms of service and privacy policy — required before the shared books DB
    ships opt-out to anyone outside the family.
16. Consent basis for the correction corpus (§9.2) — likely opt-in, and likely
    a separate toggle from the books-DB opt-out.

---

## 13. Candidate features not yet discussed

Listed so they're on record; none are committed.

**Likely valuable**
- **ISBN/barcode scanning** as a complementary capture path. Deterministic,
  free, near-perfect, and squarely in this project's philosophy — for any book
  with a barcode it beats every OCR path. A strong candidate for the modern
  half of a collection, and a good manual-add mechanism.
  Note this does **not** reopen §5.1: that decision was about not trying to
  extract an ISBN *from a spine photo*, which is genuinely infeasible.
  Deliberately scanning a barcode on the back cover is a different act, and it
  would arrive as a book identity, not an edition model.
- *(Shelf diff over time was on this list; promoted to a requirement in §5.6 —
  it is now the mechanism by which history is exposed at all.)*
- **"Do I already own this?"** — search your library from your phone while
  standing in a bookshop. Small feature, disproportionate real-world use.
- **Import** from Goodreads / LibraryThing / CSV, for users with an existing
  list.
- **Loan reminders** — a lent book with no due date is a lost book.

**Speculative**
- Series completion suggestions ("you have 1 and 3").
- A public, shareable read-only library page.
- Reading statistics.
- Family activity feed ("Dana approved 12 books").
- Accessibility pass — screen-reader support for the library views.

---

## 14. Proposed sequencing

Accuracy work continues in parallel throughout; it is not a phase that ends.

| Phase | Content | Rationale |
|---|---|---|
| **0 — now** | Detection accuracy: retrieval, reader-side recall, rules via sweep/spotcheck | The heart of the system; everything else is a shell around it |
| **1** | **Library experience**, single-user, on the current store — and with it the run→shelf/book inversion (§5.5, §5.6) | **[DECIDED]** as the first build. Highest motivation-per-hour, and it sharpens the data model *before* it's frozen into a multi-tenant schema. The inversion belongs here because it *is* the library experience |
| **2** | Datastore decision + schema + migration of existing `work/` data; shelf/physical-library entities | Do this once the phase-1 UI has revealed what the model actually needs |
| **3** | Multi-user foundation: auth, tenancy, roles, invites; job queue; object storage | The expensive-to-retrofit layer |
| **4** | Quota metering + BYO keys | Required as soon as anyone else runs anything |
| **5** | Capture + review UX for phones; PWA install | Better capture improves detection directly, not just UX |
| **6** | Physical mapping — POC both approaches, then build the winner | Depends on shelf entities from phase 2 |
| **7** | Shared books DB (with §8.4 dedup/merge from the start) + covers; sampled correction corpus (§9.2); measure both against the fixture before trusting either | Needs users before it's worth anything. Dedup is not a later addition — retrofitting identity onto a polluted shared DB is the expensive version |
| **8** | Native clients | Deliberately last; the API discipline from phase 0 is what makes it possible |

Phases 1 and 2 are deliberately ordered UI-then-schema. That is the opposite
of the usual instinct, and it is right here: the data model's hardest
questions (author identity, duplicates, shelf membership, what a "book"
actually is) become obvious the moment you try to render a browsable library,
and guessing at them first is how you end up migrating twice.
