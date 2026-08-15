# Pillar 6 — The physical map

**Status: APPROVED (owner, 2026-08-15).** Replaces the four-item sketch of
"Pillar 6 — The physical map (and shelf addresses)" in
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md), which covered about half
of what the owner actually wants and forked on the wrong question. This
document is the decomposition and the progress tracker: items gain a ✅ as
they land on `main`.

**Pillar 5 (cost) is deliberately skipped for now and is not a prerequisite.**
Nothing here spends money: the sketch is client geometry, and the one optional
automation (bookcase photo → shelf levels) is `segment.py` — local, free, and
already tuned. Pillar 4 is closed (P4.0a → P4.4 all landed), so there is no
dangling dependency either.

## 1. What the owner asked for (2026-08-15, verbatim in substance)

> Draw or provide a sketch of the rooms in the house. In each room, draw where
> the bookcase(s) are, including length relative to the room walls. **Free
> measurements — not real centimetres.** Each bookcase is clickable to provide
> columns, shelves in each column (default applies to all columns), and depth
> (how many book-lines the bookcase holds) — default for the whole bookcase,
> overridable per shelf. Later, images attach to shelves: many per shelf, with
> an optional depth.
>
> Two items: the way to draw/provide the house + bookcase information, and
> then the "regular" settings and matching.
>
> A simple but elegant way to sketch the house is the key for this feature.
> Try it in a small app of its own until we are happy, then copy the code in —
> rather than experimenting inside the main application and triggering a much
> wider scope of change.

## 2. Corrections against the standing decomposition

Re-reading `IMPLEMENTATION_PLAN.md` §Pillar 6, `UI_PLAN.md` §3 and VISION §7
against the code found one wrong fork, one under-sized item, and five things
the owner named that appear nowhere:

- **The A-vs-B fork is stale.** VISION §7 offers *A: freehand sketch,
  straightened* against *B: bookcase photo, shelf levels detected*, and calls
  the straightening "the whole bet". Those are not competing paths: B produces
  a **bookcase elevation**, A produces a **room plan**. They answer different
  questions and the plan needs both. The live fork is inside A — see §4.
- **P6.1b (shelf merge) is the risky item, filed as a footnote.** The drawing
  is a canvas; the *binding* repoints `Copy.shelf_id` across a population of
  shelves that provenance and past reads still refer to. That is where a
  silent data-loss bug would live, and it gets its own item here (P6.4).
- **Absent from the old plan entirely:** the house/rooms as an *authoring*
  surface (it only ever described *rendering* one); bookcase length relative
  to its wall; per-column shelf counts with a case-level default; the
  per-shelf depth override; and the standalone lab.
- **Already built, and the plan should stop owing it:** "many images per
  shelf, with an optional depth" is `Capture{shelf_id, depth, order}` plus
  VISION §5.3's multi-image case — shipped in P2.2/P2.3 and contract-tested.
  Pillar 6 surfaces it from the map; it does not build it.

## 3. The model, decided before any code

Four rules, each of which is cheap now and expensive later.

### 3.1 A drawn shelf slot IS a `Shelf`

Today a shelf is born **bottom-up**, from a photo: "a capture with no shelf
gets a fresh unnamed shelf" (CLAUDE.md). The sketch creates shelves
**top-down**: draw a case with 2 columns × 5 levels and ten shelves now exist
that were never photographed.

Those two populations become one population. A drawn slot is a real `Shelf`
row — created empty, carrying an address — **not** a second concept with a
mapping table beside it. The alternative forks every query about "the books on
this shelf" into two paths permanently, and forks them in the direction where
one path is always the surprising one.

Consequence, stated so it is not discovered at P6.4: a `Shelf` may now exist
with **no capture and no books**, and every screen that assumes otherwise is
wrong today.

### 3.2 Two geometries, never one canvas

| | what it is | what it carries |
|---|---|---|
| **Plan** | top-down, per Place | walls; where a case stands, along which wall, how long, facing which way |
| **Elevation** | front-on, per Bookcase | columns across × levels down; the shelf photo in each cell |

They are related — a longer case usually has more columns — but they are not
the same picture, and a length is not a column count. The moment one canvas
holds both, the model is wrong in a way no test catches. `UI_PLAN.md` §3's
three drill levels already have this right; the rule is written here so it
survives the editor being built.

### 3.3 The bookcase's depth is a **creation-time default**, never a live parent value

"Default for the whole bookcase, overridable per shelf" is right. The trap is
inheritance: if the case's depth is read live, editing it from 2 to 1 silently
deletes the location of every book standing at depth 2 in that case.

So: the case's `default_depth` is copied into each shelf **when the shelf is
created**. After that, depth is the shelf's own (`Shelf.depth_count`, which
already exists and is already validated). Changing the case's default offers
to apply to existing shelves — an explicit action, showing the count affected
— and can never take a shelf below its deepest occupied row.

### 3.4 Free measurements mean the system may never infer capacity

Lengths are relative to their wall and to each other. Nothing may derive "this
shelf holds about 40 books" from geometry, on any screen or in any export. A
plausible number nobody measured is exactly the kind of thing a later reader
adds because it looks like free value, and a wrong stated number is worse than
no number (CLAUDE.md, working style).

Geometry is stored as **integers in an abstract unit space**, never pixels: a
canvas resize, a phone rotation or a zoom must not be able to corrupt a plan.

### 3.5 The plan is pinned LTR

A floor plan does not mirror when the UI language flips — the furniture did
not move. Same rule `UI_PLAN.md` §3 already pinned for the elevation grid.
Labels inside the plan follow the UI language; the geometry does not.

## 4. The live fork, and what the lab is for

The owner's brief says *draw **or provide** a sketch*, and "simple but elegant
is the key for this feature". Two candidate interaction models:

**S — Straighten.** Freehand strokes, snapped afterwards into a clean
orthogonal schematic (VISION §7's approach A). The bet is that the
straightening reads the user's intent correctly.

**D — Direct, constrained.** Walls snap to a grid and to 90° **as you drag**;
a bookcase snaps onto a wall and gains a length handle you pull. Snapping
happens at input time.

**Recommendation on record: D.** S has one failure mode D does not have — the
system guesses wrong about what you meant, and there is no correction except
redrawing. D is also the one that degrades gracefully to a thumb on a phone.
But this is a UX claim, and CLAUDE.md's rule is that UI claims get verified in
a real browser, not asserted. **The lab settles it, by the owner drawing his
real house in both.**

**"Or provide a sketch" is answered cheaply, either way:** an uploaded floor
plan (photo or PDF export) becomes a **tracing underlay** behind the canvas at
adjustable opacity, traced with the same tools. No image understanding, no
paid call, nothing unreliable — compare room-photo → floor-plan generation,
which `UI_PLAN.md` §3 already flags for perspective, occlusion, scale, and a
paid call per attempt. That flag stands: **room-photo → floor plan is not in
this pillar.**

## 5. Items

| # | Item | Size | State |
|---|---|---|---|
| **P6.0** | **The map lab** — a standalone app, no backend, outside the gate. Both editors behind a switch; underlay tracing; the elevation editor. Exit: the owner draws his real house and picks. | M | |
| **P6.1** | **Address domain + migration** — `Place`, `Bookcase`, the shelf address, geometry in abstract units. Drawn slots create real empty `Shelf` rows. Naming lint. Schema vN with a real v(N-1) upgrade test. | L | |
| **P6.2** | **API + policy** — places/bookcases through `current_library`, one capability each, contracts regenerated. | M | |
| **P6.3** | **The port** — the chosen editor moves into `app/web`, wired to the API. **The lab is deleted in the same commit.** | M | |
| **P6.4** | **Binding and merge** — photo-born shelves bind into drawn slots; several identities merge into one physical shelf, with aliases. | L | |
| **P6.5** | **The map as navigation** — three drill levels, "where is it" incl. depth, stale-depth surfacing, capture handoff. | L | |
| **P6.6** | *Optional:* bookcase photo → proposed levels via `segment.py`, confirmed by hand. | S | |

### P6.0 — the map lab

**Why a separate app** (owner's call, and the right one): the editor is the
piece most likely to need five throwaway attempts, and each attempt inside
`app/web` drags the client ring, the shared package, the RTL rules and the
i18n table behind it. The lab has none of that.

**Where:** `planning/map-lab/`. `planning/` is already the folder that "runs
nothing in the product", and — checked against `tools/githooks/pre-commit` —
nothing outside `app/`, `tests/` and `tools/api_contract.py` routes to any
gate. The lab therefore cannot slow or block a commit.

**The three constraints that make the port nearly free**, because the failure
mode to design against is the lab drifting until "copy the code" is a rewrite,
or the lab surviving as a permanent second copy (this repo already carries one
deliberate two-copy situation — the tuning server — and a second one must be a
decision, not an accident):

1. **the core is framework-free.** Model, geometry, snapping and hit-testing
   are pure TypeScript modules with no React import, no DOM, no `fetch`, no
   router. They are the part that ports verbatim;
2. **the shell is thin and disposable.** React + Vite + TS matching
   `app/web`'s toolchain, so the port is a folder move plus a data adapter;
3. **it dies on schedule.** P6.3 deletes it. An item that is not allowed to
   quietly become permanent.

**Target for the port is `app/web`, not `app/ui`.** Only one client needs an
editor; `app/ui` is for what both clients need or must not disagree about
(CLAUDE.md #6). If the console ever renders a plan read-only, the *core*
moves to `app/ui` then — not pre-emptively.

**Done when:** the owner draws his real house — rooms, bookcases along their
walls, one case opened into columns × levels with a depth override on one
shelf — on a phone-sized viewport, in both interaction models, and says which
one to build.

## 6. What P6.1 must not repeat

Rule 11 of CLAUDE.md, in its own words: three consecutive migration reviews
(v16, v17, v18) found the same thing missing. P6.1 adds tables, so:

- `review-migration` runs **before** the commit, not after;
- the new DDL is its **own step**, never folded into the previous one;
- a `v(N-1) → vN` test on a **real old file** — build the chain to N-1, insert
  real rows, open the store, then assert the version, the rows,
  `foreign_key_check`, **and the index names**;
- no step manages its own transaction;
- `python tools/backup.py` before any live browser-driven mutation, taken
  **before** the gate runs (importing `app.main` migrates).

## 7. Open questions for the owner

1. **Does a Place nest?** "House → living room" and "the parents' place" are
   both Places today (§4.1's settled rule: a Place is any location within one
   tenant — a room *and* a whole other site). One flat list is simpler; a
   two-level site → room is truer to a house with eight rooms. *Recommendation:
   flat, with a free-text label, until a real collection makes it hurt.*
2. **Can a bookcase stand off a wall** (an island shelf, a room divider)? Wall
   snapping is the whole ergonomic win; free placement is an escape hatch that
   costs a mode. *Recommendation: yes, but as a deliberate "detach" — snap is
   the default, not the only option.*
3. **Which end is column 1** for a Hebrew user? `UI_PLAN.md` §8 already has
   this open, and the map plan inherits it — the elevation is pinned LTR, but
   *which physical end* the leftmost cell means is a real question about a real
   piece of furniture.
4. **Does the plan carry doors and windows?** They make a room recognisable at
   a glance and cost one more tool. They also carry no book data. *Recommendation:
   in the lab, so we can see whether it reads better; decide from the drawing.*
