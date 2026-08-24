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

Ten rules, each of which is cheap now and expensive later.

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
| **Elevation** | front-on, per Bookcase | sections stacked bottom to top (§3.6), each columns across × levels down; the shelf photo in each cell |

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

### 3.6 A bookcase is one or more **sections**

**[DECIDED 2026-08-16 — owner]** *"Sometimes a bookcase is built of 2
bookcases one on top the other: a low one with X columns, and a higher one on
top of it with Y columns."*

That is **one piece of furniture** — one footprint on the floor, one name, one
room it moves with — so it stays **one Bookcase on the plan** and gains
structure in the *elevation*:

```
Bookcase ──> sections (bottom → top)
               section 1 (on the floor)   X columns × levels, its own depth
               section 2 (on top)         Y columns × levels, its own depth
```

The shelf address becomes **(section, column, level)**. A plain bookcase has
**one** section, so the ordinary case costs nothing — the editor renders no
section chrome at all until a second one exists, the way the library switcher
stays a plain label until a second library does.

**Why not two Bookcases stacked.** The plan is top-down: two cases sharing one
footprint puts two objects in one place, so a tap is ambiguous, *"where is my
book"* answers *case 2* about something that is visibly one bookcase, and
moving the room has to keep two records in step. That is VISION §5.7's
argument against making "shelf 3, back row" its own Shelf — *"two shelves
occupying one physical slot… it loses the fact that they are one piece of
furniture"* — turned vertical.

**Why not per-column level counts** (which already exist): those give a ragged
top edge on one grid. They cannot say *above this height the case is divided
differently*, which is exactly what a hutch on a base is.

Three rules that come with it:

- **the address prints only what discriminates.** A one-section case never says
  "section 1", because saying it would imply there is a section 2. Same for
  every accessible name in the editor;
- **depth is per section**, seeded into each shelf at creation exactly as §3.3
  requires. A deep base under a shallow top is the common build;
- **the plan rectangle is the footprint**, so it is the *deepest* section's
  outline — the thing you would trip over — and the plan's column dividers are
  drawn from the **bottom** section. Once sections divide differently there is
  no single honest answer, and the one standing on the floor is the least
  arbitrary.

⚠ **Naming, and it is part of the design.** Not a *unit* — the plan's
measurements are already units. Not a *tier* — too close to `level`, the shelf
row inside a column. **Section**, which is what modular shelving is sold as.
This project has been bitten by exactly this before (depth ≠ row ≠ band).

The general form — free-form blocks placed anywhere in the elevation grid,
which would also express a desk niche or an L — is a layout editor, and is
deliberately **not** built until something asks for it.

⚠ Something asked, on 2026-08-22: a television in the middle of a wall unit.
What landed is **not** the layout editor — the grid is still columns × levels
— but its cheap half: cells that hold no shelf, with the extent untouched.
**§3.10a** is that decision, and this paragraph still stands for the rest.

### 3.7 Floors group rooms — they are **not** part of an address

**[DECIDED 2026-08-16 — owner]** *"We should also support multiple floors, each
with a different room structure. It can be simply just another name for a room
— no need to change the address structure. Just want it to be easy reflected
in the map."*

So a `Floor` is a **grouping over rooms**, and nothing else. A shelf's address
stays `place · case · section · column · level`; a floor never enters it, and
`P6.1`'s schema does not grow a level for it.

What it buys is the MAP, and the reason is geometric rather than conceptual:
**two storeys both start at 0,0**, so drawing them on one canvas puts the
bedroom on top of the kitchen. One storey is shown at a time; the others can be
ghosted behind, which is how you line a bookcase up over the stairwell below.

Three consequences that are rules, not conveniences:

- **a room is found only on its own storey.** Without that, a bookcase drawn
  upstairs attaches to the kitchen underneath it;
- **a bookcase carries its own floor** as well as its room, so an unattached
  case is *somewhere* rather than everywhere. It takes its room's floor
  whenever it attaches to one;
- **removing a storey with anything on it is refused**, and says what is in the
  way. Nothing here auto-removes — the same instinct as *never auto-remove a
  not-seen book*.

### 3.8 The arrow guesses; the tools overrule

**[DECIDED 2026-08-16 — owner]** *"Once a room or bookcase is drawn, touching
the border switches to move; going outside the room, back to draw room;
touching inside the room, draw bookcase. This is supposed to provide more
fluent work — what do you think?"*

Yes, and it is the default arrow rather than a fifth mode. A drag means what
its STARTING POINT means:

| where the drag starts | what it does |
|---|---|
| on an existing room or bookcase | select · move · resize |
| on a room's **border** | move that room |
| inside a room | draw a bookcase |
| outside every room | draw a room |
| Ctrl/Shift anywhere | select several |

Three amendments the idea needs, and each is a rule rather than a detail:

- **existing objects always win.** A bookcase stands ON the wall, so *"the
  border means move the room"* and *"there is a bookcase here"* collide
  constantly. The furniture is the answer, every time;
- **the explicit tools stay.** The border zone has to be fingertip-sized, which
  makes a small room mostly border — *Draw room* and *Draw bookcase* are how
  you overrule a guess you do not want, and they are the only permanent
  buttons besides the arrow and the hand;
- **the marquee pays a modifier.** A plain drag on empty canvas now draws, so
  selecting several moved to Ctrl+drag. Selecting several is the rarer act, so
  it is the one that pays.

**One order decides everything**, and it is the same in every tool:

| the press lands on | what a drag does |
|---|---|
| a handle of the selected thing | resize — and the pointer shows which WAY |
| **inside a bookcase** | move it — in every tool, since nobody draws a case inside a case |
| a room's **border** | move that room |
| anywhere, with a drawing tool held | draw that |
| inside a room | draw a bookcase |
| outside every room | draw a room |

**The border band is lopsided on purpose.** Generous outside the wall, mean
inside it, because the two gestures approach from opposite directions: you aim
*at* the wall to grab the room and just *inside* it to draw a bookcase flush
against it. A symmetric fingertip-wide band serves the first and ruins the
second, and drawing a case against a wall is far commoner.

**A handle says it is a handle.** It reports a directional resize arrow, not
the move cross: a grip and the wall it sits on are a few pixels apart and do
entirely different things, so the pointer is the only warning before the wrong
drag starts.

**A handle grabs what it draws, and never more than a third of the shape it
sits on.** The second clause is not tidiness: a bookcase is one unit deep, so
at a fixed grip size its top and bottom handles met in the middle and the case
had no body left to pick up by.

**An edge is a handle in every tool.** Holding *Draw room* does not make the
walls already on the plan stop existing: pressing on a room's border moves it,
and only a press away from every border draws. Otherwise nudging a room means
putting a tool down first, which is exactly the friction the arrow was meant to
remove.

**Columns follow the long side.** A bookcase IS long and thin, and the columns
divide across its front — so a resize that changes which side is longer turns
the case with it, or the elevation stops describing the furniture. It fires
only on the flip, so a one-unit nudge never undoes a deliberate *Turn*, and a
case flush against a wall still faces into the room.

And a fourth thing that only shows up once you build it: **a tap is not a
failed drawing.** In the arrow, a click that produces a zero-size rectangle
selects whatever is under it and says nothing — complaining about it would
make the fluent mode the noisiest one.

### 3.9 A **Site** stands above the floors, and `Place` is the room

**[DECIDED 2026-08-16 — owner]**, answering §7.1: *"Add a real Site level above
Floor."* So the grouping is two levels deep, not one:

```
Site  ("Home", "The parents' place", "The office")
  └─ Floor  ("Ground floor", "Upstairs")        — storeys of THAT site
       └─ Place  (the room; what the plan draws)
            └─ Bookcase └─ Section └─ column └─ level
```

Two rules come with it, and both are the same rule §3.7 already stated about
floors:

- **a Site is a grouping, never part of an address.** The address stays
  `place · case · section · column · level`. Adding a site to it would
  re-address every shelf the day someone renames a house;
- **each site has its own floors**, because "ground floor" of the parents'
  place is not the ground floor of this one. A floor therefore belongs to
  exactly one site, and a room to exactly one floor.

⚠ **What `Place` now means, stated once so it does not drift.** VISION §4.1
glossed a Place as *"a room, or a whole site"* — one word covering two levels.
That gloss is **retired here**: the level the address names is the **room**, and
that is what a `Place` row is. A whole site is a `Site` row. The VISION line is
amended in the same commit as this decision, because a noun that means two
things is exactly how *depth ≠ row ≠ band* happened.

The editor's word for a `Place` is **room** — that is what a floor plan draws,
and it is the only alias, documented here and in `app/domain/place.py`.

**One site and one floor exist from the start** and neither renders any chrome
until a second one does — the same rule as the library switcher, which stays a
plain label until a second library exists. A household with one house and one
storey never learns either word.

### 3.10 Doors and windows are not in this pillar

**[DECIDED 2026-08-16 — owner]**, answering §7.4: no. They make a room
recognisable and carry no book data; nine lab passes never wanted one. They can
be added later without touching the address, which is what makes deferring them
cheap.

### 3.10a A cell can be switched OFF — and the extent does not move

**[DECIDED 2026-08-22 — owner]** *"I want to be able to delete cells in the
bookcase — for example, to allow a place to TV in the middle. The lower shelves
should not get up now. They should remain in place… when marking a cell and
clicking on delete it should not delete the bookcase itself, only affect the
cell(s). User should be able to click on a 'missing' cell and make it a real
shelf again. Rather than completely deleting them, mark them as not
available."*

This is §3.6's deferred sentence arriving — *"the general form… would also
express a desk niche or an L… deliberately not built until something asks for
it"* — in its cheap form. It is **not** the free-form layout editor: the grid
is still columns × levels, and the only new fact is which cells hold no shelf.

**The model: a MASK, never a resize.** `Section.column_levels` stays the
extent — how much wood there is — and `Section.gaps` holds the `(column,
level)` cells that are switched off. Every consequence follows from that one
choice:

- **the shelves below a hole keep their level numbers.** Shrinking the column
  is the alternative, and it is what the owner ruled out in the same breath:
  those numbers are printed on addresses people have already been told to walk
  to;
- **a gapped cell is not a slot**, so `Section.addresses` skips it and no
  `Shelf` row stands there. §3.1 says a drawn slot IS a shelf; a shelf row
  flagged *unavailable* would be a shelf that is not a shelf, and every query
  about "the books on this shelf" would have to learn the word;
- **gapping every cell leaves the bookcase standing**, with its full extent to
  switch back on. *"It should not delete the bookcase itself"* is therefore
  structural rather than a UI courtesy — no number of gaps touches the extent,
  and the extent is what the furniture is;
- **a gap over a cell the owner has declared something about is REFUSED**,
  naming what is in the way — the one place this deliberately disagrees with
  every other slot edit, which DETACHES an occupied shelf
  (`plan_slot_removal`). Detaching instead would make *delete these cells* a
  gesture that quietly costs a book its address, with no way back until
  P6.4b's undo journal exists.

  ⚠ **What it covers, measured, not assumed.** The first draft of this
  paragraph said the gesture was *loss-proof* — *"only empty shelves are ever
  removed, so switching a cell back on restores what was there"* — and a
  migration review drove the real routes and disproved it: an empty shelf
  still carries a **label**, a **depth override** and an **id**. Books,
  photographs, a label and a depth override therefore all refuse the gap.
  **Standing decisions do not** — they are keyed `(library, shelf, depth,
  book_key)` with no foreign key, so the shelf id going away orphans them and
  §5.6 stops suppressing a phantom the owner already rejected at that cell.
  They are not refused because the owner cannot act on such a refusal: no
  screen clears a decision, and a refusal nobody can satisfy is one they
  retry. §3.11's alias is the real fix and **P6.4e** is where it lands — the
  same seam that already owes "history across the seam" an answer. A column
  shrink has always had these costs; a gap is the gesture that makes them
  routine, which is why they are written down instead of assumed away;
- **the hole goes with the wood.** Shrinking a column past a gap prunes it, so
  growing the column back yields a shelf and not a resurrected hole. A level
  count is what the owner is editing at that moment, and a case returning
  taller with an invisible cell missing from the middle is a surprise that
  gets explained as a bug.

⚠ **The word is *gap*** (owner's pick over *opening*, *not available* and
*blank*), and it was **already in use three times** — the first draft of this
paragraph said it was not, and a quality review counted:

- `renumber_sections` said *"close the gaps"* about section ORDINALS.
  Reworded, because that is the sense a reader would confuse;
- `app/api/routers/map.py` and `app/ports/map.py` say the same thing about a
  hole in a stack of section ordinals. Left as they are: both sentences are
  about `ordinal`, and neither is anywhere near a cell;
- ⚠ **`app/web/src/map/core/model.ts` has `gap = 6`, the pixel gutter of the
  overview layout** — and that is the module **P6.3.2b lives in**. Renaming it
  to `gutter` is that item's first step: a gutter and a missing shelf sharing
  one name inside one file is the collision that will actually bite, and it
  costs nothing while nothing reads the mask yet.

### 3.11 A merged shelf becomes an **alias** — of its id AND of its address

**[DECIDED 2026-08-21 — owner]** *"Image keeps its own identity. Shelf and
slot can be aliases (in addition to the image)"*, and the alias **carries
the old address too**.

So there are three identities in this item and they are not the same kind
of thing:

- **the image** is durable and is NEVER aliased. A capture already moves
  between shelves (`PATCH /captures/{id}`) keeping its own id, and its
  earlier reads stay filed under the shelf as it was THEN. A merge changes
  which shelf a photo hangs off; it does not re-identify the photograph;
- **the shelf** may become an alias: `alias_id -> shelf_id`;
- **the slot** may become an alias in the same row: the absorbed shelf's
  former `(section, col, level)` resolves to the survivor as well. *"The
  shelf that was at section 1, column 2, level 3"* is a question the
  library can still answer after the wood has been re-identified — which
  matters because the address is what a person reads off a drawing, and it
  is the half that survives in someone's memory when the id does not.

When photo-born shelf A merges into drawn slot B, A's `shelves` row goes
and one alias row takes its place, carrying A's id, A's former address, its
label and the date. A is no longer a shelf. It is still an answer, and so
is where it used to be.

**Why not rewrite every reference and delete A outright** — the obvious
alternative, and the one §3.1's *"no mapping table beside it"* appears to
demand. Six tables name a shelf and only two have a foreign key, so
`PRAGMA foreign_key_check` reports a clean file after a merge that lost half
the library's locations. Rewriting them all:

- **edits two archives this project has declared immutable.** VISION §5.5
  keeps runs exactly; `book.py` says provenance is append-only, never
  edited. A rewrite makes run R say it saw a book at a slot nobody had drawn
  when R ran;
- **collides on two primary keys.** `decisions` and `duplicate_questions`
  are keyed by `(library, shelf, depth, book_key)`, so a merge can hold a
  row on both sides and one human answer is discarded in silence.
  `merge_library.py` met this exact wall and REFUSED rather than choose;
- **404s every id held outside the database** — a bookmarked
  `#/map/<shelf>`, a phone mid-upload, a queued read;
- **is unmeasurable afterwards.** Once every reference is rewritten nothing
  remembers what should have moved, so *did the merge lose a row?* has no
  answer. The census in P6.4c depends on the alias existing.

**Why A's row is DELETED rather than flagged `merged_into`:** `shelves`
keeps meaning "a shelf", so every existing query stays correct with no new
`WHERE` — and with `shelf_aliases.shelf_id REFERENCES shelves(id)`, an alias
of an alias is unrepresentable, so the resolver is one hop by construction
and needs no cycle guard.

**What a past read's provenance means afterwards:** exactly what it always
meant — *run R sighted this copy at identity A*. The precedent is already
here, one level down (`ports/store.py:list_reads_for_capture`): a re-bound
capture's earlier reads stay filed under the shelf as it was THEN, because
deriving them from its current shelf would lose exactly the history a
workspace exists to show. Two rules come with it: a merge is **refused while
a read of either identity is running**, and `apply_diff` resolves through
the alias so a read that started at A finishes at B rather than raising
*"shelf no longer exists; nothing to apply"* and discarding a whole diff.

**An alias's former address may point at a cell that is now a GAP, and that is
fine** (settled here so P6.4a does not have to argue it). §3.10a leaves the
extent untouched, so `(section 1, column 2, level 3)` still exists after the
owner puts a television there — it simply holds no shelf. The alias's address
is **historical**: it answers *"the shelf that was at…"*, which is the whole
reason §3.11 records it rather than deriving it. So an alias never needs a
live slot at its former address, and a gap must never be refused because some
alias remembers that cell — old history does not get to block new furniture.

### 3.12 Depth is preserved, never renumbered

The merged shelf is `max(A.depth, B.depth, deepest_occupied(A),
deepest_occupied(B))`. B's depth is a creation-time default copied from its
section (§3.3) that nobody looked at; A's is a human declaration through
*"add a row behind this one"*, the one thing §5.7 says cannot be detected.
§5.1's ladder settles it. Deepening is never refused; shallowing never
happens here — the two paths that could already answer 409 rather than
clamp. **Depth NUMBERS are never remapped**: depth 2 of A is depth 2 of B,
because renumbering would move books without moving books.

⚠ And the order of a merged capture strip is DECLARED, not inferred:
appending A's photos after B's encodes a claim (*A's half is to the right*)
that nothing measured. One radio button — *which strip comes first* — is
§5.7's "declared, never detected" applied to order.

### 3.13 What moves with the wood, and what stays with the identity

One sentence decides all six tables: **a row that governs a future write
moves; a row that records a past event stays.**

| | | |
|---|---|---|
| `copies` | **moves** | it is where the book IS |
| `captures` | **moves**, renumbered per depth | future reads dedup against these |
| `decisions` | **moves** | see below |
| `duplicate_questions` | **moves** | a to-do list, not a record |
| `provenance` | **stays** | append-only evidence (§5.2) |
| `reads` + `claims` | **stay** | the immutable run archive (§5.5) |

**`decisions` moving is the load-bearing one.** §5.6's rule is *"a book the
user previously rejected here is not re-added"*, and "here" is
`(library, shelf, depth, book_key)`. Leave A's rejections behind and the
next read of the merged shelf **re-adds every phantom the owner ever
rejected on that wood** — no row deleted, no key violated, nothing looking
wrong. A collision is won by the newer `decided_at`, which is the rule the
table's own upsert already applies to a human changing their mind, and the
preview names every collision rather than choosing silently.

### 3.14 The map may propose; only a ✓ binds

**[DECIDED 2026-08-21 — owner]** *always an explicit ✓*. CLAUDE.md's *"nothing enters the
library unapproved"* is about BOOKS. It should extend to shelf identity, and
not by analogy: there is no evidence to be right from. §5.7 established that
nothing in a photo says which ROW it is; nothing says which SLOT it is
either, so any automatic binding is built from timing or label text, neither
of which is evidence about wood. And the cost asymmetry is worse than for
books — a wrong binding moves a POPULATION of copies, merges two capture
strips, and looks like success, because the map gets fuller.

So: every bind and every merge is an explicit ✓; the map may propose only
from things the owner TYPED (a label matching a room or bookcase name),
never from image content or timing, and a proposal shows its evidence in the
same breath; and a multi-select bind itemises what moves, the way P6.2 says
a structural edit must report what it cost the shelves.

### 3.15 Every destructive map edit is UNDOABLE, and that lands before the merge

**[DECIDED 2026-08-21 — owner]**, overruling the recommendation. The
recommendation was a preview and a confirm in front of an irreversible
merge, on the grounds that a true inverse is not derivable — a book the
owner typed onto A by hand has no provenance, so after the merge nothing
distinguishes it from one that was always on B, and a GUESSED inverse moves
books that never moved. The owner's answer: *build a real undo first*, and
not only for merges — for **every destructive map edit**.

That is the stronger reading of this project's own rules, and the
recommendation was arguing from cost rather than from principle. Removing a
column, removing a section, deleting a bookcase and removing a site all
detach or destroy shelves TODAY behind nothing but a `confirm()`, and each
of them is one mis-tap. "Nothing here auto-removes" (§3.7) and "never
auto-remove a not-seen book" (§5.6) are the same instinct one level up: the
library keeps what it cannot certainly discard. An undo is that instinct
given a mechanism.

**What makes it honest rather than a guess:** the inverse is RECORDED at
the moment of the edit — which rows moved, which slots were detached, which
answers were overwritten — and it is **invalidated the moment anything else
touches those rows**. An undo that cannot prove the world is still as it
left it refuses, and says why. That is what the guessed inverse could never
do, and it is why recording beats deriving.

The preview stays, because it is not a substitute for undo but the other
half of the same courtesy: a call that writes nothing and returns what will
move (books, copies per depth, photos per depth, the resulting depth, the
colliding decisions and which side wins), a refusal list each with its
reason, and *A already resolves to B* answering 200 as a no-op so a retry
cannot half-merge. And the alias is what makes even an expired undo
survivable: nothing 404s, and the shelf says *formerly …*.

### 3.16 A merge may not manufacture evidence of absence

§5.6's not-seen streak is scoped to the exact `(shelf, depth)`. After a
merge both scopes are wrong in opposite directions: do nothing and every
badge on the absorbed copies silently reads 0 on the day the owner is
reorganising; union the reads naively and the streak INFLATES, because two
photo-born identities merged into one slot are usually two halves of one
shelf and a read of the left half never covered the right. The walk goes
over the alias closure and **stops at the first read whose coverage cannot
be vouched for**. It reduces exactly to today's behaviour when the closure is
one shelf — which is P6.4d's own mutation check.

## 4. The fork, and how it was settled

**[SETTLED 2026-08-16 — owner, after drawing on the first build.] Freehand
loses. Everything is a rectangle on the grid.**

> *"I would suggest a rectangular draw — users can draw a rectangle on the
> grid, control its size, both for rooms and for bookcases. **The free draw was
> too free.**"*

The straightening worked — a wobbly stroke did come back as four clean walls —
and it still lost, which is the outcome a lab exists to produce cheaply. The
mode-S code is **deleted**, not disabled: it was a POC that was measured and
beaten, and a disabled second editor is a second thing to maintain and a
standing invitation to re-argue.

What replaced it, and why each part is a rule rather than a preference:

- **Rooms and bookcases are both axis-aligned rectangles.** An L-shaped room is
  two rectangles attached — the *same* mechanism as two rooms attached — so
  there is one snapping rule and no polygon editor.
- **Rooms attach to each other.** Drag one near another and its edges weld to
  that neighbour's edges, exactly, before the grid gets a say. A neighbour edge
  beats a grid line: "flush against that wall" is a fact the user is
  asserting, and rounding it to the nearest grid line leaves a hairline gap no
  zoom level closes.
- **Dragging empty space does nothing but deselect.** It used to pan, and
  *"the grid moves when I drag it — it should not move"* is the correct
  reaction: a background that slides out from under a mis-aimed drag reads as
  broken even when nothing was damaged. Panning is the Pan tool, the middle
  button, or two fingers.
- **Every tool is a verb** — *Draw room*, *Draw bookcase*, *Move & edit*, *Pan*
  — and the keyboard shortcuts moved into the tooltips. A bare "1" beside a
  button is a puzzle, not a hint.
- **Size is editable both ways:** drag the handles, or type the numbers. The
  units are relative, so what matters is that this case is twice the width of
  that one — and typing is how you say that exactly.
- **Black or white background**, as two real themes rather than an inverted
  filter: the line weights that read well on a screen and on a drawing differ.

The bookcase-photo path (VISION §7's approach B) is untouched by this and is
still P6.6 — it produces an *elevation*, and this section is about the *plan*.

**Third pass (2026-08-16), after the owner drew a house with it** — *"drawing
the rooms and bookcases was very fluent"*. Five additions, and two of them are
rules P6.1 inherits rather than lab conveniences:

- **Multi-select** — Ctrl+click to add, drag a band across empty space to
  catch everything it touches, one Delete for the lot. The band counts
  *touching* as a hit, because a bookcase flush against a wall shares exactly
  its edge with the room.
- **Copy and paste** — the value is duplicating a *configured* bookcase, so
  the clipboard is deep-cloned at copy time and a case copied together with
  its room follows THAT copy, not the original room.
- **⚠ Attachment is explicit and sticky.** A bookcase belongs to a room, moves
  with it, and can be pointed at any room from the panel. Containment may only
  ever *reassign* a case the user dragged — never orphan one, and never touch
  a case that moved only because its room did. Both halves were found the hard
  way: without the first, a case nudged half a unit past its wall silently
  lost its room; without the second, an explicit attachment survived exactly
  one move before the geometry handed the case back to the room it overlaps.
  **P6.1 inherits this as a domain rule**, not as an editor behaviour — it is
  the difference between a Place that owns its furniture and a rectangle drawn
  behind it.
- **Saving is visible.** Every edit is written immediately and the toolbar says
  so, with the honest caveat on the same line: browser storage, and *Save to
  file* is the copy that survives it. An autosave nobody can see is
  indistinguishable from no autosave.
- **A real undo stack**, 200 edits deep both ways, reachable by Ctrl+Z /
  Ctrl+Y / Ctrl+Shift+Z. Consecutive edits of the same field COLLAPSE into one
  entry, so typing a room name is one undo rather than one per keystroke — and
  stepping back clears that collapsing key, or the next keystroke would merge
  into a state the user has already undone past. The five edit commands then
  moved into an **Edit menu**, since every one of them has a working shortcut
  and each printed its own: the toolbar dropped from 162 px to 123 px on a
  phone.
- ***Fit* → *Show all***. The owner asked what it was for, which is the
  answer: it is the recovery from having zoomed or panned somewhere
  unfamiliar, and it now says so. Kept rather than dropped because it is the
  ONLY recovery — but a control whose purpose has to be asked about was
  mislabelled, not unnecessary.

### 4a. What the lab caught, for the record

Eight rounds of building and driving it in a real browser produced sixteen
defects, each of which would have been argued about rather than found if this
had been built straight into `app/web`:

1. a bookcase's facing was computed against the *wall's* direction and consumed
   against the *case's own* — drag right-to-left and the wood landed outside
   the room;
2. a burst of `pointermove` events overwrote itself, because continuous events
   batch and every handler in the burst closes over the same stale state. On a
   120 Hz phone that is most of a stroke discarded — and it reads as *"the
   straightener is bad"* rather than as dropped input. It would have decided
   the S-vs-D verdict on a bug;
3. `pointerup` ignored its own coordinates, so a fast lift came out short;
4. a traced rectangle came back with **five** walls: welding cannot see a
   collinear triple across the polygon's seam;
5. dragging empty space panned the view — the owner's first complaint;
6. **on a thin rectangle the corner handles crowd out the edge handles**, and
   the hit test took the first in reach rather than the nearest. A bookcase is
   thin by nature, so dragging its end to make it longer collapsed its depth to
   zero instead. Corners are a luxury of large rectangles; the fix drops them
   when the rectangle cannot hold them apart;
7. **halving the grid made the magnet wider than a bookcase is deep.** The
   magnet is measured on SCREEN (a fingertip) and the plan in units, so at 11 px
   a cell it reaches 1.3 units. Drawing a one-unit-deep case against a wall
   pulled *both* its edges onto that wall and the case vanished. A snap that
   annihilates the rectangle is never what anyone meant: the free corner now
   ignores any neighbour edge within one unit of its anchor;
8. **an explicit attachment survived exactly one move** — see §4's third pass;
9. **rectangles drifted off whole units and it showed on screen.** `snapRect`
   moves by ADDING a correction, and `x + (round(x) - x)` is not exactly
   `round(x)` in floating point; the dust then became a snap candidate for the
   next rectangle, which inherited it. A room rendered as
   **11.000000000000004×9**. The model already promised integers — it just was
   not enforcing them, so both rectangle constructors now do;
10. **every keyboard shortcut was dead on the owner's own keyboard.** They were
    matched on `event.key`, and on a Hebrew layout the C key reports `'ב'` — so
    Ctrl+C did nothing while the *Copy* button worked. Match `event.code`, the
    physical key. Now a one-line trap in CLAUDE.md: it will bite `app/web` the
    day it grows a shortcut, and this is a Hebrew-first product;
11. **a rectangle could not be resized by ONE unit next to a neighbour.** The
    magnet won whenever a neighbour edge was within tolerance — even when the
    pointer sat *exactly* on a grid line and the neighbour was a whole unit
    away, so the edge jumped two. A magnet that overrides a perfect grid hit is
    not helping: a neighbour now wins only when it is at least as near as the
    grid. The same arithmetic existed twice, on the draw path and the move
    path, and only the first would have been found by testing one of them;
12. **the panel stacked under the plan on a half-width window.** The breakpoint
    was 820 px, which a laptop browser at half screen hits — and the settings
    belong at the side;
13. **the all-floors view had no door.** The way out was a menu item in a
    corner, and *"I could not get rid of it no matter which button I clicked"*
    is what that costs. A mode with no visible exit is a trap however few
    keystrokes it really takes — it now carries a bar saying it is read-only
    with the way back in it, and the drawing tools are visibly disabled;
14. **the grips ate the walls.** A handle claimed a full magnet — 14 px,
    nearly twice the square it draws — so a selected room's eight grips made a
    dead zone along every wall, and a selected bookcase one unit deep was
    *entirely* handle with no body left to drag. Both were invisible: the
    controls looked small and behaved large;
15. **the cursor read the tool, not the intent.** Once an edge became grabbable
    in every tool the behaviour was right, but the pointer still showed a
    crosshair over it — the one thing telling the user about a rule was the
    thing that had not been updated;
16. **`setPointerCapture` threw the whole handler away, a second time.** The
    new panel divider called it without the guard the canvas already had, so
    the exception escaped *before* the move listeners were attached and the
    drag did nothing whatsoever. The first fix was a comment in one file; the
    lesson is that pointer capture is best-effort and the drag must not depend
    on it.

## 4b. The original fork, and what the lab was for

*Kept for its argument — §4 is the answer. Worth reading because the winning
option was not on this list: D was "snap the freehand gesture as it happens",
and what the owner actually wanted was to stop gesturing and drag a rectangle.
The recommendation was directionally right and still not the design.*

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
| **P6.0** | **The map lab** — a standalone app, no backend, outside the gate. Rectangle drawing for rooms and bookcases, room-to-room attachment, multi-select, copy/paste, explicit bookcase→room attachment, resize handles, sections, floors, the elevation editor, underlay tracing, black/white themes, visible autosave, a real undo stack. | M | ✅ nine passes |
| **P6.1** | **Address domain + migration** — `Site`, `Floor`, `Place`, `Bookcase`, `Section`, the shelf address, geometry in abstract units. Drawn slots create real empty `Shelf` rows. Naming lint. Schema **v20** with a real v19→v20 upgrade test. | L | ✅ |
| **P6.2** | **API + policy** — the map through `current_library`, one capability each, contracts regenerated. | M | ✅ |
| **P6.3** | **The port** — the lab's editor moves into `app/web/src/map/` **verbatim** where it is framework-free, wired to the API by an adapter. **The lab is deleted in the same commit.** Behaviour identical to the lab's ninth pass — that is the acceptance test, not a rewrite. | M | ✅ |
| **P6.3.1** | **The site picker** — the one thing the lab never had (§3.9). Sites and their floors become manageable in the ported editor; a single site renders no chrome. Deliberately AFTER P6.3, so "behaves the same" is verifiable before anything new is added. ⚠ Renumbered: this item was "P6.3b", and P6.3's own wiring commit spent that identifier in the git log. | S | ✅ |
| **P6.3.2** | **Gaps** — a cell of the elevation can be switched off (a television, a desk niche) and switched back on, with the extent untouched (§3.10a). Two items: **a** the model, schema **v21** and the route; **b** the editor's multi-cell selection and the hole it draws. Arrived mid-pillar, from the owner using the ported editor. | M | ✅ 
| **P6.3.3** | **The plan tab on a phone** — the drawing surface measured 375x**0**: `#root` had a `min-height` where a definite height was meant, so the settings panel became the whole page and no pillar-6 flow had ever been walked on a phone. Two flex minimums and two dead thumb-size rules came with it. Arrived from P6.3.2b's UX review, and taken BEFORE P6.4 (owner) so four more items would not land unverified on the device this catalogue is used from. | S | ✅ |
| **P6.4** | **Binding and merge** — photo-born shelves bind into drawn slots; several identities merge into one physical shelf, with aliases. ⚠ THREE schema steps now, and **b ran before a**: **v22** the undo journal, **v23** its sequence (the head could not be decided by a clock with second resolution — see P6.4b), **v24** the alias. P6.3.2a spent v21. | L | |
| **P6.5** | **The map as navigation** — three drill levels, "where is it" incl. depth, stale-depth surfacing, capture handoff. | L | |
| **P6.6** | *Optional:* bookcase photo → proposed levels via `segment.py`, confirmed by hand. | S | |

**Standing per-epic requirements** (owner, 2026-08-16 — *"use all reviewers to
verify the code and quality along the way"*): every item runs `review-quality`;
every server-side item runs `review-data-integrity`; every item that adds a
route or an input runs `review-security`; every user-visible item runs
`review-ux`; and `review-migration` runs **before** the P6.1 commit.

**P6.0's exit is called** (owner, 2026-08-16 — *"P6.0 worked well. You can start
from empty and create a file for yourself."*). The real-house export is
therefore **not** P6.1's fixture: the fixture is a hand-authored plan in the
exported shape, and the product starts with an empty map. The tenth pass the
item warned about never came.

### P6.0 — the map lab

**Why a separate app** (owner's call, and the right one): the editor is the
piece most likely to need five throwaway attempts, and each attempt inside
`app/web` drags the client ring, the shared package, the RTL rules and the
i18n table behind it. The lab has none of that.

It has already paid: two passes, six defects (§4a), and one whole interaction
model deleted — none of which cost a migration, a contract regeneration, or a
minute of either client's test ring.

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

**Done when:** the owner draws his real house — rooms attached to each other,
bookcases against their walls, one case opened into columns × levels with a
depth override on one shelf — on a phone-sized viewport, and the drawing is
exported. That export is P6.1's first fixture: a real plan, in abstract units,
made by the person the feature is for.

⚠ The lab has been through **nine passes**. The first offered freehand against
snap-while-dragging and was rejected wholesale (§4); the third came back
*"very fluent"* with five additions; the fourth and fifth were polish plus four
real bugs; the sixth cut the toolbar to eight controls and made the arrow
guess; the seventh moved the storey onto the board and drew the icons;
the eighth stacked the floors as rows and gave the read-only view a door; the
ninth tuned what the pointer grabs. Expect a tenth: the point
of a disposable app is that rejecting it costs a day, not a sprint. It is
finished when the owner stops finding things, not when the item list is
ticked.

### What P6.1 landed, and what it hands P6.3

Three reviews (`review-migration` before the commit, `review-data-integrity`
and `review-quality` after) turned one item into two commits. The findings
worth carrying forward:

- **the danger is a defaulted argument, and "required" is only half a fix.**
  `occupied_ids` defaulting to empty meant *delete everything*; making it
  required stopped a caller FORGETTING but not the answer going STALE, and a
  book added from a phone mid-edit still lost its shelf. The destructive
  functions compute occupancy themselves now, immediately before the write,
  through one function that asks both copies and captures;
- **an occupied shelf is DETACHED, never deleted** — and "occupied" includes a
  shelf with books and no photograph, which is the half a reasonable person
  leaves out;
- **v20 corrected in place** rather than amended by a v21, because the owner's
  database was verified still at v19. That window closes the moment anything
  in the primary tree imports `app.main` on a branch carrying the step.

**Two conventions P6.3 must honour**, pinned by `fixtures/map/lab_plan_v4.json`
and a test:

1. **col and level are 0-based in the lab document, 1-based in the domain.**
   `ShelfAddress` REFUSES a 0 rather than re-basing silently, so a forgotten
   `+1` raises instead of filing every book one shelf over;
2. **section ids must be carried across, not rebuilt.** `persist.ts`
   regenerates them from array position on the stated grounds that *"nothing
   outside the document refers to one"* — a sentence that stopped being true
   when `shelves.section_id` did. Rebuilding by position also renumbers
   everything above a section inserted at the bottom.

### What P6.2 landed, and the one cell the owner decided

Fifteen routes, two capabilities. **Reading the map is `BROWSE`** (owner,
2026-08-16) over a reasoned objection: the security review argued for Editor+
by analogy to `VIEW_PHOTOS`, which is Editor+ because *"the photos show the
inside of a home"*, and a labelled floor plan is arguably a more legible
disclosure than a photograph. The owner's answer — *everyone who can see the
books sees the map* — is on record in `app/api/routers/map.py` together with
the argument that lost, because a decision without its losing side gets
re-litigated.

What the two reviews measured, kept here because P6.3 inherits the shapes:

- **the map's writes are an amplification surface.** A drawn slot is a Shelf,
  and the SQLite adapter opens a connection per operation, so a 110-byte
  request asking for 40 columns of 40 wrote 1600 rows in 16.5s — and *add a
  section*, which states no size at all because it copies its neighbour, cost
  17s from 40 bytes. Batched writes, a grouped captures query and
  `MAX_SLOTS_PER_BOOKCASE` bring that to 0.02s. **The editor must not offer a
  gesture that asks for more than the ceiling**, or the owner meets a 409;
- **a room and its furniture move together, always.** Moving a room to another
  storey alone left the case behind and BRICKED it — every later write
  answered 409 about a mismatch nobody created. `move_place` takes the
  bookcases with it; an attached case may not change storey on its own;
- **one request carries one grid instruction.** `columns` and `column`/`levels`
  together is a 400, because the old fall-through silently applied half an
  edit and answered 200. An elevation panel must send one or the other;
- **a structural edit reports what it cost the shelves** (`deleted` vs
  `detached`), and P6.3 should SHOW that split before the destructive call —
  the 409 currently says "4 shelves still stand", which reads as "4 empty
  slots" when some of them hold books.

### P6.3 — the port, and what two reviews found in it

The port itself worked: `core/*` came over byte-for-byte (verified both
directions against the deleted lab, all seven files), its 83 tests run in the
web ring, and one `POST /map/bookcases` against the owner's real database
created the case, its section and 15 real addressed `Shelf` rows, which a
reload drew back by name in Hebrew.

`review-quality` and `review-ux` then found **eight criticals between them**,
every one measured. Four were fixed in 6b28c96 and the other four — with the
four smaller findings filed beside them — in cb89cce, which is what let the
branch merge. The list is kept because it is the record of what a port costs:

1. **A pasted bookcase aliases the original's section ids.** `paste` mints a
   new case id and spreads the sections through unchanged, so a depth change
   on the COPY writes to the original's shelves — server answers 200.
2. **`case.add` flattens everything but the first section**, so a pasted or
   undo-restored case with a hutch, ragged columns or per-shelf depths is
   created uniform, and `confirmed` records the loss as landed.
3. **"Clear the plan" now destroys the household's real map** — in the lab it
   cleared `localStorage`. Same family as the *Save to file* hint the port
   caught; this one was missed.
4. **The editor is half translated.** 17 keys in `text.ts` are defined and
   unread, the whole floor menu and settings panel are English, `addFloor`
   writes an English name to a Hebrew library, and the saved indicator's
   tooltip still tells the owner to use *File ▸ Save to file* — a menu that no
   longer exists. A wrong stated reason, on the exact element the i18n commit
   claimed to fix.
5. **The phone layout gives the canvas 150px** and the hint overlays half of
   it; `.app { height: 100% }` assumed a full-viewport mount, and the 38%
   split does not hold because the panel overflows its basis.
6. **`.side` collides with `base.css`** and inverts Hebrew alignment in the
   panel — exactly, in both directions.
7. **The client does not know `MAX_SLOTS_PER_BOOKCASE`**, so it offers
   gestures the server refuses — which P6.2's own note in this file said it
   must not.
8. `photos` is an editable field with no op behind it: it accepts an edit,
   reports *saved*, and discards it.

⚠ The lesson worth keeping: everything above is in the SEAM the port added,
not in the ported core. The constraint MAP_PLAN set — "the core is
framework-free, and that is the part that ports verbatim" — held exactly as
designed, and every defect landed in the ~400 lines written around it.

**What closing them changed, and the ninth defect nobody had measured.**

- **The diff MODELS the server's creates instead of assuming them.** `case.add`
  carries one column count and two defaults, which is all
  `POST /map/bookcases` accepts — so `planDiff` now follows a create with the
  calls that finish it, and it tracks what the server will hold as each op
  lands. That tracking is not fussiness: `POST /map/sections` states no shape
  at all (it copies the section it stands against), so what a new section still
  needs depends on the ops issued before it in the same pass. The plain
  `+ section` gesture still costs exactly one call; a two-section paste costs
  twelve, six of them per-shelf depths that are genuinely required — the copy's
  slots really do stand at the depth they were copied from, and §3.3 forbids a
  default reaching back into them.
- **"One grid instruction per pass" was a misreading** of a rule about one
  REQUEST. The old code sent the column count and left the per-column heights
  *"to the next pass, which converges"* — there is no next pass, because
  `confirmed` becomes the document the moment the push succeeds.
- **A section id is a shelf's address, so a copy may not share one.** The paste
  is a pure function now (`app/web/src/map/paste.ts`).
- **`POST /map/bookcases` answers with the section it minted.** 6b28c96 said it
  had fixed *"you cannot edit a bookcase you have just drawn"* by reading
  `made.section.id` off this response; `BookcaseDTO` had no such field, so the
  line was dead and `+ column` on a fresh case still answered 404. The DTO is
  `BookcaseDrawnDTO`; the ids a client cannot guess are now all told to it.
- **The ninth defect: `map.css` was still repainting the product.** The same
  commit scoped the token block and said *"every rule is scoped now"*; the ~130
  rules under it were not, including bare `button`, `input`, `select` and
  `fieldset`. Measured on the books tab, having never opened the map: every
  unclassed button and input computed `background-color: rgba(0,0,0,0)` at
  13px, because `--btn` and `--input-bg` exist only inside `.mapscreen` and an
  undefined custom property makes the declaration invalid at computed-value
  time rather than falling back. `app/web/src/styles/scoping.test.ts` is the
  gate; the same fix retires the `.side` collision (`.map-side`).

⚠⚠ **Two claims in one commit message were false**, and both were checkable in
a minute — a response field that did not exist, and a scope that covered a
tenth of the file. That is the failure CLAUDE.md names as worse than silence,
because a wrong stated reason is what makes the next reader delete the guard.
The rule it earns: a commit message asserting a property must name where the
property is enforced, and the enforcement must be opened while the sentence is
written.

**Then three reviews on the closing commits found nine more, and two of them
lost work.** Kept because they are what a port costs after the port looks
finished:

- **reloading the plan pushed the REVERSE of the session.** `initial` is the
  last plan the server was asked for, `confirmed` the last it was told; they
  agree only until the first successful push, and re-keying `MapScreen` mounts
  it on the stale one, which every mount hands to `record`. *Plan ▸ Reload* and
  every refusal deleted the session's bookcases — `DELETE …/slots` detaches the
  shelves books stand on. `startOver` unmounts before the bump, an `era`
  counter drops writes queued before it, and `done` (which the same review
  correctly called dead) decides whether what landed mid-reload needs a second
  re-derive;
- **a dropped push answered the LOAD's error screen**, which unmounts the
  editor: the drawing, the selection, the undo stack and every un-pushed edit,
  replaced by a *retry* that re-derives rather than retries. A refusal — the
  more serious event — had always kept the editor. `Trouble` is its own state
  now, and says the change rides along with the next diff, which is true
  because `confirmed` did not advance;
- **a section restored into the MIDDLE of a stack was sent as `top`.**
  `ordinal` is what an address prints, so furniture silently changed storeys.
  `POST /map/sections` takes `above_id` — the section it STANDS ON — which is
  the general form and the only way to say it at all;
- **the surface carrying the server's own words had no CSS in any sheet**, and
  the refusal outlived the remount it triggered, leaving a `role="alert"` above
  a toolbar reading *נשמר*;
- **the floor badge chose its corner from the floor's NAME** (`dir="auto"` on a
  container, with `inset-inline-start` resolving against it), and in the
  read-only overview it covered 80% of the only exit — the trap that mode's own
  comment exists to prevent, re-created by geometry;
- three smaller ones with the same shape as rules already on record: greyed
  rows a one-storey household can never use (absent now), a hard-coded Hebrew
  sentence that never entered the table, and `1 פריטים`.

⚠ **`--appbar-h` is an offset, not a subtrahend.** Filling the viewport by
`calc(100dvh - var(--appbar-h))` was measured 2px too long on a desktop and 3px
short on a phone; the shell is a flex column now and the editor fills what is
left. Twice more in the same fix: a percentage height needs a parent with a
DEFINITE one (the canvas snapped back to 150px), and an `auto` inline margin on
a flex item absorbs free space instead of stretching (the editor came out 636px
wide, centred, on a 1280px window). All three measured in a real browser.

### P6.3.1 — the site picker

§3.9's second level, made reachable. A `Site` is the property — home, the
parents' place, the office — and a `Floor` belongs to exactly one of them, so
choosing a site chooses which floors, rooms and bookcases the document is made
of. It is **not** part of an address, so switching re-addresses nothing.

Four decisions worth keeping:

- **a site is not in the document, so it is not in the diff.** `planDiff`
  describes one site's drawing; the four site gestures write directly and then
  re-derive. Putting them in the op language would mean a create whose failure
  leaves the editor drawing a plan that hangs off nothing;
- **a new site gets a storey in the same breath.** `toPlan` would otherwise
  synthesise one the server never heard of, and the first room drawn onto it is
  refused with a 404 — the same failure `ensureHome` was written for;
- **no chrome until the second site exists**, the rule the library switcher
  already holds. The one control a one-site household sees is *add a site* in
  the Plan menu, and pressing it is what brings the badge's site segment into
  being. The badge then reads `site · storey`, which is the same question asked
  twice and belongs in one corner;
- **the choice is remembered per LIBRARY.** One key would make the parents'
  place the answer for every customer, and the id would resolve to nothing in
  all but one of them. A remembered site that is gone falls back to the first
  rather than drawing an empty board — the stale-stored-id rule, again.

It also answers the note `PlanScreen` has carried since the port: two tabs
opening an undrawn library at the same instant can still mint two sites, and
the picker is where the duplicate becomes visible and removable — which is why
it does not need a lock nothing else in this app takes.

**What three reviews then measured on it**, kept because the shapes repeat:

- **the guarantee belongs at the point of USE.** "A site gets a storey when it
  is created" is two calls with no transaction, so a failure between them left
  a floorless site standing — invisible in the picker, unremovable, and a 404
  waiting for whoever selected it. The loader mints the storey for whichever
  site is being drawn, which also heals the two-tab duplicate and a site whose
  last floor another tab deleted;
- **a re-derive discards, so it must not be casual.** Every site gesture ends
  in one, and with a storey queued behind a held push it took the drawing from
  two storeys to one — no banner, indicator reading *saved*. They drain the
  queue first now. *Plan ▸ Reload* still discards, because that is what the
  owner asked for;
- **a control that re-derives cannot be a controlled input.** The site's rename
  box sent one PATCH per keystroke and unmounted itself on the first, leaving
  the rest of the word to the board's key handler — where Backspace deletes
  what is selected. It holds a draft and commits on Enter or blur; the floor's
  box beside it needs none of that, because a floor is IN the document;
- **`sites[0]` is not "the home".** `load_map` sorts by `("order", name, id)`
  and nothing sent an order, so with the real household shape — `הבית` and
  `אתר 2` — a fresh tab opened on the parents' place. The picker sends the
  count as the order, and the loader pins the choice;
- **a percentage height needs a definite parent.** The drawing surface was
  still 150px on a phone inside a 470px board, because `height: 100%` on a
  replaced element inside a stretched flex item falls back to the SVG's
  intrinsic size. I had measured the WRAPPER and reported it fixed; a review
  measured the thing the owner draws on. It is `position: absolute; inset: 0`
  now, and gated by a test that reads the declaration.

### P6.3.2 — gaps, and why they arrived here

The owner asked for this (2026-08-22) after drawing his real house in the
ported editor: a wall unit with a television in the middle of it cannot be
drawn as a grid of shelves. §3.10a is the decision; this is the shape of the
work and the reason it goes BEFORE P6.4.

| # | Item | Size | Reviewers |
|---|---|---|---|
| **P6.3.2a** | **The model, the step and the route** — `Section.gaps`, `with_gaps`, pruning on resize, schema **v21**, the sqlite round-trip, and `PATCH /map/sections/{id}/gaps`. No UI. | M | `review-migration` **before**, data-integrity, security, quality |
| **P6.3.2b** | **The editor** — marking several cells, deleting them, and tapping a hole to bring the shelf back. Hebrew, RTL, and the elevation's existing single-cell selection widened. | M | quality, ux |

**Why before P6.4 and not after.** It is independent of bind and merge, it is
what the owner asked for now, and — the part that would have cost something —
P6.4b's undo journal covers *destructive map edits*. Landing gaps first means
the journal is designed knowing about them, instead of being amended by the
next item. The price is one renumbering: P6.4a's step becomes v22.

**Why the two items split there.** The same reason P6.4b gives for keeping
bind and merge apart: the server half is the half that can lose something, and
it gets its own diff, its own migration review and its own mutation checks. The
editor half cannot destroy anything the route would not have refused.

**What P6.3.2a's four reviews measured, and what is still open.** Migration,
data-integrity, security and quality between them found no critical, one bug
in the new code, two pre-existing concurrency defects the item made reachable
by a friendlier route, and three claims that were false. Fixed in the
follow-up commit: the depth clause (`!=` locked every cell of a section whose
default had been edited — §3.3 guarantees that drift); the destructive loop
re-reading only occupancy (a name typed on the phone mid-request was deleted
outright, 200, nothing reported); the slot diff computed against a stale
section (two tabs could strand a shelf outside the extent, permanently, and
nothing healed it); the ceiling guard trusting the client's direction flag
instead of asking what the change does; and half the cost of a 400-cell
request (12.1s/1206 connections → 6.0s/408, measured).

Filed, **not** fixed here, each with a named owner:

- ⚠ **an open §5.4 duplicate question at a gapped cell becomes
  un-answerable** — it stays in `GET /duplicates` and in the Books tab count,
  while *answer* and *skip* both 404 forever, because both resolve through
  the shelf. Worse than the orphaned decision, which is merely silent: this
  one is visible and cannot be dismissed. Pre-existing — `DELETE /shelves/
  {id}` produces the identical state — so it is not P6.3.2's to fix, but
  §3.10a's cost list now names **three** orphaned kinds (decisions, duplicate
  questions, reads), not one. Belongs with **P6.4e**, which already owes
  history a resolver; if it lands sooner, the cheap form is for the release
  path to clear the queue rows it orphans, since a question nobody can answer
  is worse than no question;
- **the other half of the 400-cell cost** is 400 per-shelf `delete_shelf`
  calls, one connection each, ~3.4s. It wants a batched delete on
  `ShelfStore` beside `save_shelves` — a port change with a contract case of
  its own, and it makes the pre-existing column-shrink path faster too;
- **`SectionEditDTO.created` reports the PLANNED additions**, while `_fill`
  returns what it actually made — larger whenever it heals slots a concurrent
  edit emptied. Cosmetic until a screen shows it, which is P6.3.2b;
- **the client counts slots differently from the server**: `sync.ts` builds
  one document shelf per cell of `column_levels`, so `limits.ts:overCeiling`
  counts the extent while `check_bookcase_size` counts addresses. Safe
  direction (the editor refuses what the server would allow) and unreachable
  until the client knows about masks — but `limits.ts` claims it *mirrors*
  the server, and that claim is now false. **P6.3.2b** fixes both together.

**What P6.3.2b's two reviews measured.** Quality found a critical the item
caused: the client's `withColumnCount`/`withColumnLevels` did not prune the
mask, so shrinking a column past a hole and growing it back produced a cell
that was a gap AND a shelf — a shape the server's `Section.__post_init__`
refuses — and the next diff asked the server to re-open a hole nobody made.
§3.10a's *"the hole goes with the wood"* was implemented on one side only.
Fixed, with one exported `inExtent` so the three longhand copies became one.
UX walked the real house and found five more in this item's own work: the
broken singular («1 תאים מסומנים»), a Hebrew sentence beginning with a digit
rendering right-to-left wrong, a refusal naming a remedy that does not exist
for its cause, a hole whose contrast was 1.15:1 with its only affordances in a
`:hover` and a `title`, and — the one that mattered most — **no way for a
finger to mark a second cell at all**. All fixed; the guard against the
singular is now a test rather than a note, and it found `rows_deep` and
`in_sections` broken since before this pillar.

⚠ **FILED, not fixed — the map is unusable on a phone, and this item did not
cause it.** At 375×812 the plan canvas measures 375×**0**: `#root` gets a
`min-height` rather than a definite height, and the phone block's
`flex: 0 0 38%` on `.map-side` resolves against an indefinite column, so the
inspector takes the whole page and `elementFromPoint` over a bookcase returns
the settings panel. **No pillar-6 flow has ever been walked on a phone**,
including P6.3.2b's own verification, which was a desktop verification
truthfully reported as a browser one. The same defect is visible on desktop as
a 488px page scroll whenever an elevation is taller than the viewport. It wants
its own item — a definite height plus `min-height: 0` on the scrolling panel —
and it should come before P6.5 puts navigation on the map, because a phone is
the device this catalogue is used from.

### P6.3.3 — the plan tab on a phone

Found by P6.3.2b's UX review while walking the flows: at 375x812 the drawing
surface measured 375x**0**, `elementFromPoint` over a bookcase returned a fold
header, and the settings panel was the entire page. **No pillar-6 flow had ever
been walked on a phone** — including P6.3.2b's own verification, which was a
desktop verification reported as a browser one.

`:root:has(.page-plan) #root` had `min-height: 100%`. A minimum is not a
definite height, so every percentage below it resolved against `auto`: the
phone block's `flex: 0 0 38%` on `.map-side` became the panel's CONTENT height
(1155px for a 52-cell elevation) and the canvas got what was left. `height:
100%` is what *"a workspace that scrolls inside its own panes"* always meant.
Measured after: canvas 375x411, panel 252 and scrolling, a tap at the canvas
centre landing on furniture.

Two flex minimums came with it — the argument `.map-side` already carried on
the horizontal axis, applied to the vertical one — and **two thumb-size rules
that a comment claimed were alive**: at equal specificity the base sheet comes
later and wins, so the elevation cell had been 30px throughout. That cell is
the hole, which is the only way back from a gap.

⚠ Filed, not fixed: a CLOSED drawer stays mounted below the fold and extends
the document by 237px, so the plan still scrolls a little though its own layout
is exact. It is `aria-hidden`, it belongs to the books tab, and it predates
this pillar.

⚠⚠ **The lesson for the rest of the pillar**: a browser verification is not a
phone verification unless the viewport says so. P6.5 puts navigation on this
map; every item from here walks 375x812 before it claims a flow works.

### P6.4 — binding and merge  *(planned, not started)*

The decomposition, each landing on `main` before the next:

| # | Item | Size | Reviewers |
|---|---|---|---|
| **P6.4a** | ✅ **The alias, and nothing using it** — schema **v24**, one alias row carrying the absorbed shelf's id AND its former address, the resolver, `BookStore.books_on_shelf`, and "a shelf other identities resolve to is OCCUPIED". No merge, no route. | M | `review-migration` **before**, data-integrity, quality |
| **P6.4b** | **Undo for destructive map edits** (§3.15) — the journal, the inverse, and the invalidation rule. Covers remove column, remove section, delete bookcase, remove site, **and switching cells off** (P6.3.2, which arrived after §3.15 was written); the merge joins it in P6.4d. Fingerprint at undo time and no expiry; record all, undo the head; a minimal UI lands with it (owner, 2026-08-24). ⚠ Schema **v22** and **v23** — see the note below. | L | `review-migration` **before**, data-integrity, quality, ux | ✅ |
| **P6.4c** | **Bind** — an unaddressed shelf gains an address, and loses one. No identities join; a taken slot is a 409 naming the occupant and offering the merge. | S | data-integrity, security, quality, ux |
| **P6.4d** | **Merge** — two identities become one, undoable. ⚠ **carries the data-loss risk**, and P6.4a left it two named traps: removing the absorbed shelf's row CASCADES its captures away (`captures.shelf_id … ON DELETE CASCADE`, measured), and merging a shelf that has itself absorbed one is refused by the one-hop rule, so re-pointing must happen inside the same transaction. | L | data-integrity, security, quality, ux |
| **P6.4e** | **History across the seam** — reads, streaks, staleness and the *formerly* line resolve through the alias. | M | data-integrity, quality, ux |
| **P6.4f** | *Optional:* **the proposal** — candidates from typed labels only, each an explicit ✓. | S | quality, ux, security |

⚠ **The order moved, and so did the numbering** (owner, 2026-08-23). **P6.4b
runs FIRST**: §3.15 says every destructive map edit is undoable *"and that
lands before the merge"*, and P6.3.2 has since added a fifth destructive edit
(switching cells off) to the four that decision named. Landing the journal
first means gaps, column removal, section removal and bookcase deletion all
become reversible before anything can merge — rather than the journal being
amended by each item that arrives after it. So the steps are **v22 for the
undo journal** and **v23 for the alias**.

⚠ **And the alias moved again, to v24** (2026-08-24). P6.4b needed a
SECOND step of its own: the journal's head cannot be decided by
`recorded_at`, because `SystemClock` has second resolution and `UuidIdGen`
mints uuid4 — so two entries in one second tie and the tie breaks at
random. A data-integrity review measured it at 165/500 undoing the wrong
bookcase and 83/500 restoring an EMPTY one. v23 is a monotonic per-library
`seq`; the alias is now v24. The owner's instruction was *"I don't mind
about the order. just fix all the issues."*

**Two questions §3.11 did not settle, answered before P6.4a starts** (owner,
2026-08-23):

- **deleting a shelf that other identities resolve to is REFUSED**, naming the
  count — the same shape as `ShelfNotEmpty`. Cascading would discard *"the
  shelf that was at section 1, column 2, level 3"*, which is the one thing the
  alias exists to answer, and it would take the P6.4c census's baseline with
  it. Keeping the aliases pointing at a deleted shelf was the third option and
  is worse than either: it breaks the foreign key that makes an alias of an
  alias unrepresentable, so the resolver would need a cycle guard and a null
  check on every call;
- **two aliases may not claim one former address** — a unique index over
  `(library_id, section_id, col, level)` where it is not null. The
  address→survivor lookup must have exactly one answer, and the alternative is
  a query that silently picks the first of several.

⚠ **The numbering moved once.** P6.4a's step was planned as v21 and is now
**v22**: P6.3.2a landed first and spent v21 on the section mask (§3.10a). The
sentence below about the test frame is unchanged in substance — v21→v22 copies
what v20→v21 copied from v19→v20 — and P6.3.2a's own test is the nearest
example, since it is an ALTER on an existing table rather than a new one.

**P6.4a is separate because it is the only item of P6.4 with a schema-version
change** — so it is the only one needing `review-migration` and a worktree,
and the migration gets reviewed against a diff containing nothing else. The
v21→v22 test copies the v19→v20 frame, including the four lines that assert
the table is ABSENT on the v21 file: without them the test follows
`MIGRATIONS` wherever the DDL is written, so folding it into `_V21` — the
edit rule 11 forbids — stays green while the one database that matters never
gains the table. And it must use the table afterwards: the v19→v20 test's own
⚠ records that its `foreign_key_check` ran while every new table was empty.
Both halves were measured again on P6.3.2a's step, by mutation: folding the
DDL into the previous step was caught by exactly one test, its own.

#### P6.4b in detail — the journal  *(✅ LANDED 2026-08-24)*

**One sentence:** a destructive map edit records its own inverse, and an undo
that cannot prove the world is unchanged refuses and says why.

**The five destructive edits it must cover.** §3.15 named four — remove a
column, remove a section, delete a bookcase, remove a site. P6.3.2 added the
fifth, **switching cells off**, which is the reason the owner moved this item
ahead of the alias (2026-08-23): the journal is written knowing about gaps
rather than amended by them. Each already destroys or detaches shelves behind
nothing but a `confirm()`, and each is one mis-tap.

**Recording, not deriving**, and §3.15 gives the reason: a book the owner typed
onto a shelf by hand has no provenance, so a GUESSED inverse moves books that
never moved. The inverse is captured at the moment of the edit — which rows
went, which slots were detached, what each shelf's label and depth were — and
the undo replays exactly that.

**Schema v22**, its own step. Sketch, not settled:

    map_undo(id, library_id, kind, recorded_at, inverse TEXT)

`inverse` is JSON for the same reason `sections.gaps` is (P6.3.2a): it is read
and written whole with its entry and never queried by field. ⚠ Unlike `gaps`,
it is not small — a cleared bookcase is 400 rows — and question 1 below
decided the table is **not** bounded by age, so its growth is a real thing to
watch and a later item's problem, not a reason to expire an honest undo.

**THE THREE QUESTIONS, ANSWERED** (owner, 2026-08-24). None was derivable
from the code, and two overruled the recommendation on record:

1. **How does an undo prove the world is unchanged?** → **A fingerprint
   checked at undo time, with NO time window** (owner; the recommendation was
   the same fingerprint plus a 24h floor). §3.15's literal reading —
   *"invalidated the moment anything else touches those rows"* — was rejected
   as the expensive and quietly-incomplete shape: it puts the journal on the
   hot path of every product write, and the one write path that forgets to
   check produces a silently WRONG undo, which is worse than a refused one.
   So the undo re-reads exactly what it would restore, digests it, compares
   against the digest recorded with the entry, and **refuses naming what
   moved** if they differ. It cannot be wrong and it costs nothing on the
   write path. The 24h floor was dropped on the owner's argument that a
   mis-tap noticed a week later is still a mis-tap: age is not evidence that
   an undo is unsafe — the fingerprint is the only evidence, and it is exact.
   ⚠ The consequence is accepted deliberately: **entries never expire**, so
   the table is unbounded and retention becomes its own later item. Nothing
   in this item may quietly reintroduce an age check as a substitute.
2. **One undo, or a stack?** → **Record all, undo the head** (owner; as
   recommended). Every destructive edit writes a row — the journal is also a
   record of what happened — but only the newest still-undoable entry for the
   library can be replayed. No cursor, no out-of-order semantics, no redo.
   Older rows stay as history and are **never** replayable. Growing to n-deep
   later is a behaviour change, not a migration:

       POST /map/undo   → undoes the newest live entry
       GET  /map/undo   → what would be undone, or why nothing can be

3. **Does a UI land here, or is this the route only?** → **Route plus a
   minimal UI** (owner; the recommendation was route-only). One control in
   the map editor, the refusal surfaced honestly — not a preview of what will
   be restored, which stays with P6.4d where the stakes need it. So this item
   grows past an L and **`review-ux` is back in its reviewer list**, with the
   375x812 walk in a real browser that P6.3.3 taught us to do before claiming
   any flow works. The schema review is protected the other way instead: the
   v22 step is committed on its own, reviewed against a diff with no client
   in it, before the UI half is written.

**What P6.3.2 filed that this item should look at:** the `SectionEditDTO.
created` count reports planned rather than actual additions, and `_release`
deletes one shelf per connection (~3.4s of a 400-cell request). Neither blocks
the journal; both live near it.

**Reviewers:** all five ran. `review-migration` before both schema
commits; data-integrity and quality after the merge; **ux** last, and the
375x812 walk happened twice — once by hand (the geometry reproduces
P6.3.3's numbers exactly: canvas 375x411, panel 252) and once by the
reviewer.

⚠ **The UX review found the thing the whole item was for still broken.**
`ביטול` — the DRAWING undo — sits first in the same menu, is the word
everybody knows, and becomes enabled the instant something is deleted. It
re-draws the slot, so the server mints a NEW empty shelf while the
owner's label and books stay behind detached, and the bookcase visibly
reappears. It looks like it worked. The cure sat two rows below it under
a name nobody was looking for. No label fixes that, because the owner
never compares the rows; a destructive push now says once, in the flash,
that it can be taken back and names the control. Four more majors came
with it: a refused undo was re-deriving and discarding the session's
drawing history, "nothing to undo" was delivered as an alarm under "the
server refused the change", the one refusal §3.15 requires to say WHY was
saying "things", and switching language mid-notice produced half a
sentence in each.

**What the reviews changed, recorded because none of it was obvious.**
The three that lost data outright:

- **the head was decided by a clock that ties.** See the ⚠ above; v23.
  The same tie also broke coalescing, so a bookcase came back with no
  shelves — `record` now finds its partner BY TAG rather than by "is the
  newest entry a match", which cannot be confused by an interleave;
- **`delete_site` and `delete_place` recorded only their own row.**
  Deleting a site takes its empty storeys and deleting a room unhooks
  every bookcase in it, so the undo restored a container and reported
  success while its contents stayed gone — a site with zero storeys being
  a state `delete_floor` refuses to create on purpose;
- **the SQLite codec dropped `MapRestore.created`**, which made every
  entry carrying one permanently un-undoable while refusing with the name
  of a shelf that had not changed. Two docstrings claimed a shared
  contract test already prevented exactly that. It did not exist;
  `UNDO_CONTRACT` now does, and fails on sqlite alone when reverted.

And three where the mechanism was honest but incomplete:

- **the fingerprint was taken by re-reading AFTER the edit**, so anything
  committed in that window was digested as "the state the edit left" and
  became invisible. Measured: another tab's change reverted by an undo
  reporting `available: true` and an empty `changed`. The callers now hand
  over what they wrote. ⚠ The slot maps are still read, so that much of
  the window is open — stated rather than pretended away;
- **its scope watched rows but not the SHAPE they land in.** A restored
  row's parent and a restored section's ordinal space are now digested;
  without them two ordinary gestures reached a 500 through a route that
  had just answered `available: true`. `post_undo` also now goes through
  `_translated()`, which every other mutating route in that router did;
- **a replay that refused part-way had already written.** The removal set
  is judged before anything happens, so a refusal is clean and repeatable
  — the first version left the entry dead forever, blaming a shelf the
  undo itself had deleted.

**Worktree**, per rule 1.

**P6.4b is separate so that *bind* and *merge* are never one button.** The
safe half is a shelf gaining an address; the dangerous half is two identities
becoming one, and a UI that cannot tell them apart is how the dangerous one
gets pressed by accident.

**What proves P6.4c did not lose anything** is a census, not a constraint —
four of the six tables have no foreign key to police. One pure function
digests a library before and after: books, copies, and copies WITH a
location, all unchanged; the multiset of `(book_key, depth)` at the survivor
equal to the union; `provenance` byte-identical; every capture present with
`(shelf, depth, order)` still unique; every `(depth, book_key)` decided at
either side still decided at the survivor; and **zero rows naming a shelf id
that is neither a live shelf nor an alias** — the check no
`foreign_key_check` can perform, and the one that catches the real bug. Then
a REPLAY, which is this project's own idiom: re-run the last real read of A
against the post-merge state and assert the suppressed set is identical.

⚠ Two things the code read turned up, both filed:

- **`DELETE /shelves/{id}` orphaned copies** — measured, fixed and merged
  before P6.4a starts, because the census would otherwise report a
  discrepancy P6.4 did not cause;
- **half a merge already exists**: `PATCH /captures/{id}` moves one photo to
  another shelf and appends its order, so an owner can already move every
  photo off A onto B today — the books stay. P6.4c must not contradict that
  route's ordering, and the shelf screen should stop showing the resulting
  empty A as if it were furniture.

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

## 7. Open questions — all four closed (2026-08-16)

1. **Does a Place nest?** → **Yes: a real `Site` above `Floor`** (owner). The
   recommendation on record was *flat until it hurts*, and it was overruled —
   correctly, since "the parents' place, upstairs" needs two levels, not a
   longer label. §3.9 is the decision, including what `Place` now means and
   what VISION's gloss no longer means.
2. **Can a bookcase stand off a wall?** → **Yes, and no mode was needed.** The
   lab settled it by construction: a bookcase is a free rectangle, the wall is
   a magnet, and `frontFor` only *guesses* the facing when the case happens to
   land flush. An island shelf is drawn mid-room and turned by hand. The
   "deliberate detach" the recommendation asked for never had to exist.
3. **Which end is column 1?** → **The leftmost cell as you FACE the case.** The
   elevation is a front-on view (§3.2) and is pinned LTR (§3.5), so column 1 is
   simply the left end of the face the books look out of — `Bookcase.front`
   already records which physical face that is. It is a fact about furniture,
   not about the reading direction of the UI, which is why the Hebrew flip does
   not move it. `UI_PLAN.md` §8's copy of this question is answered by the same
   sentence.
4. **Does the plan carry doors and windows?** → **No** (owner). §3.10.
