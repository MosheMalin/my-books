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

Eight rules, each of which is cheap now and expensive later.

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

Seven rounds of building and driving it in a real browser produced fifteen
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
14. **the cursor read the tool, not the intent.** Once an edge became grabbable
    in every tool the behaviour was right, but the pointer still showed a
    crosshair over it — the one thing telling the user about a rule was the
    thing that had not been updated;
15. **`setPointerCapture` threw the whole handler away, a second time.** The
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
| **P6.0** | **The map lab** — a standalone app, no backend, outside the gate. Rectangle drawing for rooms and bookcases, room-to-room attachment, multi-select, copy/paste, explicit bookcase→room attachment, resize handles, sections, floors, the elevation editor, underlay tracing, black/white themes, visible autosave, a real undo stack. Exit: the owner draws his real house in it and exports it (§4 — the interaction model is settled; the drawing is still owed). | M | **5th pass** |
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

⚠ The lab has been through **eight passes**. The first offered freehand against
snap-while-dragging and was rejected wholesale (§4); the third came back
*"very fluent"* with five additions; the fourth and fifth were polish plus four
real bugs; the sixth cut the toolbar to eight controls and made the arrow
guess; the seventh moved the storey onto the board and drew the icons;
the eighth stacked the floors as rows and gave the read-only view a door.
Expect a ninth: the point
of a disposable app is that rejecting it costs a day, not a sprint. It is
finished when the owner stops finding things, not when the item list is
ticked.

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
