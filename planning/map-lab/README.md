# map-lab — P6.0

The standalone map editor lab. **No backend, no product code, outside every
gate — and deleted at P6.3** when the chosen editor is ported into `app/web`.
The plan is [`../MAP_PLAN.md`](../MAP_PLAN.md); this file is how to run it and
what to look at.

```bash
npm install --prefix planning/map-lab
npm --prefix planning/map-lab test          # 25 core tests, ~0.7s
```

The dev server is `map-lab` in `.claude/launch.json` (port 5175 — 5173 is the
product client, 5174 the console). Nothing here routes to `tools/check.py` or
the pre-commit hook, by design: `planning/` is outside `app/`, `tests/` and
`tools/`.

## The question it exists to answer

Draw your real house, twice, and say which one to build:

| | how you draw | the risk it carries |
|---|---|---|
| **D · snap** | walls snap to the grid and to 90° **as you drag**; a bookcase snaps onto a wall and gets a length handle | none of the kind S has — every intermediate state is legal and visible |
| **S · straighten** | draw freehand; the stroke is straightened when you lift (VISION §7 approach A) | the reading can be **wrong**, and the only correction is undo and redraw |

D is the recommendation on record. It is a UX claim, so it is settled by
drawing, not by argument.

Both modes place a bookcase through the **same** `placeCase` rule, so the
comparison isolates the authoring gesture and nothing else. (The canvas
component ended up with no `mode` prop at all, which is the same fact stated
by the type system.)

## What to try

1. **Draw a room.** `Room` tool, drag. Then drag a second room starting near
   the first one's corner — corners weld, so two rooms share a wall exactly.
2. **Drag a bookcase ALONG a wall.** It lands on the wall, as long as you
   dragged. No number is typed anywhere: the length is relative to that wall,
   which is what "free measurements, not centimetres" means.
3. **Open it.** Tap the case: columns × levels, one cell per shelf. Add a
   column, give one column its own level count, set one shelf's own depth.
4. **Watch the depth rule.** Set the case's *default* depth to 3. The five
   existing shelves keep depth 1 and the panel says so — changing a default
   never reaches back into shelves that already exist, because that would
   delete the location of every book standing in a back row. A **new** column
   takes the new default. Applying to existing shelves is a separate button.
5. **Trace a sketch.** *Trace a sketch…* puts your floor-plan photo behind the
   canvas at adjustable opacity. Draw over it, then remove it. That is the
   whole of "or provide a sketch" — no image understanding, no paid call.
6. **On a phone.** The layout stacks under 820px and the toolbar gives its
   space back to the canvas. This is the viewport the verdict should come from.
7. **Export.** The JSON is integers in abstract units, with no pixel, no
   viewport and no centimetre in it. Send it over — that is the artefact.

## Shape

```
src/core/     framework-free, pure, ports VERBATIM at P6.3
  geom.ts         vectors, projection, grid, point-in-polygon
  model.ts        Plan / Room / Bookcase / Shelf + the pure edits
  snap.ts         mode D: snapping at input time, wall attachment
  straighten.ts   mode S: simplify → rectilinear → weld → close
  history.ts      undo stack
  persist.ts      export/import, defensive on the way in
  core.test.ts    the rules that port with the core
src/ui/       the thin, disposable shell (React + SVG)
```

The split is the point: **the port is a folder move plus a data adapter**, not
a rewrite. Nothing in `core/` imports React, touches the DOM, or calls `fetch`.

## Found while building it (all fixed, all now tested)

- **`side` was computed against the wall's direction** but consumed against
  the case's own baseline. Drag a bookcase right-to-left and its body landed
  *outside* the room. The test that caught it asserts where the wood ends up,
  not what the sign is.
- **A burst of `pointermove` events was overwriting itself.** pointermove is a
  continuous event, so React batches a burst into one render and every handler
  closes over the same stale state — on a 120 Hz phone that is most of a
  freehand stroke thrown away, and it reads as "the straightener is bad"
  rather than as dropped input. Functional updates only.
- **`pointerup` ignored its own coordinates.** Lift fast and the browser
  coalesces the tail of the gesture into the up event, so a quick drag came out
  short.
- **A traced rectangle came back with five walls.** Plain welding cannot see a
  collinear triple across the polygon's seam, so the inspector told the owner
  his rectangular room had five walls. `weldPolygon` looks across the wrap.

## What this lab is NOT

Not a product surface, not styled from `app/ui`, and not a second copy of
anything. It has its own throwaway sheet **on purpose** — borrowing the
product's design system would make an undecided question look decided.
