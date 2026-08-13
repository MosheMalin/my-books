<!-- ARCHIVE. This is the full project log that used to be CLAUDE.md, moved
 here on 2026-08-11 when CLAUDE.md was condensed. Nothing was deleted:
 every trap, measurement and rationale referenced from CLAUDE.md's one-line
 summaries is argued in full here. Append new detailed write-ups here;
 CLAUDE.md gets only the distilled rule/trap line. -->

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
    retract.py    plan_retraction(): what removing a finding costs the
                  library — delete the phantom, keep what a human vouched
                  for (P2.10)
    text.py       book_key() over booksnap.catalog.normalize — NOT a copy
    search.py     Hebrew search SEMANTICS: parse + rank, pure and portable
    tenancy.py    Account/Library/Membership/Role — §4.1's boundary, and
                  NOT a place (P3.1)
  ports/        Protocols: Principal, Clock, IdGen, BookStore, ShelfStore
    blobs.py      BlobStore — image bytes, keys in rows (D1)
    decisions.py  DecisionStore — standing §5.4 answers (P2.5)
    duplicates.py DuplicateQueue — the durable "duplicates to resolve" queue (P2.6)
    tenancy.py    TenancyStore — the ONE store scoped by account, not by
                  library (P3.1)
  adapters/     implementations behind the ports
    sqlite_store.py  the real one (D1); connection per operation, WAL
    disk_blobs.py    uploaded photos; content-addressed, EXIF-normalised
    memory_store.py  the API ring's store, and the contract's 2nd implementation
    migrations.py    versioned schema via PRAGMA user_version (H6)
    legacy_import.py work/*.json -> entities; I/O and PURE mapping split
  reconcile_apply.py  turns a classified Diff into writes (P2.5); also the
                  P2.6 queue's open/close bookkeeping and P2.10's
                  retract_finding()
  api/          FastAPI routers under /api/v1 + DTOs. THIN — no rules
    routers/meta.py   service + library identity
    routers/books.py  list / get / patch / delete / manual add / export
    routers/shelves.py  shelves + captures; the capture→shelf binding (P2.2)
    routers/reads.py  start/poll/stop a read; diff/apply (P2.4/P2.5);
                      retract/restore one finding (P2.10)
    routers/duplicates.py  the durable queue: list/answer/skip (P2.6)
    routers/libraries.py   list/create/rename; the only account-scoped
                      routes, and the only ones exempt from H2 (P3.1)
  api/openapi.json          committed contract, regenerated, never hand-edited
  main.py       the composition root — the ONE file allowed to cross layers
  web/          React + Vite + TS client; talks only to /api/v1
    src/lib/        books.tsx (the store), i18n.tsx (he/en + dir), route.ts;
                    library.tsx + LibrarySwitcher.tsx — which library the
                    client is looking at, and the app-bar control (P3.1)
    src/books/      Tab 1: Toolbar, FilterBar, Feed, AddBookModal
    src/book/       the book surface: ONE renderer, drawer + page mounts
    src/capture/    Tab 3: useCapture.ts, intake rows, review panel + claim
                    row/why?/§5.4 prompt (P2.7); the image workspace —
                    useImageWorkspace.ts, ImageWorkspace.tsx, and the
                    FindingList/findingOps both surfaces share (P2.10)
    src/shelf/      the shelf-detail screen: useShelfDetail.ts, ShelfPage.tsx,
                    ReadHistory.tsx — mounted at #/map/<shelfId> (P2.8)
    src/styles/     tokens / base / books / capture / shelf — palette ported
                    from the mock (shelf.css has no mock reference; see P2.8)
  staff_api/    the SYSTEM-admin service — cross-tenant, READ-ONLY, its own
                port (:8758) and its own credential. NOT a role inside the
                product; see "Two admins, two applications"
  admin/        the system-admin CLIENT (:5174). A third application, talking
                to staff_api for everything it SEES and to /api/v1 for the
                little it may CHANGE
```

Applications coexist rather than merge, by design (plan H1/D2, "strangle,
don't refactor"): the tuning server on `:8756` `/api/*`, the product on `:8757`
`/api/v1/*`, and — since 2026-08-10 — the system-admin service on `:8758`
`/api/staff/v1/*`. Run the product with
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
  added. P3.1 adds the one exemption, as a CLOSED list: `/api/v1/libraries`
  is how a caller learns which libraries it may name, so requiring it to
  resolve one first is circular — a second meta-test asserts the exempt
  routes still resolve an ACCOUNT, so "exempt" never comes to mean
  "unscoped";
- no module-level mutable state in `app/` (the tuning server's global job dict
  is exactly what a second tenant breaks).

**Both services' contracts are committed and generated — four artefacts.**

    app/api/dto.py       → app/api/openapi.json       → app/ui/src/api/schema.d.ts
    app/staff_api/app.py → app/staff_api/openapi.json → app/admin/src/api/staff-schema.d.ts

The product's types live in the SHARED client package because both clients
call `/api/v1`; the staff service's live in the console because nothing else
speaks that protocol. After any DTO or route change on EITHER service run
`python tools/api_contract.py --write` and commit all four; `--check` fails
the commit on drift, reporting every stale artefact rather than the first.
This is why a renamed field is a client *compile* error instead of a runtime
surprise — including on the staff side, which was hand-mirrored until
2026-08-10.

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

The clients are separate, optional installs — nothing in the recognition core
or the tuning server needs them. **One install per client is enough**; each
pulls in the shared library through its own `postinstall`:

```bash
npm install --prefix app/web     # the household's client (+ app/ui)
npm install --prefix app/admin   # the operator's console (+ app/ui)
```

⚠⚠ **The `postinstall` is load-bearing, and the reason is not obvious.**
`app/ui` is consumed as SOURCE through a path alias, so a client COMPILES
files that live over there — and TypeScript resolves `@types/react` for them
from `app/ui/` upward, not from the app. A fresh clone that ran only
`npm install --prefix app/web` therefore got a client whose ring passed
**103/103** and whose `npm run build` failed with `Property 'value' does not
exist on type 'SelectProps'`, because `SelectHTMLAttributes` had silently
resolved to nothing. Measured, not assumed: `dev` and the tests survive it
(vite resolves React through `resolve.dedupe`) and only the typecheck breaks
— which is the worse of the two, arriving later and pointing at a component
instead of at a missing install.

`app/ui/check-installed.mjs` runs before `build` and `typecheck` in both
clients and refuses with the one command that fixes it — for the paths that
skip lifecycle scripts (`npm ci --ignore-scripts`), where the postinstall
never runs. `app/ui/src/install.test.ts` pins the postinstall itself, so it
cannot be removed as noise by someone who has all three installed and
therefore cannot reproduce the problem.

Read the `resolve.dedupe` ⚠ in both clients' vite configs before touching
either.

**Node 24 LTS (>=24.15.0)** — declared in `app/web/package.json` `engines`, so
npm says so rather than it being tribal knowledge. Node 22 is maintenance-only
now; the floor is the active LTS line. Installed here from the official MSI
(`winget install OpenJS.NodeJS.LTS`), not a version manager.

## Tests

**`python tests/run_all.py`** runs everything and **exits non-zero on
failure** — the individual `test_*.py` `__main__` blocks print PASS/FAIL and
then exit 0, which is fine for a human and useless as a gate. Pass module
names to run a subset (`python tests/run_all.py test_api`); `-j N` /
`--serial` set the worker count, `-v` prints a line per test with its cost.

**`python tools/check.py`** is the whole gate in one command — the python
rings, the API contract, the client rings, the client typecheck, the sweep and
the spotchecks, run CONCURRENTLY against a core budget and all reported
together. The pre-commit hook is now only the part that decides *which* of
those apply to the staged files; `--product` / `--web` / `--accuracy` pick the
same subsets by hand.

| module | count | what it protects |
|---|---|---|
| `test_core.py` | 52 | matcher / normalize / evidence gates |
| `test_integrations.py` | 24 | catalog + fallback adapters, fully mocked/offline |
| `test_domain.py` | 136 | the VISION rules that can be silently reversed |
| `test_store_contract.py` | 204 | one store spec × every implementation + isolation |
| `test_reconcile_apply.py` | 27 | `app.reconcile_apply` writing a `Diff` through real stores |
| `test_legacy_import.py` | 21 | `work/*.json` → entities, against a committed fixture |
| `test_search.py` | 15 | Hebrew search, against 24 real queries on the real 251 books |
| `test_layering.py` | 14 | the one-way import rules (plan H1), including the two services' boundary |
| `test_api.py` | 148 | `/api/v1` shapes + the versioning/tenancy meta-tests |
| `test_reader_wiring.py` | 8 | WHICH catalog the product hands the engine |
| `test_jobs.py` | 10 | the bounded, per-tenant-fair job queue (P3.4) |
| `test_blob_lifecycle.py` | 9 | the orphan collector's under-delete guards (P3.5) |
| `test_merge_library.py` | 11 | retiring a mis-modelled library into its collection |
| `test_staff_api.py` | 24 | the cross-tenant read model + its credential |

⚠ **A `unittest.TestCase` module is collected as ZERO tests and still reports
`ok`.** `run_all.py`'s discovery rule is module-level callables named `test_*`
(`_test_names`), so a class-based suite passes the runner while asserting
nothing. `test_staff_api.py` arrived that way from the staff-console branch
and was converted; if a module ever shows `0/0 passed`, that is the reason,
not an empty file.

⚠⚠ **That trap fired a second time, and the second time is the instructive
one.** A parallel session — working from a base that predated the conversion —
rebuilt the staff suite as `tests_staff/`, class-based, with its own runner and
its own gate flag, and added four tests to it. All 23 passed under
`unittest`, and every one of them would have been collected as **zero** by
`run_all.py`. Two sessions, one file, two shapes: the tests were ported into
the module-level form here, and the separate runner deleted. If you are adding
to this module, write a plain `def test_…()` — a class is silently invisible.

**703 python tests** as of the two-application tidy-up, which folded that work
back onto this base: +5 layering rules (the staff service imports no product
route, no adapter, no migration and not `app.main`; the product imports
nothing from the operator's service — each planted and watched to fail) and +4
staff-service rules (a route meta-test over `app.routes` after the
hand-written list was found to be missing one of six; the 503 a schema that
moves under a RUNNING service now answers; and the two structural guards on
opening a connection). They run alongside **187 client tests** in three
packages — `app/web` 103, `app/admin` 54, `app/ui` 30.

Before that, 627 as of P3.1 (+51: the tenancy rules, ONE store spec run
against a sixth aggregate, the v12 backfill, the resolver's three cases and
its 404-not-403, the two meta-tests that keep the account-scoped
exemption honest, the query-parameter escape hatch an `<img>` needs, and the
standing "no" a deletion records). Before that, 576 at P2.10 and the owner's feedback rounds
(+50: the retraction rule, a photo's runs across both store implementations,
`retract_finding`'s writes, the workspace routes, the approval reversal —
which also REPLACED the test that asserted an AUTO claim auto-enters — and
the sighting-resolution rule found live). The jump before that was the catalog-wiring fix's
`test_reader_wiring.py`, which exists because the product silently handed the
engine a 57-entry stand-in catalog and a real shelf matched nothing.

### The suite is fast on purpose (2026-08-10)

The python rings took **80s** and the client rings **38.6s**; they are now
**19s** and **25s**, with the same 627 + 98 tests and nothing skipped. A gate
nobody waits for stops being a gate, so this is a correctness property, not a
comfort. What it cost, in the order the time actually went:

- **one test slept 22.5s.** `test_nli_transport_failure_is_safe` injected a
  transport that raises, and `_fetch` retried it with a 1.5s backoff, five
  queries deep — 28% of the whole python suite spent waiting for a network
  that was never going to answer. The test now zeroes `retry_backoff` and
  asserts the retry COUNT and `failed_fetches` instead, which is strictly more
  than the sleep proved;
- **FastAPI 0.141 resolves a route's dependency graph lazily, on that route's
  first request** — ~50ms per app, and `test_api.py` built 153 apps. Apps are
  now pooled and rebound through `app.api.app.bind_ports` (extracted from
  `create_app`, so `_always`'s pydantic deep-copy trap is still exercised).
  ⚠ Apps are returned at the END OF THE TEST, via a `after_each()` hook
  `run_all.py` calls, **not** when a client closes: a large family of tests
  here writes `c = TestClient(_app(...))` with no `with`, so recycling on
  `__exit__` returned almost nothing (135 apps for 138 tests; it is 3 now);
- **`import booksnap.catalog` cost 6.4 seconds.** `booksnap/__init__.py`
  imported `.pipeline` eagerly, which pulls `segment` → scipy.signal + cv2. The
  layering rule that lets `app/domain/*` import `booksnap.catalog` *and nothing
  else* exists precisely to keep the domain free of that, and the package's own
  `__init__` defeated it — every domain module, every store, and the product
  server's startup paid it. Now PEP 562 lazy, with the same public surface.
  `app/adapters/booksnap_reader.py` imports `Pipeline` inside `read()` for the
  same reason: `unavailable()` and the DTO mapping do not need the CV stack;
- **`starlette.testclient` starts an event-loop thread per `with` block.**
  `tests/_fastclient.py` lends one process-wide portal instead. It substitutes
  only what `anyio.from_thread.start_blocking_portal` returns, for the duration
  of that one call, so starlette keeps doing its own lifespan and streams;
- **`test_store_contract` re-derived a byte-identical schema 109 times.** Each
  sqlite store now starts from a copy of one migrated template (the whole
  directory, because WAL leaves a `-wal` beside the file). The constructor
  still runs `migrate()` — which is what a real deployment does on a current
  file. The MIGRATION tests still build their own old-version databases;
- **`require('jsdom')` costs 3.5s on this machine** and vitest builds the
  environment once per test FILE. `isolate: false` + `maxWorkers: 2` in
  `app/web/vite.config.ts`; `src/test/setup.ts` gained the global reset that
  pays for the sharing. Measured, so nobody re-derives it: happy-dom is *not*
  the fix (3120 files, **22s** to require), and 2 workers beat both 1 (31.7s)
  and 4 (28.4s);
- **`userEvent`'s direct API pauses between every event.** 66ms per click
  against 15ms; a 12-character `type`, 235ms against 31ms. `src/test/user.ts`
  is the same API with `delay: null`, still a fresh session per call.

⚠ **`tests/run_all.py` shards across PROCESSES, and each worker runs its tests
sequentially.** Not a preference: `test_reader_wiring` swaps
`BOOKSNAP_CATALOG_BACKEND` and `test_api` pops Google/NLI credentials out of
`os.environ`, both safe against another process and silently wrong against
another thread. The shared portal and the app pool assume it too.

⚠ **Discovery happens in the worker, from the module's own `vars()` — never in
the parent and never from the source text.** Enumerating in the parent costs
12s of serial imports before the first test runs, and an AST walk finds **10**
of `test_store_contract.py`'s 202 tests, because 192 of them are generated at
import time (one spec × every implementation) — the other 192 would vanish with
no error at all. Each shard reports how many tests it saw; the parent fails the
run if the shards disagree or if they did not, between them, run all of it.
Mutation-checked: making a shard drop one test fails every module by name.

⚠ **The two measurements to distrust on this machine.** It is a 4-core i5 with
no hyperthreading, so parallel gains are modest and wall-clock numbers move
±20% with whatever else is running. And loading a package of many small files
costs ~5ms *per file* here — jsdom's 650 files are 3.5s, of which only 0.75s is
reading them. That smells like real-time AV scanning of `node_modules`; an
exclusion for the repo would speed up npm, vite and this suite together, but it
is a machine setting for the owner to make, not something the repo can fix.

**Test the real input, not a fixture you invented.** Added after uploads
shipped broken with a green suite (see the MPO warning under "Images are
real"): every test image was one the tests generated, so they validated the
code against the same model of the input that wrote the bug. Where real inputs
exist on this machine but cannot be committed (`work/` is gitignored), the
pattern is the spotchecks': a **committed fixture that reproduces the real
shape** plus a **self-skipping test over the real data**. One proves the shape
on every clone; the other catches the day reality stops matching the fixture.
Applies to photos, OCR text, and anything else arriving from the physical
world.

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

⚠ **The product did not read `.env` at all until 2026-08-08.** Only
`booksnap/server.py` had a `_load_dotenv`, so `:8756` could reach the
catalogues and the LLM reader while `:8757` silently could not — and nobody
noticed, because the product's default mode was the free offline one.
`app/main.py` now has its own copy (a COPY, not an import: the product must
not import the tuning server, and eight duplicated lines are the intended
cost of H1).

⚠ **`:8757` and `:5173` bind `0.0.0.0`, not loopback.** Capture is a PHONE
flow — photograph a shelf, upload from the camera roll — so a server only its
own machine can reach cannot do the one thing the tab exists for. The tuning
server always bound all interfaces; the product's `127.0.0.1` was an oversight
that made the phone hint in its own UI a lie. Note this is an **unauthenticated
API on the LAN** until pillar 4 lands login; that is a deliberate,
single-household trade, not an oversight.

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

## ⚠⚠ The product must hand the engine the SAME catalog (2026-08-09)

A real shelf read **69 spines correctly and matched zero books**. It looked
exactly like an engine regression. Nothing was wrong with the engine.

`BooksnapReader._build` had `if backend == "nli": … else: LocalCatalog(...)`
and no `simania` branch — so the owner's correctly-set
`BOOKSNAP_CATALOG_BACKEND=simania` fell through the `else` and loaded
**`sample_catalog.json`, the 57-entry hand-typed stand-in** from early
prototyping. 69 real Hebrew titles were matched against 57 books.

The reasoning that produced it, recorded because it is the trap: the simania
chain was judged "prototype-grade and not part of the measured baseline". That
is **backwards**. Every measured number in this file comes from that chain
(`sweep --live --sources simania,nli,…`, baseline row 20260806-142543, and
`booksnap-ui`'s own `launch.json` env). `local`/`sample_catalog.json` is the
stand-in the honest-results section calls "a 57-entry hand-typed stand-in
catalog". After the fix, the same photo: **15–17 matched of 35**, real books
(MacLean, Wouk, Philip Roth, Clavell, Čapek).

Three rules now hold, each mutation-checked in `tests/test_reader_wiring.py`:

- **the product's default IS the chain.** A product whose out-of-the-box
  catalog is the stand-in is broken for its actual purpose; `local` is opt-in
  for offline work;
- **an unrecognised backend RAISES.** Quietly degrading to the sample catalog
  is what turned a one-line config gap into an afternoon of "why does the
  engine find nothing". The refusal names the risk;
- **the confirmed library joins the chain from the PRODUCT's store**
  (`app/adapters/library_catalog.py:ProductLibraryCatalog`), never
  `booksnap.library.ConfirmedCatalog` — that one reads `work/library.json`,
  which belongs to the tuning server. Same idea, correct store. Note the
  asymmetry with the sweep, which excludes the confirmed library on purpose
  (there it is an *outcome* being measured, here it is evidence); do not
  "fix" the inconsistency by making them agree.

The general lesson, which is the same one MPO taught in a different costume:
**when the product wraps the engine, the wrapper's defaults are part of the
engine's accuracy.** `second_pass_retrieval`, the matcher gates and the
post-match path all came through `Pipeline.run_page` untouched — the one thing
the product chose for itself, the catalog, was the one thing that was wrong.
Anything else the tuning server configures through env or `launch.json` is a
candidate for the same bug; check `booksnap/server.py`'s `_build_*` against
`BooksnapReader._build` when either changes.

## The default reading mode is `llmpage` (owner, 2026-08-08)

The Capture tab preselects **LLM reading**, and `ReadCreate.mode` defaults to
it server-side. The modes are listed best-first, so the default is also first —
a default sitting third down a list reads as an afterthought rather than a
recommendation.

This does **not** contradict "deterministic first". That rule is about not
paying an LLM for work cheap deterministic code can do — it was never an
argument for making the *worse reader* the one everybody meets first. The
measured gap is not close: the spine path costs ~10s/spine and tops out around
76% title-correct, and this file already recorded llmpage as the engine's own
default. Tesseract stays, stays free, and stays the answer when no key exists.
Cost is stated **on the control** (`~$0.15/photo`), because the place to say
what something costs is where the choice is made; metering proper is P5.1.

**A mode whose credential is missing is refused at the door with 409**, and the
refusal says what to DO ("set it in .env and restart"), not merely what is
absent. A read runs in a WORKER THREAD, so a missing key discovered there
surfaces as a `failed` read with a traceback in a log nobody is watching,
minutes after the click — and the owner is left guessing whether the photo, the
shelf or the engine was the problem. `booksnap/server.py:start_run` learned
this first; this is the product's own copy.

⚠ **The preflight lives on the `Reader` PORT, not in the route.** Which
credential which engine needs is the adapter's knowledge. A first draft put an
`os.environ` check in `reads.py` and it was wrong twice over: it coupled the
route to whichever adapter was bound, and it broke the API ring, whose
`StubReader` needs no environment at all — which is exactly the property that
keeps that ring offline. `Reader.unavailable(mode) -> str | None` is the seam.

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

⚠⚠ **A synthetic image is not a sample of the input domain — MPO.** Uploads
shipped broken and every test was green. A "JPEG" out of a modern iPhone or
Samsung is usually a **Multi-Picture Object**: a JPEG container carrying a
second embedded frame (HDR, depth, the second lens). PIL reports
`format='MPO'`, the accepted-format whitelist listed only JPEG/PNG/WEBP, and
so **every real photo 415'd** — including all of the owner's, every one of
which is MPO. The tests passed because `Image.new(...).save(format='JPEG')`
produces plain JPEG. Frame 0 of an MPO is an ordinary JPEG, which is what
browsers and cv2 both read, so it is accepted and served as `image/jpeg`.

The generalised lesson, and the reason this is the loudest warning in the
file: **the repo had the real photos in `work/` the whole time and the tests
used images they generated themselves.** A fixture you construct tests the code
against your own model of the input, which is the same model that wrote the
bug. `tests/test_api.py` now carries (a) `_mpo()`, a GENUINE MPO written by
PIL's MPO encoder, committed and always run, and (b)
`test_the_owners_real_photos_upload_if_they_are_on_this_machine`, which walks
`work/library/*.jpeg` and **self-skips** on a fresh clone — the same shape as
the spotchecks, and the only test that runs the real input domain through the
real validator.

⚠ **HEIC is the next one waiting.** It is the iPhone default whenever the
camera is not set to "Most Compatible", and PIL cannot open it without
`pillow-heif`. Rather than "not a decodable image", the refusal sniffs the
container magic and names the format with the fix ("Settings → Camera →
Formats → Most Compatible"). Supporting it properly means adding `pillow-heif`
— worth doing the first time a real HEIC actually arrives, not before.

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

**"Alternatives" was READ-ONLY, and stopped being so on 2026-08-09.** P2.7
cut UI_PLAN §4's "one-click acceptable" for a good reason — the domain had no
operation to re-point an already-classified claim, and inventing one (a new
outcome, a new `AnswerKind`, a write path) was a real domain addition. The
operation then arrived from somewhere else entirely: *"nothing enters the
library unapproved"* made every machine finding a pending question, and
`AnswerKind.CONFIRM` carries an optional title/author so a human can approve
one AS CORRECTED. Accepting a runner-up is exactly that with the candidate's
text; a settled finding takes the other existing door, `PATCH /books/{id}`.
So there is STILL no "override this claim's match" op and there needs to be
none — the claim keeps the engine's reading (evidence), the book gets the
human's answer. The panel is now labelled *"try a better match?"* and each
candidate carries a **use this**; the rejection reasons stay, because "why
not this one" is what makes a ranked list judgeable — and they are ENGLISH
always, hardcoded in `booksnap/match.py`, shown verbatim rather than
mistranslated by guessing.

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

## Reads apply themselves now (P2.9) — client-driven apply was a real bug

Live phone use found the bug this item fixes: upload a photo (worked) → press
Run (started) → switch to another app → come back — Run was idle again and
**no books had appeared**. Refresh the tab → **the photo was gone too**. Two
separate causes, both in `useCapture.ts`, both structural:

**Bug A — applying a settled read was CLIENT-DRIVEN**, contradicting §5.6's
own inversion ("a read is an event that UPDATES the list", not one that waits
to be told to). `reads.py`'s job already reconciled at settle to capture
P2.8's `diff_summary`, but nothing ever *applied* that diff — the only thing
that ever called `POST .../apply` was the browser's own poll loop noticing
`status !== 'running'`. Mobile browsers throttle or fully suspend a
backgrounded tab's timers, and a refresh drops the loop's state entirely, so
a read could complete, its claims and summary land in `work/product.db`, and
the library still never change.

**Fix**: `_job`'s `run()` in `app/api/routers/reads.py` now calls
`app.reconcile_apply.apply_diff` itself, right after computing the P2.8
snapshot, reusing the SAME `diff` object `summarize()` just consumed — never
a second `reconcile()` call, which is what would let a book this very apply
just added reclassify as `unchanged` in the summary meant to record it as
`added`. `answers=()`: only the buckets `reconcile()` already settled with no
human input (added/unchanged/corrected) are written; a `needs_decision`
claim is NEVER auto-resolved — an `ambiguous_location` one opens in the
duplicates queue exactly as an unanswered `POST .../apply` would leave it,
and a `review_tier_new_book` one just stays open. `start_read` now resolves
a `DuplicateQueue` (`get_duplicate_queue`) and threads it into `_job` for
exactly this. The client's `commitDiff` still calls `POST .../apply` on
every settle (kept, not removed — see "Idempotency" below for why that is
safe rather than a duplicate-write risk); the two together are the reason
`_job` also gained a `ShelfStore` parameter, since `apply_diff` needs one to
re-verify the shelf still exists.

⚠ **The local `try/except` around `apply_diff` is not tidy, it is
LOAD-BEARING — proved by temporarily deleting it.** By the point `apply_diff`
runs, `current.status` is already terminal (`finish_read`/`stop_read` ran
earlier in the same function). Removing the `try/except` and letting a
failure reach the outer `except Exception as exc: current = fail_read(...)`
does not produce a `failed` read — `fail_read` itself raises
`ReadAlreadyFinished` when called on an already-terminal `Read`
(`app/domain/read.py`'s own `_end`), and THAT exception is uncaught, killing
the job thread before it reaches `reads.save_read` at the bottom. The read is
left showing `running` forever — worse than the bug this item fixes. Confirmed
live in `test_a_failed_automatic_apply_does_not_fail_the_read`: without the
local catch, the test times out waiting for the read to settle at all.

**Idempotency is not assumed, it is the reason both call sites are safe
together.** `Provenance.sighting = (run_id, spine_id)` (`app/domain/book.py`)
makes `observe()` idempotent, and `reconcile()`'s own `_copy_at` check means
a claim already applied here resolves as `unchanged` — same location,
same copy — the next time anything reconciles it, including the client's own
follow-up `commitDiff` call. `test_the_automatic_apply_is_idempotent_
against_a_later_client_apply_call` calls `POST .../apply` twice AFTER the
automatic apply already ran and asserts one book, one copy, one sighting.

**Bug B — the intake queue and any run state were session-only React state**,
with no hydration on mount, even though the shelves/captures/reads it
displays are all durable server-side already (P2.2-P2.4). Fixed in
`useCapture.ts`'s new `hydrate()`: `GET /shelves`, then per shelf (concurrently)
`GET .../captures` and `GET .../reads` — no new endpoint, because
`ShelfStore.list_shelves`'s own docstring says a personal library has *tens*
of shelves, and a few dozen requests once on mount is not the N+1-per-render
shape that would justify inventing an aggregate index. **In-flight reads are
RE-ATTACHED, never restarted**: a `running` read found in the per-shelf
history becomes a `RunState` exactly like `start()`'s own, and the existing
poll effect picks it up from there — confirmed live (see below), where a
read still `running` at reload showed *"קורא…"* again immediately after the
photo list reappeared, with only ONE `POST .../reads` ever hitting the
server log for that read.

`visibilitychange` now also triggers an immediate poll of every running read
(`pollRunning`, extracted from the interval body so both share it) — a
backgrounded tab's timer may not have ticked in minutes by the time the owner
switches back, and waiting for the NEXT tick was never really the bug but is
worth not reintroducing.

⚠ **React 18 StrictMode double-invokes a mount effect in dev** (setup →
cleanup → setup, same instance) — `hydrate()` would otherwise run twice
concurrently, and since its `known`-capture dedup set is only computed once,
after all its `await`s, two overlapping calls can each miss the other's
in-flight `setItems` and double every rebuilt row. Guarded with a plain
`useRef` flag (`hydratedRef`) that survives the double-invoke because the
component instance itself is never actually unmounted.

⚠ **`CaptureDTO` has no filename to give back.** A hydrated row's `filename`
falls back to the image's own storage key (`image_id`) — honest, if less
friendly than the original upload name, which the server never stored.
`file` on `IntakeItem` is now `File | null`: `null` for anything hydrated,
since its bytes already left the browser and there is nothing to re-POST if
`retryItem` were ever reached (it never legitimately is — a hydrated item is
always `'ready'`, not `'error'`).

Verified live against the real `work/product.db` (snapshotted before,
restored after — see "Copies & lending" for why this is now routine).
⚠ **`preview_start` REUSED an already-running `product-api` process** left
over from before this fix — exactly the "no `--reload`" trap this file
already warns about, caught before it cost anything only because it is
already a known trap: stopped and restarted explicitly before any live
check, since a reused process would have silently verified the OLD,
client-driven-apply code and called it fixed. A real
photo through the real `llmpage` engine was run, the page was hard-reloaded
mid-read via `location.reload()`, and after it came back: the photo was
still listed with a `readStage` badge, the review panel re-appeared reading
"קורא…" without a second read being started, and it settled into the
correct `diff_summary` moments later with no manual apply click anywhere in
the session. A second, throwaway low-resolution test photo produced zero
identifiable claims (a real, honest outcome — not this fix's concern; OCR
accuracy on a resized synthetic crop is not what P2.9 changes), which is
also why the "`added` > 0 visible in the Books tab" half of this fix rests on
the Python ring's `test_a_settled_read_applies_its_diff_with_no_client_call_
at_all` (a `StubReader` claim that resolves to a real match) rather than on
a screenshot.

## The image workspace (P2.10) — the tab is a workspace, not a pipeline

§12.2 #10, settled by the owner 2026-08-09: the first build of the Capture
tab read "capture" as **drop → run → review-now**, so a settled read had no
route back and the only visible action on a processed photo was *re-run on
selected* — which costs money, costs time, and invites re-deciding questions
already answered. The shape that replaces it:

> **the image is the durable object; runs hang off the image; findings hang
> off the run** — and each finding can be approved / edited / removed, the
> loop the engine POC already had.

This is a split by SURFACE, not a reversal of §5.5 ("a run is not a
user-facing concept"). Books and the shelf view stay run-free; there is still
no global list of runs. `GET /captures/{id}/reads` is the one run-shaped
question the product answers, and it answers it where the unit of work really
is the photograph.

**`ReadStore.list_reads_for_capture` is a store method, not a filter over
`list_reads(shelf_id)`, and that is the whole reason it exists.** A capture
can be RE-BOUND to another shelf or row after it was read (P2.2's intake
correction), and its earlier reads stay filed — correctly — under the shelf as
it was then. Deriving a photo's runs from its CURRENT shelf loses exactly the
history a workspace is for, and loses it only for the photos someone had to
correct. Same reason `useImageWorkspace` addresses every write to
`run.shelf_id`, never to the photo's current shelf.

⚠ The SQLite side narrows with `LIKE '%"<capture_id>"%'` over the v7
`capture_ids` JSON column (json1 is not guaranteed present) and then confirms
membership in Python. The confirmation **survives mutation testing** — the
quoted needle is already exact — and it stays anyway, recorded in the contract
test rather than left looking like a gap: it keeps the SQL a pure *narrowing*
clause, so an index- or FTS-shaped rewrite can be judged on speed alone.

**The three actions, and where each rule lives:**

- **approve** — `POST /books/{id}/approve` over the existing domain
  `approve()`, which had no route until now. Idempotent and never a demotion
  (`Status.merge`), so the button simply disappears once the book is
  `approved`;
- **edit** — the ordinary `PATCH /books/{id}`. H3: the workspace does not need
  a third way to write a title;
- **remove** — `POST .../reads/{rid}/findings/{cid}/retract`, and the only one
  with a rule worth arguing about. It sits between two rules of this codebase
  that point in opposite directions: *precision is the expensive metric — a
  phantom rots silently* says delete it, and UI_PLAN §5's *remove-from-shelf
  is not delete-from-library* says do not. `app/domain/retract.py:plan_retraction`
  is where they meet:

  > the library record is deleted only when **this read created it** — one
  > copy, standing here, every sighting on it from this read, and the record
  > itself no older than the read. Anything with a life of its own is merely
  > taken off this shelf.

  (That is the SECOND version of the rule; the first asked "has a human
  vouched for this?" and stopped meaning anything the same day — see
  "Nothing enters the library unapproved" below.)

  ALWAYS, in every branch, a standing `Decision` is recorded at
  (shelf, depth, book_key) — §5.6, or the very next read puts the phantom
  straight back. That is why `plan_retraction` returns a decision kind even in
  the `NOTHING` case (nothing left here to remove, and the answer still has to
  survive). `ambiguous_location` records `WRONG_BOOK` rather than `REJECTED`:
  the same suppression, but the audit trail says which question was answered.
- **undo** — `.../restore` is composed from two things that already existed
  rather than a third write path: `DecisionStore.delete_decision` (its own
  docstring calls it "the undo of a mis-click") then the ordinary
  `apply_diff(answers=())`. So an AUTO claim returns as the book it was and a
  REVIEW-tier one returns to the open question it was, decided by the same
  `reconcile()` rules as any other apply — nothing re-reads the photo or
  invents a book. **409 when the finding is not actually suppressed**; silently
  doing nothing would look identical to success.

⚠ **`retract_finding` is deliberately NOT another `AnswerKind` on
`apply_diff`.** An `Answer` RESOLVES a question that is still open; a
retraction retracts something already settled and written, often days later.
Routing it through `answers` would also have the unconditional `unchanged`
loop re-`observe()`-ing the very claim being retracted in the same call, which
reads as a bug however it is ordered.

**A retracted finding stays on screen, greyed and struck through, with its
reason and its undo.** `DiffDTO.rejected`'s own contract already said why
("so a suppressed book has a visible reason"); before P2.10 the client simply
never rendered that bucket, which meant *"why isn't my book showing up"* had
no answer and the undo had nowhere to live. `ignored` is still not rendered —
a within-read duplicate or a titleless spine is noise, not a decision anybody
made.

**Two more actions the owner asked for the same day** (2026-08-09), both
sharing the machinery above rather than adding doors:

- **approve all** — one `POST .../apply` with a `confirm` per pending finding.
  `pendingApprovals()` computes both the button's COUNT and its ACTION, so
  they cannot disagree, and it filters to `new_book_unconfirmed` only: §5.4's
  duplicate question is a DIFFERENT question and must never ride along. That
  was the POC's own hard-won rule and it is mutation-checked here;
- **add a book by hand** — `POST .../reads/{id}/findings` files a MANUAL claim
  on the read (`add_manual_claim`, the one late-claim exception, guarded to
  MANUAL tier and to a settled read) and applies it. The spine id is minted
  `manual-<id>` rather than left blank: `Provenance.sighting` is
  `(run_id, spine_id)`, so a shared blank would make every hand-added book on
  one read the same sighting and `observe()` would swallow all but the first.

**One renderer, two mounts** (the same rule the book surface follows):
`FindingList` + `ClaimRow` are shared by the LIVE review panel and the
workspace, and `findingOps.ts` holds the four ops both call. "Right after the
read" and "a week later" are the same act — that IS §12.2 #10 — so two copies
of "what does ✕ do" would be two chances for one of them to be wrong. The
workspace passes a `captureId` and the live panel does not: a read covers
every capture at its (shelf, depth) (§5.7 #1 forbids a partial read of a row),
but the workspace was opened from ONE image.

⚠ **The run row and the findings under it deliberately disagree, and that is
P2.8's distinction made visible.** Verified live: the run reads
*"+2 added · 0 unchanged"* while its findings read *"+0 added · 2 unchanged"*.
The first is `Read.diff_summary`, the archived snapshot of what that read DID;
the second is `GET .../diff`, recomputed live against the library as it stands
now — which is what the ✓/✎/✕ act on. Anyone "fixing" the inconsistency by
sourcing both from one place will silently repaint every past read as having
changed nothing (the exact failure `DiffSummary`'s docstring argues at length).

Verified live against the real `work/product.db` (snapshotted before, restored
after): approve raised a book to `approved` and the button vanished; ✕ on an
AUTO-only book deleted it from the library and left the row struck through
with its reason; ↩ put it back on the same shelf; ✕ on an **approved** book
left it in the library with `shelf_id: null` — UI_PLAN §5's separation, over
real HTTP. Both languages mirror (`dir` rtl/ltr, strings translated).

⚠ The Browser pane did not composite frames this session either (screenshot
timed out, same as P2.8), so every check above is DOM structure and API state
— real verification of wiring, NOT of paint. `capture.css`'s new rules use
only existing custom properties, the same inference P2.8 recorded; re-verify
visually the next time the pane composites.

## ⚠⚠ Nothing enters the library unapproved (owner, 2026-08-09)

`reconcile()` used to auto-enter an AUTO-tier claim for a book the library had
never seen, mirroring `booksnap/library.py::absorb_auto_claims`. The owner
watched one real photo file **fourteen books he was never asked about** and
reversed it (VISION §12.2 #11). A read now produces **findings**; a finding
becomes a `Book` only through an explicit ✓.

This is a REVERSAL of a rule with a named test, so it is written down in three
places on purpose: here, VISION §12.2 #11, and
`test_nothing_a_machine_read_enters_the_library_unapproved`, which replaced
the test that asserted the opposite.

**What moved:**

- `_classify_one`: an unknown book at AUTO **or** REVIEW → `NEEDS_DECISION`,
  reason **`new_book_unconfirmed`** (was `new_book_auto` / `review_tier_new_book`).
  Tier no longer decides ENTRY, only presentation — which is what lets both
  tiers wear the same controls (the owner's item 7 in the same round);
- `ClaimTier.MANUAL` is new, and is the ONE tier that enters at once, at
  `Status.MANUAL`. `diff.added` now means exactly "a book the owner typed onto
  a photo" and nothing else, which is why `apply_diff` creates it MANUAL rather
  than AUTO;
- `AnswerKind.CONFIRM` gained optional `title`/`author` — *approve as
  corrected*, so ✎-then-✓ is one act and one write. The CLAIM keeps the
  engine's text; it is evidence, and `Claim` is frozen for that reason.

**Three consequences that look like bugs and are not:**

1. **`Read.diff_summary` leads with `needs_decision`.** "+0 added" is what an
   honest engine read produces now. The finding list under the run row still
   shows what each finding IS today, so the two lines disagree — that is
   P2.8's snapshot-vs-live distinction, argued at length in `DiffSummary`;
2. **`POST /books/{id}/approve` is nearly unreachable.** A confirmed finding is
   created APPROVED, so the only thing left for that route is raising a legacy
   `auto` record (one of P1.3's 251) that a read has re-found. Its test says so;
3. **the retraction rule had to be rewritten the same day.** v1 asked *"has a
   human vouched for this book?"* and deleted only `AUTO` records. Once every
   confirmed finding arrived APPROVED that branch became unreachable, so every
   ✕ would have left an unshelved phantom. v2 asks **"did this read create the
   record?"** — see below.

⚠ **`plan_retraction` needs BOTH the read's id and its start time**, and the
second one is the non-obvious half. A book that already existed and that this
read merely RECONFIRMED gets its first-ever sighting from this read
(`observe()` appends one), so provenance alone says the same thing about
"created here" and "found here". `Book.added_at >= read.started_at` is the
fact that actually separates them. A record with no `added_at` reads as OLDER,
never newer — the safe direction is always to keep the book. All four clauses
are mutation-checked.

## The Capture tab carries no shelf plumbing (owner, 2026-08-09)

*"Open the shelf →"* (P2.8) and *"add a row behind"* (P2.7) are both gone, and
their mutation tests with them. §5.7's argument that nobody discovers depth
unless it is offered early still stands — it just does not get answered on
this tab. **The tab is about images**; binding a photo to a place in the house,
including how deep the furniture is, is the Map tab's job (VISION §12.2 #12).
The depth PICKER stays: an already-stacked shelf still has to say which row a
photo shows.

Deleting a test for a control that must not exist is the point — a lingering
test is what stops the next person from finding the reason.

## ⚠ A claim is settled by its own SIGHTING, not only by its title

Found live on 2026-08-09, by picking a runner-up and watching the row stay
*"awaiting approval"*. A claim's identity is `book_key(claim.title,
claim.author)` — the text the ENGINE read, frozen forever because it is
evidence. But a human can answer a claim with DIFFERENT text three ways now:
approve-as-corrected, pick one of `explain()`'s runners-up, or edit the
book's title afterwards. The book that answered then lives under a different
key, so a keyed lookup alone reports the claim as still unanswered — the
finding stays pending forever and **the next click creates a second book**.

`reconcile._classify_one` therefore checks, FIRST: has this claim's own
`(read_id, spine_id)` already produced a copy standing at this (shelf, depth)?
`Provenance.sighting` is exactly that fact, so no new state was needed —
`_sightings_here` indexes it once per call, over a library the caller already
pays O(library) to load. Both scopes in that check are rules, not
optimisations, and both are mutation-checked: another read's sighting must not
settle this claim (that would skip §5.4), and a copy that has since MOVED is
genuinely not here (§5.7 #1).

The reason it shipped broken and green: the test asserted the corrected book
had the right title and stopped there. **A test that writes and never reads
back is testing the request, not the behaviour** — the same lesson P1.7's tag
parsing already recorded, in a different costume.

## The finding row reads like a book row

Title, then author, using `books.css`'s own `.t`/`.a` classes — a finding IS a
book claim, and reading one should not feel like reading a log line (owner,
2026-08-09). Two consequences:

- **the raw OCR text moved off the row** into *"try a better match?"*. It
  explains a finding; it does not identify one;
- **a settled row shows the BOOK's title/author, not the claim's.** The claim
  keeps the engine's text forever, so a row sourced from it would still be
  showing the typo minutes after someone fixed it. NOT for a `needs_decision`
  row: there `existing_book` is a *different* book — the one already elsewhere
  that §5.4 is asking about — and showing its title as this spine's would be a
  lie. Mutation-checked in both directions.

## Adding a book by hand asks the engine's own question first

*"Did this read already find this book?"* — `GET .../reads/{id}/findings/lookup`,
straight out of `booksnap/server.py:lookup`, whose docstring names the error it
exists for: *"the review flow's expensive human error is adding a book by hand
that the run DID find and the eye simply skipped (a 40-row shelf in a language
read right-to-left)."*

⚠ **Server-side, for the reason the engine's own version gives**: it reuses the
project's normalisation and ranking rather than growing *"a second, subtly
different JS implementation"*. Here that means `app.domain.search` — P1.5's
MEASURED Hebrew rules (nikud stripped, final letters folded, in-word geresh
deleted, leading particles tolerated in the query, P@1 1.00 on the fixture).
Verified live: typing `מנהרה` surfaces the stored `המנהרה`.

`search.TextEntry` is what made that reuse free: `haystack`/`matches`/`score`
only ever touch `normalized_title` and `normalized_author`, so a `Claim` can be
searched by the same rules a `Book` is without fabricating a whole Book (with
an id, a library, a copy) to ask a question about two strings.

Two scope calls: the lookup searches **all** of this read's claims, including
ones already approved, corrected or REMOVED — the book you retracted a moment
ago is exactly the one you might be about to re-add — and it **never blocks**
the add. Sometimes the right answer really is "add it anyway".

## "Approve all auto" means both kinds of unvouched-for

The owner went looking for the POC's bulk button and did not find one that
covered what he meant. Ours counted only *pending* findings; his photo's rows
were books already IN the library but still on the `auto` rung — one **Approve**
each, fourteen of them. Both are the same state to a reader: nobody has said
yes. So `approvableFindings` returns two lists and the button counts their sum:

  - pending AUTO-tier findings → confirmed through `POST .../apply`;
  - settled findings whose book is still `auto` → raised through
    `POST /books/{id}/approve`.

REVIEW-tier findings are deliberately NOT swept up — the POC's rule, and the
reason has not changed: a bulk click is not where you accept the engine's
low-confidence guesses, and those rows keep their own ✓ one tap away. §5.4's
duplicate questions are excluded for the stronger reason that they are a
different question entirely. Both exclusions are mutation-checked.

⚠ **A hand-typed book wears the "approved" badge too.** It is stored `manual`,
which OUTRANKS approved (§5.1's ladder) — but the badge only fired on the
literal `approved` rung, so the one record a human had typed with their own
hands looked like the one thing nobody had confirmed. The badge now fires for
anything off the `auto` rung; the stored status is untouched, because
downgrading manual to approved would throw away which of the two happened.

## One spine, several volumes

*"Split into volumes"* (owner, 2026-08-09): 2–5 parts, marked in Hebrew
letters (the default — that is how Hebrew volumes are marked on a spine),
numbers, roman numerals or asterisks, with a live preview because "א/ב" versus
"I/II" is a choice about what is printed on the owner's own books and no label
describes that as well as showing it.

**It needed no new server surface.** Part 1 IS the original finding, answered
with a corrected title — confirm-as-corrected while pending, a book patch once
landed, the two doors ✎ already uses — and parts 2..N are ordinary hand-added
findings on the same read. The volumes inherit the author.

That the original finding stays SETTLED afterwards, though its book is now
called something else, is the sighting rule doing its job: a claim is answered
by the book its own `(read_id, spine_id)` produced, whatever that book ended
up being called. The split is the second feature that rule silently made
possible.

The parts are filed **next to the part they came from**, not at the bottom of
the photo: `POST .../findings` takes an optional `after_spine_id` and mints
`<parent>~m<n>`, which `FindingList.placeVolumesAfterTheirPart` orders on.
Structure in the id string, the same way the engine's own `IMG_1234_b0_s07`
encodes a band and a position that `shelves.py` already parses back out — and
no new column for a relationship only ordering cares about. The counter is
per-parent so splitting the same finding twice keeps producing distinct ids
rather than colliding on `~m1`; the sort is NUMERIC, so `~m10` does not land
before `~m2`.

**The trigger is a link, next to *"try a better match?"*, captioned with one
word and a tooltip** (owner, 2026-08-09) — because it OPENS A PANEL, which is
what the link beside it does, rather than committing something, which is what
the three coloured buttons do. ⚠ Its confirm button needed a different label
from the link that opens it (*"create volumes"* vs *"split"*): two controls on
one screen announcing identically is the `t.edit`/`t.copy_edit` collision
again, and `getByRole('button', {name})` finds both.

⚠ The parts are written SEQUENTIALLY, not in parallel. Every call returns the
diff and the last one to answer wins; firing them together lets the response
for part 2 land after part 5 and paint a list missing three volumes that are
already saved.

## A run row shows how many findings, not what became of them

The workspace's run rows used to render `Read.diff_summary`. That snapshot is a
true record of what a read DID and a **bad status line**: remove a book and the
row still read *"1 awaiting approval"*, because a snapshot cannot know about
something that happened after it was taken (owner's report, 2026-08-09). The
claim count never goes stale, and the findings list below carries the live
state — which is where a reader looks once a run is open anyway.

The snapshot is not gone: `shelf/ReadHistory.tsx` still shows it, which is the
surface P2.8 built it for, where the question really is *"what did this read
change"* asked long afterwards. And the live findings line now counts
**removals**, which it never did — a retracted finding used to leave the
pending count and appear in no other, so the line silently under-reported what
had happened to the photo.

## The author field completes against the library

`GET /books/authors?q=` — distinct authors already in the library, narrowed by
the same `app.domain.search` matching as everything else, so *"the search
mechanism"* means one thing across this codebase. Retyping an author is how
`דויד גרוסמן` and `דוד גרוסמן` become two people the author chip then treats
as two shelves' worth of books; the tuning UI grew the same control
(`libAuthors`) for the same reason.

⚠ **A chosen author closes the list, and a `waitFor` cannot prove it.**
Filtering the exact match out of the next answer is not enough — the query
"ארנסטו סבאטו" still matches OTHER authors, so a settled field kept a list of
near-misses under it. A `chosen` flag, cleared the moment the owner types
again, is the fix. The test had to wait THROUGH the 250ms debounce rather than
poll: `waitFor` passes on its first tick (the list is empty the instant the
chip is clicked) and would go green against the very bug. Found by mutation
testing.

⚠ The suggestions render OUTSIDE the two labels. Inside one, the chips make
that field taller than the other and the inputs stop sitting level.

⚠ Returned in the AUTHOR's own spelling, never normalized. Normalisation is
for MATCHING — an autocomplete that filled in the nikud-stripped,
final-letter-folded form would quietly rewrite the library's own data one
accepted suggestion at a time. Mutation-checked.

## The match score is out of 130, not 100

`booksnap/match.py:330` computes `60·tcov_c + 25·tcov + 15·acov +
0.30·title_sim`, so a flawless match scores **130**. The review UI used to
render a bare `130` beside the tier, which reads as a broken percentage — the
owner asked what it meant, which is the bug report. It now renders `130/130`
with the formula in the tooltip. If the weights in `match.py` ever change,
`MAX_SCORE` in `ClaimRow.tsx` is the one place that has to follow.

## Tenants: accounts, libraries, memberships (P3.1) — pillar 3 begins

The first item of pillar 3, and the one that makes "the library" stop being a
constant. `app/domain/tenancy.py` (Account / Library / Membership / Role),
`app/ports/tenancy.py`, both adapters, schema **v12**, `/api/v1/libraries`,
and the app-bar switcher. **The resolver stops being hardcoded**; there is
still no login (P4.1) and roles still permit nothing (P3.2).

**`Library` and `LibraryRef` are two types for one thing, on purpose.** The
REF is the tenant key — tiny, on every store method and every persisted row
since P1.0, deliberately unchanged. The ENTITY has a lifetime, gets renamed
and is listed in a switcher. `Library.ref` is the one-way door, so nothing
downstream has to know which it was handed.

⚠ **Library is not Place** (§4.1's own warning; *Place* is the settled noun,
*PhysicalLibrary* its retired synonym). Library is the
PERMISSION boundary — "the Malin family collection". A place you keep books
(home, office, parents') is an address inside it, and addresses arrive with
the map (plan §1.1). `test_a_library_is_not_a_place` asserts the absence
structurally, the same shape as P2.1's shelf-address test and for the same
reason: the tempting mistake is to add `place` here "while we're at it".

**Rules that live in the domain and are each mutation-checked:**

- **creating a library returns the library AND its admin membership**, from
  one call. A library saved without one is invisible to the person who made
  it (listing is BY ACCOUNT) and administrable by nobody — a state a caller
  that forgot the second write could otherwise reach;
- **a library is created, and kept, named** — the deliberate asymmetry with a
  shelf, whose label is optional *because identity is free* and an unnamed
  shelf is shown by its own photograph. A library has no photograph; it is a
  row in the switcher, and two blank rows are two libraries the owner cannot
  tell apart (§4.3: "create a Library, **name it**");
- **the last admin cannot be demoted or removed.** §4.2 gives only an admin
  "invite/remove members, change roles", so a library whose last admin steps
  down can never invite anyone again — an unadministrable tenant that only a
  database edit rescues;
- **a Role says who you are, never what you may do.** §4.2's matrix is P3.2's
  item — data, with ONE enforcement point — so a `can()` here would be a
  second enforcement point built before the first. `test_a_role_says_who_you_
  are_and_never_what_you_may_do` walks the module's AST for it.

⚠⚠ **`TenancyStore` is the one store that is NOT library-scoped.** Every other
port leads with a `LibraryRef`; this one is scoped by the **account**, because
it is the store that ANSWERS which libraries exist. A bug here does not leak
one record between tenants, it hands over a whole library — so every method
narrows by `account_id` in the store, never "list them all and filter in the
caller". It is also ONE port for three entities, against the
one-port-per-aggregate split the rest of the package follows: that split is
justified by independent lifetimes, and a library is created together with the
membership that administers it.

**Schema v12's backfill is the load-bearing half of the migration.** Every row
the owner already owns carries `library_id = 'dev-library'`, and from this
item on the resolver only serves a library it can FIND — so without a
`libraries` row per existing `library_id`, the first request after the upgrade
answers 404 and 251 books look deleted. The step derives them from the data
itself (a UNION of every table carrying a `library_id`), and leaves `label`
**blank**: a migration cannot know what the owner calls their collection, and
an invented English "My library" would be our string in a Hebrew switcher.
Naming it is `app/main.py:_bootstrap_dev_account`'s job, from the same env var
that has produced the label on screen since P1.0 — so nothing visibly changed.
(Confirmed on the real `work/product.db`: v12, `dev-library` named, `dev-owner`
admin, 251 books still there.)

**The resolver, `app/api/deps.py:current_library`, still the only one (H2).**
Three cases in order: no header → the principal's own library; the header
names that same library → served without a store lookup (this is the
*dev-trusted* half — a `Principal` is built by the server, never by a request);
anything else → the account's membership decides. **A library that does not
exist and one the caller is not a member of are the same answer, 404** (§4.2)
— asserted from the one place that can see every library, because a 403 here
confirms another household's collection exists.

⚠ **`test_library_resolution_has_exactly_one_implementation` had to change
shape.** It counted occurrences of the string `principal.library` in
`deps.py`, and the resolver now legitimately reads it twice. Counting a string
stopped meaning anything; what the rule was always about is that no OTHER
function decides which library a request operates on, so it is an AST walk now.

⚠ **`/api/v1/libraries` is exempt from the "every route resolves a library"
meta-test, via a CLOSED list in `tests/test_api.py`.** The reason is
circularity: these are the routes a caller uses to learn which libraries it
may name, so a client with no valid selection could never recover. A second
meta-test asserts the exempt routes still resolve an ACCOUNT — "exempt" must
never come to mean "unscoped" — and adding a route to that list is an edit to
a test, which is where someone has to justify it.

**Deliberately absent, not disabled:** DELETE a library (it means deleting
every book, shelf, read and photo in it — a cascade across six aggregates that
do not know about each other; it needs P3.2's policy and P3.5's blob purge),
and member management (an invite with no login to accept it is not a feature —
P4.3).

### The client half

**The library reference now travels on EVERY request, literally.** P1.0 built
the transport (`X-Booksnap-Library`) and predicted no call site would change
at P3.1 — nearly true. What it missed is that only `apiGet`/`send`/
`uploadImage` ever set the header: `getJson` and `getBook` did not, so a book
opened from a deep link went out with no tenant at all. One `headersFor()`
now builds the headers for every helper.

⚠ **The selection is module-level mutable state in `client.ts`, which the
server forbids — and the asymmetry is not an oversight.** There, one process
serves many people, so a module global is two members overwriting each other's
job. Here, one module instance IS one person's tab; the selection is exactly
as global as the browser window, like the language choice. Threading it
through every hook is what lets a call site forget it, which is the bug above.

⚠ **`LibraryProvider` renders NOTHING until the library is known.** Every
screen fetches on mount, so a screen mounted before `GET /libraries` answers
sends its first request untenanted and never asks again. The alternative —
remounting a moment later — throws away whatever was typed in that first
second, and it is what broke the Books tab's search race-guard test when tried.
The wait is one local request, and it is skipped when that request FAILS, so a
switcher that cannot load never holds the books hostage.

⚠ **Switching REMOUNTS the app** (`LibraryScope`, keyed on the selection) —
`main.tsx` and the test harness compose the same providers in the same order,
so the rule has one definition and the ring can catch a regression in it.
Everything below it holds state about ONE library (the book store's record
map, the intake queue, an open drawer, a shelf's read history); asking each to
notice a switch is a list that grows with every screen and is wrong the first
time someone forgets one — and "wrong" means one library's books under
another's name. Switching also **leaves any deep link behind** (`#/book/<id>`
names a record of the library being left, so following it is a guaranteed 404
the user did not ask for).

⚠ **A stored id the account no longer has recovers by itself** — a library
someone left, or a browser carrying another install's key. Left selected,
every request 404s and the app looks broken rather than merely pointing
somewhere it should not.

⚠ **`GET /libraries` returns store data only, with no special case for the
principal's default library**, even though the resolver serves that one
without a lookup. Patching it in would put a second copy of the dev-trusted
rule in a second module, and the day they disagreed the switcher would be
missing the library on screen. `app/main.py`'s bootstrap guarantees the row;
`test_the_library_meta_resolves_is_always_one_the_switcher_lists` pins the
agreement rather than trusting it.

⚠⚠ **A header is the wrong transport for the requests the BROWSER makes, and
that shipped broken for an afternoon.** An `<img src>` and a download
`<a href>` are built by the browser, which cannot be told to send
`X-Booksnap-Library`. So every photo, every spine crop and both export links
resolved against the caller's DEFAULT library — and in a second library they
404'd. The owner found it within minutes of live use: *"once processing done I
got books, but the image itself became empty"*. Reproduced exactly, over real
HTTP against the real store: `GET /images/<key>/thumb` → **404** without a
reference, **200** with `?library=<id>`.

The fix is `deps.LIBRARY_PARAM` — the same reference as a query parameter,
read only when the header is absent — plus `client.ts:browserUrl()`/`imageUrl()`,
which is the ONE place a URL the browser fetches gets built, for the same
reason `headersFor()` is one place. **The header WINS** when both are present:
the client's own `fetch()` always sets it, so a URL that outlived a switch (a
cached `src`, a kept link) must not drag a request into the wrong library.

The general lesson is the MPO one again in a third costume: *the transport you
chose is only the transport for the requests you were thinking about*. Four
call sites were already building image URLs by hand when the switcher shipped,
and every one of them was invisible to a test suite that mocks `fetch` —
jsdom does not load an `<img>`.

⚠ **A shared URL still does not carry the library by default.** The header was
chosen over a path prefix (`/api/v1/libraries/{id}/books`) so switching does
not rewrite every URL the client holds — the cost is that opening someone
else's deep link resolves it against the receiving client's own selection.
The query parameter above is the escape hatch for browser-issued requests, not
a general link format; if links ever have to travel between people, that is
the seam to reuse.

**Verified live** against the real `work/product.db` (snapshotted before,
restored after — routine here since P1.7): the switcher named the owner's real
library, creating *ספריית ההורים* switched to it and the feed went from 272
books to none, switching back brought all 272 straight back, and the panel
mirrors (`inset-inline-start`, so it hangs off the button's inline-start edge
in both directions — measured, RTL right edges equal at 1153px). All four
resolver cases were exercised over real HTTP: the new library 0 books,
`dev-library` 272, an unknown library **404**, no header at all 272.

⚠ The Browser pane did not composite frames this session either (screenshot
timed out, same as P2.8/P2.10), so the checks above are DOM structure, layout
geometry and API state — real verification of wiring, NOT of paint.
`getBoundingClientRect` still returns real numbers without compositing, which
is why the mirroring measurement stands; `getComputedStyle` would not have.

## Three things live use found the day the switcher shipped (owner, 2026-08-10)

All four of the owner's reports from one real scan in a second library. The
image one is above (it was a tenancy bug); these three are not about tenants
at all, which is why they are here.

**A running read now says what it is DOING.** The engine has reported
per-tile, per-block and per-spine progress all along — `llmreader.py` emits
`{stage: 'reading', done, total}` per tile, `pipeline.py` emits `page_read`,
`segmented`, `ocr` and `matching` — the job runner keeps the latest, and
`ReadDTO.progress` has carried it on every poll since P2.4. The panel threw
all of it away and printed one static *"קורא…"* for minutes, which is
indistinguishable from a hung job. `capture/RunProgress.tsx` renders it, with
a bar **only when the engine gave a real denominator**: a made-up fraction is
worse than no bar, because it claims someone knows how far along this is.
An unrecognised stage falls back to the plain line rather than printing a raw
key — a new engine event should read as *less* detail, never as a broken
screen.

**Run is disabled while a read is running.** Pressing it again is legal
server-side and starts a second read of the same (shelf, depth) — money, time,
and it replaces the panel you were watching. The reason is stated next to the
button rather than left to a greyed-out control nobody can explain.

**The Books tab refetches when you come back to it.** The store fetched on a
query change and never otherwise, but books are also created and approved on
the Capture tab, through routes the store never sees — so returning showed a
list from before that work, and typing in the search box "fixed" it, which is
exactly how the owner found it: *"after searching, the books appeared"*.
`BooksTab` unmounts when you leave the tab, so its own mount IS the signal.
⚠ It distinguishes coming BACK from arriving by reading `loading` at mount
time — on the first mount the store's query effect is already in flight, and
reloading there costs an extra request on every cold start. A ref cannot tell
them apart: it resets with the component, and the component remounts on
exactly the event being detected. A cross-tab invalidation channel is the
general answer and is not worth it for two tabs; revisit at the third writer.

**Deleting a book marks its finding REMOVED — and records the "no" that makes
that true** (owner, 2026-08-10: *"removing a book in the books tab should mark
it as removed (strike through) in the image"*).

The finding itself never disappears, and that part was always the design: a
finding is evidence of what the photograph said, and deleting a library record
does not change what the camera read. What was wrong is what it reverted TO.
Deleting wrote no decision anywhere, so the claim came back as an ordinary
unanswered question with its ✓ on screen — as if nobody had decided — and, the
same fact seen from the other end, **the next read of that shelf would put the
book straight back**. That is §5.6 ("a rejected book must not be re-added by a
later run") going unenforced for the plainest rejection the product offers.

`DELETE /books/{id}` now records a standing `REJECTED` `Decision` at every
`(shelf, depth)` the book's copies stood at — `app/domain/retract.py:deletion_sites`,
pure and mutation-checked. `reconcile()` already reports a suppressed claim in
`rejected`, and P2.10 already renders that bucket struck through with its ↩,
so both halves of the owner's ask came from one write and no new UI.

- **locations, not "the shelf"**: a book with copies on two rows was claimed
  on two rows, and a decision is scoped to one (shelf, depth) by §5.7 #1;
- **`REJECTED`, not `WRONG_BOOK`**: the two suppress identically and the kind
  is the audit trail of WHICH question was answered. Deleting says *"I do not
  have this book"*, not §5.4's *"is this the copy I already have"*;
- **an unshelved book suppresses nothing** — P1.3's 251 imports have no row
  for a future read to re-find them on. Asserted, so the empty case is a
  decision rather than an accident;
- **↩ brings it back as the PENDING finding it was**, never as a book nobody
  approved: restore clears the decision and re-applies, and "nothing enters
  the library unapproved" outranks every path in.

⚠ ✕ (retract) and *delete* are still two different doors and both are needed:
✕ answers *"this reading was wrong"* for ONE photo's finding and deliberately
keeps a book that has a life of its own (`plan_retraction`); delete removes the
record outright. They now agree about the one thing they always should have:
neither leaves the shelf ready to re-add what a human just removed.

⚠ **`preview_start` reuses a running Vite dev server, and Vite can serve a
STALE module graph after out-of-band writes.** Live verification of the image
fix showed the old URLs; `fetch('/src/api/client.ts')` from the page proved
the dev server was still serving pre-edit source (the new `browserUrl` was
simply not in it) after a mutation-test script had rewritten those files
repeatedly. Same family as the `:8757`-serves-a-stale-build trap already
recorded here, and diagnosed the same way: **grep the served artefact for a
string only the new code has**, rather than assuming HMR kept up. Restarting
the dev server fixed it.

## The permissions matrix is data (P3.2), and isolation closed out (P3.3)

§4.2's matrix, settled and shipped: `app/domain/policy.py` holds `Capability`
(13 members — the vision's rows, plus `VIEW_PHOTOS` for §12.2 #1 and
`MANAGE_LIBRARY` for rename) and `POLICY`, a dict of capability →
frozenset[Role]. `allowed(role, capability)` is the whole module API, and it
**raises `PolicyUndeclared` for a capability with no row** rather than
answering False — "denied by policy" and "nobody wrote the policy" must stay
distinguishable, same stance as the fire table's `fires()`.

**The one enforcement point is `app/api/policy.py:require(capability)`.**
Every library-scoped route swapped `Depends(deps.current_library)` for
`Depends(require(Capability.X))` — the checker itself depends on
`current_library`, so H2's meta-test holds unchanged, and the route's own
signature is otherwise untouched (the checker returns the `LibraryRef`).
`tests/test_api.py:test_every_api_route_declares_exactly_one_policy_capability`
is the meta-test the file's docstring promised since P3.1: a route with no
declaration FAILS rather than defaulting to open. Exactly one, not at least
one — two `require`s on a route would enforce the stricter intersection while
reading as either-or.

Decisions settled here (both recorded in VISION §12.2, both cheap to
reverse because they are cells, not control flow):

- **a Viewer never sees the photographs** (§12.2 #1). The photos show the
  inside of a home; the catalog is what a Viewer is for. `VIEW_PHOTOS` gates
  the image routes' GETs — metadata AND bytes, and the 403 comes from the
  DEPENDENCY, before any store lookup, so a viewer cannot probe which keys
  exist. Loosening later shows photos to people who could not see them;
  tightening later cannot un-show them;
- **two members reviewing one read need no locks** (§12.2 #3). The write
  paths already have the right semantics: applies recompute against current
  state and are idempotent by sighting, a second answer to a closed question
  409s. Settled as "the schema already holds", which is exactly why guessing
  it earlier would have produced lock tables nobody needs;
- **`DELETE /images` is admin, not editor** — §4.2's own last row. Deleting
  a photo destroys the evidence every read of it points at;
- **renaming a library is admin.** The one direct `allowed()` call outside
  `require()`, because `/libraries` is on the ACCOUNT axis (the closed
  exemption list) — same matrix, different transport of "which library".
  403 there is honest, not a §4.2 violation: the membership lookup already
  proved the caller may SEE the library; §4.2's 404 protects OTHER
  households' libraries, and it is answered by `current_library` one
  dependency earlier. Order pinned by
  `test_a_foreign_library_is_still_404_never_403_now_that_policy_exists`.

⚠ **Two "admins", one word.** §4.2's Admin is an admin INSIDE one account's
library — the household's owner. The System Admin console (`app/admin/`,
`app/staff_api/`, `planning/ADMIN_CONSOLE_PLAN.md`) is the OPERATOR's
surface, a separate track in a parallel session; it never authorizes through
this matrix, and this matrix never grants operator powers.

⚠ **Why the enforcement point is NOT in `deps.py`**:
`test_library_resolution_has_exactly_one_implementation` walks every other
function in that module and fails on any `.library` attribute read — and the
role resolver legitimately reads `principal.library` for the dev-trusted
case (its own library is ADMIN without a row, mirroring the resolver's case
2; `app/main.py`'s bootstrap writes the real row anyway). A separate module
keeps H2's structural test meaningful.

Mutation-checked, each against a named test: a flipped `VIEW_PHOTOS` cell, a
route quietly reverted to bare `current_library`, `allowed()` defaulting
instead of raising, and the rename check deleted.

**P3.3 arrived mostly by having been paid for earlier**, which was the plan's
own bet ("P3.3 inherits a suite instead of writing one under pressure"): the
store contract's isolation cases have run against two library refs since
P2.1 for every aggregate, blob isolation is pinned at the API ring
(`test_a_photo_in_another_library_is_404_not_403`), foreign-vs-fictional
indistinguishability was P3.1's, and the route meta-test is above. Nothing
new to build; the item's content is that the claims are now enforced from
three directions (store, resolver, per-route policy declaration).

## The job queue (P3.4) — bounded, fair, and reads still settle themselves

`app/adapters/queued_jobs.py:QueuedJobRunner` replaced the thread-per-job
`InProcessJobRunner` (deleted, not kept as a second implementation to keep
honest). Same `JobRunner` port, so the reads router changed one line; what
changed is capacity discipline, not meaning:

- **a fixed pool of workers drains a queue** (2 in `app/main.py` — a read is
  engine-CPU or a paid LLM call, and ten at once helps neither on 4 cores);
- **fairness is round-robin ACROSS tenants, FIFO within one** — one deque per
  tenant, a ring of tenant keys. `submit()` grew `tenant=` (the reads router
  passes `library.id`) and the API test pins that wiring with a spy, because
  dropping `tenant=` would silently collapse every library into one queue
  and no adapter-ring test could see it;
- **`retries=` exists and the reads job passes 0 ON PURPOSE.** The job
  settles its own failure (`fail_read` + save); a runner-level retry would
  re-run the ENGINE — paying for the same photos twice because the final
  save hiccuped. Retry is for cheap idempotent callables; the option exists
  so the queue is complete, not so reads use it;
- **a queued job reports state `"running"` with progress
  `{"stage": "queued"}`** rather than a fifth port state — every poller
  would have to learn the new state and none can act on it; the client's
  unknown-stage fallback (P3.1's live round) renders it as the plain line;
- **a stopped-while-queued job still RUNS, with stop already set.** The
  runner never settles a job from the scheduler: the caller's durable `Read`
  (saved as `running` before submit) waits for `fn` to write its own ending,
  so the work must run — it sees `should_stop()` true on its first poll and
  settles as `stopped` in milliseconds. Settling from the scheduler is the
  bug where a stopped read shows `running` forever, the same hang the
  load-bearing try/except in `reads._job` guards against from the other side.

`tests/test_jobs.py` (8) is the runner's own ring — fairness, retry budget,
stop-while-queued, bounded concurrency, two-runners-share-nothing — all
event-gated, never sleep-calibrated. The plan's named case ("two concurrent
reads in two libraries do not observe each other") runs twice: adapter-level
and over real HTTP (`test_two_concurrent_reads_in_two_libraries_do_not_
observe_each_other`, whose GatedReader produces claims NAMING their library
so a leak shows in data, not just timing). Mutation-checked: `tenant=`
dropped in reads.py, round-robin broken, retry dead — each fails a named
test.

## Blob lifecycle (P3.5) — the reconciler under-deletes on purpose

The tenant-keyed layout, content addressing and upload idempotency were
P2.3's; what P3.5 added is the lifecycle: `BlobStore.list_keys` /
`BlobStore.purge` on the port, `app/blob_lifecycle.py` (the ONE module
allowed to say "orphan" — a sibling of `reconcile_apply`, ports only), and
`tools/blob_gc.py` (dry-run by default; the dry run is the same code path as
`--collect` minus the deletes, so the printout is the plan, not an
estimate). Retention POLICY is §3's decision verbatim — keep originals +
crops, user-purgeable — so there is no TTL machinery anywhere.

Photos are the evidence the product runs on, so the collector is built to
under-delete, and each guard is mutation-checked:

- **references come from BOTH aggregates** — `Capture.image_id` and
  `Claim.crop_key`. Captures alone would collect every spine crop; reads
  alone every unread photo;
- **reads come from `ReadStore.list_all_reads`** (new port method, contract-
  tested in both adapters), never a walk of current shelves. The reads that
  need it most are filed under a RETIRED shelf id: captures deleted one by
  one, then the shelf — legal since P2.1 (`ShelfNotEmpty` counts captures,
  not reads) — leaves reads whose crops are evidence a DB row still points
  at. No route serves `list_all_reads`; a screen wanting it is re-inventing
  the run list §5.5 forbids;
- **the age floor (24h default) is a safety, not a knob.** Upload and
  capture-binding are two calls (P2.3, deliberately), so a blob is
  legitimately unreferenced for the whole afternoon someone spends dropping
  photos before filing them. `min_age_s=0` is for tests;
- **the wishlist's photos count** — `list_shelves` defaults to excluding
  virtual shelves, the one default that is wrong here;
- **`list_keys` reports originals only** — variants/sidecars are derived and
  travel with their original, so listing them double-counts what one
  `delete` removes.

`purge(library)` is §3's "user-purgeable" as a primitive: one library's
whole tree, idempotent, counted. No bulk route yet — per-photo deletion
exists (`DELETE /images`, admin), and the whole-library form is half of what
DELETE-library needs; the other half (a six-aggregate cascade) is still a
design owed, per `libraries.py`'s updated note.

Verified against the real `work/` data with the tool's dry run: two
libraries, every stored photo referenced or too young, zero would-collect —
the honest boring answer.

## The run rate cap (P3.6) — one number, and it is not a quota

`app/api/routers/reads.py:RUN_RATE_CAP_PER_HOUR` (30, env-overridable via
`BOOKSNAP_RUN_RATE_CAP`): a library that already STARTED that many reads in
a rolling hour gets **429** from `POST .../reads`, with a message that names
the cap, says it is a retry-loop guard and not a quota, and says what to do.
§1.2's own framing, kept: family won't run the bill up on purpose; a stuck
client re-POSTing, or a 400-photo burst, will. Metering proper is pillar 5.

- counts EVERY status — a retry loop's reads mostly fail, and failures cost
  the engine work the cap protects;
- per library, rolling hour — a burst in one library never freezes another
  (tested), and old reads age out or the cap becomes a lifetime quota
  (tested; both mutation-checked);
- the honest O(reads) scan over `list_all_reads`, same trade as the diff
  endpoints' `_FULL_LIBRARY_SCAN_LIMIT` — measure before optimising a route
  a human presses a few times an hour.

Client follow-through: the 429's detail surfaces through the existing
failed-run panel (no new client path), and the queue's `{stage: "queued"}`
progress (P3.4) got a real line — *"ממתין בתור…"* — instead of falling to
"קורא…", which is exactly the looks-hung confusion the progress line exists
to prevent. Client ring is 99 tests as of this.

## What the pillar-3 review round found (2026-08-10)

Three reviewer passes (data-integrity, quality, UX+concurrency) ran against
P3.2–P3.6 as they landed; every finding below is fixed and has a named test.
Recorded because each is the kind of thing that would read as intentional
later:

- **a repeat upload REFRESHES the blob's mtime** (`DiskBlobStore.put`,
  `os.utime` on the dedup path). Without it the GC's age floor was provably
  false for re-dropped photos: a 3-day-old unbound blob re-uploaded today
  still listed as old, and a collect racing the new binding deleted bytes a
  capture pointed at — reproduced end to end by the reviewer before fixing.
  The one-line fix restores the documented guard;
- **stopping a QUEUED read acknowledges immediately**: `stop()` writes
  `{"stage": "stopped"}` into a not-yet-picked-up job's progress, so the
  phone shows "עוצר…" instead of "ממתין בתור…" for however long the pool
  stays busy — which read as the tap not registering. (Money was never at
  risk: `Pipeline.run` checks stop before the first image.);
- **a read stopped with ZERO claims archives no diff summary** — it never
  looked, and "12 not seen" forever in the history row would be a lie.
  Routine now that stop-while-queued exists; treated like `failed`;
- **the global Run disable was retired, the per-group half kept.** The
  owner's rule was about re-reading the SAME (shelf, depth); P3.4's queue
  makes NEW shelves safe to accept mid-batch (they queue fairly), so
  `pendingGroups` now excludes running groups and the button disables only
  when nothing is startable. Both halves have client tests;
- **a 429 stops `start()`'s loop** — six selected groups hitting the cap
  rendered six identical failure panels;
- **a settled job releases its closure** (`job.fn = None` AND the worker's
  local binding — the weakref test caught that the local alone kept the
  world alive through the worker's next idle wait). `self._jobs` never
  evicts, so retained closures were a slow leak the thread-per-job runner
  never had;
- `_next_locked`'s defensive branch uses `pop`, never `del` — the KeyError
  it guarded against would have killed the worker it was defending.

Deliberately NOT changed on review advice: the rate cap's O(reads) scan
(fine to ~1–2k reads; the fix at that point is a `count_reads_since` store
method, not a cache), and `library.id` charset validation in the blob layout
(ids are server-minted and the resolver 404s unknowns; noted as
defence-in-depth for P4).

## ⚠⚠ A tenant is an ownership boundary, never a geography (owner, 2026-08-10)

Settling the question P3.1's switcher surfaced (and the parallel admin
session first raised): **a different tenant is a different account's
collection. Within one account, the living room, the child's room, and a
whole other site (office, shelves at the parents') are LOCATIONS of one
Library — pillar 6's Place — never Libraries.** Full statement in VISION
§4.1; the discriminator is whose books, not whose roof. Splitting one
collection across Libraries has a silent cost: search, dedup and §5.4's
duplicate question are tenant-scoped, so a second copy of a book you own
would never be flagged.

What changed to match (the domain already matched —
`test_a_library_is_not_a_place` and the whole per-library tenancy stack are
exactly this rule):

- **the switcher renders as a plain LABEL until a second library genuinely
  exists** (`LibrarySwitcher.tsx`, `.libswitch-label`). An always-present
  "+ new library" was the only noun the UI offered for "child room", one tap
  away — the modelling error it invited is the one the owner hit. Creation
  now lives in the menu (≥2 libraries); an account's normal path to a second
  library is MEMBERSHIP (P4.3), and the API remains the escape hatch for the
  rare genuine second collection;
- **the create form states the rule where the choice is made**
  (`t.library_create_hint`, both locales): a library is another person's or
  household's collection; rooms arrive with the Map. Both the demotion and
  the hint are mutation-checked;
- P6.1 (plan) now says Places include SITES, and is the recorded exit for
  any room-modelled-as-library: its books move back under a Place and the
  extra Library retires. Sign-up creates exactly ONE library (P4.1 mints
  it; P4.3's §4.3 onboarding names it — the constraint spans both items).

Verified live against a running two-library server (menu + roles + hint,
DOM-level; the pane did not composite frames — the recurring limitation —
so paint is inferred from existing tokens as before). The single-library
label variant is pinned by the client ring, which is where it can be built.

## The library merge tool — §4.1's cleanup, P6.1's exit arriving early

`tools/merge_library.py` over `app/adapters/merge_library.py`: retire a
mis-modelled library (a location that got created as a TENANT before Place
existed) into the collection it belongs to. Built for the owner's ruling that
**lib2 (`103e0de5…`) is the parents' shelves, not a tenant** — 14 books, one
scan, 3 works colliding with the main 272.

The rules, each with a named test (11) and the load-bearing ones
mutation-checked:

- **identity is re-homed, never re-minted** — shelf/capture/read/claim/copy
  ids survive; provenance is keyed by copy and never touched;
- **a colliding work becomes another COPY of the book already owned** (the
  physical truth), with its status, lending and provenance riding along;
  positions renumber after the target's. A colliding source ROW carrying a
  rating/note/read-status is REFUSED — which side wins is a human question;
- **photos copy first, verify by hash (content addressing makes that exact),
  and the source tree is purged only after the commit** — at every failure
  point, every key a row names resolves somewhere. Mutation-checked: purging
  before the commit fails the mid-copy-abort test;
- **recorded human answers refuse the merge**, checked twice — before the
  copy (clear message) and inside the transaction (a live server writing a
  decision during the copy window must not be orphaned); deliberately
  redundant with the leftover check over EVERY `library_id` table, the P2.1
  "what else enforces this?" pattern, verified in both directions;
- the CLI: dry-run by default (UTF-8 stdout — cp1255 rendered the collision
  list, the dry run's whole job, as mojibake), `--execute` requires
  `--confirm-retire <src-id>` (naming what you RETIRE catches swapped
  src/dst), refuses to retire the dev principal's default library (the
  bootstrap would resurrect an empty ghost), and snapshots via **SQLite's
  backup API with an integrity check ON the backup** — three `copy2`s of a
  live WAL database is not a snapshot, a checkpoint between them silently
  loses committed rows.

All of this is the pre-run data-integrity review (9 findings, each fixed the
same day) — the reviewer rehearsed the real merge end-to-end on a snapshot:
283 books after, integrity ok, zero orphans, every blob key resolving.

## Two applications, four packages (the tidy-up before pillar 4, 2026-08-10)

The admin console arrived under a hard "touch no existing file" constraint
(`planning/ADMIN_CONSOLE_PLAN.md`), so it necessarily re-implemented what the
product client already had. The constraint is lifted; this is the settlement.

```
app/
  web/        the household's client        :5173 dev, built into :8757
  admin/      the operator's console        :5174 dev, `vite preview` only
  ui/         what the two clients share    no build step; consumed as source
  api/        the product server            /api/v1     :8757
  staff_api/  the operator's server         /api/staff/v1  :8758
```

**`app/ui/` is the shared client library**, extracted mainly FROM `app/web`
because that is the app the owner has actually used. Its README argues the
membership rule (*a mechanism both apps need, or a rule both apps must not
disagree about*); the entries worth knowing here are the sort control (the
console's re-invention had lost both of its rules), `.rtl-safe` (UI_PLAN §7.2
is a CORRECTNESS rule about Hebrew and the two copies had drifted in their
selectors), `vouchedFor` (§5.1's ladder — the two apps had already disagreed
about whether `manual` counts as vouched-for), `formatDate` (one returned the
raw ISO string on an unparseable date, the other `''`), and `useAsync`'s
request-id guard.

⚠⚠ **`resolve.dedupe` must list the TESTING libraries, not just React.** Found
by watching one product test fail the moment `test/user.ts` moved into the
shared package. `@testing-library/dom` keeps its config in MODULE state and
`@testing-library/react` writes React's `act` into it on import; a second copy
resolved from `app/ui/node_modules` has its own, unconfigured config, so
`userEvent` built from it fires events OUTSIDE `act`, React never flushes the
effects, and the symptom is *a component that has not rendered its data yet*.
It reads as a timing flake. The React half of the same trap is the familiar
one (two copies break hooks). Both clients' vite configs carry the list and
the reason.

⚠ **Shared CSS draws only from `--ui-*`, and the bridge is a tested contract.**
The two palettes differ on purpose (a reading surface vs a dense table
surface), so each app maps its own colours onto the shared names in one block.
`app/ui/src/tokens.test.ts` reads the shared sheet and both apps' styles and
fails on a missing name — it has to, because **jsdom computes no cascade**, so
a control whose colour resolves to nothing renders invisibly through a
completely green client ring.

**The API split was already right; it is now enforced.** The console READS
cross-tenant through the staff service and WRITES through `/api/v1` as an
ordinary member — two surfaces, one authorization model each, because
`/api/v1` resolves a library from the caller's memberships (§4.2) and
loosening that to serve a console would weaken isolation for every household.
`tests/test_layering.py` now holds that as five mutation-checked rules: the
staff service imports no product route, no adapter, no migration and never
`app.main` (importing the product's composition root MIGRATES the owner's real
database), and the product imports nothing from `app/staff_api`. The two
clients' own rings each assert they do not reach into the other's source.

**Both services' contracts are generated and committed** —
`tools/api_contract.py` now produces four artefacts, two per service:
`app/api/openapi.json` → `app/ui/src/api/schema.d.ts` (in the SHARED package,
because both clients call `/api/v1`), and `app/staff_api/openapi.json` →
`app/admin/src/api/staff-schema.d.ts` (in the console, because nothing else
speaks it). That retired the console's hand-mirrored copy of the staff DTOs —
a renamed staff field is a compile error now, not an `undefined` in a table —
and the console's one crossing into `app/web` went with it.

**The gate is per application.** `tools/check.py` grew `--admin` (the console's
ring and typecheck) and `--ui`; the pre-commit hook routes to them. Two routings are the point of the file: `app/ui/*` asks for
BOTH clients' rings (a change to shared code is a change to two apps, and only
they can prove a screen still renders), and `app/staff_api/*` asks for
`--product` as well, because the rules keeping the two services apart live in
the product's ring. An unknown flag is now refused rather than ignored — a
typo used to run the whole gate and read as a pass of the thing you asked for.

⚠ **The staff service's tests ride with the PRODUCT, not with the console**
(`tests/test_staff_api.py`, inside `tests/run_all.py`). Ownership says
otherwise — they are the operator's — and ownership is the wrong axis here:
the read model duplicates the product's schema on purpose, so the change that
breaks it is a migration made on the product side. A gate keyed on ownership
never runs on the change that breaks it, which a review demonstrated by
renaming `books.sort_author` and watching the console die at startup while the
product ring stayed green. What was actually missing was never a merge; it was
that neither the staff suite nor the console's client tests were in any gate
at all.

### What the three reviewers found on this round (2026-08-10)

All fixed, each with a named test. Recorded because most of them are the same
lesson in different costumes — **a shared thing is only shared where something
checks it.**

- ⚠⚠ **the console had no `button` reset, so the shared sort control rendered
  with full UA chrome.** `.sortdir` was written against an app whose base sheet
  strips every button; the console has no such rule, so the toggle appeared as
  a grey raised box with an outset border wedged inside the sort field — and in
  dark mode a mid-grey box with a WHITE outline. Worse than the plain ↑/↓ it
  replaced. **A shared control now resets its own UA chrome**, because the
  sheet cannot assume anything about the page it lands in;
- ⚠⚠ **`tokens.test.ts` checked the tokens and not the sheet.** Deleting
  `import '@booksnap/ui/styles/ui.css'` from the product's `main.tsx` turned
  `.rtl-safe` off across the whole app and dropped the sort toggle out of its
  box — with **every ring green, 9/9**. It now asserts each app imports the
  sheet, and imports it after its tokens;
- **three of the new tests were not gates**, proved by mutation: the abort test
  asserted through a post-`unmount()` snapshot no `setState` could reach; the
  hash test set the hash *before* render, which the lazy initializer already
  catches; and both boundary regexes missed double quotes and bare side-effect
  imports. All three rewritten and re-mutated. The abort one took three goes,
  and the second failure taught something real: when the hook aborts a request
  ITSELF the request-id guard has already returned, so the `AbortError` branch
  only ever fires for an abort the hook did not cause;
- **a routing hole in the gate**: the staff service's suite ran on `--admin`
  only, but the change that breaks it is a migration or a store rename made on
  the PRODUCT side. A reviewer executed it — renamed `books.sort_author`,
  product ring green, console dead at startup with `SchemaMismatch`. Ownership
  and dependency point in opposite directions here; the suite runs for both
  now;
- **the staff service had no meta-test that a route carries its credential.**
  The hand-written list had five paths for six routes, so removing
  `dependencies=guard` from `/libraries/{id}/shelves` served every tenant's
  shelves to anyone on port 8758 with the suite green. It walks `app.routes`
  now, like the product's policy meta-test;
- **the documented 503 could not happen.** `self_check()` runs once, at
  construction, so a schema that moved while the service was RUNNING surfaced
  as a raw `OperationalError`. An `OperationalError` now re-runs the shape
  check and answers 503 with the named columns — or re-raises untouched, so an
  ordinary lock is never dressed up as a migration problem;
- **two stated reasons were wrong**, which matters more than it sounds: a
  comment in `Toolbar.tsx` justified its guard with "it would fire a second
  query" (it would not — `setQuery` short-circuits), and the migration-import
  rule reads as primary when it is redundant. A wrong reason is what makes the
  next reader delete the guard.

**Entities: one tenancy layer.** Account → Library → Place → Bookcase →
Shelf(column, level, depth) → Capture → Read/Claim → Book/Copy, settled in
VISION §4.1/§4.1a with the honest "what exists today" column (Place and
Bookcase are pillar 6; `Shelf` is identity-only by P2.1's design). The
question answered there: **Account is not a second tenant.** Library is the
isolation boundary (every row carries `library_id`); Account is the identity
axis that answers *which libraries may I name* — which is why `TenancyStore`
is the one port scoped by account. A cap on libraries per account is a policy
number at create time, never a second scope on the data.

## Reviewer agents (`.claude/agents/`) — run them after substantive items

Four persisted reviewer personas, born from the pillar-3 round where every
one of them found real, fix-worthy bugs (see "What the pillar-3 review round
found"). They are project files, so any session on any machine can spawn
them via the Agent tool by name; the definition carries the persona, method
and repo rules — the CALLER's prompt supplies only the scope (commit shas or
files) and any item-specific questions:

| agent | when |
|---|---|
| `review-data-integrity` | any substantive server-side change |
| `review-quality` | any substantive change (attacks the new tests) |
| `review-ux` | anything that changes user-visible behaviour |
| `review-migration` | BEFORE committing a schema-version change |

Ground rules baked into all four, worth knowing when reading their reports:
they verify by RUNNING (tests, probes, temporary mutations they restore
byte-exact), they review a clean worktree if the live tree is flapping from
a parallel session, they never touch the staff-console workstream, and a
"clean checks" section is part of the deliverable — a clean check is
information. Run them in the BACKGROUND after committing an item and keep
working; fold their findings into a follow-up commit. Don't run all four on
every keystroke — one pass per landed item is the cadence that has paid.

## ⚠⚠ Two admins, two applications (`app/staff_api/` + `app/admin/`)

Settled by the owner 2026-08-10, after P3.1 put *create a library* in the
household client's app bar. There are **two admin jobs** and only one of them
lives in the product:

| | sees | is a member of | invites people |
|---|---|---|---|
| **system admin** — the console | every tenant | nothing | no (P4.3) |
| **account admin** — `Role.ADMIN` | one library | that library | no route yet (P4.3) |

**A system admin is NOT a `Role`, and must never become one.**
`app.domain.tenancy.Role` says who you are *within one library*; an operator
who oversees tenants is a member of none of them. A `SYSTEM_ADMIN` value would
make every membership row a place someone could grant themselves the world —
and now that P3.2 ships the matrix, the same rule reads: **never give it a
`POLICY` column either.** It is a property of the operator, carried today by a
shared token on a separate service.

**Why a second application rather than a wider view.** Every `/api/v1` route
resolves its library through `app/api/deps.py:current_library`, which answers
from the caller's MEMBERSHIPS. That is not an obstacle to route around — it is
§4.2 ("a foreign record reads as ABSENT") and the tenant-isolation suite exists
to keep it true. Loosening it to serve a console would weaken isolation for
everyone. So the console gets its own service, the same "strangle, don't
refactor" shape (D2) that lets the tuning server and the product coexist.

```
app/staff_api/   FastAPI on :8758, /api/staff/v1. Cross-tenant, READ-ONLY.
  queries.py       the read model: overview / libraries / accounts / books /
                   shelves / recent reads, one SELECT per question
  app.py           DTOs + routes + the credential
  main.py          composition root (a SECOND one — see below)
app/admin/       Vite + React client on :5174, `host: true` (phone). Talks to
                 BOTH services; see its README.
```

**Read-only by construction, not by intention.** Every statement is a
`SELECT`, the connection sets `PRAGMA query_only`, and there is **no
`migrate()` call anywhere in the package**. That last one matters more than it
looks: this file already records that merely importing `app.main` advances the
real database's schema, so a console that opened `work/product.db` the usual
way would upgrade the owner's data as a side effect of being *looked at*.
`test_reading_never_migrates_the_owners_database` pins `user_version` across
every query.

**It carries its own read model instead of using `app.ports.store`.** Every
port method leads with a `LibraryRef` by design, so "every library at once"
through them would mean either loosening the ports or N queries per figure.
The price is that `queries.py` knows the SCHEMA — paid up front by a
`self_check()` that refuses to serve a database whose shape has moved, rather
than letting a renamed column surface as a plausible wrong number on a
dashboard nobody double-checks. ⚠ **A migration that touches `books`,
`copies`, `shelves`, `captures`, `reads`, `accounts`, `libraries`,
`memberships` or `duplicate_questions` must update `REQUIRED_COLUMNS` and the
queries together.**

**No RULE is duplicated, only schema.** The §5.1 ladder is one SQL expression
derived the way the entity derives it (`STATUS_RANK_SQL`), and search imports
`app.domain.search` — so the console ranks Hebrew by P1.5's measured rules
rather than a second approximation. Verified live: staff and product search
returned identical totals on four terms.

**The credential is `BOOKSNAP_STAFF_TOKEN`**, compared with
`secrets.compare_digest`, accepted as `X-Booksnap-Staff` or
`Authorization: Bearer`. ⚠ `/api/v1`'s "no login until pillar 4" trade does
**not** carry over — a route returning every account and every household's
books is a different exposure from one returning your own. **Unset means the
service still serves and SAYS so** (`authenticated: false`, which the client
turns into a banner): refusing to start would leave the owner with a console
that cannot be opened and no obvious reason, and silence would leave a
cross-tenant surface open on the LAN with nothing on screen to suggest it.

**Reading is cross-tenant; writing is not.** The staff service never writes.
The console's approve/edit/delete go through the ordinary product API, which
resolves the operator's own membership — so a book or a library outside those
memberships is shown with its numbers and marked read-only, rather than
offering a button that 404s. A deliberate limit: a system administrator
silently rewriting a household's book titles is a power this product has no
reason to grant before it has a login and an audit trail.

**Users are reported, not profiled.** `GET /api/staff/v1/accounts` returns
identity and membership and deliberately no per-person reading or capture
activity — aggregate figures live on the library rows, where they describe a
collection rather than a person. A client test pins the absence.

⚠ **`app/staff_api/main.py` is a SECOND composition root**, and it is
deliberately NOT in `tests/test_layering.py`'s `COMPOSITION_ROOTS`. That
exemption exists for the `app/api -X-> app/adapters` rule, and nothing here is
under `app/api`: the service wires a read model that imports no adapter at all
(`app.domain.search` is its only cross-package import). Add it to that list the
day it binds a real adapter — and argue the diff then, which is what the
one-element set is for.

⚠ It also does **not** import `app.main`. Same reason the product keeps its own
copy of `_load_dotenv`: importing the product's composition root opens the
database and migrates it at import time.

Run both, plus the client:

```bash
python -c "import uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=8757)"
python -c "import uvicorn; uvicorn.run('app.staff_api.main:app', host='0.0.0.0', port=8758)"
npm --prefix app/admin run dev     # :5174, proxies /api/staff -> 8758, /api -> 8757
```

⚠ The admin client's Vite proxy keys are order-sensitive: `/api/staff` must
precede `/api`, or every staff request lands on the product API.

⚠ Its product-API types come from `app/web/src/api/schema.d.ts` by a
**type-only** import — one generated artefact, so a renamed DTO breaks both
clients on the same commit. The staff DTOs in `src/api/staff.ts` are
hand-written and mirror `app/staff_api/app.py`; that service is not part of the
committed `app/api/openapi.json` contract.

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

Client rings (need the three `npm install`s above):
`npm --prefix app/web run test` (vitest + React Testing Library, **102 tests**
as of the two-application tidy-up — 98 at P3.1, plus the boundary test), with
`npm --prefix app/ui run test` (**25**, the shared rules) and
`npm --prefix app/admin run test` (**53**) beside it, and
`npm --prefix <pkg> run typecheck` for each. Test what encodes a
*decision*, not layout and not DTO plumbing — same standard as the Python
rings. The suite mocks `fetch`, never `useBooks`/`useCapture`/`useShelfDetail`:
the store, the request-id race guard and the paging arithmetic are exactly
what needs exercising, and the Capture/shelf fake servers
(`capture/captureHarness.ts`, `shelf/shelfHarness.ts`) do not reimplement
`reconcile()`/`apply_diff`/`not_seen_streak`/`depth_staleness` either — each
test hands back the exact overview/books/diff a call should answer with, the
way the Python API ring injects a `StubReader`.
Mutation-checked — fifty reversed decisions (dropped race guard, missing
`.rtl-safe`, edit not abandoned on book change, delete without confirmation,
409 clearing the form, focus not restored, drawer left open on promote,
sort direction surviving a key change, tags not trimmed/blanks-dropped, the
`duplicates` filter dropped from the request — P2.6; "add a row behind" hidden
until a shelf is already stacked, ✓/✕ shown for every `needs_decision` reason
instead of only `review_tier_new_book`, an alternative given a one-click
accept button, a freshly-uploaded photo not auto-selected — P2.7; the depth
bar hidden at `depth_count` 1, a book title rendered without `.rtl-safe`,
the *"open the shelf →"* chip dropped from the review panel header — P2.8;
the intake list never rebuilt from the server, an in-flight read not
re-attached on mount, `visibilitychange` not wired to an immediate poll —
P2.9; the workspace showing the whole row's findings instead of this photo's,
`rejected` findings dropped from the list, *approve* still offered on an
already-approved book, the newest run not opened on arrival, the
approve/fix/remove loop missing from the LIVE panel; approve-all sweeping up
a §5.4 duplicate question, a pending finding drawn without its controls, the
match score shown without its 130 denominator, and the ✎ form patching a book
that does not exist yet instead of approving-as-corrected; a runner-up with
no *use this*, picking one on a pending finding patching instead of
confirming, a row sourced from the claim rather than the book it became, and
the author line dropped; the removed count missing from the findings line,
the run row echoing a snapshot that cannot see a later removal, and the
add-a-book lookup not actually asking the server, the vouched-for badge
narrowed back to the literal `approved` rung, review-tier guesses swept into
a bulk approval, already-vouched books counted in one, a volume style
dropped, the author list unfiltered, and the author list normalized rather
than spelled as the owner spells it, split volumes left at the end of the
photo instead of under their part, `~m10` sorted before `~m2`, and the author
suggestions left open after one was chosen — P2.10's feedback rounds;
`getBook` sending no library header, the app not remounting on a switch, a
stale stored library kept, the choice not persisted, a deep link carried into
the new library, *create* not switching to what it just made, and the first
render not waiting for the library to be known — P3.1; Run left enabled during
a read, a running read's progress thrown away, an unknown engine stage printed
raw, an `<img>` URL without the library, no refetch on returning to the Books
tab, and a refetch on the first visit too — the owner's live round) each fail
a named test.

Two P2.7/P2.8 tests were DELETED rather than fixed in that round (*"add a row
behind"*, the *"open the shelf →"* chip): the owner removed both controls, and
a test for a button that must not exist is what stops the next person from
reading why it went.

⚠ **This ring cannot see CSS.** jsdom computes no cascade, so every finding
in the "traps" list above was invisible here and had to be caught in a real
browser. Do not read a green client ring as "the screen is right".

⚠ jsdom keeps `localStorage` across tests in a file, and the language choice
persists deliberately — so `afterEach` must clear it, or every test after the
mirroring one starts in English and looks for the wrong strings. Since
`isolate: false` (see "The suite is fast on purpose") it keeps it across FILES
too, along with `client.ts`'s selected library — `src/test/setup.ts` resets
both globally, and anything else that becomes module-level state belongs in
that list rather than in a per-file workaround.

**The pre-commit hook decides which checks apply; `tools/check.py` runs them**
(`tools/githooks/pre-commit`). Still two independent halves — accuracy (sweep +
spotchecks) and product (`tests/run_all.py`,
`tools/api_contract.py --check`, and the client tests when `app/web/` is
staged). Product work must never require touching the accuracy baseline. The
client half self-skips without `node_modules`, like the spotchecks do without
run data.

Two properties of `check.py` worth not undoing: **every check runs even after
one fails** (stopping at the first red hides the other three and turns one
fix-and-rerun cycle into four), and **checks are admitted against a core
budget** rather than all launched at once. The free-for-all version made every
check slower — the python rings went 19s → 52s — because two of them fan out
internally; the budget is cores + 2, measured (47s at exactly-cores, 44s at
+2, 46s at +4: enough slack to cover startup I/O, not enough to thrash).

## ⚠⚠ P3.7 — the tenancy boundary moves from Library to Account (2026-08-11/13)

The decomposition is `planning/TENANCY_BOUNDARY_PLAN.md`; the decision is
VISION §4.1 **[REVISED 2026-08-11]**. This is the long-form record: the
argument, the reversal, and what six review passes actually found.

### The reversal, and why a plan document forced it

On 2026-08-10 the owner was asked directly whether there should be two layers
of tenant. The answer recorded that day was **no**: Library is the isolation
boundary, Account is a pure identity axis, *"there is ONE tenancy layer, not
two"*. On 2026-08-11 it was reversed:

> within an account there can be multiple libraries, and multiple users. and
> it will not be strange if user can see books across all libraries. but user
> from account A should not be able to [know] anything about account B. So the
> hard separation is not in library level, but in account level.

What is worth keeping is **how the mistake surfaced**. Not a bug, not a
failing test — a *plan document that needed a paragraph of apology*.
`ADMIN_CONSOLE_PLAN.md` revision 4 had to write down that the console says
"account" and the storage says `Library`, and to put the library id on screen
under the account name, labelled, so the mapping stayed visible. A design that
needs a disclaimer explaining that the operator's word maps to a different
record than the domain carries is a model that is wrong, not a plan that is
unclear. **The gloss was the bug report.**

### One enforced scope, not two — the objection that was honoured

The 2026-08-10 argument against two layers was concrete: *"every query narrows
twice, and each of the six aggregates gains a second way to leak."* That
objection is correct and it is why this work looks the way it does:

- **`library_id` stays the ONE enforced physical scope.** Every store method
  still leads with a `LibraryRef`, every row keeps its column, every read
  index still leads with it, blobs keep `libraries/<library_id>/`, and
  `test_store_contract.py`'s isolation suite passes unchanged. It is not
  weakened — it is demoted from *the* boundary to defence in depth inside one;
- **the account boundary is enforced at the DOOR.** `libraries` gained an
  `account_id`, and `app/api/deps.py:current_library` asks *"is this library
  owned by an account this user belongs to?"* instead of *"is there a
  membership row for this (user, library)?"*. One narrowing in SQL, one
  authorization decision, in the two modules that already own those jobs.

The rule that keeps it honest: **if an item starts adding `account_id` to a
second table, it has gone wrong.** None did.

### The backfill — the one genuine judgment call

The real database held one person, two libraries, and an ADMIN membership by
that person on each. "One account per library" is the obvious rule and it is
**wrong on the only data that exists**: it splits one owner into two customers.

The rule used instead: **libraries whose membership set is IDENTICAL collapse
into one account.** Group by the exact frozenset of `(user_id, role)`; each
group becomes one Account; every user in the set gets one account-membership
with that role. The safety property is that no user gains access to anything
they could not already reach, because every library in a group had exactly
that member set. The owner's data produced the right answer: **one account
owning two libraries.**

### What the reviews found, item by item

Six items, each landed on `main` green before the next, each with its
reviewers. The pattern from the console epic repeated: **most majors were
wrong stated REASONS rather than wrong behaviour** — the failure mode that
makes the next reader delete a guard.

- **P3.7a** (the person becomes a `User`, schema v13). A pure rename, its own
  item so that P3.7b's diff would be the boundary change and not a 60-file
  rename. SQLite's `RENAME TO`/`RENAME COLUMN` rewrite the REFERENCES clause,
  the composite PRIMARY KEY and the secondary index in place — four
  statements, not the twelve-step table rebuild the docs prescribe. Measured
  to depend on `legacy_alter_table` being off, not on `foreign_keys`.
- **P3.7b** (the boundary moves, schema v14). One commit, because the tree is
  red between any two halves of it. A security review found *a viewer could
  stock the customer's account*; another found *the door had a stopwatch on
  it*.
- **P3.7c** (one customer, one quota). The §1.2 rate cap and the job queue's
  fairness key moved to the account — a customer had been multiplying their
  own quota by pressing *new library*. ⚠ Both rules were mutation-checked at
  the ROUTER, which is where the decision lives; `QueuedJobRunner` is agnostic
  about what a tenant key means and correctly stayed untouched. The plan's
  original note naming its line numbers was wrong about that.
- **P3.7d** (the staff read model reports customers). `/accounts` returns
  customers with their libraries' figures summed — **folded from
  `libraries()`** rather than computed by a second set of grouped queries,
  because `image_files`/`image_bytes` come from the blob tree keyed by LIBRARY
  and have no per-account figure to GROUP BY. Two of twelve cannot be computed
  independently, and once two are folded and ten are queried you have
  manufactured a disagreement between two screens about the same books.
  ⚠ The aggregation fixture gives one account a second library **with books in
  it**: an empty one makes every sum equal its first term, and a fold that
  dropped the rest passed on the first draft.
- **P3.7e** (the console stops glossing) — below.
- **P3.7f** — this write-up.

### P3.7e: what a console review is for

The item itself is small to state: rows become customers, the drawer becomes
*account → its libraries → users/books/images*, `t.acct_library_id` is deleted
rather than relabelled, and `t.th_account` — which was rendered over **three
different entities** — splits into account / user / library headers. Splitting
that string was a *prerequisite*, not a cleanup: one word over three nouns is
what let the console keep saying "account" about a person and a collection
alike.

Two reviewers ran, each in its **own detached worktree**. That detail is
load-bearing: earlier in this epic three reviewers shared one tree and
contaminated each other's mutations, which makes every "SURVIVES" reading
worthless. What they found is worth recording as a class:

**Tests that were not gates.** Four rules survived reversal with the whole
ring green:

- the drawer's member list was not scoped to the open account. Every test
  opened the one customer where `memberships[0]` and *"the membership naming
  this account"* coincide. The fixture now gives one person a **different role
  in each of two customers**, so the wrong fold lists a stranger and badges
  them wrong;
- the images preview's fan-out had no gate at all — the books one did, and the
  commit message claimed the decision for both;
- ⚠⚠ **the dashboard tile and the access screen's gap line were unpinned
  against `users`, because the fixture made accounts and people BOTH 2.** So
  the ORIGINAL defect — customers counted by `users.length` — survived the
  test written to catch it, under a comment asserting the numbers were
  "deliberately all different". *A comment claiming a fixture has a property
  is not the same as the fixture having it.* They are 2 / 4 / 3 now, pairwise;
- the per-library preview cap was unexercised in both directions, because **the
  fake ignored `limit` entirely**. A drawer for the owner's 286-book customer
  would have fetched all 286 with the ring green. A fake that silently drops a
  parameter has decided the screen cannot be wrong about it.

**A console that fabricates the anomaly it exists to detect.** Measured in a
real browser, both directions. With `/users` failing and everything else
healthy, every customer rendered the warn badge *"no admin"* and every drawer
*"nobody can see or administer this account"* — states `new_account` and
`NoAdminLeft` make unreachable, which is exactly why they are rendered in
alarm tone — beside a stat card reading 2 users, **with no error anywhere on
screen**. The same shape with `/libraries` down. Three causes, all fixed:

- one fact had three sources (`AccountDTO.admins`, a fold over `/users`, and
  `overview.accounts_without_admin`) and the screen picked the only one that
  can vanish. The alarm reads the account row now; the NAMES stay a fetch;
- `peopleKnown` distinguishes *absent* from *unknown*. One `error` string for
  four independent `allSettled` requests cannot;
- the error box was gated on `accounts.length === 0`, a guard from when one
  list fed the whole screen.

**Layout that jsdom cannot see.** The five per-library controls were put in a
trailing actions column that measured **834px inside a drawer capped at
`min(720px, 100%)`** — rename and both exports outside the box at
`scrollLeft: 0`, absent from the accessibility tree until the table was
scrolled sideways. This item had MOVED them there from a full-width table, so
it was a regression of its own goal. They stack under the library name now.
Only two of the five carried a disambiguating `aria-label`, and the duplicated
ones included **rename — the only control that writes**.

**A refresh is not a first load.** `reload()` raised `loading`, and every
screen answers `if (loading) return <Loading/>`, so renaming a library from
inside the drawer blanked the app to a spinner and remounted the drawer
scrolled back to the top, re-issuing four preview fetches. Caught with a
`MutationObserver` across a real rename.

⚠ Pinning that last one took three attempts, and the two failures are the
instructive part: a test that waited on the PATCH asserted against a screen
the reload had not touched yet (a request is recorded when it is *made*), and
a held-open handler with an off-by-one flag let the first call through — and
the first call *was* the reload. **A mutation that survives is as often a weak
test as a missing rule; the way to tell is to make the mutation and read what
the test actually observed.**

### Two smaller things worth keeping

**A dead-key guard with a hole in it.** `app/admin/src/lib/i18n.test.ts`
checked `code.includes('t.' + key)` — a bare substring — so **every key that
is a PREFIX of another passed on its longer sibling's back**. `acc_account`
had been dead since `acc_account_admin` was added; `lib_export` since
`lib_export_csv`. The test whose entire job is finding dead keys reported both
as rendered. It is anchored at both ends now, and the detector is extracted so
the boundary has its own gate — because against the real table it cannot have
one: once the dead keys are deleted, loosening the check back to a substring
passes (measured). *A rule that is only observable while it is broken has no
gate.* The scanner also skips test files now: a key named only by an assertion
is not a key anything renders.

**A client argument resting on a server constant nothing named.** The drawer's
image preview takes the newest five of a union, which is correct only if each
per-library page is that library's newest first — and `/images` takes no sort
parameter, so the client cannot ask. That was the same shape as `MAX_SCORE`
tracking `match.py`. `test_staff_api.py` pins the ordering now, so changing the
`ORDER BY` is a decision rather than an accident.

### Found on the way, deliberately NOT fixed — three holes in the migration RUNNER

All three are older than this epic, none is a regression of it, and all three
change how every schema step behaves — which is not a rider on a rename. Two
were found by P3.7a's migration review; the third by P3.7e's first gate run in
a fresh worktree:

1. **a string step is not atomic.** `conn.executescript` commits as it goes, so
   the runner's `with conn:` wraps nothing. A crash between two statements of
   one step leaves the file half-upgraded with the OLD `user_version`, and the
   next open re-enters the step and raises on what already succeeded — a
   database openable only by hand. `migrations.py`'s docstring now says so (it
   previously claimed the opposite); the fix is a `BEGIN`/`COMMIT` per script;
2. **no guard against a database NEWER than the code.** `migrate()` skips
   quietly when `user_version > SCHEMA_VERSION`, so an older build against an
   upgraded file dies later with a raw `no such table` instead of naming both
   numbers. This epic made that likely rather than theoretical, because rolling
   back between items is a real action;
3. ⚠ **no cross-PROCESS mutual exclusion.** `tests/run_all.py` shards across
   processes, and `work/product.db` is gitignored — so in a fresh worktree the
   first gate run creates the file and N workers each read `user_version 0` and
   each replay the whole chain. Observed as
   `sqlite3.OperationalError: duplicate column name: lent_out`, which is
   simply the first `ALTER` to lose the race. It self-heals (the next run finds
   a migrated file) and it is timing-dependent — one reviewer's first run in a
   fresh worktree passed 13/13. That is the argument for writing the mechanism
   down rather than relying on reproducing it. It compounds with (1): the loser
   can leave the file half-upgraded at the old `user_version`.

⚠ **Landing any item of this epic advances the owner's real `work/product.db`**
the first time the gate or the pre-commit hook runs in the primary tree —
`tools/api_contract.py` imports `app.main`, which migrates — and there is no
down step. Snapshot through SQLite's backup API before each merge to `main`.

### The scope fence, held

Pillar 4 is not started and nothing here started it: no login, no auth, no
magic links, no invites, no sign-up, no libraries-per-account cap. Principals
stay dev-trusted. A user belonging to more than one account is *representable*
after P3.7b and *unreachable* until P4.3 — the correct state, not an omission.
Also not built: the merge of two Books that are the same work in two libraries
of one account (VISION §4.1 records it as the user's escape hatch), and any
per-library role scope (no dead nullable column).

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

## ⚠⚠ Scratch space is `D:\tmp` — never bare `/tmp` (2026-08-10)

**`/tmp` means two different directories on this machine**, and the mismatch is
silent:

| who | resolves `/tmp` to |
|---|---|
| Git Bash (MSYS) | `C:\Users\<user>\AppData\Local\Temp` — the `usertemp` automount in `C:\Program Files\Git\etc\fstab` |
| the Windows-native file tools | `<current drive>:\tmp` — i.e. `D:\tmp` while the cwd is this repo |

So a shell command and a file write that both name `/tmp/thing` touch
**different files**, and neither errors. It cost a real near-miss: a git
worktree created at `/tmp/tidy` (→ `C:\…\Temp\tidy`) was edited at
`/tmp/tidy/...` (→ `D:\tmp\tidy\...`), the edit appeared to succeed, and the
worktree still held the old file. The tests that then ran were verifying a
stale tree while reporting success — the most expensive kind of wrong.

**The rule: always name the drive.** `/d/tmp/x` in a shell, `D:\tmp\x` for a
file tool. One real directory, no ambiguity, and it sits on the same volume as
the repo (so worktrees are a fast local operation). `D:\tmp` is created; a
worktree there was verified to round-trip through both toolchains.

⚠ This is not fixable from inside the repo. `/tmp`'s mapping is set by the MSYS
runtime at process start from `/etc/fstab`, so no `.bashrc` export can move it,
and that file lives under Program Files and needs elevation. If bare `/tmp`
should ALSO point at D: as a safety net, run **once, from an elevated shell**:

```powershell
Add-Content -Path "C:\Program Files\Git\etc\fstab" -Value "`nD:/tmp /tmp ntfs binary,posix=0,noacl 0 0" -Encoding utf8
```

Even then, prefer the explicit form: the file tools resolve `/tmp` against
whatever drive the cwd is on, so bare `/tmp` is only ever correct *by
coincidence*.

## Working style notes

The owner is a senior engineer (25y) who values honest assessment over
optimism, catches overstated claims, and wants deterministic/cost-efficient
solutions. Report real numbers, flag what's unverified, don't oversell. When a
refactor might regress accuracy, measure before and after on the sample photos.

⚠ **Multiple sessions run against this one working tree.** A parallel session
may have a different branch checked out, so a `git checkout` here can revert
another agent's files underneath it. Do isolated work in a worktree
(`git worktree add D:/tmp/<name> <branch>`) and merge from there; the primary
tree stays where its owner left it. Landing a branch this way — build the
commit, merge `--no-ff` in a worktree at `main`, push, remove the worktree —
never moves this directory at all.


## P4.0a — the migration runner owns one transaction (pillar 4 begins)

Pillar 4's first landing is not auth — it is the runner that every auth
schema step will ride through. The three holes recorded at P3.7
(TENANCY_BOUNDARY_PLAN, "Found on the way") were closed together, in
`app/adapters/migrations.py`, before v15 exists to be hurt by them:

- **atomicity**: the whole pending chain — every not-yet-applied step and its
  `PRAGMA user_version` bump — runs in one explicit `BEGIN IMMEDIATE` …
  `COMMIT`. String steps are split by `sqlite3.complete_statement` and
  executed statement-by-statement; `executescript` is banned in the runner
  (it commits before it starts, then autocommits as it goes). A crash leaves
  the file at the version it STARTED at — never between;
- **cross-process exclusion**: the write lock lands BEFORE `user_version` is
  read, and the version is re-read under it. N test workers opening a fresh
  worktree's first database replay the chain exactly once; the loser finds
  the winner's number. The recorded `duplicate column name: lent_out` race
  reproduces on demand by reverting either half (measured at review:
  `executescript` restored → 1/6 runs; deferred `BEGIN` → 8/8);
- **newer-than-code**: `SchemaNewerThanCode` names both versions and the
  file at the door, instead of a silent skip and a later raw `no such
  table`. The guard exists from P4.0a on — an older checkout still dies the
  old way, which the class docstring says.

Decisions worth recording, both corrected by the review pass:

- **one transaction per RUN, not per step — and for atomicity, not the
  race.** The plan text suggested per-step `BEGIN`/`COMMIT`; a per-step
  variant that re-reads under each step's lock is equally race-free
  (measured). What the single transaction buys is that no file is ever at
  an intermediate version. The first draft of the docstring claimed the
  race as the reason; review-quality proved that claim false empirically,
  and the stated reason was fixed before it could teach anyone to delete
  the guard;
- **steps never manage transactions, with zero exceptions.** v13/v14's own
  `BEGIN` became dead the moment the runner owned the transaction; a
  guarded `_begin()` shim survived one draft and was deleted — dead code
  that contradicts the rule stated thirty lines above it is exactly the
  example the next step author copies. Their schema statements are
  byte-identical to what shipped;
- **the dies-halfway crash test drives the REAL `migrate()`** through the
  dying connection. Its first P4.0a form open-coded the runner's
  transaction shape around the step, and stayed green under three runner
  mutations — a mirror, not a gate ("never re-state the thing you are
  trying to gate", the test's own warning, one level up).

Review evidence (review-migration, in its own worktree): a database built at
EVERY version v0–v13 with real rows migrates clean under the store's exact
pragmas; the splitter is byte-equivalent to `executescript` across all
twelve string steps (schema diffed table by table); whole-chain time at the
owner's real size is 16ms, and a reader during the chain returns in 1ms
under WAL, so the staff service never blocks. The failure envelope for the
10s busy timeout starts around a 600× larger chain, and the lock failure now
names the file and what was happening.


## P4.1 — login: the magic link, and the day the fallbacks died

Two landings (P4.1a additive, P4.1b the cutover), each with its own review
pass folded before merge. The long-standing sentence closed here: the
unauthenticated-LAN trade ("until pillar 4") ended when every `/api/v1`
route began requiring a session cookie — verified live against the owner's
real database: login screen, link printed by the dev mailer, redeem, 272
books, sign-out, and a cookie-less `curl` answering 401.

**P4.1a** added machinery without consuming it: `app/domain/auth.py` holds
every number and rule (90-day rolling sessions refreshing when under 60
days remain — one write a month per device; 15-minute single-use tokens;
the rate doors), schema v15 (sessions + login_tokens, HASHES only), the
`AuthStore`/`Mailer` ports, three pre-auth routes with their own closed
exemption list and structural meta-test, and the identity anchor: the
bootstrap linked `BOOKSNAP_OWNER_EMAIL` into the owner's email-less user
row while it still existed. The pre-commit migration review earned its
place — it found that anchor gap (v15 made `users.email` load-bearing and
the owner's row predated email entirely; without the link, P4.1b's cutover
would have stranded 286 books under a user nobody could authenticate as).

**The review fleet then earned its place twice more.** Security measured a
targeted LOCKOUT — five link requests for the owner's address from
anywhere closed the owner's own sign-in for an hour — so the narrow rate
door counts the (address × source) PAIR now; it also measured a CRLF
payload riding an "email" into the mailer message (a forged Bcc, verbatim)
and into `users.email`, so the shape check refuses control characters and
inner whitespace, and nothing else. Data-integrity proved the memory
adapter's GIL-atomicity claim false with numbers (2299/4000 double-redeems
at 4 threads — a real lock now), found the email-uniqueness rule enforced
only by the sqlite index (a port-level `EmailTaken` in both adapters now,
and the redeem races it idempotently), and found `sessions_by_user` was an
index nothing read — `revoke_sessions_of_user` (the lost-phone answer the
90-day lifetime assumes) and `purge_login_tokens` (expired rows kept
addresses in cleartext forever; every link request now sweeps) exist
because of it.

**P4.1b deleted, structurally:** all three dev-trusted fallbacks
(`current_library`'s no-lookup branch, `policy._role`'s ADMIN upgrade,
`owning_account`'s id-as-account), `DevPrincipal`, `_bootstrap_dev_user`
(pinned gone by `test_the_composition_root_writes_no_tenancy_at_all` — an
AST-style check, because that hazard returns as a WRITE, not a flag), and
`routers/libraries.py`'s `_user`/`_account`. The `Principal` port is
identity-only — a session says WHO; which libraries follow is the tenancy
store's answer, resolved in the one place H2 always named. "Operating as"
for `POST /libraries` is the request's own library header (the client's
actual selection); a multi-account caller naming nothing is refused with
instructions, never guessed at. `refreshed()` wired in
`app/api/principal.py`, the one door every authenticated request passes.

**Client:** the login screen replaces the whole tree on any 401 —
`SIGNED_OUT_EVENT` fires from the ONE function all five request helpers
throw through, so a new helper cannot opt out silently. The login route is
the one hash route that keeps its query (the general parse rule eats `?…`,
which would have eaten the token). The email input is `dir="ltr"` inside
the RTL page, and `input[type=email]` joined `base.css`'s styled selector
list — it was unlisted, and no jsdom test can see UA chrome.

Worth remembering: the sign-in marker in client tests is the LANGUAGE
toggle, not the library switcher — one library renders the switcher as a
plain label (the settled §4.1 demotion), so a test waiting for a switcher
button waits forever on exactly the default fixture.

Admin console: unchanged by design. Its reads are the staff service (own
token); its tenancy writes go through the product API and now ride the
operator's product session — cookies are host-scoped, not port-scoped, so
signing into the product once per browser covers the proxied console.
