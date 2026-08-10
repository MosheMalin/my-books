---
name: cycle
description: Run one booksnap code cycle — plan, implement, review, land. The argument is the item to build (a feature, a fix, a plan item like "P4.1") — or an epic ("implement pillar 4", "rework the admin console"), which Phase 0 decomposes and executes item by item.
---

# The booksnap code cycle

Run the item through the phases below. Do not skip a phase because the change
"looks small" — the recorded bugs here mostly came from small-looking changes.
Trivial mechanical edits (a typo, a comment) may skip straight to implement,
but say so.

## Phase 0 — Size it

Decide what you were handed, and say which it is:

- **One item** — a fix, a single feature, one plan item ("P4.1"): go to
  Phase 1.
- **An epic** — several landable changes hiding in one sentence (a pillar, a
  console rework, "focus on X"): do NOT stretch one cycle over it. A
  week-long branch, a review panel drowning in scope, and no point to
  correct course is the failure mode this phase exists to prevent.

For an epic, first look for an EXISTING decomposition — do not re-analyze
what has already been analyzed: `planning/IMPLEMENTATION_PLAN.md` (the
pillars are already itemized), `planning/ADMIN_CONSOLE_PLAN.md`, `VISION.md`,
`docs/HISTORY.md`, or a plan a prior session produced that the owner is
referencing. If one exists, **re-read it against what has actually landed**
(plans drift — an item may be half-done, obsolete, or already delivered by a
different route), adjust the item list, state the adjustments, and go to
Epic execution.

If no plan exists, run a planning pass — its deliverable is a document, not
code:

1. **Audit first, design second.** Spawn subagents (`Explore`, or a reviewer
   persona in audit mode) to enumerate everything the requirement touches —
   including the instances the owner didn't list. The enumeration comes
   before any design decision.
2. **Settle open questions with the owner ONCE, batched** — plan-level
   questions belong here, not sprinkled across items.
3. **Write/update the plan under `planning/`**: a numbered item list, each
   item sized for one cycle, with its constraints (which CLAUDE.md rules it
   brushes against), its reviewer set, and its done-criteria.
4. **Get the owner's nod on the plan before implementing** — the plan is the
   cheap place to redirect.

## Epic execution ("do pillar 4")

Run each item through Phases 1–3 and LAND it on `main` before starting the
next — `main` stays green between items and the owner can stop, reorder or
redirect after any of them. Rules:

- work autonomously from item to item; after each landing, report one short
  progress note (item, what landed, anything surprising) and continue —
  don't wait for permission the plan already gave;
- PAUSE for the owner only when: an item surfaces a design decision the plan
  didn't settle; a reviewer critical can't be fixed within the item's scope;
  the gate is red for a cause outside the item; or reality shows the plan
  itself is wrong;
- the plan document is the progress tracker — mark items done as they land,
  and if a later item invalidates an earlier assumption, amend the plan in
  the same commit;
- reviews run per item, never batched across items; the plan may add
  standing per-epic requirements (e.g. `review-security` on every pillar-4
  item, `review-migration` before every auth-schema commit);
- one item = one worktree branch; remove it after landing. Never let two
  items' changes share a branch "to save time".

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
