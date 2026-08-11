# CLAUDE.md — booksnap

Hebrew bookshelf cataloguer: the owner photographs shelves, the system reads
spines and maintains a structured catalog. Engine (`booksnap/`) + product app
(`app/`). This file is the distilled rules; the full project log with every
measurement and argument is `docs/HISTORY.md` — consult it before re-deciding
anything that looks odd here, and append new detailed write-ups there.

## Philosophy

- **Deterministic first; LLM/paid API only as fallback.** Exhaust free local
  methods before escalating. (The default *reading mode* is still `llmpage` —
  that rule was never "make the worse reader the default"; the measured gap is
  large and cost is stated on the control.)
- **Nothing enters the library unapproved** (owner, 2026-08-09). A read
  produces findings; a finding becomes a Book only through an explicit ✓.
  MANUAL is the one tier that enters at once.
- **Precision is the expensive metric.** A missing book is noticed; a phantom
  rots silently. Prefer "I don't know" over a plausible wrong match.
- **Never trust an idea that wasn't measured on the fixture.** Hungarian
  assignment, matcher prefix-stripping and a stoplist all measured worse or
  neutral despite being plausible. Fixing the scorer changed conclusions more
  than fixing the code.

## The code cycle

Every non-trivial item goes **plan → implement → review** — `/cycle` runs it
(`.claude/skills/cycle/SKILL.md`). Reviewers are project agents under
`.claude/agents/`, spawned in the background after a commit, findings folded
into a follow-up commit:

| agent | when |
|---|---|
| `review-data-integrity` | substantive server-side change |
| `review-security` | new routes/inputs/credentials/file handling |
| `review-quality` | any substantive change (attacks the new tests) |
| `review-ux` | user-visible behaviour — verifies in a REAL browser |
| `review-migration` | BEFORE committing a schema-version change |

One review pass per landed item is the cadence that has paid — not every
keystroke, not never.

**Epics** (a pillar, a console rework, "focus on X") don't get one stretched
cycle: `/cycle`'s Phase 0 fetches the existing decomposition (the planning/
docs, re-read against what actually landed) or runs a planning pass to
produce one, then executes item by item — each landed on `main` before the
next, pausing for the owner only on unsettled decisions.

## Rules of engagement

1. **Worktrees for parallel work.** Multiple sessions share this tree; never
   `git checkout` under them. Isolated work: `git worktree add D:/tmp/<name>
   <branch>`, commit there, land on `main` with `merge --no-ff`, remove the
   worktree. The primary tree stays where its owner left it.
2. **Scratch space is `D:\tmp`, never bare `/tmp`.** Git Bash maps `/tmp` to
   `C:\Users\<u>\AppData\Local\Temp`; the native file tools map it to
   `<drive>:\tmp`. Same name, two directories, silent mismatch — always name
   the drive (`/d/tmp/x` in shell, `D:\tmp\x` in file tools).
3. **Measure before believing.** Accuracy changes go through `tools/sweep.py`
   (+ spotchecks) BEFORE the claim; UI claims are verified in a real browser
   (jsdom sees no CSS); performance claims come with numbers.
4. **Keep the gates fast.** A gate nobody waits for stops being a gate.
   Python rings ~19s, client ~25s — protect that. No sleeps in tests
   (event-gate instead); reuse expensive setup (app pool, sqlite template,
   shared portal); don't add an eager import of cv2/scipy to a cheap path.
5. **Use subagents.** `Explore` for broad searches, `Plan` for design,
   the reviewers after each landed item — run them in the background and keep
   working.
6. **Shared things live in `app/ui`** — a mechanism both clients need, or a
   rule they must not disagree about. One copy of every rule, everywhere:
   normalizer, sort key, policy matrix, resolver. A shared control resets its
   own UA chrome (it cannot assume the host page's base sheet).
7. **Mutation-check every decision test.** Reverse the rule, watch the named
   test fail, restore byte-exact. A test that writes and never reads back
   tests the request, not the behaviour. Before calling a mutation survivor a
   gap, ask "what else enforces this?" — redundant enforcement is a pattern
   here.
8. **Test the real input, not a fixture you invented** (the MPO lesson).
   Committed fixture reproducing the real shape + self-skipping test over the
   real local data (`work/`).
9. **Contracts are generated.** After any DTO/route change on either service:
   `python tools/api_contract.py --write`, commit all four artefacts.
10. **Snapshot `work/product.db` (and `work/product_blobs`) BEFORE driving
    live mutations through the browser**; restore after. It is the owner's
    real data.
11. **Never edit a migration step in place** — importing `app.main` migrates
    the real DB (the contract check and pre-commit hook both import it), so
    "not shipped yet" is usually already false. A fix is a new step.
12. **Trust nothing stale.** No `--reload` anywhere: restart servers after
    route changes. `:8757` serves a gitignored build — rebuild `app/web`
    after client changes. Vite's dev server can serve a stale module graph
    after out-of-band writes. Diagnose all three the same way: grep the
    served artefact for a string only the new code has.
13. **Commit/push only per the owner's ask.** The pre-commit hook routes
    checks by staged files (`tools/check.py` subsets); accuracy regressions
    block, and an intended trade-off is accepted explicitly with
    `sweep.py --accept-baseline --note`.

## Architecture

```
booksnap/    engine: config, types, segment, ocr, catalog, nli_catalog,
             match, fallback, pipeline, cli, scoring, replay
             server.py + static/  = the TUNING/AUDIT surface (:8756, /api/*)
             single-file vanilla JS — deliberately NOT migrated to React
app/
  domain/    entities + rules; pure, no I/O. Imports booksnap.catalog and
             NOTHING else from the core (normalize() must not fork).
  ports/     Protocols: stores, blobs, reader, jobs, decisions, duplicates,
             tenancy (the ONE account-scoped store — it answers which
             libraries exist)
  adapters/  sqlite_store (WAL, conn per op), disk_blobs, memory_store,
             migrations (PRAGMA user_version), legacy_import,
             booksnap_reader, queued_jobs, merge_library
  reconcile_apply.py / blob_lifecycle.py  the two port-only top-level modules
  api/       FastAPI /api/v1 (:8757) — THIN routers, DTOs, deps.py resolver,
             policy.py enforcement; openapi.json committed+generated
  main.py    composition root — the ONE file allowed to cross layers
  web/       household client, React+Vite+TS (:5173 dev → built into :8757)
  ui/        shared client package; consumed as SOURCE via path alias
  staff_api/ operator's service (:8758, /api/staff/v1) — cross-tenant,
             READ-ONLY by construction, own credential (BOOKSNAP_STAFF_TOKEN)
  admin/     operator's console (:5174) — reads staff_api, writes /api/v1
tests/       python rings; tests/run_all.py is the runner with a real exit code
tools/       check.py (the whole gate), sweep.py, spotcheck.py, rescore.py,
             api_contract.py, import_legacy.py, blob_gc.py, merge_library.py
```

Two applications coexist by design ("strangle, don't refactor"): tuning
server, product, staff service. The product DB is `work/product.db`
(`BOOKSNAP_DB`); the tuning server's `work/store.json`/`work/runs/` is a
different world — the product never reads it.

**Invariants enforced by tests** (don't re-argue, don't quietly break):

- `booksnap/*` never imports `app/*`; sweep/spotcheck/rescore never import
  `app/*`; `app/api/*` never imports `app/adapters/*`; staff service imports
  no product route/adapter/migration and never `app.main`; product imports
  nothing from `app/staff_api`.
- Every `/api/v1` route resolves its library through the single
  `app/api/deps.py:current_library` and declares exactly one capability
  (`app/api/policy.py:require`). `/api/v1/libraries` is the CLOSED exemption
  list (account-scoped, still resolves an account).
- Foreign and fictional libraries are the same answer: **404, never 403**,
  before any capability check.
- No module-level mutable state in `app/` (client-side `client.ts` selection
  is the deliberate asymmetry — one tab is one person).
- A system admin is a property of the operator (staff token), never a `Role`
  and never a `POLICY` column.

## Engine facts (measured — see HISTORY.md before "improving")

- **OCR keeps BOTH line-based reads and the whole-strip PSM 6 pass.** A
  refactor dropping the strip pass regressed AUTO 11→4 on one shelf.
- **Matching gates**: existence needs ≥2 matched title tokens or one
  distinctive ≥5-char one — author agreement may raise the tier, NEVER create
  a match. Short tokens (≤4ch) need ratio ≥90. `min_title_sim` 47 is a gate,
  not a ranking term. `ngram_sim` ≥50 kills subset pathology. Embedded-token
  matching (≥5ch) handles fused OCR words. Dedup: a rival below 0.70 of the
  winner is DROPPED (unmatched beats a wrong title). Run-16: qcov fragment
  suppression, single-word claims explaining ≤half their read rejected,
  volume siblings cap at REVIEW.
- Hebrew `normalize()`: strip nikud/punct, fold finals, geresh DELETED
  in-word (never space-split). The product's `book_key` uses the same
  function — two normalizers drift.
- **NLI helps because it's a search engine, not because it's bigger** — it
  retrieves 5–15 candidates, our matcher ranks. NLI needs a real API key
  (`NLI_API_KEY`; no guest key; browser UA required through Cloudflare);
  `_parse()` field mapping still unverified against live data.
- `fullpage` mode (one Vision call/photo) beat `spines` on IMG_6082: 13 vs 8
  AUTO, ~26× cheaper. Vision is a per-spine fallback, NOT a replacement
  (it lost to Tesseract on some spines). ~6/13 empty-both-engines crops are
  segmentation artifacts, not missed books.
- Tesseract-only deterministic ceiling ~76% title-correct; the honest hard
  core needing a stronger engine is ~15%.
- `match.explain()` recomputes with CURRENT code/config (deliberately — "would
  my change fix this spine?"), exposed via the tuning UI's *why?*.

## Accuracy measurement (before believing any change)

- `ground_truth.json` — owner-labelled shelves, coverage CURATED (never nag
  about unlabelled shelves). `tools/sweep.py` replays stored reads+candidates
  through the current match pipeline in seconds, offline. Replay mode is only
  valid for MATCHING changes — "N unrecorded queries" means retrieval changed:
  re-measure `--live`. Baseline: `tools/sweep_baseline.json`, enforced by the
  pre-commit hook (tolerance 0.01, mean AUTO P / AUTO F1 / A+R F1); per-shelf
  moves print but never block. Committed inputs in `fixtures/sweep/` make a
  fresh clone reproduce the baseline exactly.
- `tools/spotcheck.py` — owner review feedback as forbid/want/not_auto
  fixtures, replayed offline; self-skips without run data. A rules change must
  pass BOTH sweep --check and spotchecks.
- The confirmed library is never a sweep source (it's an outcome). The
  PRODUCT, by contrast, does include it in the chain
  (`ProductLibraryCatalog`) — the asymmetry is deliberate; don't "fix" it.
- A change that only LOOSENS a gate can sweep identical — the hook proves
  non-regression, not that the change did anything.

## Product domain rules (each mutation-checked; full arguments in HISTORY.md)

- **Reads apply themselves** (P2.9): the server job reconciles AND applies at
  settle; the client's `commitDiff` is a safe second call because applies are
  idempotent by `Provenance.sighting` `(run_id, spine_id)`. A claim is
  settled by its own SIGHTING, not its title (humans answer with different
  text: corrected, runner-up, later edit).
- **Snapshot vs live, deliberately disagreeing**: `Read.diff_summary` is an
  archived snapshot ("what this read DID"); the findings list is recomputed
  live. Sourcing both from one place repaints history as "changed nothing".
- **Retraction** (`plan_retraction`): delete the library record only when
  THIS read created it (`added_at >= read.started_at` is the load-bearing
  clause); otherwise only unshelve. EVERY branch records a standing Decision
  or the next read re-adds the phantom. Deleting a book records REJECTED at
  every location its copies stood.
- **§5.4 fires rarely by design**; the fire table is data (`FIRE_TABLE`),
  `fires()` raises on unknown reasons. Queue skip default = ALREADY_LISTED
  ("a missed duplicate is trivially fixed; an invented one rots").
- **Never auto-remove**: a not-seen book stays; streaks are derived from
  provenance (`not_seen_streak`), scoped to the exact (shelf, depth).
- **Shelf = identity, not address** (place/bookcase are pillar 6). Shelf ids
  MERGE (P6.1); nothing may treat one as a permanent handle. Depth is
  declared, never detected; front row is depth 1; never call depth
  "row"/"band" in code (AST-checked). Deleting a shelf never cascades into
  copies. A capture with no shelf gets a fresh unnamed shelf (no "assign
  later" state). Shelf label optional; library name mandatory.
- **Tenant = ownership boundary, never geography** (owner, 2026-08-10).
  Rooms/sites are Places (pillar 6), never Libraries — splitting one
  collection breaks search/dedup/§5.4 silently. Switcher renders as a label
  until a second library exists.
- **Images**: content-addressed (SHA-256), EXIF applied at STORE time,
  untouched bytes when no correction needed; variants carry their own
  extension; blob keys validated, never joined. Real phone JPEGs are MPO.
  HEIC: refuse naming the fix until real need. Blob GC under-deletes on
  purpose (24h age floor, refs from BOTH captures and claims, via
  `list_all_reads`).
- **Jobs**: bounded pool (2), round-robin across tenants, FIFO within;
  reads pass `retries=0` on purpose (a retry re-pays the engine). Rate cap
  30 reads/hr/library → 429 (a retry-loop guard, not a quota).
- **Credential preflight lives on the Reader PORT** (409 at the door with
  what to DO), never `os.environ` in a route.
- **The product must hand the engine the same catalog the baseline measured**
  — `BooksnapReader._build` vs `booksnap/server.py:_build_*`; an
  unrecognised backend RAISES. The wrapper's defaults are part of the
  engine's accuracy.
- **Library transport**: `X-Booksnap-Library` header on every fetch
  (`headersFor()`/`browserUrl()` are the single builders); browser-issued
  requests (`<img>`, downloads) use `?library=`; header wins. Switching
  libraries REMOUNTS the app.

## Tests & gates

- `python tests/run_all.py` — real exit code, shards across PROCESSES
  (env-swapping tests assume it). **Discovery is module-level `def test_*`
  only: a `unittest.TestCase` module collects as ZERO tests and reports ok**
  — this fired twice; `0/0 passed` means exactly that. Discovery happens in
  the worker from `vars()` (192 of the store-contract tests are generated at
  import).
- `python tools/check.py` — the whole gate concurrently under a core budget;
  every check runs even after one fails; `--product/--web/--admin/--ui/
  --accuracy` pick subsets; unknown flags are refused. The pre-commit hook
  routes: `app/ui/*` → both clients' rings; `app/staff_api/*` → `--product`
  too (the change that breaks the staff read model is a product-side
  migration).
- ~703 python + ~187 client tests (web 103 / admin 54 / ui 30). Speed is a
  correctness property — the big wins (lazy `booksnap/__init__`, app pool +
  `bind_ports`, shared portal, sqlite template copy, `isolate:false` + 2
  workers, `delay:null` userEvent, no retry-sleeps) are argued in
  HISTORY.md; don't undo them casually.
- `test_domain.py` is one test per reversible VISION sentence, not coverage.
  `test_store_contract.py` is ONE spec × every implementation (+ tenant
  isolation, running against two library refs since P2.1).
- Client suites mock `fetch`, never the hooks; harnesses hand back exact
  responses (like the API ring's `StubReader`). jsdom keeps
  `localStorage`/module state across FILES (`isolate:false`) —
  `src/test/setup.ts` owns the global reset.

## Traps (one line each; full stories in HISTORY.md)

- FastAPI: bind a port with a zero-arg closure, never `lambda v=value: v` —
  pydantic deep-copies mutable defaults and writes silently vanish.
- FastAPI silently ignores unknown query params — a stale server answers
  plausibly; restart after route changes.
- `getComputedStyle` lies while the Browser pane is backgrounded (static
  properties too); transitions freeze at t=0 (`getAnimations().finish()`);
  `getBoundingClientRect` still works. `get_page_text` reads only `<main>` —
  the drawer mounts outside it.
- A span is not a div (mock CSS silently stops applying); equal-specificity
  later rule wins; Chrome pins the native `<select>` chevron (draw your own).
- `resolve.dedupe` must list React AND the testing libraries — a second
  `@testing-library/dom` fires events outside `act` and reads as a timing
  flake. Read the vite-config warnings before touching either client's.
- A client-test fake must AWAIT its handler, or no test can observe a screen
  mid-fetch (two `key`-remount rules lost their gates this way) and an async
  handler serialises to `{}`. `renderApp().rerender` must re-wrap its
  providers — the bare one throws "useI18n outside <I18nProvider>", which
  reads as a screen bug.
- A route-guard meta-test must assert STRUCTURALLY (`require_staff` in
  `route.dependant`, and no `Mount`) and probe each route with its OWN
  methods. Path-based + GET-only missed an unguarded POST on an existing path
  and a `StaticFiles` mount serving CLAUDE.md unauthenticated — both measured.
- `response_model is not None` proves nothing about what a route SENDS:
  FastAPI short-circuits on a returned `Response`. Assert the content type.
- One correlated subquery per row over a JSON column is a DoS on an
  unauthenticated service: `/images` measured 13.6s for one `limit=200`.
  Grouped CTE pre-pass, 14ms.
- The console's **"account" is the TENANT** (a `Library` record) while the
  wire and the domain keep `library` — the owner's word for a customer, with
  the id shown labelled so the mapping is visible. `accounts` on the wire is
  the PEOPLE count. See planning/ADMIN_CONSOLE_PLAN.md revision 4.
- `app/ui` is consumed as source: each client's `postinstall` installs it;
  `check-installed.mjs` + `install.test.ts` guard the `npm ci
  --ignore-scripts` path. One `npm install --prefix <client>` per client.
- Two controls announcing the same accessible name collide
  (`t.edit`/`t.copy_edit`; "split"/"create volumes") — every new per-item
  action needs its own label.
- Author autocomplete returns the owner's spelling, never normalized —
  normalization is for matching only.
- The match score is out of **130** (`60·tcov_c+25·tcov+15·acov+0.30·sim`);
  `MAX_SCORE` in `ClaimRow.tsx` must track `match.py`.
- `author_sort_key` is a SECOND key (surname), not a re-ordered
  `normalized_author` (that one is identity). No particle list — measured.
- sqlite backfills must call the SAME domain function as the write path
  (v3's lesson); WAL sidecars travel when copying DB files; snapshot a live
  DB via SQLite's backup API, never three `copy2`s.
- `:8757`/`:5173` bind 0.0.0.0 on purpose (phone capture); unauthenticated
  LAN API is a known single-household trade until pillar 4.
- Windows/AV: loading many small files costs ~5ms each (jsdom 3.5s) — likely
  real-time AV scanning of node_modules; machine setting, not repo-fixable.
- 4-core i5: wall-clock numbers move ±20%; distrust small parallel gains.

## Running things

```bash
# dev servers — use preview_start with these launch.json names, never Bash:
#   booksnap-ui (:8756)  product-api (:8757)  product-web (:5173)
#   staff-api (:8758, start before admin-web)  admin-web (:5174)
python tests/run_all.py            # python rings (module names to subset)
python tools/check.py              # the whole gate
npm --prefix app/web run test      # client ring (also app/admin, app/ui)
npm --prefix app/web run build     # :8757 serves this build — rebuild or you
                                   # are looking at history
python tools/import_legacy.py --db work/product.db
python tools/merge_library.py      # dry-run by default
```

Node 24 LTS (engines-pinned). `./setup.sh` installs Tesseract + Hebrew
models. Keys live in `.env` (gitignored) — never hard-code or commit;
adapters read env (`NLI_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`,
`BOOKSNAP_STAFF_TOKEN`).

## Working style

The owner is a senior engineer (25y) who values honest assessment over
optimism: report real numbers, flag what's unverified, don't oversell. When a
change might regress accuracy, measure before and after. Absent, not
disabled, in the UI. Hebrew/RTL correctness is a correctness rule
(`.rtl-safe`, direction per string, alignment per container). A wrong stated
reason is worse than none — it's what makes the next reader delete the guard.
