# UI plan — the user-facing application

**Status:** proposal + clickable mock. Drafted 2026-08-07, revised same day with
the owner's answers (list-first books, separate delete, wishlist-as-shelf,
duplicates filter, map-first tab 2).
Nothing here is implemented in the product; `booksnap/static/` is untouched.
**Reads with:** `VISION.md` (§5.5 run→shelf inversion, §5.6 durable shelf list,
§5.7 depth, §6 library experience, §7 physical map, §4.2 roles).
**Mock:** `planning/mockup/` — see `planning/README.md` to run it.

---

## 1. The navigation model

Three tabs plus settings — the owner's structure, and the shape §5.5 argues for:
*"my books, and my shelves. A shelf can be re-read. That's it."*

| Tab | User's sentence | Vision anchor |
|---|---|---|
| **הספרים / Books** (default) | "what do I own?" | §6 library experience |
| **מפה / Map** | "where is it / what's on that shelf?" | §7, §5.3, §5.6, §5.7 |
| **צילום וקריאה / Capture** | "read this photo" | §5.5 (runs, demoted) |
| **הגדרות / Settings** | everything else | §4.2, §8.2, §10 |

**There is no run list anywhere.** A run surfaces twice, both subordinate: as a
row in a shelf's read history (`6.8.2026 · +9 added · run 17 · llmpage`, where
`run 17` is small grey mono text, not a link), and in the technical log behind
Settings. That is the whole of §5.5's "reachable but not on the main path".

**Scoping chrome.** A *Library* switcher ("משפחת מלין") sits in the app bar —
§4.1 makes Library the tenancy boundary and an Account may belong to several.
*Place* (Home / Office / Parents') is **not** in the app bar; it's a filter
inside the Map tab, because it must not scope Books: "do I own X" has to answer
across every place you keep books. **[owner-confirmed]**

**Hierarchy stays three levels: Place → Bookcase → Shelf.** **[owner-confirmed]**
A "work-room library" is simply another bookcase inside Home — no room level.
What it needed was a visible **＋ add a bookcase** inside a place, which now
exists both as a button and as a ghost block on the sketch.

### 1.1 A shelf's address: three axes, three words

A bookcase is not a single stack — it has **columns** (vertical bays), so a
shelf is *"column 3, shelf 1"*, not *"shelf 1"*. **[owner-raised]** With depth
from §5.7 that makes three independent axes, and they must never share a word:

| Axis | Field | Direction | Declared or detected |
|---|---|---|---|
| **column** | `Shelf.col` | across the case, left→right | declared (or proposed from a case photo) |
| **level** | `Shelf.level` | down the case, top→bottom | detectable — `segment.py`'s shelf-band signal |
| **depth** | `Copy.depth`, `Shelf.depthCount` | front→back | declared only (§5.7 — nothing in the image says "the row behind") |

Full address: `Home · Living room case · Col 2 · Shelf 1 · Row 2 (back)`.

Two rules carried over from the depth decision, for the same reasons:

- **column is an attribute of position, not a new entity.** Splitting a case
  into one Bookcase per bay would put two records in one physical slot on the
  map and lose the fact that it's one piece of furniture — exactly the argument
  §5.7 makes against modelling the back row as its own shelf;
- **it is hidden until it exists.** A single-bay case renders `Shelf 1`, never
  `Col 1 · Shelf 1`, just as a flat shelf never mentions depth. Most users' cases
  have one column and should never meet the concept.

⚠️ **Naming, extending the §5.7 warning.** `segment.py` already owns **band**
for horizontal shelf rows found inside one photo. So: **column** across,
**level** down, **depth** back — and *never* "row" or "band" for any of them.

---

## 2. Tab 1 — Books

Sticky toolbar → filter row → count line → endless-scroll feed.

- **List is the default and carries no image.** **[owner's call]** The spine
  crop is a slice of the shelf a book happened to sit on, not a cover; a column
  of them is noise. The crop stays where it is *evidence* — the book detail and
  the review rows. If real covers arrive later (§8.3) the decision is worth
  revisiting. A grid toggle exists for browsing, also image-free.
- **Search** — one box over title *and* author on the normalized forms (§6):
  nikud stripped, final letters folded, geresh deleted in-word, a leading
  ה/ו/ב/ל/מ/ש/כ tolerated. The mock implements a miniature of `normalize()` so
  the behaviour can be felt, not just described.
- **Sort** — title / author / recently added / by shelf.
- **Filters** — status (auto / approved / manual), shelf, lent-out-only, an
  author chip (arrived at by clicking an author anywhere), plus two that came
  out of the vision:
  - **כפילויות לבירור / duplicates to resolve** — §5.4's queue of skipped
    copy-resolution questions, surfaced here rather than as a separate screen
    **[owner's call]**. The same books also carry a badge wherever they appear
    on a shelf, so the question is never only in one place;
  - **☆ רשימת משאלות / wishlist** — see below.
- **Wishlist is a virtual shelf**, not a tab and not a separate entity
  **[owner's call]**: a `Shelf` with `virtual: true`, no bookcase, no photo,
  never read. Books on it are **excluded from the default list and from the
  book/author counts** — "50 books" must mean what you own — and the chip
  switches to them. It also shows up as a destination in *Add a book* and is
  filtered out of every shelf-assignment picker.
- **Two primary actions live here**: **צלמו מדף** (jumps to Capture) and
  **הוספת ספר** — a modal with title, author autocomplete, and an optional
  shelf + depth binding, which answers *"is it already here?"* as you type.

---

## 3. Tab 2 — Map

**Sketch-first** **[owner's call]**: the physical skeleton *is* the navigation.
Three drill levels in one column, with the selected shelf beside it.

**Level 1 — the place, as a clean schematic.** Rooms are outlines; **bookcases
are blocks** placed on them, each labelled with its shelf and book counts, all
clickable. This is §7's approach A, and the vision is explicit that the target
is *a clean schematic derived from a wobbly sketch*, not a wobbly canvas — so
the mock draws crisp orthogonal rectangles. A dashed **＋ הוספת ארון** ghost
block sits on the plan, and the same action is a button in the header. A place
with no sketch yet falls back to the card list with a *"draw a sketch"* /
*"or photograph the room"* prompt (see Parents' in the mock).

**Level 2 — the bookcase elevation.** The case drawn as it physically is: a
**grid of `columns` bays across × levels down**, each cell being **the shelf
photo** with its level, book count and depth badge. Missing cells are dashed
`+ Shelf` slots, so a half-catalogued case is visibly half-catalogued rather
than silently short. `+ Add a column` sits under the grid. This is §7's
approach B where it is strongest: `segment.py` already detects horizontal shelf
bands, so the levels of a case can be *proposed from one photo of it* and
confirmed by hand.

The grid is **pinned to LTR** — column 1 is always the leftmost cell — because a
piece of furniture must not mirror when the UI language changes. Text inside a
cell still follows the UI language. (Which end column 1 *should* be for a Hebrew
user is genuinely open; see §8.)

**Level 3 — the shelf** (unchanged from the first draft, now in the side panel):
photo · last-read date and declared depth · a soft staleness line
(*"rows 2, 3 not read since 11.3.2026"*) · a **depth bar** with one button per
front-to-back row and a visible **+ add a row behind** (§5.7 is explicit that
depth cannot be detected and most users won't know the feature exists, so it is
surfaced even on single-row shelves) · **the books at the selected depth** —
the durable list of §5.6, with soft *"not seen in the last 3 reads"* badges and
no auto-removal ever · **read history** as diffs
(`+3 added · 1 corrected · 12 unchanged · 1 not seen`). This *is* the history
UI; it replaces the run list entirely.

`#/map/<shelfId>` deep-links straight to level 3 with the right place, case and
elevation already open — which is how Capture hands off.

**Honest flag on "photograph the room, Sonnet draws the sketch".** Detecting a
*bookcase's shelf rows* from a photo is deterministic, free, and already built
(`segment.py`) — that part is solid. Turning a room photo into a floor plan is
a different problem: perspective, occlusion and scale make it unreliable, and it
would be a paid call on every attempt. The cheap hybrid the vision already
anticipates ("B is a good input to A") is: detect the case from its photo, let
the user drag the resulting block onto the room sketch. Worth deciding before
any POC work starts.

---

## 4. Tab 3 — Capture

Today's view, re-centred on shelves. Left column = intake, right = inline review.

**Intake** — drop zone, phone-on-same-Wi-Fi hint, select all / clear /
only-unread, then a row per photo. The one structural change: **each photo
carries a shelf and, when the shelf is stacked, a depth**, chosen inline. A
photo with no shelf reads *Unassigned*. This is what makes §5.6 possible —
reconciliation must know which shelf and which row a read is about, and §5.7
warns that comparing a front-row read against a whole 3-row shelf would flag
two-thirds of its books as missing every time.

Mode selector, run/stop and progress are unchanged from the working UI.

**Inline review** (the hybrid decision) — a header stating the target
`case · shelf · row` and the running diff, then a row per claim: crop, title,
author, the raw read in guillemets, tier badge with score, a diff badge
(*new* / *already here* / *duplicate?*), ✓ / ✕, *why?*. Two expansions:

- **alternatives** — the ranked runners-up with scores, one-click acceptable;
- **the §5.4 copy-resolution prompt** — *the listed copy / another copy / wrong
  book*, with the default (**the listed copy**) stated on screen. Skipping it
  lands the book in the duplicates filter on Books rather than losing it.

An **פתחו את המדף →** chip sits in the header, and the copy under it says
plainly that confirming here is a shortcut and the shelf is the durable home.
That is the hybrid contract, made visible rather than assumed.

---

## 5. The book surface (drawer + full page)

One renderer, two mounts. Opened from a card, a list row or a shelf row it
slides in as a **side drawer** (bottom sheet under 620px) over the untouched
list. **⤢** promotes it to a **full page at `#/book/<id>`** — deep-linkable and
returnable.

- spine crop, title, author (a link → Books filtered to that author), status,
  lending and staleness badges, and **Edit** turning title/author into fields.
  Saving marks the book `manual` — a human decision outranking an auto one,
  matching `library.py`;
- **Where it is / Copies** — one box per copy: location (place · case · shelf ·
  row), lending with lend / mark-returned, last seen, move-to-shelf. The word
  "copies" and the count appear **only when there's more than one** (§5.1);
  **"I have another copy"** is the only path that creates one;
- **two different destructive actions, deliberately separate** **[owner's call]**:
  *remove from shelf* keeps the book in the library (it may have moved, §5.6),
  and says so in a toast; *delete from the library* is a distinct, confirmed
  action that removes every copy;
- **Mine** — rating, read status, notes (§6 "Should", phase 2);
- **Where it was seen** — the reads that touched this book's shelf, plus **why?**;
- every edit fires a change event and the list behind repaints. One book record,
  one component — that is "edit it anywhere, it changes everywhere".

---

## 6. Settings (a first inventory, nothing decided)

**Library** (members & roles §4.2, places/cases/shelves, export) ·
**Reading & cost** (default mode, API keys & quota §3/§10, auto-approve AUTO) ·
**Privacy & sharing** (shared books DB opt-out §8.2, correction-corpus opt-in
§9.2, photo retention & purge) · **Technical log** (config, code version,
per-spine scores, `explain()` — the audit view §5.5) · **Language**.

---

## 7. Decisions the mock takes on its own (say if any is wrong)

1. **RTL-first with a real he/en switch.** The whole layout mirrors — nav,
   drawer, filters, map — because the collection is Hebrew and §6 makes RTL
   baseline, not polish. Every rule uses logical properties, so mirroring is
   free.
2. **Mixed-script alignment: direction per string, alignment per container.**
   `unicode-bidi: plaintext` gives each title its own base direction, which is
   what makes `Sapiens` and `משחקי הכס` both render correctly in one list. But
   it *also* resolves `text-align: start` per string, so in English mode Hebrew
   titles flushed right and Latin ones flushed left — a column with two ragged
   edges, which is what looked wrong. The fix separates the two concerns:
   `unicode-bidi: plaintext` for glyph order, an explicit `text-align` keyed on
   the *container's* `dir` for the edge. One clean edge, correct text.
   Rejected alternatives: dropping `plaintext` (breaks punctuation and embedded
   numbers in Hebrew titles); centring (worse for scanning a long list); forcing
   the whole app RTL regardless of chrome language (defeats the point of the
   English mode).
3. **The shelf photo is the shelf's identity** in the elevation and the card
   fallback — a wall of photographed shelves is recognisable in a way names
   aren't.
4. **The depth bar is always visible**, even at depthCount 1, for discovery.
5. **The duplicate prompt states its default on screen.** §5.4 warns it becomes
   click-through-approved if it fires often; showing the default makes skipping
   it an informed act.
6. **`run N` is visible but unlinked** in read history — enough to correlate
   with the experiments ledger, not enough to read as a feature.
7. **The map gets the wider column**, the shelf panel the sidebar — sketch-first
   means the sketch is not the small one.

## 8. Still open

- **Does Capture survive as a permanent tab**, or dissolve into "re-read this
  shelf" launched from the map? Today it is both. **[owner: undecided]**
- **Which end of a case is column 1** for a Hebrew user — the left (as the mock
  renders it, matching how the numbers read in the plan) or the right (matching
  how Hebrew reads)? Whichever it is, it must be fixed once: the elevation and
  every location label have to agree, and it must not flip with UI language.
- **Assigning a photo to a shelf now means picking a cell**, and the dropdown
  (`case · col · shelf`) gets long as cases grow. Clicking the target cell in a
  miniature elevation would be better; not built.
- Room-photo → floor-plan generation (see the flag in §3).
- The physical **map editor** itself — the mock renders a schematic but has no
  drawing tool; §7 wants a POC of both input paths first.
- Covers, summaries, series awareness, "who has my books", onboarding, auth.
  All in the vision; none change the shape of these three tabs.
