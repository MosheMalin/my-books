# planning/mockup — the design reference

A no-build vanilla-JS mock of the product. It is a **design reference, not a
donor** (`planning/IMPLEMENTATION_PLAN.md` D4): the real client is rewritten
against a live paginated API, so the mock's value is the *decisions* it
takes — layout, colour, RTL behaviour, what appears when — not its code.

Run it: `python -m http.server 8790 --directory planning/mockup`
(or the `ui-mock` entry in `.claude/launch.json`).

## What is still here, and what has graduated

D4: **once a tab reaches parity in `app/web/`, that tab's mock code is
deleted.** Two live implementations of one screen drift, and the drift is
invisible — you find it when someone reports that a fix landed in one place
and not the other.

| Tab | State |
|---|---|
| **Books** | **graduated (P1.6)** — `js/library.js` deleted, its CSS removed |
| Map / Shelves | still the reference (pillar 6) |
| Capture | still the reference (pillar 2) |
| Settings | still the reference (pillar 4+) |

The Books tab is gone from the router, the bottom nav and the app bar. A
stale `#/library` hash lands on Map rather than erroring.

## Why `js/book.js` survived the same cut

The book surface reached parity too — `app/web/src/book/` is the real one now.
But `book.js` is **not** Books-tab-exclusive: `js/map.js` imports `openDrawer`
from it, and the shelf panel's book rows (`data-open`) call it directly.
Deleting it would break the Map tab, which is still the reference for pillar 6.

So it stays until the Map tab graduates, and it is the one file in here that
is *knowingly* duplicated by shipped code. Two consequences worth stating:

- **do not "fix" the book surface here.** Changes belong in
  `app/web/src/book/BookSurface.tsx`. This copy exists only so the Map mock
  has something to open;
- its Books-only affordances were removed rather than left to silently
  no-op — the author name was a link that filtered the Books tab, and a
  control that does nothing when clicked is worse than no control.

## What the CSS still carries for other tabs

`.seg` (Map's map/list toggle) and `.booklist` / `.brow` (Map's shelf-panel
book rows) were in the old "library tab" block and are still in use. The
Books-only rules — `.toolbar`, `.searchwrap`, `.filterbar`, `.countline`,
`.bookgrid`, `.card*`, `.brow .side`, `.groupsep`, `.sentinel` — live on in
`app/web/src/styles/books.css`, along with the palette, which the real client
took verbatim so the two stay visually related.

`js/ui.js` still exports `normalize()` and `searchHit()`, now unused: they
were the mock's miniature of the matcher's normalizer. The real client does
not have an equivalent and must not grow one — search is server-side, and two
normalizers drift (see `CLAUDE.md`, Hebrew search).
