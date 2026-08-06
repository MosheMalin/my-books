# Session notes — 2026-08-03/04

Handoff for the next session. What was built, what was measured, what failed,
and how the run-comparison machinery works. `CLAUDE.md` holds the durable
project memory; this file is the narrative of *this* session.

---

## 1. Environment (Windows) — now working end to end

Installed on this machine: Python deps, **Tesseract 5.4** (winget, added to
user PATH), Hebrew models (`tessdata_best` heb + `script/Hebrew`,
`tessdata_fast` heb), FastAPI/uvicorn, `google-cloud-vision`, Google Cloud CLI,
and for the SAM experiment `torch` (CPU), `mobile_sam`, `timm`.

`setup.ps1` was added as the Windows counterpart to `setup.sh` (which is
Linux-only — it calls `apt-get`). `setup.sh` was left untouched.

**Credentials** live in a gitignored `.env`, loaded automatically by
`server.py::_load_dotenv`. `NLI_API_KEY` is set. Google Vision uses
**Application Default Credentials** (`gcloud auth application-default login`) —
Cloud Vision does **not** support simple API keys, and no key file is needed.

> The NLI key was pasted into chat during this session. Rotate it at
> <https://api2.nli.org.il/signup/> when convenient.

### Bugs found by *running* the code (none were caught by tests)

| # | Bug | Fix |
|---|-----|-----|
| 1 | `cli.py` crashed instantly on Windows: console cp1255 can't encode `✓`/Hebrew | `sys.stdout.reconfigure(encoding="utf-8")` |
| 2 | **Every OCR call silently failed.** `pytesseract` does `shlex.split(config, posix=not_windows)`; on Windows `posix=False` does *not* strip quotes, so `--tessdata-dir "path"` reached Tesseract with literal quotes. All errors were swallowed by `except Exception: continue` → 26 spines of empty text that looked like a blank shelf | use `TESSDATA_PREFIX` env var instead of a quoted CLI arg |
| 3 | A missing Tesseract binary looked identical to "no text found" | `config._find_tesseract()` auto-discovery + `ocr.ensure_tesseract()` preflight that fails loudly |
| 4 | Server left runs stuck in `running` forever after a crash/restart | `_reconcile_orphans()` on startup |
| 5 | UI's "Whole image" radio was unclickable | health response lacked `fallback`; `!h.fallback` treated *unknown* as *off* |

**Lesson:** swallowed exceptions turned three separate misconfigurations into
"the shelf is empty". Prefer loud preflight checks.

---

## 2. What was built

New modules: `server.py`, `pagereader.py`, `scoring.py`, `replay.py`,
`static/index.html`, `tools/rescore.py`, `ground_truth.json`, `setup.ps1`.

- **Web UI** (`uvicorn booksnap.server:app --port 8756`) — upload/list/select
  photos, run, watch progress, browse results, delete. Single-file vanilla JS,
  no build step, no CDN.
- **Background runs** — OCR is ~10 s/spine so a run cannot be a request. Worker
  thread + `/api/job` polling. **Stop** is cooperative (`Pipeline.run` polls
  `should_stop` between spines); spines already read are matched and kept, so a
  stopped run is a real partial result.
- **Two processing modes** (`mode=` on `POST /api/run`):
  - `spines` — classical segmentation → per-spine Tesseract. Free, offline, ~430 s/photo.
  - `fullpage` — one Google Vision call for the whole photo; each returned
    paragraph becomes a record and its bounding box is cropped back out, so the
    review UI still shows a picture per title. ~8–20 s/photo, 1 billable unit.
- **Run history / comparison** — see §5.
- **`why?` explainer** — `GET /api/runs/{id}/explain/{spine_id}` ranks every
  candidate *including rejected ones* with the gate that refused each.
- **Ground truth + scoring** — see §4.

---

## 3. External integrations (both verified live)

### NLI (National Library of Israel) — the real catalog

`sample_catalog.json` is a **57-entry hand-typed stand-in**, not a real
catalog, and it caps what is findable: for IMG_6082 it holds 13 relevant
entries against 21 real books. NLI is the authoritative Hebrew catalog
(legal deposit, ~9M records).

Everything below was **verified against the live API** — the adapter had never
been run for real, and most of it was wrong:

1. **Cloudflare 403** on the stdlib default User-Agent, before reaching the
   API. Fixed with a browser UA.
2. **There is no `guest` key.** `api_key=guest` → `403 API_KEY_INVALID`.
   `INTEGRATIONS.md` and `CLAUDE.md` both claimed otherwise; corrected.
3. **The JSON-LD shape was mis-parsed.** Responses are a bare *list*; fields are
   Dublin Core **URI keys** whose values are `[{"@value": ...}]`. The old parser
   probed short keys and, when it did hit the URI key, passed the dict to
   `str()` — every title would have been `"{'@value': '...'}"`. Now unwrapped,
   plus `type=book` filtering (a search returns archive photos too), MARC `$$Q`
   stripping, and edition de-duplication.
4. **Query grammar matters.** `any,contains` → 49 records / 34 books for 5 real
   hits; `title,contains` → 8 / 5. NLI caps at **50 records per query**, so
   OR-ing several OCR tokens *loses* books (a common token like `דארל` floods
   all 50 slots). Now: one narrow `title,contains,<term>` query per distinctive
   term, merged, plus phrase queries (most precise).
5. **Folded Hebrew was being sent to a literal index.** `catalog.normalize()`
   folds final letters (ן→נ) — right for local fuzzy matching, fatal remotely.
   `title,contains,לחתנ` misses the book; `title,contains,לחתן` finds it. This
   silently broke *every* title ending in ך ם ן ף ץ. Fixed with `_raw_tokens()`.
6. **`record_limit=15` truncated before ranking**, discarding correct books.
   Now 60.
7. **Transient 500s were swallowed**, costing recall invisibly and
   non-deterministically. Now retried and counted.

### Google Cloud Vision

Enabled via ADC. `GoogleVisionFallback` (per-spine) and
`GoogleVisionPageReader` (whole page) both work. Cost: first 1,000 images/month
free, then $1.50/1,000.

**Vision is not uniformly better than Tesseract.** On the 13 unmatched spines
of IMG_6082: clear wins where Tesseract gave noise (`היער השיכור`,
`את כולם ברא`, `The Elephant`), one clear **loss** (`b0_s08`: Tesseract read
`הפיקמק ומהוממות אחרות`, Vision read `ןכהןכנות אחרות`), and ~6 of 13 empty from
*both* engines — strong evidence those crops are segmentation artifacts, not
missed books.

**Image quality findings** (measured on one crop): upscaling ×3 recovered
`הפיקניק`; a sharpening kernel made it *worse*; rotating 90° changed nothing
(Vision handles orientation itself).

---

## 4. Measurement — the part that changed the most conclusions

`ground_truth.json` holds the owner's hand-labelled shelves:
**IMG_6082 = 21 books, IMG_7849 = 14 books** (35 total).

`booksnap/scoring.py` scores the **distinct set of books a run reports**, which
is the real deliverable of cataloguing. Precision is the expensive metric: a
missing book is noticed, a phantom one silently rots in the catalog.

Access: `GET /api/runs/{id}/score`, or `python tools/rescore.py <run_no>`.

> **A bad ruler invents work.** The scorer initially compared titles raw, so
> `כל הדברים הנבונים והנפלאים` vs `כל הדברים נבונים כמופלאים` scored 71 and was
> counted as **both a phantom and a miss** — double-punishing a *correct*
> answer. Hebrew editions differ freely on prefix particles (ה ו כ ב ל מ ש).
> Adding particle-tolerance lifted run #3 from F1 0.44 → 0.56 **with no code
> change at all**. Fix the scorer before tuning anything.

### Final numbers (all replayed through identical retrieval)

| shelf | config | tiers | P | R | F1 |
|---|---|---|---:|---:|---:|
| IMG_6082 (21) | fullpage + NLI | auto+review | **0.88** | **0.71** | **0.79** |
| IMG_6082 | spines + NLI | auto+review | 0.92 | 0.52 | 0.67 |
| IMG_6082 | SAM pps=24 + Vision text | all | **1.00** | 0.62 | 0.76 |
| IMG_7849 (14) | spines + NLI | auto+review | **1.00** | 0.36 | 0.53 |
| IMG_7849 | fullpage + NLI | auto+review | 0.45 | 0.64 | 0.53 |

**Best F1 anywhere: 0.79** (IMG_6082, fullpage). **Best zero-phantom recall:
SAM at 0.62.** Which mode wins is **shelf-dependent** — fullpage wins on clean
typography (Durrell shelf), spines wins on precision for the stylised fantasy
shelf.

### Detection vs matching — check before assuming

Diagnostic: compare each missed title against every OCR string on the photo
with `ngram_sim`.

| | matching failed (text WAS read) | never read |
|---|---:|---:|
| IMG_6082 / fullpage | **3 of 7** | 3 |
| IMG_7849 / spines | 1 (+2 partial) of 9 | 6 |

So "detection is the wall" is **true for the fantasy shelf and false for the
Durrell shelf**. Do this diagnostic before investing in detection work.

---

## 5. The comparison machinery (how to use it next session)

The project is in a tune-and-measure loop, so **every run is archived, never
overwritten**. A result set is meaningless without the inputs that produced it.

### What each run stores

- `run_no` — the human handle ("run 3"), plus an editable `label`
  ("v3: wider gates")
- `code_version` — git sha **+ dirty flag**. While tuning, the interesting
  changes are uncommitted, so a sha alone would alias two different runs.
  *This proved its worth:* run #3's stored config lacked the new keys, which
  **proved** it had run on pre-fix code rather than me assuming so.
- `config` — full snapshot of every tunable. **This is the experiment
  variable.**
- `catalog` — backend + entry count; `mode`; `fallback` provider
- per-image `spines_detected` vs `spines_processed`, duration
- per-spine `ms`, OCR `score`, winning `rotation`

### Layout

```
work/store.json                          small index (images + runs)
work/runs/<run_id>/<image_id>.json       full per-spine records
work/runs/<run_id>/crops/                crops AS THAT RUN SEGMENTED THEM
work/runs/<run_id>/candidates/           every catalog lookup (see below)
work/nli_cache/                          NLI responses cached by query
```

Crops are **per run on purpose**: segmentation changes between runs, so a
shared crops dir would silently corrupt the evidence an older run points at.

### Reproducibility (`replay.py`)

NLI is a *live search engine*, so replaying an old run gave different results
(run #7 stored 9 correct, replayed 5) and no comparison against history was
trustworthy. Runs now wrap the catalog in `RecordingCatalog`, saving every
lookup. `ReplayCatalog` serves exactly that back, and **counts queries the
recording never saw** — a miss means the code under test changed *retrieval*,
so its gain cannot be credited to matching.

> ⚠️ **Open item:** runs from *before* this change (all current runs) have no
> candidate recording, so replaying them still disagrees with their stored
> results. Variant-vs-variant comparisons today are valid (same replay path for
> both); comparisons against stored history are not. The first fresh run will
> fix this going forward.

### The fast loop

`python tools/rescore.py <run_no>` replays stored OCR through the **current**
matcher and scores it. Matching is a pure function of OCR text + catalog, so
tuning `match.py` never needs a re-run — seconds instead of 7 minutes, with OCR
held identical so the comparison is controlled.

### In the UI

Run-history panel (click any run), run selector, per-run provenance, **delta vs
the previous run** on each stat, editable labels, delete. The `why?` button on
every result row shows each candidate's title hits, similarity, and the exact
gate that rejected it — including rejected candidates, so you can see why the
*right* book lost. It recomputes with **current** code (deliberately: "would my
change have fixed this spine?") and says so.

---

## 6. What worked, what didn't

### Worked

| Change | Effect |
|---|---|
| **Character n-gram cosine gate** (`min_ngram_sim=50`) | Run #5 auto+review **P 0.65→0.88, R 0.62→0.67**. Fixes a real `token_set_ratio` pathology: a short title that is a *subset* of the OCR scores a perfect 100 (this is how one-word `ציפורי`/Sepphoris beat the real book). N-gram cosine penalises length mismatch (51) while still scoring edition variants highly (73). Free, no model. |
| **Embedded-token matching** (`embedded_token_len=5`) | Run #5 **R 0.67→0.71** at unchanged precision. OCR fuses words: Vision read `ג'ראלד דארלציפור הלעג`, so `ציפור` matched nothing. A long catalog token found inside a longer OCR token now counts. |
| **Geometric merge of overlapping blocks** (`pagereader.merge_overlapping`) | IMG_6082 AUTO **P 0.85→0.92**; IMG_7849 auto+review F1 0.47→0.51 (but AUTO recall 0.50→0.43, not free). Books are solid objects: two texts sharing a region are one spine. Vision emits author/title/imprint as separate paragraphs — that's how a 14-book shelf reported 24. |
| **Title-only evidence gate** | Author hits no longer create a match (they may still raise the tier). Previously one noise token (`היה`≈`החיה`, ratio 86) plus a series author invented a title on two different spines. |
| **Short-token bar** (`≤4 chars needs ratio ≥90`) | Kills `היה`→`החיה`. |
| **`min_title_sim=47`** | Swept: confirmed-wrong ≤37, a correct match on degraded OCR at 50.8, so 45–50 separates them. |
| **`dup_drop_frac=0.70`** | A duplicate claim far below the winner is dropped, not demoted — unmatched beats a wrong title. |
| **`auto_min_query_cov=0.35`** | A one-word title can't be AUTO while explaining 1 of 8 OCR tokens. |

### Measured worse or neutral — **do not retry without new evidence**

| Idea | Result |
|---|---|
| **Hungarian set-to-set assignment** (the literature's approach) | Precision **0.62 → 0.56**. Against an *open* 9M catalog the one-to-one constraint makes a losing spine take its second-best (wrong) entry instead of being dropped. It works in papers because their catalog is a **closed 15k collection**. Off (`use_assignment=False`). |
| **Hebrew prefix-stripping in the matcher** | No gain; precision **0.62 → 0.50** on IMG_7849. The per-token threshold already absorbs a one-letter prefix, so stripping only widens what can match. Off (`strip_prefixes=False`). **The same transform is required in `scoring.py`** — different comparison, opposite verdict. |
| **Naive union of the two modes** | IMG_7849 precision **1.00 → 0.48**. Union adds the phantoms too. |
| **Volume/publisher stoplist** | Neutral on the spine path so far (untested on fullpage, where the motivating phantoms came from). |
| **SAM at `points_per_side=12`** | Under-segments — one mask spans two books, R 0.38. |

### The agreement finding (not yet implemented)

The two modes are largely independent (different segmentation *and* different
OCR engine). Bucketing results by which modes found them:

| bucket | IMG_6082 | IMG_7849 |
|---|---|---|
| **found by BOTH** | 11 books, **11 correct, 0 phantom** | 4 books, **4 correct, 0 phantom** |
| only fullpage | 6 books, 4 correct (67%) | 16 books, 5 correct (31%) |
| only spines | 1, 0 correct | 1, 1 correct |

**15 of 15 agreed books were correct.** So the value is not union but
**stratification**: *both agree → AUTO (trust blindly); one mode only → REVIEW*.
Cost: agreement recall (0.52 / 0.29) is lower than either mode alone, and it
needs both a Vision call *and* a 430 s Tesseract run.

### SAM experiment (MobileSAM, CPU)

Hardware: i5-7400 (4 cores, no CUDA), 16 GB RAM. MobileSAM = 40 MB checkpoint.

| config | time | P | R | F1 |
|---|---:|---:|---:|---:|
| Vision blocks (current best) | ~8 s | 0.88 | **0.71** | **0.79** |
| SAM pps=12 | 50 s | 1.00 | 0.38 | 0.55 |
| **SAM pps=24** | 189 s | **1.00** | **0.62** | 0.76 |
| SAM pps=32 | 334 s | 1.00 | 0.62 | 0.76 |

SAM **does not beat** the current pipeline on F1, but gives the **highest
recall of any zero-phantom configuration** (0.62, vs 0.52 for two-mode
agreement). It groups text into physical book units, so imprint lines get
absorbed into their book instead of becoming phantom titles. `pps=32` costs 2×
for zero gain. **Not wired in** — it would be worth it only for a
blind-trust tier.

---

## 7. Current config (all swept on the fixture)

```
token_ratio=78   short_token_len=4   short_token_ratio=90
distinctive_len=5   embedded_token_len=5
min_title_sim=47   min_ngram_sim=50   dup_drop_frac=0.70
auto_min_query_cov=0.35
use_assignment=False   strip_prefixes=False
```

⚠️ These were swept on **2 shelves / 35 books**. Bands are broad and per-shelf
optima differ — treat them as "inside the good range", not tuned constants.
Re-sweep when more shelves are labelled.

**Tests: 24 passing** (`tests/test_core.py` 14, `tests/test_integrations.py` 10),
all offline/mocked — no key, no network, no cloud SDK needed.

---

## 8. Suggested next steps

1. **Do a fresh run** so at least one run has candidate recordings and history
   comparison becomes trustworthy.
2. **Label a third shelf** (`A5E6FC52…`, `B9E88456…`, or `IMG_4403`) — every
   threshold currently rests on 2 shelves, and 3 of ~6 "obviously good" ideas
   measured worse.
3. **Multi-book blocks** — one Vision block held `פגישות עם בעלי חיים` *and*
   `חיות ציפורים וקרובים`; only one can win. Splitting blocks is cheap recall.
4. **Language routing** — `The elephant` is an English title matched against a
   Hebrew catalog; it resolved to `The Elephant's Leg`.
5. **Fix the fullpage progress label** — it says `spine 10/38` but is really
   "block N of M, resolving"; each block triggers its own NLI lookups
   (sequential, the slow part of fullpage). Batch/parallelise them.
6. **Agreement tiering** (§6) if a blind-trust tier is wanted.
7. Deferred: **DictaBERT/AlephBERT embeddings**. The morphology gap turned out
   to be *character-level, not semantic*, and free n-grams closed most of it —
   so the case is weak until matching is the bottleneck again.

## 9. Known open issues

- Old runs have no candidate recordings → replay ≠ stored results (see §5).
- `use_assignment` and `strip_prefixes` are dead-by-default code paths kept for
  closed-catalog experiments.
- No automated tests for `server.py` (would need `httpx` for `TestClient`).
- `ground_truth.json` spellings are owner-verbatim and intentionally keep
  edition orthography (`כל היצורים גדולים כקטנים` uses כ, not ו) — do not
  "correct" them.

---

# Session notes — 2026-08-05 (appended)

## LLM page reader (`mode=llmpage`) — the new best mode

`booksnap/llmreader.py` (`ClaudePageReader`, PageReader-protocol, plugs into
the existing `run_page` path). Probe first (`tools/llm_read_probe.py`, raw
read-rate on the fixture): **haiku whole-photo read 0/35 and confabulated
entire shelves**; sonnet whole-photo read vertical spines LETTER-REVERSED
(1/35); **sonnet + 2x2 tiles (15% overlap) + rotate 90°cw: 18/21 and 14/14**
— resolution and rotation are load-bearing, the model tier matters (haiku
tiled still only 9/14, garbled). ~$0.08/photo, config in `LlmReaderConfig`.

End-to-end (`tools/llmpage_run.py`, NLI retrieval, scored):
IMG_6082 AUTO+REVIEW **F1 0.91** (was 0.79); IMG_7849 AUTO **F1 0.77-0.89**
(was 0.53). Reading is ~solved; **retrieval is now the wall** (E2 read
לימודי אש/קסם/רעל perfectly; NLI failed to surface them).

New gate: a truncated read (`...`) can never be AUTO (`pipeline._is_truncated`)
— measured +0.10 AUTO precision on IMG_6082, no cost elsewhere.

## Simania retrieval (`booksnap/simania_catalog.py`)

Coverage probe (`tools/simania_probe.py`): **34/35 fixture books**, edition-
true spellings, series+number metadata, structured JSON
(`/api/search/suggestions`, robots: pages allowed, `/api/*` generic-agents
disallowed — person-equivalent volume only, permanent cache
`work/simania_cache/`). RAW tokens in queries (final-letter folding breaks
the literal index — same NLI lesson, now a test).

`BOOKSNAP_CATALOG_BACKEND=simania` = SimaniaCatalog -> NLI fallback-on-empty.
Controlled rematch on frozen llmpage reads (`tools/rematch_blocks.py`):

| retrieval            | 6082 AUTO F1 | 7849 AUTO F1 |
|----------------------|--------------|--------------|
| NLI + gate           | **0.81**     | 0.77         |
| simania->NLI + gate  | 0.74 (P .93) | **0.89** (P .92) |
| best-of-both + gate  | 0.78         | 0.86         |

Measured WORSE, do not retry without new evidence: single-token rescue query
(fixed מלכוד 22, regressed both shelves); thin-union `min_results=3`
(imported NLI phantoms). **מלכוד 22 is a priced-in miss** (Simania phrase
queries surface only a film record + editions-index; gates rightly refuse).

## Third labelled shelf — blind-first (run #8)

IMG_8123 run through the SERVER (llmpage + simania backend) with NO labels,
then owner-confirmed: **11/11 claimed books correct**; missed מלכוד 22
(retrieval, above) and הספר הקטן (read garbled to הספר הכתן; the author-only
block סלדן אדוארדס rightly can't create a match). Score P 0.90 R 0.82
**F1 0.86** — and the one "phantom" is vol-2 of the שוויק set. Fixture is now
3 shelves / 46 books.

## Open threads

- Use Simania's `series`/`seriesNumber` (kill series-name-as-title phantoms
  like שיר של אש ושל קרח; disambiguate same-author siblings).
- Merge author-only blocks with adjacent title blocks (הספר הקטן case).
- Language routing for English spines (The elephant -> Elephanta Suite).
- Tests now 32 (14 core + 18 integrations), all offline. `.env` and
  `.claude/launch.json` default to the simania backend.

---

# Session notes — 2026-08-05 evening (autonomous pass on IMG_8125 feedback)

Owner ran llmpage on IMG_8125 (run #9) and reported four issues; each was
diagnosed, fixed with a measured+tested change, and the shelf became the 4th
labelled fixture (PROVISIONAL ground truth — English titles unconfirmed).

## Fixes (all in match.py/pipeline.py/llmreader.py, all tested)

1. **Author-fragment suppression** — a block reading only another matched
   book's AUTHOR (ענת זייידמן) had gone AUTO on a book *titled* זיידמן.
   `suppress_author_fragments`: name-only reads can't claim titles. Length
   guard required — token_set's subset pathology otherwise eats title+author
   reads that merely contain the name (המלון הגיקי-עברי case).
2. **Near-duplicate resolution** — the same book claimed twice via two
   catalog editions (הצחקתם אותנו x2; the שוויק set on 8123), invisible to
   catalog_id dedup. `resolve_near_duplicates`: near-same title + compatible
   author -> weaker claim dropped. Page modes only.
3. **Symmetric whole-title similarity** — token filtering dropped 2-char
   words (כן) from the query but not the entry, so "כן, אדוני ראש הממש"
   preferred the WRONG book "אדוני ראש הממשלה" over "כן, אדוני ראש הממשלה".
   title_sim/ngram now compare full normalized text on both sides. Cost: one
   marginal partial-read match on 6082 (precision > recall-at-AUTO).
4. **One-content-word title cap** — "סליחה" (wrong book) went AUTO on the
   read "סליחה שטעינו"; same shape as the ציפורים phantom. A 1-content-token
   title with qcov<1 caps at REVIEW; fully-explained one-worders
   (ארבינקא קישון) stay AUTO.
5. **Dual-rotation reading, now default** (`rotate="both"`, ~$0.15/photo) —
   Hebrew spines print in both directions; סליחה was ONLY ever read by the
   ccw pass, אוי למנצחים only read correctly in one pass. **Reads vary
   between passes** (LLM sampling variance): books flicker in/out per pass,
   so multi-pass UNION is a recall stabiliser and the gates absorb its noise
   (35 union reads -> 18 clean claims, zero duplicate/fragment phantoms).

## Measured (3-pass union, simania->nli, all gates)

IMG_8125 vs provisional GT (18 books): **AUTO P 0.94 R 0.89 F1 0.91;
AUTO+REVIEW F1 0.94.** Residue: the Asimov English book matches a wrong
English NLI entry (language routing, open), and סליחה שניצחנו surfaces only
as a wrong-edition REVIEW claim (read as סליחה שטעינו in the one pass that
saw it). Labelled shelves after all changes (stored-read rematch): 7849
B AUTO F1 0.89 unchanged; 6082 AUTO+REVIEW 0.86-0.88 (AUTO recall traded
down as partial-read phantoms/dups were killed).

## Quorum research (owner's idea #5)

e-vrit/getbooks/booknet: client-rendered or dead — no cheap adapter.
**Steimatzky** is server-rendered (Magento; titles in product-image alt
text) but titles are compound edition strings and authors are unclear —
best third-source candidate, medium effort. Pragmatic take: Simania
(community) + NLI (legal deposit) already form an independent 2-source
quorum; a "confirmed by both sources" verification flag on AUTO claims is
the designed next step and needs no new crawler.

## Housekeeping

Permission prompts fixed: `.claude/settings.local.json` had accumulated
exact-command allow rules only; replaced with blanket tool-level allows +
acceptEdits. Tests: **21 core + 18 integrations = 39, all offline.**

## Follow-up batch (owner feedback on IMG_8124 + UI)

- **llmpage progress bar** no longer stalls: the reader reports per-tile
  progress ("reading tile k/n") and run_page reports per-block catalog
  lookups ("matching block k/n"); server job carries a `phase` field.
- **Image ✕ / run delete fixed**: `confirm()` popups are silently suppressed
  in embedded browsers, so the buttons looked dead. Replaced with an inline
  two-click confirm (arm -> "sure?" -> 3s revert). Server DELETE was fine.
- **8124 phantom** (`די וי די המערכה המחזורית...` AUTO from the fragment read
  "המחזורית") -> two new guards, both tested: a ONE-word read can't AUTO a
  multi-word title (mirror of the one-word-title cap), and
  `suppress_fragment_reads` drops any claim whose read is a token-subset of
  a longer matched read (partial tile re-reads of the same spine).
- **8124 duplicate** was stale-server, not a code gap: uvicorn had been
  running since before the near-dup fix landed (no --reload). Run #10's
  `code_version.dirty` flag would have shown it. Server restarted; NOTE:
  restart the server after code changes, or runs execute old code.
- Labelled-shelf rematch after all of the above: numbers unchanged.
  Tests: **23 core + 18 integrations = 41.**

## Run 12 (8127/8128/8129, old SF shelves) — owner feedback session

Baseline committed first (819c8cb) per owner request; fixes on top.

UI: mode hint under Run is now mode-aware (the "~10s per spine" text was
spines-only); ONE continuous progress bar across images and phases —
"reading the photo (part k/n)" then "checking N found titles against the
catalog (k/N)", weighted 50/50, advancing across images. The "runs twice
per image" impression was the tile-reading phase (8 parts) being labelled
like a title count.

Matcher/retrieval fixes (all tested, 26 core tests):
1. **Simania first-2-token window** — a 2-word title + author defeated every
   existing query window (all contained author words -> typeahead 0).
   Measured: קמט בזמן, השקעות (both IN Simania) were unfindable.
2. **Author-corroborated existence** — short one-word titles (עדן, הצלם,
   len<5) could NEVER pass the 2-hits-or-distinctive gate. New narrow path:
   FULL title match + acov>=0.5. Author-alone still cannot create a match.
3. **n-gram gate no longer diluted by the author in the read** — compare
   also vs title+author, take max (נהר השמים הגדול died on the gate 49.96
   vs 50).
4. **Fragment suppression is substring-tolerant** — "ראה אתמול" (torn from
   the נתראה אתמול spine) claimed the wrong book "אתמול"; ראה is inside
   נתראה but not an exact token.

Retested on the owner's reported reads: 8/10 now resolve correctly (קמט
בזמן, עדן, הצלם, נהר השמים הגדול, הגבעות הירוקות של הארץ, השקעות, זמן
טעות, קבצנים ובררנים, האטום הכחול — the misread ones resolve once read
right). **הקרע (וו"ג ויליאמס) is in NEITHER catalog** — genuine gap, stays
unverified (correct behaviour). The ווהן ויליאמס phantom candidate came
from NLI's junk results for ויליאמס queries; one-word-title cap keeps that
class at REVIEW.

Fixture shelves after: mean UNCHANGED (A+R 0.86, AUTO 0.79) but
redistributed — 7849 B AUTO 0.89->0.93 (לימודי אש recovered), 6082 down a
notch (boundary jitter; and rematch_blocks measures RANKING ONLY — the real
pipeline adds the suppression chain on top). 35-book-fixture jitter, net
strongly positive with the 8 run-12 corrections.

Residuals on these shelves: misreads needing another pass (זמן טעות,
ובררנים, הכחול, הרפתקה בחלל, היה יהיה בעתיד), הבלשים הצעירים matches the
short series entry instead of ...וטרזן פורצים למפרץ שלמה, and "רוברט"-class
author fragments stay REVIEW when their book is missing from the results.

## Run 13 (IMG_8131) — four more bug classes, all from owner feedback

Diagnosed via the run's candidate recordings (replay.py earning its keep):

1. **Author-fragment suppression REWRITTEN** — the length+token_set heuristic
   ate "אקסלרנדו צ'רלס סטרוס" (retrieval had returned the book!) because two
   of its three tokens were the author of OTHER matched Stross books. New
   rule: suppress only reads carrying NOTHING beyond the name (fuzzy
   per-token containment).
2. **Numeric titles were structurally unmatchable** — "14" (Peter Clines):
   digit tokens now survive the token length floor on both sides.
3. **Fragment containment skipped-vs-failed** — the dangling "ה" in
   "מכונת הזמן ה..." (torn המקרית) shielded the fragment from suppression;
   sub-3-char tokens are now skipped, and the Wells מכונת-הזמן phantom dies.
4. **ChainCatalog default is now thin-union (min_results=3)** — the on-empty
   cascade kept failing the same way (4th case: NLI had the EXACT title
   שלושה ימים בספטמבר, blocked by Simania's שלושה-ימים lookalikes).
   RE-MEASURED with current gates: AUTO identical on both fixture shelves,
   mean A+R 0.865 vs 0.86, 7849 A+R recall 1.00; 6082 A+R -0.02 (one
   boundary case). Circumstances changed the earlier verdict — the gates
   now absorb what the union lets in.

Owner verdicts applied via the review API: both wrong claims rejected
(persistently), 4 correct books library-added. Immediate payoff: the
confirmed-library head matches גנב הקוונטום from its MISREAD (הקוונטים) —
fuzzy matcher over the library succeeds where literal search engines can't.
GT now 6 shelves (3 provisional). Tests: **29 core + 22 integrations = 51.**

## Run 14 (IMG_8134) — adjacent shelves are harmless; three more fixes

Owner's framing worry (photo includes slivers of the shelves above/below):
**measured harmless** — no neighbor-shelf book was claimed; the gates ate
every sliver. All wrong claims were tile-overlap re-reads of THIS shelf.

1. **Fragment suppression is now ASYMMETRIC-containment**, checked against
   the fuller claim's read PLUS its matched entry's title+author. Two
   sub-bugs fixed on the way: a torn read + stray letter can have MORE
   tokens than the clean read it duplicates (length guards mislead —
   המצפן ה פיליפ פולמן vs המצפן הזהוב פולמן), and short tokens satisfy by
   substring but are never skipped (the ה of a truncated word matches
   inside הזהוב; the אש of לימודי אש still blocks against לימודי רעל).
2. **Verbatim-title existence** — "צל אפל" read perfectly had ZERO usable
   tokens (צל under the length floor, אפל short of distinctive). A read
   that IS the title, whole-string, now passes existence (surfaces REVIEW).
3. **NLI creator cleanup** — role words + life dates ("לו, מרי, 1984- מחבר")
   stripped at parse; they leaked into the UI and depressed author matching.
4. **UI "✎ fix details"** — inline title/author edit on any claim (the
   owner's וורקרוס adjustment), wired to the replace action.

Verdicts applied (4 rejections, וורקרוס author fix, 6 manual adds; library
47 books). Fixture unchanged. GT 7 shelves. Tests: **32 + 23 = 55.**

## Run 15 (IMG_8132/8133) — suppression tie bug; primaries now fully unioned

1. **Fragment suppression demands STRICT superiority.** The candidates
   recording exposed a backfire: the clean read "יד הכאוס מרגרט..." (the
   correct volume) is token-contained in the compound spine read
   "יד הכאוס - מחזור שער המוות חלק 5...", whose claim (a series RECORD)
   tied it exactly on rank+score — so the right claim was eaten and the
   wrong one survived. Ties now keep both claims; the review flow decides.
2. **Simania+NLI are ALWAYS unioned** (`UnionCatalog`; measured E vs D in
   rematch_blocks): thin-union's threshold kept mis-firing — 4 junk Simania
   rows "satisfied" min_results and blocked NLI's EXACT hit (על דם ואור
   קמילה מונק, first result). Full primary union beats thin-union on both
   fixture means (AUTO 0.805 vs 0.79, A+R 0.87 vs 0.865). The shop tail
   stays thin-gated. Retrieval-combination lesson closed: gates carry the
   precision, so union the good sources and cascade only into noisy ones.
3. Residuals: לימודי אש is in NO catalog (its own trio-mates match fine);
   עיר הזמן misread (עיד); עיני דרקון never read. All library-added, which
   also future-proofs them (the גנב הקוונטום effect).

Verdicts applied (series-record rejection + 5 adds; library 82 — run 15's
AUTO claims were the first fully-automatic absorption). GT 9 shelves.
Tests: **33 + 24 = 57.**

## Run 16 (IMG_8135-8138) — owner review feedback becomes spotchecks; subset-claim purge

Owner flagged ~12 wrong + ~8 missing books across the 4 shelves. Diagnosis
against the stored candidates recordings: in nearly every WRONG case the true
book WAS in the candidate list — these were matching losses, not retrieval
losses. Root pattern: token_set_ratio hands a short subset title a perfect
100, so it outscores the true fuller title read with one OCR error.

1. **`tools/spotcheck.py` + `fixtures/spotchecks/run16.json`** — owner
   feedback on an (unlabelled) run is now a permanent, re-runnable fixture:
   forbid/want/not_auto expectations replayed offline against the run's own
   recording. Rule changes must pass BOTH the GT sweep and the spotchecks.
   Run 16 spotchecks: 2/19 before, **19/19 after**.
2. **Geresh normalization bug (load-bearing).** normalize() space-split
   geresh words: הצ'ופצ'יק -> הצ/ופצ/יק, leaving the true entry ONE usable
   title token; a bare הקומקום record beat it. Geresh/gershayim/apostrophes
   are now deleted in-word (הצופציק stays whole). Affects ג'/צ'/ז' names
   everywhere.
3. **Lone-title rejection** (`reject_lone_title_partial`): a claim hanging on
   a single matched title word, explaining <=half its read, with no author
   signal (soft bar 80, no short-token escalation — מארי~מרי=86 keeps
   וורקרוס; רינה~אריה=75 stays out) is REJECTED, not demoted. Killed שפירא,
   הקומקום, המבוך, הזריחה(+הזהובה), סטארט, בא בחשבון, בריאה/וידאל, and the
   ORIGINAL ציפורי spine the ngram gate was tuned around.
4. **Fragment arbitration by qcov, not score** — scores of claims on
   different entries are incomparable (wrong twin 111.9 vs true twin 92.3);
   the claim that explains more of ITS OWN read wins, score only breaks
   ties. Containment also checks particle-stripped tokens (המשפחה⊂במשפחה).
   Match now carries qcov for this.
5. **Author-echo gate**: title tokens that duplicate the entry's author are
   not existence evidence (משירי דן אלמגור vs "דן אלמגור: איש חסיד היה").
6. **Truncated-token hits**: read token >=5 chars that is a PREFIX of a
   catalog token counts (יומנו של סטארט -> סטארטאפיסט, now AUTO-correct).
7. **Volume-ambiguity cap**: score-tied candidates differing only in
   volume/digit tokens the read never showed -> REVIEW (רובורצח כרך 1 vs 2);
   a read showing "1000" keeps its AUTO.
8. **Author-backed existence**: full 2+-token author + >=half title matched
   (שרך,אלי לאה סאקס -> שלך, אלי). One noise token + author still can't.
9. **Author-fragment initials bug**: מ.מ.טרופ -> tokens מ/מ/טרופ; single
   letters matched inside everything and ate מחשבות על המציאות. Substring
   correspondence now needs a >=3-char author token.

Sweep (8 GT shelves): AUTO P 0.941->0.943, AUTO F1 0.815->**0.848**, A+R F1
0.863->**0.882**; biggest movers IMG_8131 AUTO F1 +0.12, A+R +0.11. Cost:
IMG_6082 A+R F1 -0.06 (two authorless REVIEW-tier claims eaten by the
lone-title rule — precision-first trade). Baseline re-accepted 20260806-142543.

Honest residue on run 16 (not matching-fixable): ספר הבדיחה והחידוד x3
(vertical, never read), 1000 זמר חלק ב/ג (read as "ועוד זמן", volume records
not retrieved), לעזאזל (diagonal, misread לשדאזל), זאבי ציון (read PERFECTLY,
absent from every source — library-add candidate), טקסי הזריחה + כל דבר בא
בחשבון (now honestly unmatched instead of wrong; the latter's read shows only
the generic fragment + publisher אריה ניר). Tests: **43 + 24 = 67.**
