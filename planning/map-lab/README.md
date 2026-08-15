# map-lab — P6.0

The standalone map editor lab. **No backend, no product code, outside every
gate — and deleted at P6.3** when the editor is ported into `app/web`. The plan
is [`../MAP_PLAN.md`](../MAP_PLAN.md); this file is how to run it and what to
look at.

```bash
npm install --prefix planning/map-lab
npm --prefix planning/map-lab test          # 29 core tests, ~0.7s
```

The dev server is `map-lab` in `.claude/launch.json` (port 5175 — 5173 is the
product client, 5174 the console). Nothing here routes to `tools/check.py` or
the pre-commit hook, by design: `planning/` is outside `app/`, `tests/` and
`tools/`.

## Where it stands

**Second pass.** The first offered freehand-and-straighten against
snap-while-you-drag; the owner drew on it and rejected both — *"the free draw
was too free"*. Everything is now a **rectangle on the grid**, for rooms and
bookcases alike, and the freehand code is deleted rather than disabled.

## What to try

1. **Draw room** — drag a rectangle. Then drag a second one so it lands near
   the first: its edges **weld onto the neighbour**, exactly, so rooms attach
   and an L-shaped room is two rectangles.
2. **Draw bookcase** — drag a rectangle inside a room. It snaps flush against
   the wall and the books face into the room. The thick line is the front.
3. **Move & edit** — drag to move, drag a handle to resize, tap to open the
   panel. A room takes its bookcases with it when it moves. Sizes are typeable
   in the panel as well as draggable: the units are relative, so "twice as wide
   as that one" is the only thing that matters, and typing is how you say it
   exactly.
4. **Watch the depth rule.** Set a case's *default* depth to 3. Its existing
   shelves keep depth 1 and the panel says how many — changing a default never
   reaches back into shelves that already exist, because that would delete the
   location of every book standing in a back row. A **new** column takes the
   new default. Applying to existing shelves is a separate button.
5. **Black or white** — two real themes, not an inverted filter.
6. **Trace a sketch** — your floor-plan photo goes behind the canvas at
   adjustable opacity. Draw over it, then remove it. That is the whole of "or
   provide a sketch": no image understanding, no paid call.
7. **On a phone.** The layout stacks under 820px and the toolbar gives its
   space back to the canvas. This is the viewport the verdict should come from.
8. **Export.** Integers in abstract units — no pixel, no viewport, no
   centimetre. Send it over; that file is the artefact.

Panning is deliberate: the **Pan** tool, the middle mouse button, or two
fingers. Dragging empty space deselects and does nothing else.

## Shape

```
src/core/     framework-free, pure, ports VERBATIM at P6.3
  geom.ts         points, the grid, snapping one coordinate
  rect.ts         rectangles, edge-to-edge attachment, resize handles
  model.ts        Plan / Room / Bookcase / Shelf + the pure edits
  history.ts      undo stack
  persist.ts      export/import, defensive on the way in
  core.test.ts    the rules that port with the core
src/ui/       the thin, disposable shell (React + SVG)
```

The split is the point: **the port is a folder move plus a data adapter**, not
a rewrite. Nothing in `core/` imports React, touches the DOM, or calls `fetch`.

## Found while building it (all fixed, all now tested)

- **`side` was computed against the wall's direction** but consumed against the
  case's own baseline. Drag a bookcase right-to-left and its body landed
  *outside* the room. (First pass; the rectangle model retired the concept.)
- **A burst of `pointermove` events was overwriting itself.** pointermove is a
  continuous event, so React batches a burst into one render and every handler
  closes over the same stale state — on a 120 Hz phone that is most of a stroke
  thrown away, and it reads as a bad straightener rather than as dropped input.
  Functional updates only.
- **`pointerup` ignored its own coordinates.** Lift fast and the browser
  coalesces the tail of the gesture into the up event, so a quick drag came out
  short.
- **A traced rectangle came back with five walls.** Welding cannot see a
  collinear triple across the polygon's seam. (First pass.)
- **Dragging empty space panned the view** — the background sliding out from
  under a mis-aimed drag reads as broken even when nothing was damaged.
- **On a thin rectangle the corner handles crowd out the edge handles**, and
  the hit test took the first in reach rather than the nearest. A bookcase is
  thin by nature, so dragging its end to lengthen it collapsed its depth to
  zero. Corners are now dropped when the rectangle cannot hold them apart.

## What this lab is NOT

Not a product surface, not styled from `app/ui`, and not a second copy of
anything. It has its own throwaway sheet **on purpose** — borrowing the
product's design system would make an undecided question look decided.
