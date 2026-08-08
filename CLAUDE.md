# CLAUDE.md — booksnap

Project memory for Claude Code. Read this fully before touching code; it
encodes decisions and hard-won findings from the prototyping sessions that the
code alone doesn't explain.

## What this is

A Hebrew bookshelf cataloguer. The owner photographs shelves of printed Hebrew
books (a personal library of a few thousand); the system reads the spines and
produces a structured catalog of {title, author}. This package is the OCR/
matching **core** — intended to become the engine of a FastAPI backend, with a
PWA or app front-end for photo capture and a review screen.

## Guiding philosophy (do not drift from this)

**Deterministic first; LLM/paid API only as a fallback.** The owner explicitly
does not want to spend tokens/money on letter recognition or book lookup that
cheap deterministic code can do. The pipeline must exhaust free, local,
deterministic methods (classical CV segmentation, Tesseract OCR, fuzzy matching
against a catalog) and only escalate the spines that genuinely fail to a
stronger engine. Every design choice should respect this ordering. When
tempted to reach for an LLM, first ask whether deterministic code can do it.

## Architecture (modules)

```
booksnap/
  config.py     all tunables in one place; paths via env vars (dev == server)
  types.py      Spine, OcrResult, Match, SpineRecord dataclasses
  segment.py    shelf-band detection -> multi-signal spine boundaries -> crops
  ocr.py        line-based + whole-strip Tesseract, dual Hebrew models
  catalog.py    Catalog protocol + LocalCatalog + normalize()
  nli_catalog.py  NLICatalog: National Library of Israel search API adapter
  match.py      token-gated fuzzy matching, series disambiguation, dedup
  fallback.py   Fallback protocol + Null/GoogleVision/ClaudeVision adapters
  pipeline.py   orchestrator: segment -> ocr -> match -> optional fallback
  cli.py        `python -m booksnap.cli --catalog ... img...`
  server.py     FastAPI: upload/select images, background runs, run history
  static/       single-file vanilla-JS UI (no build step, no CDN) — see below
tests/          python rings; see "Tests" below. run_all.py is the runner
                with a real exit code
```

⚠️ **"single-file vanilla-JS UI (no build step, no CDN)" describes the TUNING /
AUDIT surface only** — `booksnap/static/index.html`, served by
`booksnap/server.py` on `/api/*`. It is not a project-wide rule. The
user-facing product client is a React + Vite + TypeScript app in `app/web/`
(build step, npm deps, still no CDN — everything bundled locally). That
reversal is argued in `planning/IMPLEMENTATION_PLAN.md` D3. The tuning page is
deliberately NOT migrated: it is where `explain()`, config snapshots, per-spine
scores and crops live, and putting the accuracy loop through a build step buys
nothing.

Stages are independent and individually callable, so the server can parallelise
OCR across cores and run the fallback in a separate queue.

## The product app (`app/`) — separate from the engine on purpose

```
app/
  domain/       entities + rules. pure Python, no I/O, no framework
    book.py       Book/Copy/Status/Provenance + the rules (VISION §5.1-5.6)
    shelf.py      Shelf/Capture — identity and depth, no address (P2.1)
    read.py       Read/Claim + DiffSummary — the archive a history row reads (P2.4/P2.8)
    reconcile.py  reconcile(): a read's claims -> Diff, pure (P2.5, §5.6)
    history.py    not_seen_streak() + depth_staleness() — the badge/staleness
                  rules derived from a copy's provenance + a shelf's reads (P2.8)
    copy_resolution.py  the §5.4 fire table, the queue entity, the two cheap
                  wins (P2.6)
    text.py       book_key() over booksnap.catalog.normalize — NOT a copy
    search.py     Hebrew search SEMANTICS: parse + rank, pure and portable
  ports/        Protocols: Principal, Clock, IdGen, BookStore, ShelfStore
    blobs.py      BlobStore — image bytes, keys in rows (D1)
    decisions.py  DecisionStore — standing §5.4 answers (P2.5)
    duplicates.py DuplicateQueue — the durable "duplicates to resolve" queue (P2.6)
  adapters/     implementations behind the ports
    sqlite_store.py  the real one (D1); connection per operation, WAL
    disk_blobs.py    uploaded photos; content-addressed, EXIF-normalised
    memory_store.py  the API ring's store, and the contract's 2nd implementation
    migrations.py    versioned schema via PRAGMA user_version (H6)
    legacy_import.py work/*.json -> entities; I/O and PURE mapping split
  reconcile_apply.py  turns a classified Diff into writes (P2.5); also the
                  P2.6 queue's open/close bookkeeping
  api/          FastAPI routers under /api/v1 + DTOs. THIN — no rules
    routers/meta.py   service + library identity
    routers/books.py  list / get / patch / delete / manual add / export
    routers/shelves.py  shelves + captures; the capture→shelf binding (P2.2)
    routers/reads.py  start/poll/stop a read; diff/apply (P2.4/P2.5)
    routers/duplicates.py  the durable queue: list/answer/skip (P2.6)
  api/openapi.json          committed contract, regenerated, never hand-edited
  main.py       the composition root — the ONE file allowed to cross layers
  web/          React + Vite + TS client; talks only to /api/v1
    src/lib/        books.tsx (the store), i18n.tsx (he/en + dir), route.ts
    src/books/      Tab 1: Toolbar, FilterBar, Feed, AddBookModal
    src/book/       the book surface: ONE renderer, drawer + page mounts
    src/capture/    Tab 3: useCapture.ts, intake rows, review panel + claim
                    row/why?/§5.4 prompt (P2.7)
    src/shelf/      the shelf-detail screen: useShelfDetail.ts, ShelfPage.tsx,
                    ReadHistory.tsx — mounted at #/map/<shelfId> (P2.8)
    src/styles/     tokens / base / books / capture / shelf — palette ported
                    from the mock (shelf.css has no mock reference; see P2.8)
```

Two applications coexist through pillars 1–2, by design (plan H1/D2,
"strangle, don't refactor"): the tuning server on `:8756` `/api/*`, the product
on `:8757` `/api/v1/*`. Run the product with
`uvicorn app.main:app --port 8757`; in dev, `npm --prefix app/web run dev`
serves the client on `:5173` and proxies `/api` to it.

The product database is `work/product.db` (override with `BOOKSNAP_DB`;
defaults under `BOOKSNAP_WORK`). It is a **different file from the tuning
server's `store.json`** — the product never writes into the run archive, and
the run archive is not the product's source of truth. Populate it with
`python tools/import_legacy.py --db work/product.db`.

⚠ **Bind a port with a zero-argument closure, never `lambda v=value: v`.**
FastAPI analyses a dependency's signature and treats a defaulted parameter as
a field to resolve, which runs the default through pydantic — and pydantic
DEEP-COPIES mutable defaults. Every endpoint then gets a *copy* of the store:
reads look perfect, writes silently vanish. `app/api/app.py:_always` is the
correct form, and `test_a_write_through_the_api_reaches_the_real_store` is the
only test that catches it (every other assertion reads back through the same
request-scoped copy and passes).

Rules that are enforced mechanically, not by intention
(`tests/test_layering.py`, `tests/test_api.py`):

- `booksnap/*` never imports `app/*` — this is what lets accuracy work and
  product work run on separate branches without colliding;
- `tools/sweep.py|spotcheck.py|rescore.py` never import `app/*` either, so a
  product bug cannot move a baseline number;
- `app/api/*` never imports `app/adapters/*` — the rule that keeps the
  datastore choice (plan D1) a swap rather than a rewrite;
- `app/domain/*` imports **`booksnap.catalog` and nothing else** from the
  core. That direction is legal (only `booksnap → app` is banned) and it is
  used on purpose: the product's search keys come from the *same*
  `normalize()` the matcher uses, because two normalizers drift. Importing
  the pipeline or the OCR modules there would put cv2/tesseract behind a
  "milliseconds, no I/O" rule test, so it is blocked;
- every `/api/v1` route resolves its library through the single function
  `app/api/deps.py:current_library`, and every API route is under `/api/v1`.
  Both are meta-tests over *all* routes, so they keep holding as routes are
  added;
- no module-level mutable state in `app/` (the tuning server's global job dict
  is exactly what a second tenant breaks).

**The API contract is committed and generated, both halves.**
`app/api/dto.py` → `app/api/openapi.json` → `app/web/src/api/schema.d.ts`.
After any DTO or route change run `python tools/api_contract.py --write` and
commit both artefacts; `--check` fails the commit on drift. This is why a
renamed field is a client *compile* error instead of a runtime surprise.

## How the pipeline works (the parts that took iteration)

**Segmentation** (`segment.py`): detect horizontal shelf lines to split into
bands; within each band, trim empty space, then find spine boundaries by
combining three column signals — long vertical edges, colour change, shadow
creases — with `scipy.find_peaks` (prominence-gated). Tuned to slightly
over-segment rather than merge (a split spine still matches; a merged one loses
a book).

**OCR** (`ocr.py`): per spine crop, for BOTH 90° rotations:
  (a) line-based reads — detect text lines, crop tight, normalise height
      (48/80px), binarise (CLAHE + Sauvola, polarity detection), OCR each line
      with PSM 7 using both `heb` and `script/Hebrew` best models;
  (b) a whole-strip PSM 6 read as a COMPLEMENTARY candidate.
Every read is a candidate; the matcher picks the best. The rotation with higher
total confidence wins.
  IMPORTANT: keeping BOTH (a) and (b) matters. A refactor once dropped the
  strip pass and regressed AUTO matches badly (11 -> 4 on one shelf), because
  line-detection fragments decorative-font titles. Don't remove it.

**Matching** (`match.py`): normalise Hebrew (strip nikud/punct, fold final
letters so OCR final/medial confusion is harmless; geresh/gershayim are
DELETED in-word, not space-split — splitting shredded הצ'ופצ'יק into junk
tokens and cost the true book its match on run 16), then per catalog entry
count token-level fuzzy hits on title and author separately, with EVIDENCE
GATES:
  - EXISTENCE needs >=2 matched *title* content tokens, or one distinctive
    (>=5-char) title token. Author hits DO NOT count toward existence. They
    used to (`evidence = mt + ma`), and that was a real bug: one noise token
    (`היה` scores 86 vs `החיה`) plus a series author invented a title on two
    different spines. Author agreement may raise the tier, never create the match;
  - short catalog tokens (<=4 chars) need ratio >=90 instead of 78 — a
    one-letter difference on a 3-4 char Hebrew word is far too cheap;
  - whole-title similarity must clear `min_title_sim` (47). This is a GATE,
    not just a ranking term. Swept on the 26-spine Durrell shelf: confirmed-
    wrong matches sit at <=37, a correct match on badly-degraded OCR at 50.8,
    so 45-50 separates them. RE-MEASURE when the catalog changes;
  - AUTO requires real *title* evidence — author agreement alone is NEVER
    enough (this is what stopped every book in a series collapsing onto one
    title; the fantasy shelf has many same-author siblings);
  - a whole-title similarity term disambiguates siblings (מלכי הכופרים vs
    ספינות מן המערב, same author);
  - run-16 additions: a claim hanging on ONE matched title word that explains
    <=half its read with no author signal is REJECTED (subset pathology —
    שפירא/הקומקום/סטארט); author-name-in-title tokens are not existence
    evidence; a read token that is a prefix of a longer catalog token counts
    (סטארט->סטארטאפיסט); score-tied volume siblings the read can't separate
    cap at REVIEW; fragment suppression arbitrates by qcov (how much of its
    OWN read a claim explains), because scores across different entries are
    incomparable;
  - dedup: the same catalog entry can't be AUTO on two spines of one shelf.
    A rival scoring below `dup_drop_frac` (0.70) of the winner is DROPPED, not
    just demoted — the winner already explains that title, so a far-weaker
    claim is a mis-assignment, and unmatched (-> fallback) beats a wrong title.

`match.explain()` ranks every candidate and keeps the REJECTED ones with the
gate that refused them; `GET /api/runs/{id}/explain/{spine_id}` and the UI's
"why?" button expose it. It recomputes with CURRENT code/config, not the run's
snapshot — deliberately, so you can ask "would my change have fixed this
spine?" — and the UI says so.

Beware the failure mode these gates address: on this stand-in catalog most
mismatches are books that are simply ABSENT from the catalog, so the matcher
had no right answer and picked a neighbour. The gates make it say "I don't
know" instead. A real (NLI) catalog fixes the other half — retrieval.
Output tiers: AUTO (auto-accept), REVIEW (one-tap human confirm), unmatched
(-> fallback). For cataloguing, correct-book-identification matters more than
tier; REVIEW items are correct assignments needing a confirm, not errors.

## Honest state / measured results

On the 4 sample photos (90 detected spines), against a 57-entry hand-typed
stand-in catalog: 26 AUTO + 21 REVIEW = 47 matched, nearly all naming the right
book. Tesseract-only deterministic ceiling is ~76% title-correct. The residue
is two groups:
  - real books absent from the stand-in catalog (become matches with real NLI);
  - genuinely hard OCR: stylised display typography (e.g. משחקי הכס, yellow
    Kearney lettering) that NO Tesseract config reads — the fallback's job.
The honest hard core needing a stronger engine is ~15%.

Correcting an earlier overstatement: "bigger catalog = better" is NOT the
reason NLI helps. A bigger flat list also adds noise (more chances for garbled
OCR to hit the wrong book). The real reason NLI helps is that it's a SEARCH
ENGINE, not a flat list: OCR text -> NLI returns 5-15 real candidates -> our
matcher ranks them. It does the retrieval; we do the scoring.

## Run history (the tune-and-measure foundation)

`uvicorn booksnap.server:app --port 8756` serves the UI. Every execution is a
**run** that is archived, never overwritten, because the project is in a
tune-and-measure loop and "run 3 was better" is meaningless without the inputs
that produced it. Each run stores:

  - `run_no` — the human handle (talk about "run 3" / label it "v3: wider gates");
  - `code_version` — git sha + **dirty flag** (while tuning, the interesting
    changes are usually uncommitted, so a sha alone would alias two runs);
  - `config` — a full snapshot of every tunable in `config.py`. THIS IS THE
    EXPERIMENT VARIABLE. Comparing runs without it is guesswork;
  - `catalog` — path + entry count (swapping catalogs changes everything);
  - per-image `spines_detected` vs `spines_processed`, duration, and summary;
  - per-spine `ms`, OCR `score`, winning `rotation` — the data needed for the
    variant-pruning/speed work in "next steps".

Layout: `work/store.json` is a small index; full per-spine records live in
`work/runs/<run_id>/<image_id>.json`, and crops in `work/runs/<run_id>/crops/`.
Crops are **per run on purpose** — segmentation changes between runs, so a
shared crops dir would silently corrupt the evidence an older run points at.

Runs are stoppable: `POST /api/stop` sets an event that `Pipeline.run` polls
between spines (cooperative, not a kill). The spines already read are matched
and saved, so a stopped run is a real partial result set — that's the fast way
to iterate without paying 4.5 min for a full shelf.

`Pipeline.run` grew `progress=` and `should_stop=` callbacks and a `crops_dir`
init arg for this; all optional, so the CLI path is unchanged.

## Measuring accuracy (do this before believing any change)

`ground_truth.json` holds the owner's hand-labelled shelves (8 as of
2026-08-06). **GT coverage is CURATED, not automatic** (owner decision): a
processed shelf joins the fixture only when the owner chooses to label it —
do not treat unlabelled shelves (e.g. run 16's IMG_8135-8138) as a backlog
or nag about them. Shelves without GT simply don't take part in sweeps.
`booksnap/scoring.py` reports precision/recall over the
DISTINCT set of books a run claims; `GET /api/runs/{id}/score` and
`tools/rescore.py` expose it. **Precision is the expensive metric here** — a
missing book is noticed, a phantom one silently rots in the catalog.

**`tools/sweep.py` is the standard rule-tuning harness** (built 2026-08-06):
it replays every GT shelf's STORED LLM reads + STORED candidates recording
through the current match pipeline (the same post-match path as
`Pipeline.run_page`, including fragment suppression and truncation demotion),
scores each shelf, and appends the result to `work/experiments.jsonl`
(full detail incl. config snapshot + phantom/missed lists in
`work/experiments/<id>.json`). So a rules/threshold change is measured across
the whole labelled collection in seconds, offline, without one Sonnet or
catalog call. Rules of use:
  - default replay mode is only valid for MATCHING changes. If the sweep
    prints "N unrecorded queries", the change altered retrieval — re-measure
    with `--live` (real sources, per-query disk caches, so repeats are ~free);
  - `--live --sources simania,nli,...` selects which sources take part
    (testing a new source = add it here first, promote to `_build_catalog`'s
    baseline only after a measured win). Each live sweep records its
    retrieval per shelf; `--replay-exp <id>` replays that snapshot, giving a
    fixed retrieval context to compare rule variants against;
  - the confirmed library is NEVER in a sweep catalog — owner decision: it is
    an *outcome* of runs, not a source (revisit if the system ever has many
    users). Caveat: recordings from runs 13+ were captured with the library
    head in the chain, so its influence is frozen inside those recordings;
  - baseline row 20260806-142543 (run-16 fixes): AUTO mean P 0.94 R 0.78
    F1 0.85, A+R P 0.94 R 0.83 F1 0.88 over 8 shelves. `--list` shows history.

**`tools/spotcheck.py` complements the sweep for shelves WITHOUT full GT**:
owner review feedback on a run (wrong books, missing books, must-stay-REVIEW)
is encoded in `fixtures/spotchecks/<name>.json` as forbid/want/not_auto
expectations and replayed offline against that run's own candidates
recording. A rule change must pass BOTH `sweep --check` and the spotchecks
(`python tools/spotcheck.py run16`); the pre-commit hook enforces both
(spotchecks self-skip on machines without the run data). This is how one-off
feedback becomes a permanent measurement.

**The sweep is ENFORCED, not advisory** (owner request, 2026-08-06): a git
pre-commit hook (`tools/githooks/pre-commit`, installed via
`git config core.hooksPath tools/githooks` — already set on this machine,
one-time per clone) runs `sweep.py --check` whenever accuracy-relevant files
are staged (match/config/pipeline/catalog/scoring/replay/types/the catalog
adapters/ground_truth). The check compares mean AUTO P, AUTO F1 and A+R F1
against the COMMITTED baseline `tools/sweep_baseline.json` (tolerance 0.01)
and BLOCKS the commit on regression. Per-shelf F1 moves are printed but never
block — accepted changes routinely trade a point on one shelf for gains
elsewhere (see run 13). An intended trade-off is accepted explicitly:
`python tools/sweep.py --accept-baseline --note "why"`, then commit the
updated baseline file. Rehearsed end-to-end: min_title_sim 47→95 was blocked
(mean AUTO F1 0.815→0.754); NOTE that a change which only LOOSENS a gate can
sweep identical (other gates absorb it) — the hook proves non-regression,
not that a change did anything. server.py changes only get a printed
reminder: `_build_catalog`'s retrieval chain is invisible to the offline
replay and needs a manual `--live` judgment.

The sweep's inputs are COMMITTED in `fixtures/sweep/` (~1MB JSON: each GT
shelf's reads + candidates recording + provenance manifest, written by
`sweep.py --export`): a fresh clone with no `work/` runs the gate and
reproduces the baseline exactly (verified with an empty BOOKSNAP_WORK).
`--accept-baseline` re-exports automatically so the committed inputs and the
committed numbers can't drift apart; `find_fixtures` prefers local `work/`
data and falls back to the export. If neither exists the check skips rather
than blocks.

Two hard-won rules:

1. **Never trust an idea that wasn't measured on the fixture.** Three plausible
   ideas were implemented and MEASURED WORSE or neutral:
   - *Hungarian set-to-set assignment* (the literature's approach): precision
     0.62 -> 0.56. Against an OPEN 9M-record catalog the one-to-one constraint
     just makes a losing spine take its second-best (wrong) entry instead of
     being dropped. It works in papers because their catalog is a closed 15k
     collection. Off by default (`use_assignment`).
   - *Hebrew prefix-stripping in the matcher*: no gain, precision 0.62 -> 0.50
     on IMG_7849. The per-token fuzz threshold already absorbs a one-letter
     prefix; stripping only widens what can match. Off (`strip_prefixes`).
     The SAME transform is REQUIRED in scoring.py, where whole-title
     token_set_ratio is strict enough that edition spellings
     (הנבונים/נבונים) scored 71 and were counted as both phantom and miss.
   - *Volume/publisher stoplist*: neutral on the spine path so far.
2. **Fixing the scorer changed conclusions more than fixing the code.** Adding
   prefix-tolerance to scoring lifted run #3 from F1 0.44 to 0.56 with no code
   change at all. A bad ruler invents work.

What DID help: **geometric merging of overlapping page blocks**
(`pagereader.merge_overlapping`). Books are solid objects, so two texts sharing
a region are one spine — Vision emits author, title and imprint as separate
paragraphs, which is how a 14-book shelf reported 24 books. Measured: IMG_6082
AUTO precision 0.85 -> 0.92, IMG_7849 auto+review F1 0.47 -> 0.51 (but AUTO
recall 0.50 -> 0.43, so not free).

**Reproducibility**: NLI is a live search engine, so replaying an old run gave
different results (#7 stored 9 correct, replayed 5) and no comparison against
history was trustworthy. Runs now record every catalog lookup
(`replay.RecordingCatalog` -> `work/runs/<id>/candidates/<image>.json`);
`ReplayCatalog` serves exactly that back, and counts queries the recording
never saw — a miss means the code under test changed *retrieval*, so its gain
cannot be credited to matching.

What ALSO helped (both free, no model, no download):

- **Character n-gram cosine gate** (`match.ngram_sim`, `min_ngram_sim=50`).
  `token_set_ratio` has a pathology: a SHORT candidate title that is a subset
  of the OCR text scores a perfect 100, which is how the one-word "ציפורי"
  (Sepphoris) beat the real book. N-gram cosine penalises length mismatch (51
  there) while still scoring edition variants highly (הנבונים/נבונים = 73).
  Lifted run #5 auto+review from P 0.65/R 0.62 to P 0.88/R 0.67.
  NOTE: it does NOT fix the ציפורי spine itself (51 > 50 threshold); 55 would,
  but swept worse overall. The test asserts this honestly.
- **Embedded-token matching** (`embedded_token_len=5`). OCR fuses adjacent
  words on a spine — whole-page Vision read "ג'ראלד דארלציפור הלעג", gluing
  author to title, so ציפור matched nothing. A long catalog token found inside
  a longer OCR token now counts as present. Run #5 recall 0.67 -> 0.71 at
  unchanged precision.

**Before assuming a miss is a detection problem, check whether the text was
read.** Diagnostic: compare each missed title against every OCR string on the
photo with ngram_sim. Measured split — IMG_6082/fullpage: 3 of 7 misses were
READ but unmatched; IMG_7849/spines: 6 of 9 genuinely NOT read. So "detection
is the wall" is true for the stylised fantasy shelf and FALSE for the Durrell
shelf. The two modes also fail on DIFFERENT books (fullpage gets משחקי הכס,
spines gets המסע של הוקווד), so unioning modes is unexplored recall.

Current best (both replayed through identical retrieval):
IMG_6082 spines+NLI AUTO P 0.86 R 0.57 F1 0.69 | fullpage AUTO P 0.92 R 0.52.
IMG_7849 spines AUTO P 1.00 R 0.36-0.50. Recall is now the wall, and the
remaining misses (משחקי הכס, The elephant, פגישות עם בעלי חיים - a very thin
spine) are DETECTION/OCR failures, not matching failures.

## External integrations

**NLI catalog** (`nli_catalog.py`) — National Library of Israel Open Library
search API. VERIFIED live: endpoint
`https://api.nli.org.il/openlibrary/search?api_key={KEY}&query=...`, field-
scoped boolean query grammar (title/creator, contains/exact, AND/OR), JSON
output. Key required — sign up free at https://api2.nli.org.il/signup/ .
Reads key from env `NLI_API_KEY`. HTTP transport is injected (stdlib urllib
default) so it's testable offline. Caches responses on disk by query.
  CORRECTION (verified live Aug 2026, this repo previously claimed otherwise):
  there is NO usable "guest" key — `api_key=guest` returns 403
  `{"error":{"code":"API_KEY_INVALID"}}`. Also, api.nli.org.il is behind
  Cloudflare and 403s the stdlib default User-Agent before reaching the API;
  `_default_transport` now sends a browser UA. With that, the endpoint answers
  normally, so the transport path is confirmed working — only a real key is
  missing.
  ⚠️ ONE THING TO VERIFY AGAINST LIVE DATA: NLI's exact JSON field names vary
  by record. `_parse()` probes common title/creator keys defensively, but on
  the FIRST real call, dump one raw response and confirm/adjust the field
  mapping. This is the single spot most likely to need a tweak. It could not be
  verified during prototyping (no API access in that sandbox).

## Two processing modes (`mode=` on `Pipeline.run` / `POST /api/run`)

`spines` (default) — the classical path: segment -> per-spine Tesseract ->
match. Free, offline, ~10s/spine.

`fullpage` — ONE Google Vision call for the whole photo; each returned
paragraph becomes a record, and its bounding box is cropped back out of the
original so the review UI still shows a picture per title. Needs
`BOOKSNAP_FALLBACK=google_vision`.

MEASURED head-to-head on IMG_6082, same image, same NLI catalog (runs #3 vs #5):

| | spines | fullpage |
|---|---|---|
| AUTO | 8 | **13** |
| unmatched | 13 | **7** |
| unique titles | 11 | **20** |
| duration | 430s | **~8-20s** |
| billable Vision units | 13 (fallback) | **1** |

fullpage found books the spine path never could (היער השיכור, פגישות עם בעלי
חיים, את כולם ברא) because a 190px-wide vertical strip destroys the page
layout context the engine uses. It is also ~26x cheaper. Do NOT assume spines
mode is the "cheap" one for a Vision-enabled setup — per-spine fallback bills
per spine.
Caveats: fullpage also surfaces publisher/imprint text as false books
(`ספרית פועלים` -> `ספרית א`), and title->physical-spine association is looser.

**MEASURED, Aug 2026 — Google Vision is NOT uniformly better than Tesseract.**
Ran live `document_text_detection` on all 13 unmatched spines of IMG_6082 and
compared against the stored Tesseract text:
  - clear WINS where Tesseract produced pure noise: b0_s02 -> `היער השיכור`
    (real Durrell title, matched AUTO via NLI), b0_s18 -> `...הריוט ... את כולם ברא`,
    b0_s22 -> `הריוט ... הדברים מבהיקים`, b0_s01 -> `The Elephant` (English book);
  - a LOSS on b0_s08: Tesseract read `הפיקמק ומהוממות אחרות` (close to the true
    `הפיקניק ומהומות אחרות`); Vision read `ןכהןכנות אחרות` — worse;
  - ~6 of 13 returned empty/near-empty from BOTH engines. That is a useful
    signal: those crops are almost certainly SEGMENTATION ARTIFACTS (over-split
    fragments), not missed books. Don't count them in the denominator when
    judging capture rate.
So Vision belongs exactly where it is — a per-spine fallback — not as a
replacement engine. Enable with `BOOKSNAP_FALLBACK=google_vision`.

**Fallbacks** (`fallback.py`):
  - GoogleVisionFallback — Cloud Vision DOCUMENT_TEXT_DETECTION, deterministic,
    excellent Hebrew, ~$1.50/1000 imgs (first 1000/mo free). Returns raw text
    -> fed back through match_candidate(). Client injected; reads Google creds
    from env GOOGLE_APPLICATION_CREDENTIALS. booksnap never touches the secret.
  - ClaudeVisionFallback — returns structured {title, author} directly; you
    supply a `send` callable wrapping the Anthropic client + strict-JSON prompt.
  Only spines that fail deterministic OCR are ever sent (respects the
  philosophy). NullFallback is the default (fully offline).

## Credential hygiene (important)

Never hard-code or commit keys. They live in env vars / a .env file (gitignored)
on the machine running the code. The NLI and Google adapters already read from
the environment. `.gitignore` excludes .env, *-key.json, credentials.json, etc.

## Setup

`./setup.sh` installs Tesseract + Hebrew models (tessdata_best `heb` and
`script/Hebrew`, tessdata_fast `heb`) + Python deps. Models are gitignored
(fetched, not source). Env overrides: BOOKSNAP_TESSDATA_BEST,
BOOKSNAP_TESSDATA_FAST, BOOKSNAP_WORK.

The product client is a separate, optional install — nothing in the
recognition core or the tuning server needs it:
`npm install --prefix app/web`. Skipping it only means the client half of the
commit gate self-skips.

**Node 24 LTS (>=24.15.0)** — declared in `app/web/package.json` `engines`, so
npm says so rather than it being tribal knowledge. Node 22 is maintenance-only
now; the floor is the active LTS line. Installed here from the official MSI
(`winget install OpenJS.NodeJS.LTS`), not a version manager.

## Tests

**`python tests/run_all.py`** runs everything and **exits non-zero on
failure** — the individual `test_*.py` `__main__` blocks print PASS/FAIL and
then exit 0, which is fine for a human and useless as a gate. Pass module
names to run a subset (`python tests/run_all.py test_api`).

| module | count | what it protects |
|---|---|---|
| `test_core.py` | 52 | matcher / normalize / evidence gates |
| `test_integrations.py` | 24 | catalog + fallback adapters, fully mocked/offline |
| `test_domain.py` | 105 | the VISION rules that can be silently reversed |
| `test_store_contract.py` | 171 | one store spec × every implementation + isolation |
| `test_reconcile_apply.py` | 20 | `app.reconcile_apply` writing a `Diff` through real stores |
| `test_legacy_import.py` | 21 | `work/*.json` → entities, against a committed fixture |
| `test_search.py` | 15 | Hebrew search, against 24 real queries on the real 251 books |
| `test_layering.py` | 9 | the one-way import rules (plan H1) |
| `test_api.py` | 88 | `/api/v1` shapes + the versioning/tenancy meta-tests |

505 python tests as of P2.8 (+25 since P2.7: the diff-summary snapshot and
the not-seen-streak/staleness rules — `app.domain.history` (new module),
`DiffSummary`/`summarize`/`with_diff_summary` in `read.py`/`reconcile.py`,
schema **v11** — and the two new endpoints, `GET /shelves/{id}/overview` and
`GET /shelves/{id}/books`, in `test_domain.py`/`test_store_contract.py`/
`test_api.py`; see "Shelf view + read history (P2.8)"). No pytest
dependency, deliberately — the repo has never had one and the accuracy gate
runs on bare python. Counts grow with each run's fixes; the commit log is
the history (`SESSION_NOTES.md` was a one-time handoff and is gone —
session scratch belongs in `notes/`, which is gitignored).

**`test_domain.py` is not coverage** — it is one test per sentence of VISION
that someone could plausibly "fix" later, and every one was verified to FAIL
when its rule is reversed (mutation-checked, not assumed). Two of them are
structural rather than behavioural, which is the more valuable kind here:
`Copy()` may be constructed only in `new_book`/`add_copy` (an AST walk — P2.5's
`relink_copy` does not construct one, so it needed no exemption), and
`normalize()` may not be re-implemented in `app/domain`. Add rules there, not
assertions about dataclass plumbing.

**`test_store_contract.py` is ONE spec run against EVERY implementation** —
now four aggregates (`BookStore`, `ShelfStore`, `ReadStore`, `DecisionStore` as
of P2.5) × (`Memory*`, `Sqlite*`). Adding an adapter (Postgres) means adding
one line per aggregate's `IMPLEMENTATIONS` tuple; that is what makes D1's
datastore choice a swap rather than a leap. It carries the
**tenant-isolation** suite too, already running against two library refs even
though the app resolves one until pillar 3 — §4.2's "a foreign record reads as
ABSENT" is a store property, and no route can answer 404-not-403 unless it
holds here. Mutation-checked: eight planted bugs (dropped library scope in
get/delete/list, `foreign_keys` left at SQLite's OFF default, the unique index
removed, missing wrong-library check, missing sort tiebreaker) each fail named
cases, and each only in the adapter that was broken.

⚠ A paging test that inserts in id order and checks for duplicates passes with
NO tiebreaker at all — Python's sort is stable and dicts keep insertion order.
The committed test inserts in DESCENDING id order for exactly that reason.
Found by mutation testing, not by review.

## The Books UI (P1.6)

Built against the real API; `planning/mockup/` was the design reference, and
per plan D4 the Books/book parts of the mock are deleted now that this is at
parity — two live implementations of one screen drift invisibly.

**State is hand-rolled, not TanStack Query.** One paginated list query, one
record map, three mutations: a query library would mostly be API surface here.
The one thing it would have given us free is the request-id guard in
`lib/books.tsx` — a response whose query has been superseded is DROPPED, or a
slow first page lands after a search and repaints books the user already
filtered away. That guard is tested, and the test fails without it. Revisit
when a second screen needs its own cache.

Rules that are load-bearing and easy to "simplify" later:

- **mixed-script alignment (UI_PLAN §7.2).** `unicode-bidi: plaintext` for
  glyph order, `text-align` keyed on the CONTAINER's `dir` for the edge.
  Direction per string, alignment per container — that is what lets `Sapiens`
  and `משחקי הכס` share one clean edge instead of two ragged ones. Every
  user-generated string carries `.rtl-safe`, and a test asserts the class is
  actually on them, because a missing one is invisible until someone looks at
  a mixed-script list;
- **the drawer is not a route.** It overlays an untouched list, so a URL would
  make Back close it rather than leave the tab. ⤢ promotes it to
  `#/book/<id>`, and promoting CLEARS the drawer — otherwise Back lands on the
  list with the drawer still over it;
- **the drawer mirrors via a custom property** (`--slide`), not a duplicated
  transform. Verified live: `x 501..961` in LTR, `0..460` in RTL — both the
  inline-end;
- **absent, not disabled.** Shelf/wishlist/duplicates filters, the spine crop,
  location, Mine, and "where it was seen" all need P2.1/P2.4/P2.5/P3.5/P6. A
  greyed-out control that never becomes clickable reads as a bug; absence
  reads as a product that has not grown that far. Copies/lending/lent-out
  graduated out of this list at P1.7 — see below.

- **the sort control carries its own direction.** The select names the KEY,
  a toggle overlaid at the box's inline-start edge names the DIRECTION —
  one control, one question, and it mirrors with the language. Changing the
  key RESETS the direction to that key's natural one (`naturalAscending`):
  carrying A-Z's "ascending" onto a date key silently answers a question
  nobody asked (recently added, oldest first). The API already took
  `ascending`; only the client hard-coded it.

Traps found while verifying in the browser, all worth knowing:

⚠ **A span is not a div — and CSS ported from the mock will not say so.**
Three of the mock's rules stopped applying when its `<div>`s became `<span>`s
inside a `<button>`: the feed's title/author rendered glued on ONE line, and
`text-align` is a no-op on an inline box, so §7.2's per-container alignment
was silently OFF for the entire feed. The book hero was worse — `.bhero` is a
flex ROW (it seats a cover image), and the head lost the mock's
`flex:1;min-width:0` wrapper, so title, author, badge and buttons splayed
side by side. Both were invisible in the test ring: jsdom computes no
cascade, so only a browser catches them.

⚠ **A later rule at equal specificity wins.** `.dangerzone .btn { color:
var(--danger) }` sits after `.btn.danger` in the same file, so the filled
delete button got red text on its red background and rendered as a blank red
rectangle. It needs `:not(.danger)`.

⚠ **Chrome pins the native `<select>` chevron** a fixed distance from the
border and ignores `padding-inline-end`. The only way to control the gap is
`appearance: none` plus a chevron of our own — drawn from two borders on
`.sortwrap::after` rather than a background-image data URI, because a drawn
one can read `var(--muted)` and so follows dark mode.


⚠ **FastAPI silently ignores unknown query params.** A `product-api` started
before P1.5 answered `?q=…` with the whole 251-book library and a 200. The
client looked broken; the server was stale. **Restart the API server after any
route change** — there is no `--reload` in `.claude/launch.json`.

⚠ **Port 8757 serves a BUILD, and the build is gitignored — so it goes stale
silently.** `app/main.py` mounts `app/web/dist/` at `/`, and nothing rebuilds
it. After P2.7 shipped the Capture tab, `:8757` still served a bundle from
before the tab existed: the nav had one button, and `grep capture_tab
dist/assets/*.js` returned nothing. The reason it is worse than the stale-server
trap above is that **the API was completely current** — all 28 routes present —
so the UI looked like the bug. Diagnose it by grepping the built bundle for a
string only the new code has, not by reading the source.

  - dev loop: `npm --prefix app/web run dev` (`:5173`, serves from source and
    proxies `/api` to `:8757`). This is the one to use while building;
  - `:8757` directly: `npm --prefix app/web run build` after every client
    change, or you are looking at history.

⚠ **CSS transitions freeze at t=0 when the Browser pane is not displayed.**
No frames composited means no animation progress, so `getComputedStyle`
returns the transition's START value and the element looks mis-positioned.
`el.getAnimations().forEach(a => a.finish())` before measuring, or the reading
is a lie. Cost half an hour of chasing a drawer bug that did not exist.

## Copies & lending (P1.7)

The last Pillar 1 item: "I have another copy", per-copy label/tags/condition,
lend/mark-returned, and "who has my books" (VISION §5.2). Domain ops added to
`app/domain/book.py`: `lend`/`return_copy` (a copy is out or it isn't —
lending an already-out copy raises `CopyAlreadyLentOut` naming the current
borrower, rather than silently overwriting who has it; returning a copy that
isn't out raises `CopyNotLentOut`) and `edit_copy` (label/tags/condition —
object-level metadata, so unlike `edit()` it must NOT touch status; a person
noting "torn cover" has not vouched for the book's identity). `add_copy`
gained a `fields:` param so the API can create a copy with its metadata in
one domain call instead of two.

Store-side: `list(..., lent_out: bool | None)` — a book qualifies if AT LEAST
ONE copy is currently out. SQLite gained schema **v4**: a materialized
`copies.lent_out` column rather than filtering the `lending` JSON blob at
query time (SQLite's json1 extension isn't guaranteed present, and even where
it is, deriving `is_out` on every row of every query is exactly the cost
`search_text`/`sort_author` were added to avoid). v4 is pure SQL, unlike v3 —
every row at v3 predates lending, so `DEFAULT 0` is already correct for all of
them; there is nothing to backfill.

API: `POST/PATCH .../copies[/{id}]`, `POST .../copies/{id}/lend`, `POST
.../copies/{id}/return`. Every one returns the whole `BookDTO`, never a bare
`CopyDTO` — same reasoning as `patch_book`: the client replaces one record by
id, and a partial response would force it to reassemble the book itself,
which is exactly the logic H3 keeps out of the client. `lend_at`/`returned_at`
are server time (the injected `Clock`), never client-supplied, same as
`added_at`.

Client: the sort control's "own its result" pattern repeats here — the
lending badge is drawn in BOTH the feed row and the drawer hero (VISION §5.2:
"visible in list and detail", not detail alone), via one shared `CopyBadges`
component so the two cannot drift. The copy's lend/edit forms replace the
read view in place (the same idiom as the title/author edit), not a modal —
lending a copy should cost no more UI than editing one. Tag parsing
(comma-split, trim, drop blanks) happens in the CLIENT — the server takes an
array — and is mutation-checked: the first version of the test only asserted
the form closed, which passed even with unparsed tags, because the UI had no
read-view display of a copy's metadata to check against. Fixed by adding one
(`.kv` row, `t.copy_details`) — a lesson on its own: **a test that never reads
back what it wrote isn't testing the parsing, only that the request didn't
crash.**

⚠ **The generic `t.edit` label collides with a copy-level edit button on the
same screen.** Screen readers announce both as "Edit" with nothing to tell
them apart, and `getByRole('button', {name: 'עריכה'})` in the existing edit
tests started matching two elements the moment the copies section shipped.
Fixed with a distinct string (`t.copy_edit`, "Edit copy details") — any new
per-copy action button needs its own label for the same reason, not a reuse
of a book-level one.

⚠ **Verifying this one mutated the real `work/product.db`.** Live browser
testing (lend, return, add copy) went through the real dev API against the
real file, same as any other live verification here — but unlike a read-only
check, these are writes. Restored from a `cp work/product.db` snapshot taken
before the live pass; **take that snapshot BEFORE driving mutations through
the browser against `work/product.db`**, not after.

## Shelf identity & depth (P2.1) — the first Pillar 2 item

`Shelf{id, label, depth_count, virtual}` and `Capture{shelf, depth, order}`,
plus `Copy` located at `(shelf, depth)`. Domain + ports + adapters + tests
only; the `/api/v1/shelves` routes land with P2.2, where the intake UI
consumes them.

**There is deliberately no place, bookcase, col or level.** Plan §1.1 splits
shelf IDENTITY (pillar 2 — an id, an optional label, a declared depth) from
shelf ADDRESS (pillar 6 — the map, the geometry, the "where is it" highlight).
`test_a_shelf_carries_no_address_only_identity` asserts the absence
structurally, because the tempting mistake is to add `bookcase` here "while
we're at it" and end up with two modules owning an address.

**The label is OPTIONAL** — owner's call, 2026-08-07, settling plan §1.1's
`[OPEN]` and reversing the earlier reading that made the label the interim
location and therefore mandatory. *Identity is free*: a shelf must exist and be
re-findable, not be described. An unnamed shelf is shown by the image it came
from — the owner recognises a photo of their own bookshelf without a caption —
and any location information stays optional, with the real binding waiting for
pillar 6. The rule this protects is that **capture never becomes a two-step
action**: demanding a label before the first photo can be filed buys an interim
answer to "where is it?" that pillar 6 replaces anyway.

⚠ **"One image = one shelf" is a PLACEHOLDER, and a shelf id is not a
permanent handle on a piece of wood.** Without the map there is nothing to bind
several photos of one physical shelf together, so intake gives each image its
own shelf identity. Pillar 6 provides the exit: the owner merges several shelf
identities into one physical shelf, by hand on the map, where you can *see*
that two of them are the same shelf (plan P6.1b). Until then, the rule this
puts on everything in pillars 2–5 is:

> nothing may treat a shelf id as a permanent, one-to-one handle on a physical
> shelf — it is one *identity*, and identities merge.

So: `Copy.shelf_id` is a pointer a merge repoints, which is fine as long as
nothing derives from it in a way a repoint cannot reach. `Provenance.shelf_id`
is HISTORY and must not be rewritten — a sighting happened against the shelf
that existed then — so a merge leaves an **alias** from the retired identity to
the surviving one rather than mass-updating. Same shape as P7.1's alias table
for shared book identity, and the same reasoning: retrofitting identity onto
records that assumed it was permanent is the expensive version. And **no
automatic merging** — two photos overlapping is not evidence they are one
shelf (the same books can sit on two), which is the ambiguity §5.4 already
refuses to guess at.

Consequence worth knowing: with labels optional, most early shelves share the
empty one, so "sorted by label" would be a block of visually identical rows in
*id* order — arbitrary to whoever is reading it. `Shelf.sort_key` is
`(label, created_at, id)`: named shelves first and alphabetically, then unnamed
ones oldest-first, which at least matches the order they were photographed in.
The rule lives in the domain and both adapters mirror it, same split as
search's parse/score — an adapter that invents its own order is caught by the
contract suite.

⚠ **Never call depth "row" or "band" in code** (VISION §5.7's named collision):
`segment.py` already uses *band* for the horizontal rows found *within one
photo*, and `Spine.band` is in the stored record format. That is a vertical
concept; this one is front-to-back. A test walks `app/domain/shelf.py`'s AST
and fails on either identifier — prose may say "row" (the UI string is *"add a
row behind this one"*); the ban is on what code calls it.

Rules that are load-bearing and each mutation-checked:

- **a location is `(shelf, depth)` together, never shelf alone.** §5.7 #3 puts
  "a different row of the same shelf" in the ASK column of §5.4's firing
  table. Matching on shelf alone would answer it silently *and answer it
  "already listed"* — relinking a copy that never moved onto the row behind it
  and losing the second copy that is genuinely there. `_resolve_copy` compares
  `Copy.location` to `Provenance.location`, both `(shelf_id, depth)` tuples;
- **the front row is depth 1, always.** A located copy with `depth=None` and
  one at `depth=1` are the same physical place but compare as two, which fires
  §5.4's prompt on a book that never moved. `_normalize_location` fills it in
  at construction;
- **a depth with no shelf raises, it is not dropped.** It names a row of
  nothing, and it is always a wiring bug — most likely clearing `shelf_id`
  and forgetting `depth`. A silent drop would make *remove from shelf* look
  correct while leaking the old row into the next place the copy stands. So
  `remove_from_shelf` and `observe` move both halves together;
- **depth is declared, never detected** (§5.7). `new_capture` takes the whole
  `Shelf` — not a `shelf_id` — precisely so the depth can be checked against
  what the owner declared. A capture is the one place an undeclared depth can
  enter the system;
- **the wishlist is `Shelf{virtual: true}`, and it does not count.** The store
  listings default to `include_virtual=False`: a *forgotten* filter would
  inflate both the shelf list and the apparent size of a library of books the
  owner does not own yet, and it would do it silently. The caller that wants
  it says so;
- **deleting a shelf is refused when it has captures** (`ShelfNotEmpty`), not
  cascaded. Its captures are the record a re-read diffs against (§5.6), and a
  cascade would destroy them on a misclick. Deletion is for the shelf typed by
  mistake.

⚠ **Two aggregates in one SQLite file means cascades must be checked, not
assumed.** `shelves` deliberately does NOT cascade into `copies` — deleting a
mistyped shelf must never delete the books that stood on it, which is the
destructive direction the whole §5.6 design refuses. The consequence is a
recorded gap, not an oversight: a deleted shelf leaves copies still naming it,
and clearing them is `remove_from_shelf` in the API layer where both stores
are in hand (P2.2). `test_deleting_a_shelf_never_touches_the_books_that_stood_on_it`
pins both halves.

⚠ **Importing `app.main` MIGRATES the owner's real database.** The composition
root opens `work/product.db` at import time, and `SqliteBookStore.__init__`
runs `migrate()`. `tools/api_contract.py` imports `app.main` to generate the
OpenAPI — so *running the contract check, or the pre-commit hook, advances the
real file's schema*. Found the hard way: `work/product.db` was already at v5
while v5 existed only on an unmerged branch. The consequence is that **"not
shipped yet" is never a reason to edit a migration step in place** — by the
time you check, it has usually run on the one database that matters. v6 is a
separate step for exactly this reason, and a test pins the v5→v6 upgrade path.

**Schema v5** adds `shelves`, `captures`, and `depth` on both `copies` and
`provenance`. Pure SQL and no backfill, like v4 and unlike v3: every row at v4
predates shelves entirely — the 251 imported books have `shelf_id IS NULL`, and
an unlocated copy has no depth, so NULL is already correct for all of them.
`captures` carries a unique index on `(shelf_id, depth, "order")` because §5.3
makes that triple a capture's identity; two in one slot would make a shelf's
book order ambiguous, and the ambiguity would surface much later as a
reconciliation diff that reorders itself between reads. **v6** rebuilds
`shelves_by_label` as `(library_id, virtual, label, created_at, id)` — the full
sort key, once labels became optional.

⚠ **A redundantly-enforced rule survives mutation testing without being
untested.** Two P2.1 mutations survived and both turned out to be a second
enforcement point, not a gap: `add_depth`'s virtual-shelf guard is unreachable
because `Shelf.__post_init__` rejects the same state, and the sqlite shelf
`ORDER BY label, id` tiebreaker is invisible because the covering index
`(library_id, virtual, label, id)` already yields id order. Removing the
*other* line of each pair IS caught. Worth knowing before reading a survivor
as a missing test — the question to ask is "what else enforces this?", and
only if nothing does is it a gap.

## Capture → shelf binding (P2.2, API half)

`/api/v1/shelves` (list/create/get/patch/delete, `POST .../depths`,
`GET .../captures`) and `/api/v1/captures` (create/get/patch/delete). The
client half — the intake UI that assigns shelf and depth inline — is still to
come.

**The binding is that `POST /captures` may omit `shelf_id`, and then a fresh
unnamed shelf is created for the photo.** That is not a convenience: a capture
with no shelf is a read with nothing to reconcile against (§5.6), so *"assign
it later"* is deliberately not a state the model offers, and *Unassigned* on
screen means *not yet named*. The rule lives in
`app/domain/shelf.py:capture_onto_a_new_shelf`, not in the router, so it is
testable in the domain ring and mutation-checked.

- **the response returns the capture AND its shelf** (`CaptureBinding`). When
  the shelf was auto-created the client has no other way to learn its id, and
  a second round trip to discover the thing you just implicitly made is the
  kind of gap that gets papered over with a client-side guess. Same reasoning
  as the copy routes returning the whole `BookDTO`;
- **`captures` has its own root, not `/shelves/{id}/captures/{id}`.** Binding
  MOVES a capture between shelves, and nesting would make "change the shelf" a
  change of the resource's own address;
- **`order` is computed, not supplied** — intake is "photograph it left to
  right", so a caller with its own opinion is two clients waiting to disagree.
  A capture moved to another shelf or row is appended there rather than
  inheriting a position that would collide;
- **"add a row behind" is its own endpoint**, not a settable `depth_count`, so
  a client cannot jump to 5 and leave three rows nobody photographed;
- an undeclared depth is **409 naming the declared depth**, never a silent
  clamp to 1: filing a photo at a row that does not exist would hand
  reconciliation a location with no counterpart in the room.

## Images are real (P2.3)

`BlobStore` port (`app/ports/blobs.py`) + `DiskBlobStore`, and
`/api/v1/images` — upload, metadata, `/full`, `/thumb`, delete.
`Capture.image_id` now holds a real key. Bytes live on disk with the key in a
row (D1); the product **never** reads the tuning server's `work/runs/`, and its
photos go under `work/product_blobs` (`BOOKSNAP_BLOBS`).

The layout is **already P3.5's**: `libraries/<library_id>/blobs/<ab>/<sha>.<ext>`.
Pillar 3 inherits retention, purge and orphan collection rather than a path
migration.

- **content-addressed.** The key IS the SHA-256 of the stored bytes, so
  re-uploading a photo after a browser refresh writes nothing and returns the
  same key (§12.3 #13) — the normal case with a camera roll, not an edge one.
  It also means a URL built from a key can be cached forever, since different
  bytes can never reuse one;
- **upload and binding are two calls.** `POST /images` then `POST /captures`.
  One multipart call that did both reads tidier and is worse in the flow that
  happens: twelve photos dropped at once, shelf and depth decided while looking
  at the thumbnails;
- **validation is decoding.** The filename and the declared content type are
  both the client's own claim; a store that believes them serves whatever was
  really uploaded back under an image content type;
- **variants are a cache, owned by the adapter.** `read(variant="thumb")`
  re-derives a missing rendition rather than reporting it absent — on screen
  "no thumbnail yet" and "this photo is gone" look identical and only one is a
  real problem. Rendering sits behind the port because `app/api/*` may not
  import `app/adapters/*`, and a first draft of the route did exactly that.

⚠ **EXIF orientation is applied at STORE time, not at display time.** Phone
photos carry a rotation flag; `cv2.imread` honours it, PIL does not unless
asked, and browsers honour it inconsistently. Left alone, the engine reads an
upright shelf while the review grid shows it on its side — and the person
reviewing reasonably concludes the reader is broken. Normalising once, up
front, is what makes the pixels the engine sees and the pixels on screen the
same. It also makes the hash agree: the same photo uploaded upright and
rotated is one key, not two. Bytes that need no correction are stored
**untouched** — a JPEG round-tripped through PIL loses quality for nothing, and
accuracy is measured on the pixels the engine is given.

⚠ **A variant carries its own extension, not the original's.** Every rendition
is a JPEG, so deriving the variant path from the key's extension writes JPEG
bytes into a `~thumb.png`, which is then served as `image/png` and renders as a
broken image. Found by a test, not by review.

⚠ **A blob key arrives in a URL, so it is validated, never joined.** `<64 hex>.<ext>`
or nothing — `../` in a path segment is how a store that just concatenates ends
up serving a private key file.

⚠ Deleting an image does **not** check whether a capture still points at it —
the stores cannot see each other's aggregates, and reference counting is
P3.5's. A capture whose image was deleted shows a missing picture rather than
disappearing. Recorded, not accidental.

## Reading (P2.4)

`Reader` port (`app/ports/reader.py`) + `BooksnapReader`
(`app/adapters/booksnap_reader.py`, over `booksnap.Pipeline`), `JobRunner`
port (`app/ports/jobs.py`) + `InProcessJobRunner`
(`app/adapters/inprocess_jobs.py`), the `Read`/`Claim` entities
(`app/domain/read.py`), `ReadStore` (in `app/ports/store.py`, alongside
`BookStore`/`ShelfStore`) + its memory/sqlite adapters (schema **v7**), and
`/api/v1/shelves/{shelf_id}/reads` — start, poll, stop, list history, get one
read with its claims. This is the item that turns "photograph a shelf" into
"books land in the library" — P2.5 (reconciliation) and P2.6 (copy
resolution) both consume a finished `Read`'s claims; nothing before this item
produced any.

**Strangle, don't refactor, literally.** `BooksnapReader` does not import
`booksnap.server` — the layering test only forbids that from `app/api`, but
the plan's instruction is unconditional, so `_build_catalog` /
`_build_fallback` / `_build_page_reader` are COPIED, not shared. Deliberately
NARROWER than the tuning server's version: only the `local` and `nli` catalog
backends are wired, not the experimental Simania/Rebooks/Booksefer chain
(`BOOKSNAP_CATALOG_BACKEND=simania`) — that chain is prototype-grade and not
part of the measured baseline this file documents, and copying untested
surface into the product for no product benefit is the wrong trade. Promote
it here the same way a new retrieval source gets promoted into
`_build_catalog`'s own baseline: after a measured win, not by default.

**No module-level job dict, on purpose — this is the whole point of the
item.** `InProcessJobRunner` keeps every job's lock, stop event, state and
progress on `self._jobs`, keyed by job id. Two `InProcessJobRunner()`s (one
per app, e.g. two tests) never see each other's jobs — contrast
`booksnap/server.py`'s module-level `_job` dict and `_stop_event`, which is
exactly the shape H2/§1.3 forbids for the product (two members starting a
read would overwrite each other's job). `tests/test_api.py`'s
`test_no_module_level_mutable_state_in_api` is the meta-test that would catch
a regression back to a module global, and it already covers every file under
`app/`, so nothing new had to be added to it.

**Claims are saved once, not incrementally.** The job glue
(`app/api/routers/reads.py:_job`) calls the Reader, builds every domain
`Claim` in memory, then calls `ReadStore.save_read` exactly once — either
when the read finishes, stops, or fails. "Per-image progress" (plan wording)
is served by a SEPARATE, unpersisted channel: `JobRunner.status(job_id)`
returns whatever dict the Reader last reported through `JobHandle`, and
`GET .../reads/{id}` merges it into the response only while `status ==
"running"`. Two consequences worth knowing:
  - a crash mid-read loses the claims already produced in memory (they were
    never written), UNLESS the exception path runs — which it does, because
    the job's `try/except` calls `fail_read` with whatever claims had already
    been `append_claim`-ed onto the in-memory `Read` before the exception,
    then saves that. So a genuine engine crash is NOT silently lost; only a
    hard process kill (not a Python exception) would lose it, same exposure
    as the tuning server's own job;
  - polling mid-read never sees partial CLAIMS, only partial PROGRESS. If a
    future review screen needs to show claims as they arrive rather than
    after the whole depth finishes, that is an incremental-save change to
    `_job`, not a port change — `ReadStore.save_read` already replaces the
    aggregate whole, so calling it more often costs nothing structurally.

**`ReadStore` does not validate `shelf_id` the way `ShelfStore.save_capture`
validates a capture's.** A capture's `shelf_id` is client-supplied and must
be policed (§4.2 — a forged foreign shelf id must not silently attach); a
Read's is not, because the ONLY constructor, `new_read(shelf, captures, ...)`,
takes an already-loaded `Shelf` and rejects any capture that doesn't belong to
it (§5.7 #1, mutation-checked — see below). By the time a caller has a `Read`
object to save, its `shelf_id` is already known-good, so re-validating it in
the store would duplicate a guarantee the domain gives for free. Documented as
a ⚠ in `app.ports.store.ReadStore` and in the v7 migration comment, because it
is the one place this port's shape looks inconsistent with `ShelfStore`'s
until you know why.

**Two DTOs, not one.** `ReadSummaryDTO` (status, `claim_count`, no claims) for
`GET .../reads`; `ReadDTO` (everything, claims included) for start/get/stop.
The plan's own wording splits them — "list a shelf's reads" vs. "get one read
with its claims" — and a shelf's history screen (P2.8) has no reason to pull
every claim of every past read just to render a row of status + counts.

**`ReadDTO.progress` is never persisted.** It is populated only from
`JobRunner.status(read_id).progress` while the stored read is still
`"running"`; once the read settles, `progress` is `null` in every response.
Keeping it live-only avoids a second place (the stored `Read`) that could
disagree with the job runner about whether a read is actually still going —
the two would drift the moment a crash left one updated and not the other.

⚠ **A read at an undeclared depth, or with captures at the wrong depth, is
checked in TWO places and that is deliberate, not redundant.** The router
calls `shelf.check_depth(body.depth)` before even fetching captures (for the
clearer 409 message), and `new_read` re-checks depth AND shelf identity on
every capture it is handed (for the mutation-checked domain guarantee, §5.7
#1). Removing either check independently still leaves the other one standing
— confirmed by mutation-checking them separately in `app/domain/read.py`
(temporarily deleting each `if` block, running `test_domain.py`, seeing the
named rule test fail, then restoring it).

⚠ **A capture with no uploaded photo is skipped, not fatal, but "every
capture at this depth has no photo" IS a 409.** P2.2's recorded gap (a
capture can exist before `POST /images` ever names it) means `ReadRequest`s
are built only from captures that have an `image_id`; the router refuses to
even submit a job if that list would be empty, because a read that silently
produces zero claims looks like the engine failed, not like nothing was ever
uploaded.

## Reconciliation (P2.5)

The item VISION §5.6 calls "the single biggest change from how the system
behaves today": a shelf's book list is durable state, and a read is an event
that *updates* it, never replaces it. `app/domain/reconcile.py`'s `reconcile`
is the pure function — `(shelf, depth, claims, library_books, decisions) ->
Diff` — and it is the highest-risk logic in the product for exactly the
reason the plan names: it is the one place a silently-reversed rule deletes
someone's books. It is comfortable to call an item rather than a project only
because it is fully offline-testable — no store, no clock, no ids, milliseconds
per case.

**Signature note — why `library_books` is the WHOLE library, not just this
location.** The plan's one-line summary undersells the inputs: §5.4's ask
fires when a claimed book is already confirmed *somewhere else* in the
library, so the pure function needs every book, keyed by `book_key`, not only
this shelf's occupants. The caller (`app/api/routers/reads.py:diff_for`)
pays an honest O(library) `BookStore.list` scan per diff — the same trade
`books.py`'s CSV export already makes with `EXPORT_MAX`, and the same one
`app.domain.search` documents for its `LIKE` scan. Revisit if it is ever
measured to cost something; guessing at a narrower query now would be
premature.

**The five buckets, and what `corrected` actually means.** VISION's table
only literally distinguishes four outcomes (already-here / elsewhere-ask /
not-in-library / previously-rejected) plus the not-seen rule; `corrected` is
named in the plan (`+3 added · 1 corrected · 12 unchanged · 1 not seen`) but
never defined. The call made here, and the one thing in this item VISION
genuinely left open: **`corrected` is a REPLAYED §5.4 decision** — a claim
whose (shelf, depth, book_key) was already answered by a human on an earlier
read (`ALREADY_LISTED` or `ANOTHER_COPY`), applied automatically this time
with no second prompt. It is a real, distinct thing from `unchanged` (the
copy's location is actively being corrected/created, not merely reconfirmed)
and from `needs_decision` (the question already has a standing answer). Once
applied, the copy really does stand at this location, so the NEXT read of the
same spot resolves as ordinary `unchanged` — `corrected` only fires once per
decision, which is what makes the shelf-history line
(`app/reconcile_apply.py`'s test suite proves this end to end) an honest count
rather than one that grows forever.

**`relink_copy` — a new domain operation, not a reuse of `observe`.**
`observe()` deliberately never moves an already-located copy, even with an
explicit `copy_id` (its own docstring: "adopting an unshelved copy is the
only relink a read may perform") — a bare read's claim must never relocate a
copy on its own say-so, because the claim alone might simply be wrong.
§5.4's "already listed copy" answer is different: a HUMAN decision, stronger
evidence, and it explicitly means *move it*. `app/domain/book.py:relink_copy`
is that second, narrower door — same append-only/idempotent/never-demote
shape as `observe`, but it WILL change `shelf_id`/`depth` on a copy that
already has one. It does not construct a `Copy`, so it needed no exemption
from `test_only_two_functions_in_the_domain_may_construct_a_copy`'s AST walk.
Found by writing the first end-to-end apply test and watching a relink
silently no-op — see "what a green domain ring can't catch" below.

**`add_copy` gained an optional `provenance` param.** §5.4's "another copy"
answer creates a copy that a read genuinely just observed (unlike P1.7's "I
have another copy" button, which has no read behind it and still defaults to
none). Threaded through, default `()`, so every existing call site is
unaffected — `test_domain.py`'s AST walk still names `add_copy` as one of the
two functions allowed to construct a `Copy`, unchanged.

**Decisions are two different vocabularies, and `AnswerKind` keeps them
separate on purpose.** `DecisionKind` (persisted) has four values —
`REJECTED`, `WRONG_BOOK`, `ALREADY_LISTED`, `ANOTHER_COPY` — deliberately with
**no `CONFIRMED`**: confirming a REVIEW-tier claim for a brand-new book
*creates the Book*, and that Book's existence is already the durable record —
a later read of the same spot resolves as `unchanged` without ever consulting
a stored decision again. Only the SUPPRESSING answers need to persist,
because nothing else remembers "no" on their behalf. `AnswerKind`
(`app/reconcile_apply.py`, the API-facing vocabulary) has five —
`CONFIRM`/`REJECT` for a `review_tier_new_book` claim,
`ALREADY_LISTED`/`ANOTHER_COPY`/`WRONG_BOOK` for an `ambiguous_location`
one — and `apply_diff` refuses a mismatched pairing (`CONFIRM` on an
ambiguous claim, say) as a 400 rather than silently doing nothing or, worse,
doing the wrong thing.

**Where the rules live vs. where they execute.** `reconcile()` classifies —
it decides the bucket and, for a replayed decision, which domain operation
that implies — but it never mints an id, reads a clock, or calls
`new_book`/`observe`/`add_copy`/`relink_copy` itself; doing so would need an
`IdGen` and make it impure. `app/reconcile_apply.py` (a new top-level module,
sibling to `domain`/`ports`/`adapters`/`api` — it needs BOTH `app.domain` and
`app.ports`, and the plan says explicitly not `app/api`) is the thin layer
that turns a classified `ClaimOutcome` into an actual write. "Keep the rules
in the pure function; that part only persists" is the plan's own phrasing for
the split, and it is why every rule test above lives in `test_domain.py`
against `reconcile()` alone, with zero store involved.

**`DecisionStore`** (`app/ports/decisions.py` + `MemoryDecisionStore` +
`SqliteDecisionStore`, schema **v8**) is a fourth, independent port — same
reasoning as every other split in `app.ports.store`: a decision can outlive
the read that produced it and exist before the book it concerns is ever
created (a `REJECTED` decision for a claim that never became a `Book`).
Identity is `(library, shelf, depth, book_key)`, a composite PRIMARY KEY, so
`save_decision` is a plain upsert — a human who changes their mind (rare, but
possible once P2.6's queue exists) overwrites rather than accumulating a
history nobody reads. `list_decisions(library, shelf_id, depth)` returns
exactly the shape `reconcile()`'s caller needs, one call per read.

**API**: `GET /shelves/{id}/reads/{read_id}/diff` (read-only, recomputed
fresh every call — never cached, so "would this resolve differently now" is
always a real, current answer) and `POST .../apply` (writes everything
`reconcile()` already decided unconditionally, plus whatever `answers` the
body supplies for still-open `needs_decision` claims; returns the diff
RECOMPUTED after writing, so a resolved claim visibly leaves
`needs_decision` in the same response that resolved it). Both 409 on a
`RUNNING` read — applying against claims a background job could still be
appending to would be writing provenance for a read the store might overwrite
out from under it (H2/§1.3's concurrency concern, one layer up from the job
runner itself).

**Deliberately deferred, and named so they are not mistaken for gaps:**
  - **not-seen streak counting.** `Diff.not_seen` reports THIS read's facts
    only; persisting a count across several reads and surfacing "not seen in
    the last 3 reads" softly is P2.8's, which has the read archive to count
    from. `apply_diff` writes nothing for a `not_seen` entry — asserted
    directly (`test_not_seen_entries_are_never_written_anywhere`), not just
    assumed from the absence of a call site;
  - **the "duplicates to resolve" queue.** `needs_decision` is a snapshot of
    ONE read's open asks; an entry with no matching `Answer` simply stays
    open and reappears next time the diff is asked for. Making it durable and
    filterable on the Books tab, independent of any one read, is P2.6's item.

**What a green domain ring can't catch, again.** The first version of
`app.reconcile_apply`'s "already listed" path called `observe()` (matching
`unchanged`'s path) instead of the new `relink_copy()`. Every `reconcile()`
test still passed — the pure function only classifies, it never checked
whether an outcome, once EXECUTED, actually changed anything — and the bug
only surfaced when an end-to-end apply test asserted the copy's `shelf_id`
after the write. Recorded because it is the same shape of lesson
P1.6/P1.7 already logged twice: a ring that cannot see the full round trip
is not proof the round trip works.

## Copy resolution (P2.6)

§5.4's whole point is a prompt that fires RARELY — "or it becomes review
fatigue and gets click-through-approved, which is worse than not having it."
P2.5 already built the machinery that keeps it rare (`reconcile()`'s
within-depth dedup and its `same_location`/`ambiguous_location` split); this
item's job was to make the RULE that decides "ask or not" a first-class,
tested artefact instead of something you'd have to read `reconcile.py`'s
control flow to reconstruct, plus the parts P2.5 explicitly deferred: the
queue that survives past one read, and the two cheap wins.

**The fire table (`app/domain/copy_resolution.py:FIRE_TABLE`)** is data, not
control flow — four `FireRule` rows, each naming a situation from §5.4's own
table, the `ClaimOutcome.reason` `reconcile()` actually produces for it, and
`ASK`/`NEVER_ASK`. `fires(reason)` is the load-bearing function: it is not
just read by tests, `app.reconcile_apply`'s queue bookkeeping calls it too
(`assert fires(outcome.reason) is FireDecision.ASK` guards the one branch
that opens a queue entry), so a table edited without a matching change to
`reconcile()` — or the reverse — trips an assertion instead of silently
drifting apart. `fires()` **raises** for any reason outside the four rows
(`review_tier_new_book`, `rejected`, `no_identity`, ...) rather than
defaulting to `NEVER_ASK` — those answer a different question entirely (is
this a real book? has a human already decided?), and guessing would make an
unrecognised reason indistinguishable from one the table covered on purpose.
Two of the four rows share one reason (`duplicate_within_depth` — "two
spines, same run" and "overlapping captures" are mechanically the SAME
collapse once a Read is scoped to one (shelf, depth)), and
`test_fire_table_rows_sharing_a_reason_agree_with_each_other` pins that the
table cannot contradict itself.

**The durable queue (`DuplicateQuestion` + `app.ports.duplicates.DuplicateQueue`,
schema v9).** P2.5's `needs_decision` is a snapshot of ONE read; a
`DuplicateQuestion` is what survives after that read's response has come and
gone. Identity is the SAME `(library, shelf, depth, book_key)` quadruple as
`Decision` — a question and its eventual answer are two states of one fact —
which is what makes closing it mechanical: answering (via
`POST /reads/{id}/apply` OR the queue's own `/duplicates/{id}/answer`)
deletes the row in the SAME write as the `Decision` it creates, and a repeat
unanswered claim on a LATER read refreshes the existing row (`open_or_refresh`,
pure) rather than piling up a second one — `opened_at` and the minted `id`
both survive a refresh, so the queue doesn't lie about how long a question
has been waiting and a client's open tab on it doesn't 404. There is
deliberately no "resolved" state to query: closed means gone, same shape as
`DecisionStore.delete_decision`'s "undo of a mis-click" but triggered by the
opposite event.

**The two cheap wins**, both in `copy_resolution.py` and both PRESELECTIONS
a human still confirms or overrides — never applied on their own:

  - `pick_default_copy` — "no shelf assigned, or the least-recently-seen."
    Checked in that order even when a located copy was seen very recently and
    the unlocated one never has been; a copy with NO provenance at all (an
    "I have another copy" declaration that was never actually read) counts as
    the most extreme case of "least recently seen" and sorts first among
    located copies;
  - `build_prompt` — swaps the plain three-way prompt for "you lent this to
    Dana — is it back?" when `pick_default_copy`'s OWN candidate is
    `Lending.is_out`. Sharing one candidate between the two wins is
    deliberate (`test_build_prompt_only_checks_the_default_candidate_not_any_copy`
    pins it): a different copy being lent out must not leak the sharper
    question onto a prompt about an unrelated candidate.

**`DEFAULT_RESOLUTION = DecisionKind.ALREADY_LISTED`** — §5.4 verbatim: "a
missed duplicate is mildly wrong and trivially fixed later; an invented one
is a phantom that rots silently." Consulted in exactly ONE place: the
queue's explicit `POST /duplicates/{id}/skip` action ("not now — use the
safe default"), which is deliberately NOT the same thing as leaving a claim
unanswered during `POST /reads/{id}/apply` (that opens the durable question
instead of resolving anything). Mutation-checked twice, at two different
layers, because this is the rule a silent regression would be most expensive
in: `test_default_resolution_is_already_listed` pins the constant, and
`test_the_skip_default_relinks_rather_than_creating_a_second_copy` /
`test_skipping_a_queued_question_applies_the_safe_default` (API, over real
HTTP) prove the BEHAVIOUR — reversing the constant to `ANOTHER_COPY` makes
`copy_count` come back 2, not 1, in both.

**API** (`app/api/routers/duplicates.py`): `GET /duplicates` (whole-library
listing — a queue entry is about a BOOK, not about which shelf happens to be
open, so it is not nested under `/shelves/{id}`), `POST .../{id}/answer`,
`POST .../{id}/skip`. Both mutating routes re-derive the exact `ClaimOutcome`
a question was raised from by calling `reads.py`'s own `diff_for` (renamed
from `_diff_for` so a second router can share it) against the stored
`(shelf_id, read_id)` — the queue stores a POINTER, never a frozen snapshot,
same "recompute against current reality" idiom as `GET .../diff`. If it no
longer resolves to an open `ambiguous_location` outcome at that key (the
book was deleted, or someone else already answered it a moment ago), the row
is deleted right there and the caller gets a 409 rather than a confusing
silent no-op.

**The Books tab filter is a generic `book_ids` narrowing on `BookStore.list`,
not a new aggregate join.** `BookStore` has no idea what a "duplicate
question" is — that would put a second aggregate's shape inside a port that
should only know about books — so `GET /books?duplicates=true` is composed
at the API layer exactly the way `reads.py` already composes across four
ports: list the open questions, collect their `existing_book_id`s, narrow
`store.list(..., book_ids=...)`. An explicit EMPTY tuple means "match
nothing" (an empty queue pages as zero books), which had to be handled
before a query was even built — `book_ids=()` would otherwise compile to an
invalid `IN ()` clause in SQLite. Client half: `BooksQuery.duplicates`, a
plain boolean exactly like `lentOut` — same chip shape in `FilterBar`, same
`toParams` mapping, same `filtersActive` inclusion. Deliberately did NOT
build a client-side answer/skip screen in this item; the plan puts "inline
review of each claim" in P2.7 (the Capture tab), and the filter is what the
plan literally asked for here — a way to FIND the books, not yet a
third UI for resolving them.

⚠ **The linear scan in `_find_open` (`duplicates.py`) is deliberate, not an
oversight.** Addressing one queued question by its minted id means scanning
`list_open_questions(library)` rather than an indexed point lookup — correct
because §5.4's whole design goal is that this list stays small (a firing
rate this codebase is actively trying to keep near zero), never
library-scale. Same "measure before indexing" stance `app.domain.search`
documents for its own linear scan; revisit only if that assumption is ever
measured wrong.

## The Capture tab (P2.7)

The last item of the "capture a shelf and review it" arc: drop zone → a row
per photo with shelf + depth assigned inline → mode selector → run/stop with
live progress → inline review of every claim (crop, tier, diff badge, ✓/✕ or
the §5.4 three-way prompt, *why?*). `app/web/src/capture/` — `useCapture.ts`
(all the state and API orchestration), `CaptureTab.tsx`/`CaptureRow.tsx`
(intake), `ReviewPanel.tsx`/`ClaimRow.tsx` (review). A two-button `<nav>` was
added to the app bar (`App.tsx`, `#/capture` in `route.ts`) — the first time
the product has had more than one tab.

**The intake queue is SESSION state, not a server resource.** Every dropped
photo becomes a real `Image` + `Capture` the moment it uploads (P2.2/P2.3
already made that durable), but nothing in P2.1–P2.6 built a "list every
capture nobody has read yet" index — a shelf's captures are only listable BY
shelf. So the queue this tab renders lives in `useCapture`'s own state, not a
fetch; a page refresh loses its ordering/selection, though nothing already
uploaded is lost — it is simply not re-listed here. Building that index is a
P2.8 (shelf view) concern, not this tab's.

**A read is scoped to exactly one (shelf, depth) — `new_read`'s own rule —
and the intake selection is a per-PHOTO convenience layered on top of that,
not a new unit of work.** `POST /shelves/{id}/reads` always reads EVERY
capture filed at that shelf+depth, checked or not (§5.7 #1 forbids a partial
read of one row). `start()` turns the checked photos into the DISTINCT
`(shelf, depth)` pairs they touch and starts one read per pair — checking one
photo of a pair queues its siblings too. That is the domain's own
granularity, not a shortcut invented here, and multiple pairs run as
multiple independent review panels, stacked in the right column.

**Claims commit automatically; only `needs_decision` rows ask for a click —
and every answer, including the automatic commit, is a REAL network call,
not a local stage-then-batch.** The first plan here was to batch ✓/✕/3-way
answers locally and send them in one `POST .../apply`, on the theory that
`apply_diff` persists `added`/`corrected`/`unchanged` UNCONDITIONALLY on
every call and repeated calls would duplicate provenance. **That theory was
wrong, and worth recording because it is the non-obvious part:**
`Provenance.sighting` is `(run_id, spine_id)` and `observe()`
(`app/domain/book.py`) skips appending when that pair is already present, so
replaying the SAME read's `apply` is idempotent — a claim already turned into
a `Book` reconciles as `unchanged` on the next call rather than a fresh
`new_book` (a fresh id would be the real duplication risk; reconciling
against CURRENT state is what prevents it). That is what makes `commitDiff`
safe to call automatically the instant a read settles (with an EMPTY answers
list — `reconcile()` already decided those buckets, there is nothing to wait
for a click on) and `answerClaim` safe to fire immediately per ✓/✕/3-way
click rather than staged. Simpler code, and a more honest UI: the reviewer
never has to trust an unlabelled "Apply" button to know whether their read
actually landed on the shelf.

**"Alternatives"/*why?* — `booksnap.match.explain()`, threaded end to end,
computed at READ time.** `app/domain/read.py:Alternative`,
`app/ports/reader.py:ReadAlternative`, `ClaimDTO.alternatives`, and SQLite
schema **v10** (`claims.alternatives`, nullable JSON, no backfill — same
shape as every claim column that predates it). `BooksnapReader._alternatives`
re-runs `explain()` against the SAME query text `pipe.run` already sent the
catalog for that spine, which is why this is free rather than a second
lookup: `NLICatalog` caches responses on disk by query (CLAUDE.md, "External
integrations"), so `catalog.candidates(text)` a second time for the identical
text is a cache hit, not a live call. Deliberately NOT a
`GET .../claims/{id}/explain` endpoint computed on demand — that would mean a
live catalog round trip every time a human clicks *why?*, which is exactly
the cost the "deterministic first" philosophy asks this codebase to avoid
paying twice.

**"Alternatives" is READ-ONLY, not "one-click acceptable" (UI_PLAN §4's own
phrase) — a deliberate, reported scope cut.** The domain has no operation to
re-point an already-classified claim at a different catalog candidate;
building one (a new `reconcile()` outcome, a new `AnswerKind`, a write path)
is a real domain addition, not a UI tweak, and out of this item's size. The
ranked list still renders inside *why?* for transparency (title, author,
score, and the gate `explain()` refused it on, verbatim — those reason
strings are ENGLISH always, hardcoded in `booksnap/match.py`, and are shown
as-is rather than mistranslated by guessing at their meaning). No accept
button is drawn next to a candidate — absent, not a button that does nothing.

**The *"פתחו את המדף →"* chip (UI_PLAN §4) is also left out**, for the same
"absent, not disabled" reason: it links to `#/map/<shelfId>`, and neither a
map tab nor a shelf-detail route exists yet (P2.8/pillar 6). The sentence
under it — confirming here is a shortcut, the shelf is the durable home — is
plain text with no link, and still says the true thing.

**Depth reassignment always resets to row 1.** Moving a photo to a different
shelf (`assignShelf`) sends `depth: 1` explicitly rather than keeping
whatever row it was on — the target shelf may not have declared as many rows
as the one the photo is leaving, and the server answers an undeclared depth
with a 409 (§5.7), not a clamp. 1 always exists.

**Multiple unnamed shelves are visually identical in the shelf `<select>`.**
Verified live: dropping two photos with no shelf named creates two shelves
that both read "לא משויך" in the picker, distinguished only by their (hidden)
id. Honest given P2.1's own rule that identity is free and an unnamed shelf
is normally shown by its photo, which a flat `<option>` list cannot do — a
miniature elevation/thumbnail picker is UI_PLAN §7's "still open" problem
(§8, "clicking the target cell... not built"), not this item's to solve.

Traps found while verifying in the browser:

⚠ **`getComputedStyle` is not reliable while the Browser pane is not
displayed — for STATIC properties too, not only running transitions.** A
`.badge` element (`display: inline-block` in `books.css`) read back as
`display: block` while the pane was backgrounded; re-querying the identical
selector match confirmed only one rule affects `display` and it says
`inline-block`, and the value read correctly the moment the pane was visible
again. CLAUDE.md's existing transition warning undersold this — treat ANY
`getComputedStyle` read while the pane is backgrounded as unverified, not
only ones involving `getAnimations()`.

⚠ **A synthetic canvas image is enough to verify the upload → capture →
shelf → depth → run wiring live, but not enough to populate a claim row.**
`segment_image` found zero spine candidates on a flat-colour test JPEG, so
the real engine ran end to end (Tesseract, real HTTP, real SQLite) and
produced a genuine, correctly-rendered EMPTY diff — but no claim ever reached
`ClaimRow`. Getting a populated row live needs a real shelf photo, and
`spines` mode costs ~10-20s **per detected spine** (CLAUDE.md, "Legacy spines
mode"), which was not paid for in this session — the populated-row rendering
(tier/diff badges, the §5.4 prompt, *why?*'s alternatives table) is instead
covered by `CaptureTab.test.tsx`'s fixture-driven tests, mutation-checked.
Re-verify visually the next time a real multi-spine read is run through this
UI.

## Shelf view + read history (P2.8)

The last item of the run→shelf inversion (§5.5/§5.6): a shelf's own screen —
photo, last-read date, a soft staleness line, the ALWAYS-visible depth bar
(§5.7), the durable list of books at the selected depth (never auto-pruned),
and read history as diffs. This *is* the history UI; there is still no run
list anywhere (§5.5's "not a user-facing concept" holds all the way through).
Mounted at `#/map/<shelfId>` — UI_PLAN §3's own deep-link shape, reused now
even though the Map tab's levels 1-2 don't exist yet (pillar 6): this screen
*is* "level 3", so when the map arrives it gains an entry point into this
same screen rather than a second shelf-detail surface. Reachable today from
the Capture tab's *"open the shelf →"* chip (P2.7 left it out on purpose,
named exactly this item as the reason) and by direct URL.
`app/web/src/shelf/` — `useShelfDetail.ts` (state), `ShelfPage.tsx` (the
screen), `ReadHistory.tsx` (the diffs list).

**The hard design question was NOT the UI — it was what a "read history diff"
even means once the read that produced it is old.** `app.reconcile_apply`'s
own diff endpoints (P2.5) deliberately recompute `reconcile()` fresh against
CURRENT library state on every call, and say so in their own docstring — the
right answer for the ONE active, not-yet-applied read every review screen
shows. Reusing that same "recompute, never cache" idiom for HISTORY is wrong:
recompute an already-applied read's diff today and every `added` claim now
classifies as `unchanged` — the book it added is, by definition, already
standing at that (shelf, depth) the moment you ask again — which would
silently repaint "this read added 3 books" into "this read changed nothing"
the instant the read was reviewed, forever. So `app.domain.read.DiffSummary`
is a SNAPSHOT: seven plain counts, computed once by `reads.py`'s own `_job`
closure right after a read settles into `done`/`stopped` (never for `failed`
— its claims may be an arbitrary partial slice from whatever blew up), and
persisted on the `Read` itself (`Read.diff_summary`, SQLite schema **v11**,
nullable JSON, no backfill — same shape as v10's `alternatives`). Verified
live end to end: applying an already-summarised read's diff afterward does
not change its history row's counts (`test_a_finished_read_carries_a_diff_
summary_and_it_is_archived_not_repainted`).

**The not-seen streak (§5.6 option 2, deliberately deferred by P2.5 — its own
docstring says so) is derived from a copy's OWN provenance, not from
re-running `reconcile()` across the archive.** `app/domain/history.py` (new
module — `reconcile.py`'s docstring explicitly reserves this for P2.8) adds
`not_seen_streak(copy, shelf_id, depth, reads)`: each `Provenance` entry
already names the read (`run_id`) that produced it, so "was this copy
reconfirmed by read R" is a plain set-membership check requiring no
library-wide state reconstruction. Counts backward from the shelf's most
recent terminal reads of that EXACT (shelf, depth) — scoped per §5.7 #1, so a
front-row re-read cannot age a copy standing in the row behind, mutation-
checked (`test_not_seen_streak_is_scoped_to_the_depth_read` fails if the depth
filter is dropped) — and stops counting at the first read that reconfirmed
it, or at a read that predates the copy's own first sighting there (a copy
placed last week must not inherit a streak from photos taken in March). A
read with no sighting at this (shelf, depth) AT ALL returns 0 rather than
counting every read as a miss — the real caller (`shelf_books`) only ever
asks about a copy it already found located here, so an empty case is
defensive, not the normal path. **The function has no way to remove
anything** — it takes reads and a copy, returns an int — so the "never
auto-remove" rule (§5.6's central one) cannot be reversed HERE; it lives in
`reconcile._not_seen_here` (P2.5) exactly as strict as before. The
mutation-check the plan asked for by name was done at the door someone would
actually add a "cleanup" bug: `GET /shelves/{id}/books` was temporarily
edited to delete a book once its streak reached 2, confirmed
`test_shelf_books_reports_a_not_seen_streak_and_never_removes_the_book`
failed, then reverted.

**Physical order has no real data to draw on yet, so it is a documented
proxy, not a guess dressed up as a fact.** A claim's bounding box
(`Claim.box`) lives only on the live `Read` that produced it (P2.4) and is
never carried onto a `Copy`/`Provenance` once applied — there is no persisted
X-coordinate for "books at a depth" to sort by. `shelves.py:_physical_order_key`
instead parses the numeric suffix off the engine's own spine id
(`IMG_1234_b0_s07` already encodes a left-to-right position within its band,
`segment.py`), numerically so spine 10 does not sort before spine 2, with a
title fallback for anything with no spine at all (a manual add, or a legacy
import). Honest, not exact: two captures of one row (§5.3) or a corrected
relink would need a real position to order perfectly, which nothing stores
today. Revisit if `Claim.box` ever gets a home on `Provenance`.

**Staleness is relative to the shelf's own freshest row, never a clock.**
`app/domain/history.py:depth_staleness` flags a depth `is_stale` only when
another depth of the SAME shelf was read more recently — a shelf nobody has
ever photographed shows no staleness signal at all (there is nothing fresher
to be stale against), which reads as honestly quiet rather than nagging about
a feature the owner hasn't started using. UI_PLAN §3's own example
("rows 2, 3 not read since 11.3.2026") is rendered by joining each stale
depth's own clause (`stale_since`/`stale_never`) with `·` — a design call
where the plan specified content but not exact phrasing, made explicit here
because it is a joined sentence, not literal grouped text.

**`GET /shelves/{id}/books`, `GET /shelves/{id}/overview` — both new, both
accept the SAME O(library) trade `reads.py`'s diff endpoints already made**
(no `shelf_id`/`depth` filter exists on `BookStore.list` — P2.5 chose not to
add one), rather than inventing a second, divergent narrowing strategy for a
query this rare (one shelf view at a time). `CopyDTO.not_seen_streak` and
`BookDTO.of(..., streaks=)` are additive optional fields — every other call
site of `BookDTO.of` simply doesn't pass `streaks`, so the badge is `null`
everywhere except the one endpoint that has a shelf's read archive in hand.

**Read history is scoped to the SELECTED depth, not the whole shelf.**
`GET /shelves/{id}/reads?depth=N` already existed (P2.4); the UI simply always
passes the depth bar's current selection. Mixing two rows' diffs in one list
would be exactly the §5.7 #1 mistake the rest of this item goes out of its
way to avoid — a diff is per-depth, or it is nonsense (§5.7 #1, verbatim).

**No `run_no`.** `app.domain.read.Read` has no human-numbered handle, unlike
the tuning server's own runs (CLAUDE.md, "Run history") — §5.5 is explicit
that a run is not a user-facing concept, and this product's `Read` was built
that way from P2.4, so there was nothing to hide here. `ReadHistory.tsx`
renders a date and the engine mode, never an id. Asserted live and in the
client ring (`queryByText(/run/i)` finds nothing in a history row).

Traps found while verifying in the browser (`work/product.db`/
`work/product_blobs` snapshotted before, restored after — the DB carries the
owner's real 250 imported books, not a fixture):

⚠ **Live data for "books at a depth" cannot come from the API alone — there
is deliberately no endpoint that places a book at a location directly.**
Every legitimate path is a read + `apply` (P2.5) or a §5.4 decision replay;
a synthetic photo produces zero claims (P2.7's own finding, confirmed
again — `segment_image` found nothing on a flat test PNG), and a real
multi-spine photo was not paid for in this session either. Verification used
the SAME adapters the server uses (`SqliteBookStore.save`,
`SqliteReadStore.save_read`, called directly with real `Provenance`/`Read`
objects, not through HTTP) to seed three books at one depth with different
not-seen streaks (0/1/2) and a genuinely stale, never-read second row — this
is code-identical to what `apply_diff` would have written, just without
paying for OCR. One REAL read was also run through the actual engine
(`mode=spines` against a synthetic image) to confirm the failed-read path
live: `status=failed`, `diff_summary=null`, exactly as designed.

⚠ **`get_page_text` only reads `<main>` — the book drawer renders as a
sibling of it (`App.tsx` mounts it outside `<main>`, deliberately, so it
survives a tab change), so a page-text check after clicking a shelf row
shows the shelf screen UNCHANGED even though the drawer opened correctly
underneath.** Caught by checking `document.querySelector('[class*=drawer]')`'s
own class list (`"drawer on"`) instead. Worth knowing for the next screen
that opens the drawer from somewhere new.

⚠ **The Browser pane did not composite frames this session** (`computer`
screenshot timed out every time), so — per CLAUDE.md's own existing warning
that `getComputedStyle` lies while backgrounded — every visual check here
used DOM structure instead: `className`/`getAttribute` reads (which are not
paint-dependent) for `dir`/`lang`/`.rtl-safe`/badge text/depth-bar `.on`/
`.dot` state, confirmed against `get_page_text` content in both languages.
That is real verification of markup and wiring, but it is NOT a verification
that the CSS actually paints correctly (spacing, the photo's aspect ratio,
dark-mode contrast) — `shelf.css` was written using only existing CSS custom
properties (`var(--review)`, `var(--line)`, etc.), the same tokens every
other screen already proves work in both themes, but that is inference from
the token system, not a rendered screenshot. Re-verify visually the next
time the pane composites.

## Author sort, and why it needed a schema version

"Sort by author" means the SHELF order — by surname. Sorting the stored string
files גרג הורביץ under ג and דיוויד באלדאצ'י under ד, i.e. everyone under
their given name, which makes the sort useless for finding an author. The rule
is `app/domain/text.py:author_sort_key`, and it handles both shapes that exist
in the owner's 251 books: `אסימוב, אייזיק` (19 — everything before the first
comma is the surname, which also absorbs the `(אדריכל)` parentheticals) and
`גרג הורביץ` (232 — the last whitespace-separated token). Measured on the real
data before it was written, not guessed at.

Things worth knowing:

- **it is a SECOND key, not a re-ordered `normalized_author`.** That one is
  identity: the author chip filters on it and it is half the search haystack.
  Making it sort nicely would silently change which books an author filter
  returns;
- **no particle list.** `סבסטיאן דה קסטל` files under קסטל, not דה — 2 books
  of 251, and which is "right" depends on the cataloguing convention. A list
  containing `ד` would file `ג'ואן ד. וינג'` under ד, which is the kind of
  improvement that costs more than it buys. `ארתור סי.קלארק` files under ס
  because the source string is missing a space; that is a data fix;
- **sqlite needed schema v3** (`sort_author` + its index): ORDER BY has to see
  the key, and Python-side sorting would break LIMIT/OFFSET. Same reasoning as
  P1.5's `search_text` column;
- ⚠ **v3 is the first migration step that is a CALLABLE, not SQL.** "the last
  word, unless there is a comma" is not expressible in SQLite without a user
  function, and writing one there would put a second copy of the rule in
  `migrations.py`. The runner now accepts either, and the rule is reached for
  only when the column is DERIVED by domain logic. The migration test asserts
  a v1 database backfills AND that a book saved afterwards interleaves with
  the migrated ones — a backfill using a different rule from the write path
  looks fine until the two groups sort apart.

**Export downloads are named `books-<library>-<YYYY-MM-DD>.<ext>`.** The file
lands in a Downloads folder next to everyone else's, and it is a snapshot — a
second `booksnap-library.csv` becomes `booksnap-library (1).csv` and neither
one says what it holds or when. Both halves of RFC 6266 are sent, because the
library name may be Hebrew: `filename*=UTF-8''…` carries the real name and the
ASCII `filename=` fallback keeps the date rather than degrading to something
generic.

## Hebrew search (P1.5)

**The semantics are in `app/domain/search.py`; adapters own only retrieval.**
That split is what makes a Postgres adapter cheap: `parse()` says what a query
means and `score()` says what comes first, both pure and shared, so an adapter
chooses only how it NARROWS — SQLite `LIKE` over a stored `search_text`
column, Postgres could use `pg_trgm` or a tsvector — and then ranks with the
same function. **Ranking is never done in SQL**: doing it there means writing
it twice in two dialects and finding the drift in a user report. The store
contract runs the same search cases against every implementation, so a clever
retrieval strategy that changes the ANSWERS gets caught.

Measured on `fixtures/search/` (24 real queries × the real 251 books,
`python tools/search_eval.py --compare`):

| mechanism | P@1 | recall | results/query |
|---|---|---|---|
| **and + particles + rank** (shipped) | **1.00** | **1.00** | **2.8** |
| alphabetical instead of ranked | 0.88 | 1.00 | 2.8 |
| no particle variants | 0.94 | 0.97 | 2.7 |
| OR terms | 1.00 | 1.00 | 6.8 |
| word-start matching only | 0.81 | 0.89 | 2.5 |

P@1 is the metric that matters — the failure mode on a personal library is
never "nothing found", it is the right book at rank 9 behind its series
siblings. AND does *not* beat OR on P@1; its case is the 2.4× smaller result
set.

Things worth knowing:

- **leading ה/ו/ב/ל/מ/ש/כ are tolerated in the QUERY only.** Note the
  asymmetry with the matcher, where the same transform measured *harmful*
  (precision 0.62 → 0.50): a matcher compares two machine strings, search
  compares a human's typing to a catalogue. The stored key is never stripped;
  only one leading letter is removed, and only if ≥2 chars remain;
- substring matching covers the other direction free — a query for `נבונים`
  finds the stored `הנבונים` with no variant at all;
- terms shorter than 3 chars match only at a word start. 1–2 letters appear
  inside almost every Hebrew word, so infix matching on them returns the
  library;
- **the title-length bonus applies only when the query touched the TITLE.** On
  a pure author search every hit scores identically, so a length bonus becomes
  the sole tiebreak and orders an author's shelf by title length. Without it
  the tie falls through to alphabetical, which is what browsing wants. Found
  by reading real output, not by the fixture;
- search cost is a linear scan and that is deliberate: no index helps
  `LIKE '%x%'`. Measured 4ms at 251 books, 9ms at 2k, 53ms at 10k. The target
  is a few thousand; when it stops being enough the fix is a better narrowing
  clause (FTS5, trigram) in the adapter, not a different ranking.

## Legacy import (`work/` → the product store)

```bash
python tools/import_legacy.py --dry-run          # report only, nothing written
python tools/import_legacy.py --db work/product.db
python tools/import_legacy.py --export-fixture   # refresh fixtures/legacy/
```

Measured on the real data: **251 books → 117 approved, 110 auto, 24 manual**,
one copy and one provenance entry each, ~296KB SQLite. Re-running is a clean
no-op. Four things here are not obvious and are each pinned by a test:

- **stored keys are RECOMPUTED, never trusted.** 30 of the 251 keys in
  `library.json` predate the geresh fix in `normalize()` (`צ רלס סטרוס` vs
  today's `צרלס סטרוס`). Imported verbatim they would carry a key no future
  lookup could produce. Re-keying yields 251 distinct keys, zero collisions —
  but a collision would be *reported*, not silently resolved;
- **`store.json`'s `runs` is a DICT keyed by run_id**, not a list. Reading it
  as a list fails silently: iterating a dict yields strings, an `isinstance`
  guard drops them all, and every hand-typed book quietly loses its date. The
  committed fixture caught this;
- **manual adds are identified by `source.manual`, not by the `owner-fb-`
  spine prefix.** 9 of the 24 use `manual-<timestamp>`, and `owner-fb-` also
  covers 5 books that were *replaced* rather than typed;
- **"already present" is checked by id AND key, and the id is the load-bearing
  half.** Once a title is edited the key changes, so a key-only check reads as
  absent and re-saves under the same deterministic id — replacing the
  correction with the original text.

`source.replaced` (5 books) imports as `approved`, not `manual`: a human chose
from ranked alternatives, but the text is the catalog's. Constant
`REPLACED_STATUS` if that judgement should flip.

⚠ **14 rejected claims are NOT migrated.** §5.6 says a rejected book must not
be re-added by a later run; a rejection is scoped to a *shelf*, and shelves
arrive in P2.1. The importer reports them loudly rather than dropping them —
until P2.3 lands, a re-read could re-add those books.

Client ring (needs `npm install --prefix app/web` once):
`npm --prefix app/web run test` (vitest + React Testing Library, **55 tests**
as of P2.8) and `npm --prefix app/web run typecheck`. Test what encodes a
*decision*, not layout and not DTO plumbing — same standard as the Python
rings. The suite mocks `fetch`, never `useBooks`/`useCapture`/`useShelfDetail`:
the store, the request-id race guard and the paging arithmetic are exactly
what needs exercising, and the Capture/shelf fake servers
(`capture/captureHarness.ts`, `shelf/shelfHarness.ts`) do not reimplement
`reconcile()`/`apply_diff`/`not_seen_streak`/`depth_staleness` either — each
test hands back the exact overview/books/diff a call should answer with, the
way the Python API ring injects a `StubReader`.
Mutation-checked — sixteen reversed decisions (dropped race guard, missing
`.rtl-safe`, edit not abandoned on book change, delete without confirmation,
409 clearing the form, focus not restored, drawer left open on promote,
sort direction surviving a key change, tags not trimmed/blanks-dropped, the
`duplicates` filter dropped from the request — P2.6; "add a row behind" hidden
until a shelf is already stacked, ✓/✕ shown for every `needs_decision` reason
instead of only `review_tier_new_book`, an alternative given a one-click
accept button, a freshly-uploaded photo not auto-selected — P2.7; the depth
bar hidden at `depth_count` 1, a book title rendered without `.rtl-safe`,
the *"open the shelf →"* chip dropped from the review panel header — P2.8)
each fail a named test.

⚠ **This ring cannot see CSS.** jsdom computes no cascade, so every finding
in the "traps" list above was invisible here and had to be caught in a real
browser. Do not read a green client ring as "the screen is right".

⚠ jsdom keeps `localStorage` across tests in a file, and the language choice
persists deliberately — so `afterEach` must clear it, or every test after the
mirroring one starts in English and looks for the wrong strings.

**The pre-commit hook now has two independent halves** (`tools/githooks/pre-commit`):
accuracy (sweep + spotchecks, unchanged) and product (`tests/run_all.py`,
`tools/api_contract.py --check`, and the client tests when `app/web/` is
staged). Product work must never require touching the accuracy baseline. The
client half self-skips without `node_modules`, like the spotchecks do without
run data.

## Known constraints / next steps (roughly prioritised, updated 2026-08-06)

1. **Any rules/threshold change goes through `tools/sweep.py` first** (see
   "Measuring accuracy"): replay sweep for matching changes, `--live` when
   retrieval is affected, note in the ledger. This supersedes ad-hoc
   rescoring as the tune-and-measure loop.
2. Candidate new retrieval sources (e.g. additional used-book shops): trial
   via `sweep --live --sources ...`; promote into `server._build_catalog`'s
   baseline only after a measured win on the fixture.
3. Remaining recall losses on the labelled shelves are mostly READER-side
   (misreads like עיר הזמן→עיד, thin/unread spines), not matching — a
   second-pass READ of unmatched regions is the unexplored lever. (The
   retrieval-side twin is DONE, run 17: `second_pass_retrieval` re-queries
   sources with collapsed/leave-one-out variants for unmatched reads —
   measured live +0.03 AUTO F1 / +0.05 A+R F1 with precision UP. Probe
   before adding catalogs: run-16/17's "missing" books were almost all IN
   the sources already, unreachable only through the literal search;
   bookpod deferred until a measured coverage gap appears.)
4. Longer term, multi-user: revisit the confirmed library as a retrieval
   source (today it is an outcome of runs only, never a sweep/test source).
5. Legacy spines mode (Tesseract) still costs ~20s/spine from the 2 rot × 2
   height × 2 binarize × 2 model search; only worth pruning if that path is
   ever needed again — llmpage is the default mode.

## Working style notes

The owner is a senior engineer (25y) who values honest assessment over
optimism, catches overstated claims, and wants deterministic/cost-efficient
solutions. Report real numbers, flag what's unverified, don't oversell. When a
refactor might regress accuracy, measure before and after on the sample photos.
