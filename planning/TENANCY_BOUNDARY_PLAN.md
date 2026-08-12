# P3.7 — moving the tenancy boundary from Library to Account

The decision is VISION §4.1's **[REVISED 2026-08-11]** settlement; this file is
the decomposition. Read §4.1 first — nothing here re-argues it.

One line: **the tenant is the Account (the customer); a Library becomes a
logical partition inside it.** A user of account A must not be able to learn
that account B exists.

## The design, in one paragraph

`library_id` stays the **one enforced physical scope**: every store and blob
method keeps leading with a `LibraryRef`, every row keeps its column, every
read index keeps leading with it, blobs keep `libraries/<library_id>/`, and
`test_store_contract.py`'s isolation suite keeps passing byte-for-byte. The
**account boundary is enforced at the door**: `libraries` gains an
`account_id`, and `app/api/deps.py:current_library` resolves a named library
by asking *"is this library owned by an account this user belongs to?"*
instead of *"is there a membership row for this (user, library)?"*. One
narrowing in SQL, one authorization decision, in the two modules that already
own those jobs. Library isolation is not weakened — it is demoted from *the*
boundary to defence in depth inside it.

⚠ This is the whole reason the 2026-08-10 objection ("every query narrows
twice; six aggregates gain a second way to leak") does not apply. If an item
below starts adding `account_id` to a second table, it has gone wrong.

## The nouns after this work

| was | is | what it is |
|---|---|---|
| `Account` | **`User`** | a person, one identity |
| — | **`Account`** | the customer; the tenancy boundary |
| `Library` | `Library` | a collection inside an account — logical |
| `Membership` (Account × Library × Role) | `Membership` (**User × Account** × Role) | |

## The backfill rule — the one judgment call

The real database (`work/product.db`, schema v12) holds **one person
(`dev-owner`), two libraries (`dev-library`, `lib2`), both with a single
ADMIN membership by that person**. So "one account per library" is *wrong* on
the only data that exists: it would split one owner into two customers.

**The rule: libraries whose membership set is IDENTICAL collapse into one
account.** Group `libraries` by the exact frozenset of `(user_id, role)` over
their memberships; each group becomes one `Account`; every user in the set
gets one account-membership carrying that same role.

- the safety property `review-migration` must verify: **no user gains access
  to any library they could not already reach**, because every library in a
  group had exactly that member set;
- the owner's data therefore produces **one account owning two libraries** —
  the right answer;
- a library with no memberships (today's "orphan") gets its own account with
  no members. It was already unreachable and the console already reports it;
- account label: the sole admin's `display_name` if there is one, else blank.
  Blank is representable and un-mintable, exactly as v12 did for `Library`.

## Items

Each lands on `main` green before the next starts. One worktree per item.

### P3.7a — Free the word: the person becomes a `User`

A pure rename with **zero semantic change** — Library is still the tenant when
this lands. It exists as its own item so that P3.7b's diff is the boundary
change and not a 60-file rename, which is the difference between a review
that can see the security property and one that cannot.

- `app/domain/tenancy.py` `Account`→`User` (+ `app/domain/__init__.py`
  exports/`__all__`); `Membership.account_id`→`user_id`.
- `app/ports/tenancy.py`: `save_account`/`get_account` → `save_user`/`get_user`;
  every `account_id` parameter → `user_id`.
- `app/adapters/sqlite_store.py` (`SqliteTenancyStore`, ~`745-882`) and
  `app/adapters/memory_store.py` (`MemoryTenancyStore`, `379-434`).
- **migration v13**: `accounts` → `users`; `memberships.account_id` →
  `user_id`; `accounts_by_email` → `users_by_email`. *As landed:* SQLite's own
  `RENAME TO`/`RENAME COLUMN` rewrite the REFERENCES clause, the composite
  PRIMARY KEY and the secondary index in place, so this is four statements and
  NOT the twelve-step table rebuild the docs prescribe for other alterations.
  Measured to depend on `legacy_alter_table` being off (the default), not on
  `foreign_keys`.
- `app/api/dto.py` `AccountDTO`→`UserDTO`, `MetaResponse.account`→`.user`;
  `app/api/routers/meta.py`, `app/api/routers/libraries.py:_account`.
- `app/staff_api/`: `AccountDTO`→`UserDTO`, route `/accounts`→`/users`,
  **`queries.py:REQUIRED_COLUMNS` (85-104) in the same commit** — it is the
  self-check that 503s the console if the schema moves without it.
- contracts ×4 (`tools/api_contract.py --write`).
- `app/admin`: `staff.ts` types + `system.tsx` field, the screens that read
  `accounts` as people (`AccountsPage` unaffiliated section, `AccountDrawer`
  members, `AccessPage`, `Dashboard.stat_people`), test harness factories.
- tests: `test_domain.py:1750-1841`, `test_store_contract.py:1324-1479`,
  `test_api.py:98-112`, `test_staff_api.py`, `test_merge_library.py`.

⚠ `tests/test_domain.py:1828` hardcodes `app/domain/tenancy.py` for the
no-`can()` AST guard — the module keeps its name, so the guard is untouched.
Do not split the module.

**Reviewers**: `review-migration` (before the commit), `review-quality`.
**Done**: `python tools/check.py` green; console renders unchanged in a real
browser; not one behaviour test rewritten (a rename that needed a behaviour
test changed is not a rename).

### P3.7b — The boundary moves: `Account` is the customer

The item. Everything below is one commit because the tree is red between any
two halves of it.

- domain: new `Account`; `new_account(owner: User)` returns `(Account,
  Membership)`; `new_library(account, label)` returns a `Library` only —
  minting a membership per library is exactly the thing being deleted;
  `NoAdminLeft` becomes account-level; `Library` gains `account_id`.
- **migration v14**: `libraries.account_id NOT NULL REFERENCES accounts(id)`,
  a new `accounts` (customer) table, `memberships` re-keyed to
  `(user_id, account_id)`, and the backfill rule above.
- `app/ports/tenancy.py`: `list_libraries(account_id)` becomes *by
  ownership*; new `list_accounts(user_id)`; `membership(user_id, account_id)`;
  `list_members(account_id)`. Both adapters.
- `app/api/deps.py:current_library` — library → account → membership; foreign
  and fictional stay one answer (404). `app/api/policy.py:_role` reads the
  account membership.
- `app/api/routers/libraries.py` — the account-scoped exemption list; create
  goes under the caller's account; the one `allowed()` call outside
  `policy.py` follows.
- `app/main.py:_bootstrap_dev_account` — dev user + dev account + both
  libraries under it.
- tools that will not survive `NOT NULL` unchanged:
  `app/adapters/merge_library.py:_LIBRARY_TABLES` (drops `memberships`;
  **cross-account merges refused**), `tools/merge_library.py` raw SQL,
  `tools/import_legacy.py` (`--account`), `tools/blob_gc.py`.
- contracts ×4; `app/web` harness stubs (the household client renders no
  account vocabulary — the surface there is fixtures only).

⚠ `tests/test_domain.py:1844 test_a_library_is_not_a_place` inspects
`Library.__dataclass_fields__` against a banned set that does **not** include
`account_id` — so the new field passes silently. Extend the test to say
`account_id` is expected and a Place field still is not, or the guard quietly
stops meaning anything.

⚠ Decide in-item, with the reason recorded either way: the dev-trusted
fallback at `app/api/policy.py:75-76` (flagged at `:60-65` as a P4-era
landmine, pinned by the single test `test_api.py:1023`). Principals are still
dev-trusted at pillar 3, so if deleting it breaks the bootstrap, restate the
exit condition rather than forcing it.

**Reviewers**: `review-migration` (before the commit), `review-data-integrity`,
`review-security`, `review-quality`.
**Done**: `check.py` green; the 404-never-403 suite unchanged and passing; a
new mutation-checked test that a library of another account is 404 *by
ownership* and not merely by a missing membership row; the real DB migrates
from a v12 snapshot to one account owning two libraries.

### P3.7c — One customer, one quota

- `app/api/routers/reads.py` — the §1.2 rate cap counts per **account**, not
  per library. Today a customer multiplies their own quota by pressing *new
  library*.
- `app/ports/jobs.py` / `queued_jobs.py` — the round-robin `tenant` key
  becomes the account id. The port already says "round-robin ACROSS tenants";
  this is that sentence catching up, and it means two libraries of one
  customer stop competing as strangers.

**Reviewers**: `review-data-integrity`, `review-quality`.
**Done**: ✅ landed. Both rules mutation-checked at the ROUTER, which is where
the decision lives — `tests/test_jobs.py` exercises `QueuedJobRunner`, which
is agnostic about what a tenant key means and correctly stayed untouched; the
plan's original note naming its line numbers was wrong about that. The two
cases that moved are `test_the_run_rate_cap_blocks_a_retry_loop_and_only_this_
account` (a sibling library now shares the cap, a second customer does not)
and `test_two_concurrent_reads_in_two_libraries_do_not_observe_each_other`
(the spy now asserts the key is the account).

⚠ Both fan-outs live in the API layer on purpose. `list_all_reads` stays
library-scoped, because a cross-library store method would be the second
enforced scope §4.1 refuses; the account is already known at the door, so
that is where the loop belongs.

### P3.7d — The staff read model tells the truth

- `/api/staff/v1/accounts` returns **customers**, each with its libraries;
  `/users` (from P3.7a) keeps returning people with their memberships.
- `OverviewDTO`: `accounts` becomes the customer count, `users` the people
  count — the two numbers stop meaning each other's thing.
- `queries.py:orphan_libraries()` (`601-614`) is meaningless once every
  library has an owning account: replace with **accounts with no admin** and
  **accounts with no library**, which are the states that can actually occur.
- ~~`storage.py:9,27` say "account" and mean library~~ — done early, in
  P3.7a: blob paths are NOT moving, so it was a wording fix and it belonged
  with the rename that made the word wrong.
- contracts ×4.

**Reviewers**: `review-data-integrity`, `review-security`, `review-quality`.
**Done**: ✅ landed. `/accounts` returns customers with their libraries'
figures summed — folded from `libraries()` rather than computed by a second
set of grouped queries, so the two screens cannot drift; the overview counts
accounts / users / libraries as three numbers and adds
`accounts_without_admin` (a state `new_account` and `NoAdminLeft` make
unreachable, so any number there is a bug that already happened).
`orphan_libraries` was re-aimed at the owning account back in P3.7b and
stays.

⚠ The aggregation fixture gives one account a second library WITH BOOKS IN
IT. An empty one makes every sum equal its first term, and a fold that
dropped the rest passed — measured on the first draft.

### P3.7e — The console stops glossing

The console has been saying "account" and meaning a `Library` since revision
4; this is where it stops being a gloss and starts being true.

- `#/accounts/<id>` — the id becomes an **account id**; keep the library-id
  route landing somewhere sensible rather than 404ing an operator's bookmark.
- the drawer becomes *account → its libraries → users / books / images*;
  `acct_library_id` (the deliberate mapping label) is deleted, not relabelled.
- ⚠ **`t.th_account` is rendered over three different entities today** —
  libraries (`AccountsPage:212`, `Dashboard:81`, `ImagesPage:108`,
  `ImagePanel:80`) and people (`AccountsPage:315`, `AccountDrawer:110`).
  Splitting that one string into account/user/library headers is a
  prerequisite of this item, not a cleanup after it.
- `Dashboard` counts, `AccessPage`'s two-admins text, the i18n tables (HE
  first, EN mirror) — `i18n.test.ts:30-46` is structural and fails if a key
  stops being rendered, so table and screens land in one commit.

**Reviewers**: `review-ux` (real browser, `work/product.db` snapshotted
first), `review-quality`.
**Done**: admin ring green; the Accounts screen shows one account with two
libraries against the real database.

### P3.7f — Write it down

`CLAUDE.md` (the tenancy bullet, the ports line, the jobs/rate-cap line, and
**deleting** the console-"account" trap entry at `304-307` — the trap is the
mismatch, and the mismatch is gone), `docs/HISTORY.md` (the argument, the
reversal, and what the audits found), `planning/IMPLEMENTATION_PLAN.md` (a
P3.7 row + the ⚠ blocks at `476-495`), `planning/ADMIN_CONSOLE_PLAN.md`
(revision 5 retiring revision 4's gloss at `490-506`),
`planning/UI_PLAN.md:30-31`.

Per-item one-liners land WITH their items; this is the long-form write-up.

## Found on the way, deliberately NOT fixed here

P3.7a's migration review turned up two pre-existing holes in the migration
RUNNER. Both are older than this epic, neither is a v13 regression, and both
change how all thirteen steps behave — which is not a rider on a rename. They
are written down so the next reader adds the guard instead of re-deriving the
problem:

- **a string step is not atomic.** `conn.executescript` commits as it goes, so
  the runner's `with conn:` wraps nothing. A crash between two statements of
  one step leaves the file half-upgraded with the OLD `user_version`, and the
  next open re-enters the step and raises on what already succeeded — a
  database openable only by hand. `migrations.py`'s module docstring now says
  so (it previously claimed the opposite); the fix is to wrap each script in
  its own `BEGIN`/`COMMIT` so a mid-script failure leaves something to roll
  back;
- **no guard against a database NEWER than the code.** `migrate()` skips
  quietly when `user_version > SCHEMA_VERSION`, so checking out an older build
  against an upgraded file dies later with a raw `no such table` instead of
  naming both numbers. This epic makes that likely rather than theoretical,
  because rolling back between items is a real action.

⚠ **Landing any item of this epic advances the owner's real
`work/product.db`** the first time the gate or the pre-commit hook runs in the
primary tree — `tools/api_contract.py` imports `app.main`, which migrates —
and there is no down step. **Snapshot `work/product.db` through SQLite's
backup API before each merge to `main`.**

## Scope fence

Pillar 4 is not started and nothing here starts it: **no login, no auth, no
magic links, no invites, no sign-up flow, no libraries-per-account cap.**
Principals stay dev-trusted. A user belonging to more than one account is
*representable* after P3.7b and *unreachable* until P4.3 — that is the correct
state, not an omission.

Also explicitly not built: the **merge** of two Books that are the same work
in two libraries of one account (VISION §4.1 records it as the user's escape
hatch), and any **per-library role** scope (no dead nullable column).
