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
  static/       single-file vanilla-JS UI (no build step, no CDN)
tests/          test_core.py (matcher/normalize), test_integrations.py (adapters, mocked)
```

Stages are independent and individually callable, so the server can parallelise
OCR across cores and run the fallback in a separate queue.

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
letters so OCR final/medial confusion is harmless), then per catalog entry
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

`ground_truth.json` holds the owner's hand-labelled shelves (IMG_6082: 21
books, IMG_7849: 14). `booksnap/scoring.py` reports precision/recall over the
DISTINCT set of books a run claims; `GET /api/runs/{id}/score` and
`tools/rescore.py` expose it. **Precision is the expensive metric here** — a
missing book is noticed, a phantom one silently rots in the catalog.

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

## Tests

`python tests/test_core.py` (7, matcher/normalize) and
`python tests/test_integrations.py` (6, NLI+fallback adapters, fully mocked/
offline — no key, no network, no cloud SDK needed). Keep these green.

## Known constraints / next steps (roughly prioritised)

1. FIRST live NLI call: verify the `_parse` field mapping (see ⚠️ above).
2. Wire ONE real fallback provider; measure the true combined match rate on the
   4 sample photos (prototyping could only measure the deterministic ~76%).
3. OCR is ~20s/spine single-threaded because of the 2 rot × 2 height × 2
   binarize × 2 model search. Parallelise across cores; ALSO prune the variant
   search (measure which combos actually produce winning reads) — directly
   serves the "don't waste compute" goal.
4. Segmentation occasionally over/under-splits adjacent same-colour spines; a
   small YOLOv8 spine model would be more robust and handle tilted/horizontal
   books. Only pursue if classical detector proves insufficient at scale.
5. Wrap the core in FastAPI; build the PWA capture + review-screen front-end.

## Working style notes

The owner is a senior engineer (25y) who values honest assessment over
optimism, catches overstated claims, and wants deterministic/cost-efficient
solutions. Report real numbers, flag what's unverified, don't oversell. When a
refactor might regress accuracy, measure before and after on the sample photos.
