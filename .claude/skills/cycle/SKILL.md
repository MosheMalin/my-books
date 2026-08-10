---
name: cycle
description: Run one booksnap code cycle — plan, implement, review, land. Use for any non-trivial change; the argument is the item to build (a feature, a fix, a plan item like "P4.1").
---

# The booksnap code cycle

Run the item through three phases. Do not skip a phase because the change
"looks small" — the recorded bugs here mostly came from small-looking changes.
Trivial mechanical edits (a typo, a comment) may skip straight to implement,
but say so.

## Phase 1 — Plan (no .md file required)

Produce a short plan **in the conversation**, not a document:

1. Restate the item in one sentence; if scope is genuinely ambiguous, ask the
   owner ONE batched set of questions now — never mid-implementation.
2. Collect the facts: the relevant CLAUDE.md rules and traps (follow the
   pointer into `docs/HISTORY.md` when a one-liner isn't enough), VISION/plan
   sections, and the actual code. Use the `Explore` agent for broad searches,
   `Plan` for genuinely hard design; read narrow things yourself.
3. State: files to touch · domain rules affected · whether a schema version
   is needed · which tests will pin the new decisions · which reviewers apply
   (see Phase 3) · accuracy-relevant? (then the sweep is part of the plan).
4. **Worktree decision**: parallel sessions share the primary tree, so any
   multi-file change works in `git worktree add D:/tmp/<name> <branch>`.
   Always name the drive (`D:/tmp`, never bare `/tmp`).

## Phase 2 — Implement

- One copy of every rule; shared client mechanisms go in `app/ui`.
- Every new decision gets a named test, and every named test gets
  mutation-checked: reverse the rule, watch it fail, restore byte-exact.
  A test that writes and never reads back is testing the request.
- Test the real input shape, not an invented fixture (the MPO lesson):
  committed fixture + self-skipping test over real `work/` data.
- Run the NARROW gate while iterating (`python tests/run_all.py <modules>`,
  `npm --prefix <pkg> run test`); the full `python tools/check.py` once,
  before committing. If a check feels slow, fixing the slowness is in scope —
  a gate nobody waits for stops being a gate.
- DTO/route changed? `python tools/api_contract.py --write`, commit all four
  artefacts. Schema changed? A NEW migration step, never an edit in place —
  and run `review-migration` BEFORE the commit.
- Commit in the worktree with a message that records the decision, not the
  diff.

## Phase 3 — Review

**Before the commit**: `review-migration` if any schema version / backfill /
persisted shape changed (it must see the step before `app.main` gets imported
by hooks and migrates the real DB).

**After the commit**, spawn the applicable reviewers IN ONE MESSAGE, in the
background, and keep working:

| spawn | when |
|---|---|
| `review-quality` | always, for any substantive item |
| `review-data-integrity` | server-side change (stores, domain, routes, jobs, blobs) |
| `review-security` | new routes/inputs/params, credentials, file/path handling, exposure |
| `review-ux` | any user-visible behaviour — it verifies in a real browser |

Pass each reviewer the commit shas (or file scope) and any item-specific
questions. When the reports land: fix critical/major findings in a follow-up
commit on the same branch; record judgment calls you decline with the reason;
re-run the affected rings.

## Landing

From the worktree branch: merge into `main` with `--no-ff` (via a worktree at
`main` if the primary tree isn't on it — never `git checkout` in the primary
tree), remove the worktree. Push only if the owner asked. If the sweep
baseline moved intentionally: `python tools/sweep.py --accept-baseline
--note "why"` and commit the baseline file with the change, not after it.

## Definition of done

- `python tools/check.py` green (the relevant subsets at minimum).
- New decisions pinned by mutation-checked tests.
- Applicable reviewers ran; findings fixed or explicitly declined with
  reasons.
- UI changes verified in a real browser (not only jsdom) — with
  `work/product.db` snapshotted first if the flow mutates.
- Landed on `main`; worktree removed; primary tree untouched.
- Anything non-obvious learned goes into CLAUDE.md as a one-liner with the
  full story appended to `docs/HISTORY.md`.
