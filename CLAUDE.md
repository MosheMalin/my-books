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
tests/          test_core.py (matcher/normalize), test_integrations.py (adapters,
                mocked), test_layering.py + test_api.py (product app),
                run_all.py (runner with a real exit code)
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
    text.py       book_key() over booksnap.catalog.normalize — NOT a copy
    search.py     Hebrew search SEMANTICS: parse + rank, pure and portable
  ports/        Protocols: Principal, Clock, IdGen, BookStore
  adapters/     implementations behind the ports
    sqlite_store.py  the real one (D1); connection per operation, WAL
    memory_store.py  the API ring's store, and the contract's 2nd implementation
    migrations.py    versioned schema via PRAGMA user_version (H6)
    legacy_import.py work/*.json -> entities; I/O and PURE mapping split
  api/          FastAPI routers under /api/v1 + DTOs. THIN — no rules
    routers/meta.py   service + library identity
    routers/books.py  list / get / patch / delete / manual add / export
  api/openapi.json          committed contract, regenerated, never hand-edited
  main.py       the composition root — the ONE file allowed to cross layers
  web/          React + Vite + TS client; talks only to /api/v1
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
| `test_domain.py` | 22 | the VISION rules that can be silently reversed |
| `test_store_contract.py` | 75 | one store spec × every implementation + isolation |
| `test_legacy_import.py` | 21 | `work/*.json` → entities, against a committed fixture |
| `test_search.py` | 15 | Hebrew search, against 24 real queries on the real 251 books |
| `test_layering.py` | 9 | the one-way import rules (plan H1) |
| `test_api.py` | 28 | `/api/v1` shapes + the versioning/tenancy meta-tests |

246 total as of P1.5. No pytest dependency, deliberately — the repo has never
had one and the accuracy gate runs on bare python. Counts grow with each run's
fixes; SESSION_NOTES.md tracks the history.

**`test_domain.py` is not coverage** — it is one test per sentence of VISION
that someone could plausibly "fix" later, and every one was verified to FAIL
when its rule is reversed (mutation-checked, not assumed). Two of them are
structural rather than behavioural, which is the more valuable kind here:
`Copy()` may be constructed only in `new_book`/`add_copy` (an AST walk, so it
also constrains the reconciliation code that P2.3 will add to the same
package), and `normalize()` may not be re-implemented in `app/domain`. Add
rules there, not assertions about dataclass plumbing.

**`test_store_contract.py` is ONE spec run against EVERY implementation** —
24 cases × (`MemoryBookStore`, `SqliteBookStore`) + 4 sqlite-specific. Adding
an adapter (Postgres) means adding one line to `IMPLEMENTATIONS`; that is what
makes D1's datastore choice a swap rather than a leap. It carries the
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
`npm --prefix app/web run test` (vitest + React Testing Library) and
`npm --prefix app/web run typecheck`. Test what encodes a *decision*, not
layout and not DTO plumbing — same standard as the Python rings.

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
