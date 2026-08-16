# planning/

Design work for the user-facing application. **Nothing here runs in the
product** — `booksnap/` is untouched by everything in this folder.

- [`UI_PLAN.md`](UI_PLAN.md) — the proposed layout, tab by tab, with the
  `VISION.md` decision each part implements and the calls the mock takes on its
  own.
- [`MAP_PLAN.md`](MAP_PLAN.md) — pillar 6, the physical map: the decomposition
  that supersedes `IMPLEMENTATION_PLAN.md` §Pillar 6.
- `map-lab/` — the standalone map editor lab (P6.0). A real Vite + React + TS
  app with **no backend**, deliberately outside every gate, and **deleted at
  P6.3** when the chosen editor is ported into `app/web`. See its own README.
- `mockup/` — a clickable mock of that layout. Vanilla ES modules, no build
  step, no CDN, no backend. Fake data lives in `mockup/js/data.js`, shaped like
  the target `Book` / `Copy` / `Shelf` records in VISION §5.2–§5.7 so the mock
  exercises the real model (depth rows, multiple copies, per-shelf read
  history) rather than a flat list.

## Running the mock

It uses ES modules, so it needs to be served, not opened from disk:

```bash
python -m http.server 8790 --directory planning/mockup
```

Then open <http://localhost:8790>. There is also a `ui-mock` entry in
`.claude/launch.json` for the same thing.

Worth clicking:

- the **עב / EN** switch in the app bar — the whole layout mirrors;
- **list ⇄ grid**, the status chips, **☆ רשימת משאלות** and **כפילויות לבירור**,
  and typing Hebrew without nikud or with a ה/ב/ל prefix into search;
- any book → the drawer → **⤢ open as full page** (`#/book/<id>`, deep-linkable
  and returnable) → edit the title and watch the list behind it change. Also
  note *remove from shelf* and *delete from library* are separate actions;
- **מפה** → click a bookcase block on the sketch → **ארון הסלון** opens as a
  2-column × 3-level grid (its shelf photos, an empty `+ מדף` slot, `+ הוספת טור`)
  → pick a stacked shelf (טור 1 · מדף 2/3) for the depth bar and the read
  history with its diffs. Try **אצל ההורים** for the no-sketch-yet state, and
  `#/map/sh8` as a deep link;
- **צילום וקריאה** → *Read selected* → the inline review, the alternatives
  table, and the duplicate prompt on הזקן והים.

## Assets

`mockup/assets/` holds downscaled copies of four sample shelf photos and 20
spine crops from a local run, so the mock is self-contained (~800 KB) and looks
like the real thing. Regenerate with the snippet in the session notes if the
samples change.
