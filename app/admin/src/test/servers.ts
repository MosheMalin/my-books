/**
 * The default two-service fake every screen test starts from.
 *
 * ⚠ The console talks to TWO backends and the tests must too, or they prove
 * the wrong thing: reading comes from `/api/staff/v1` (cross-tenant) and
 * writing from `/api/v1` (the operator's own memberships). A fake that served
 * both from one set of rows would let a screen mix the scopes and still pass.
 */
import {
  fakeServer, makeOverview, makeStaffAccount, makeStaffBook, makeStaffImage,
  makeUser, makeStaffLibrary, makeStaffWork, makeLibrary, type FakeServer,
} from './harness'
import type {
  StaffAccount, StaffBook, StaffImage, StaffLibrary, StaffOverview, StaffUser,
  StaffWork,
} from '../api/staff'
import type { LibraryDTO } from '../api/schema'

/**
 * The SERVER's ordering for a paged list: newest first, undated last.
 *
 * ⚠ Written out here rather than imported from `AccountDrawer`, even though
 * the two agree. The drawer's copy is the CLIENT's merge rule and this one is
 * the server's page order; a fake that shared the client's helper would be
 * asserting that the client agrees with itself, which is the failure this
 * file's header warns about. `app/staff_api/queries.py` orders
 * `COALESCE(<date>,'') DESC, id DESC` — the id tiebreak is not modelled,
 * because no fixture has a tie.
 */
function newestFirst<T>(rows: T[], at: (row: T) => string | null | undefined): T[] {
  return [...rows].sort((a, b) => (at(b) ?? '').localeCompare(at(a) ?? ''))
}

export interface World {
  overview: StaffOverview
  /** The CUSTOMERS. ⚠ Not derived from `libraries` — see `makeStaffAccount`. */
  accounts: StaffAccount[]
  libraries: StaffLibrary[]
  users: StaffUser[]
  books: StaffBook[]
  /** The aggregate the Books screen actually renders. Kept SEPARATE from
   *  `books` on purpose: the server derives works from books, and a fake that
   *  derived them here would be a second implementation of the display-title
   *  and spread rules — agreeing with itself while the real one drifts. */
  works: StaffWork[]
  /** Which books each work resolves to, keyed by `work.key`. */
  instances: Record<string, StaffBook[]>
  /** What `/works?library_id=<id>` answers. Fixture data, not derived — see
   *  the handler. ⚠ Each row keeps its FULL spread: narrowing to lib-2 still
   *  reports 'אבא' as held by two libraries, because that is what the server
   *  does and it is the rule the screen exists to honour. */
  worksIn: Record<string, StaffWork[]>
  images: StaffImage[]
  /** What `/api/v1/libraries` answers — the operator's OWN memberships, which
   *  is deliberately a SUBSET of `libraries` in the default world so that
   *  "reads everything, writes only mine" is exercised by default. */
  mine: LibraryDTO[]
}

export const DEFAULT_WORLD: World = {
  overview: makeOverview({
    // ⚠⚠ Two customers, FOUR people, THREE collections — pairwise different,
    // and the review that forced the fourth person is the reason to keep them
    // so. Until P3.7e the dashboard's "accounts" tile read `libraries`; the
    // first fixture made accounts and users BOTH 2, so swapping the tile to
    // `overview.users` passed the whole ring, and `AccessPage` measuring
    // customers by `users.length` passed too. A comment claiming the numbers
    // are all different is not the same as their being all different.
    //
    // `users` here EQUALS `users.length` below, as it must in a coherent
    // world — they are two ways to count the same people. What catches the
    // AccessPage bug is that neither of them equals `accounts`.
    accounts: 2, accounts_without_admin: 0,
    users: 4, libraries: 3, memberships: 5, books: 4, copies: 4,
    auto: 1, approved: 1, manual: 2, shelves: 3, captures: 6, reads: 2,
    duplicates: 1, lent_out: 1,
  }),
  // ⚠⚠ **acc-1 owns TWO libraries** — the shape of the owner's own database
  // (one account, two libraries, 286 books) and the shape this console could
  // not draw before P3.7e, when it showed two rows and called them two
  // customers. The second collection has BOOKS AND IMAGES in it on purpose:
  // P3.7d measured that an empty second library makes every sum equal its
  // first term, so a fold that dropped the rest passes.
  accounts: [
    makeStaffAccount({ id: 'acc-1', label: 'משפחת מלין', libraries: 2,
                       members: 2, admins: 1, books: 3, copies: 3, auto: 1,
                       approved: 1, manual: 1, shelves: 2, captures: 5,
                       image_bytes: 240_000, image_files: 2,
                       last_activity: '2026-02-01T00:00:00Z' }),
    // ⚠ NOT 'ההורים' — that is its LIBRARY's name. Every screen that names a
    // collection now names its owning customer beside it, so a fixture where
    // the two are the same string makes every such assertion ambiguous and
    // hides exactly the pairing under test.
    makeStaffAccount({ id: 'acc-2', label: 'משפחת כהן', libraries: 1,
                       members: 3, admins: 1, books: 1, copies: 1, manual: 1,
                       shelves: 1, captures: 1,
                       last_activity: '2026-01-20T00:00:00Z' }),
  ],
  libraries: [
    makeStaffLibrary({ id: 'lib-1', label: 'הבית', members: 2, admins: 1,
                       books: 2, auto: 1, approved: 1, shelves: 1, captures: 3,
                       image_bytes: 120_000, image_files: 1 }),
    // The second collection of acc-1. ⚠ Its `members`/`admins` repeat the
    // OWNING ACCOUNT's headcount, exactly as the wire reports them — which is
    // why no screen renders them on a library row.
    makeStaffLibrary({ id: 'lib-3', label: 'המשרד', members: 2, admins: 1,
                       books: 1, manual: 1, shelves: 1, captures: 2,
                       image_bytes: 120_000, image_files: 1 }),
    makeStaffLibrary({ id: 'lib-2', account_id: 'acc-2', label: 'ההורים',
                       members: 3, admins: 1,
                       books: 1, manual: 1, shelves: 1, captures: 1 }),
  ],
  // ⚠⚠ FOUR people over two customers, and `usr-2` belongs to BOTH with a
  // DIFFERENT role in each — viewer at acc-1, admin at acc-2. That pair is
  // what makes the drawer's member list falsifiable: a section that took
  // `memberships[0]` instead of the one naming the open account lists a
  // stranger and shows the wrong badge, and until a second customer had its
  // own people the right answer and the wrong one coincided.
  users: [
    makeUser({ id: 'usr-1', display_name: 'משה', memberships: [
      { account_id: 'acc-1', role: 'admin', joined_at: '2026-01-01' },
    ] }),
    makeUser({ id: 'usr-2', display_name: 'שכן', memberships: [
      { account_id: 'acc-1', role: 'viewer', joined_at: '2026-01-02' },
      { account_id: 'acc-2', role: 'admin', joined_at: '2026-01-03' },
    ] }),
    makeUser({ id: 'usr-3', display_name: 'סבתא', memberships: [
      { account_id: 'acc-2', role: 'viewer', joined_at: '2026-01-04' },
    ] }),
    makeUser({ id: 'usr-4', display_name: 'סבא', memberships: [
      { account_id: 'acc-2', role: 'viewer', joined_at: '2026-01-05' },
    ] }),
  ],
  // ⚠ The same four books the `instances` map resolves to. They disagreed for
  // one commit (three here, four there) and it was latent only because nothing
  // read both — the account drawer now does.
  books: [
    makeStaffBook({ id: 'b1', library_id: 'lib-1', title: 'אבא', author: 'א' }),
    makeStaffBook({ id: 'b1b', library_id: 'lib-2', title: 'אבא!', author: 'א',
                    status: 'manual' }),
    makeStaffBook({ id: 'b2', library_id: 'lib-1', title: 'בבא', author: 'ב',
                    status: 'approved' }),
    makeStaffBook({ id: 'b3', library_id: 'lib-2', title: 'גגא', author: 'ג',
                    status: 'manual' }),
    // ⚠ In acc-1's SECOND library, and the newest of the lot. The account
    // drawer merges its libraries' previews newest-first, so a merge that
    // silently kept only the first library's page would put 'אבא' on top and
    // this row nowhere — which is the bug the fixture exists to expose.
    makeStaffBook({ id: 'b4', library_id: 'lib-3', title: 'דדא', author: 'ד',
                    status: 'manual', added_at: '2026-02-01T00:00:00Z' }),
  ],
  // ⚠ Three works over four books: 'אבא' is held by BOTH libraries — one of
  // them a house the operator cannot write to — which is the default fixture
  // precisely because "one book, several households" is the case the whole
  // aggregate exists for.
  works: [
    makeStaffWork({ key: 'אבא|א', title: 'אבא', author: 'א', libraries: 2,
                    copies: 3, mixed: true, status: 'manual' }),
    makeStaffWork({ key: 'בבא|ב', title: 'בבא', author: 'ב',
                    status: 'approved' }),
    makeStaffWork({ key: 'גגא|ג', title: 'גגא', author: 'ג',
                    status: 'manual' }),
  ],
  worksIn: {
    'lib-1': [
      makeStaffWork({ key: 'אבא|א', title: 'אבא', author: 'א', libraries: 2,
                      copies: 3, mixed: true, status: 'manual' }),
      makeStaffWork({ key: 'בבא|ב', title: 'בבא', author: 'ב',
                      status: 'approved' }),
    ],
    'lib-2': [
      makeStaffWork({ key: 'אבא|א', title: 'אבא', author: 'א', libraries: 2,
                      copies: 3, mixed: true, status: 'manual' }),
      makeStaffWork({ key: 'גגא|ג', title: 'גגא', author: 'ג',
                      status: 'manual' }),
    ],
  },
  instances: {
    'אבא|א': [
      makeStaffBook({ id: 'b1', library_id: 'lib-1', title: 'אבא', author: 'א' }),
      makeStaffBook({ id: 'b1b', library_id: 'lib-2', title: 'אבא!', author: 'א',
                      status: 'manual' }),
    ],
    'בבא|ב': [
      makeStaffBook({ id: 'b2', library_id: 'lib-1', title: 'בבא', author: 'ב',
                      status: 'approved' }),
    ],
    'גגא|ג': [
      makeStaffBook({ id: 'b3', library_id: 'lib-2', title: 'גגא', author: 'ג',
                      status: 'manual' }),
    ],
  },
  images: [
    makeStaffImage({ id: 'cap-1', library_id: 'lib-1' }),
    makeStaffImage({ id: 'cap-2', library_id: 'lib-2', shelf_id: 'sh-2',
                     shelf_label: '', present: false, bytes: 0, width: 0,
                     height: 0, content_type: '', filename: '',
                     reads: 0, findings: 0, auto: 0, review: 0, unmatched: 0,
                     last_read: null }),
    // acc-1's second collection, so the drawer's merged preview has something
    // from more than one library to order.
    // ⚠ Its tier figures differ from cap-1's deliberately: two rows reporting
    // the identical "N auto · M review · K unmatched" line make every
    // by-text assertion on that line ambiguous.
    makeStaffImage({ id: 'cap-3', library_id: 'lib-3', shelf_id: 'sh-3',
                     shelf_label: 'ארון', captured_at: '2026-02-02T00:00:00Z',
                     reads: 1, findings: 5, auto: 4, review: 0, unmatched: 1,
                     last_read: '2026-02-03T00:00:00Z' }),
  ],
  // ⚠⚠ **Both of acc-1's libraries, and neither of acc-2's.** Since P3.7b a
  // membership names an ACCOUNT and covers every library it owns, so
  // `GET /api/v1/libraries` cannot answer with one of a customer's two
  // collections — a fixture that did would be testing a state the server can
  // no longer produce. The read/write asymmetry the console is built around
  // is still exercised by default, one level up: the operator SEES two
  // customers and may write inside exactly one.
  mine: [
    makeLibrary({ id: 'lib-1', label: 'הבית', role: 'admin' }),
    makeLibrary({ id: 'lib-3', label: 'המשרד', role: 'admin' }),
  ],
}

export function bothServices(world: Partial<World> = {}): FakeServer {
  const w: World = { ...DEFAULT_WORLD, ...world }
  return fakeServer({
    'GET /api/staff/v1/overview': () => w.overview,
    'GET /api/staff/v1/accounts': () => w.accounts,
    'GET /api/staff/v1/libraries': () => w.libraries,
    'GET /api/staff/v1/users': () => w.users,
    'GET /api/staff/v1/books': (req) => {
      const url = new URL(req.url, 'http://x')
      const lib = url.searchParams.get('library_id')
      const all = lib ? w.books.filter((b) => b.library_id === lib) : w.books
      // ⚠ HONOURS `limit`, and `total` still reports the whole set. It ignored
      // the parameter until a review measured what that hid: the account
      // drawer caps each library's preview at 5, and with no fixture library
      // holding more than two books the cap was unexercised in both
      // directions — a drawer for a 286-book customer would have rendered 286
      // rows and every test would have stayed green. A fake that drops a
      // parameter is a fake that decides the screen cannot be wrong about it.
      const limit = Number(url.searchParams.get('limit') ?? 25)
      const items = newestFirst(all, (b) => b.added_at).slice(0, limit)
      return { items, total: all.length, offset: 0, limit, truncated: false }
    },
    // ⚠ The narrowing SELECTS works and does not change what one reports —
    // the fake filters the list and leaves each row's `libraries` alone,
    // because that is what the server does and a fake that recomputed it
    // would hide the bug this rule exists to prevent.
    'GET /api/staff/v1/works/instances': (req) => {
      const key = new URL(req.url, 'http://x').searchParams.get('key') ?? ''
      return w.instances[key] ?? []
    },
    'GET /api/staff/v1/works': (req) => {
      const lib = new URL(req.url, 'http://x').searchParams.get('library_id')
      // ⚠ A LOOKUP, not a derivation. Which works a library filter selects is
      // a server decision (a HAVING over the grouped set), and an earlier
      // version of this fake computed it from `instances` — which meant the
      // test named for that rule was largely asserting the fake's own
      // arithmetic. The narrowed answers are fixture data now, like every
      // other payload here.
      const items = lib ? (w.worksIn[lib] ?? []) : w.works
      return { items, total: items.length, offset: 0, limit: 25,
               truncated: false }
    },
    'GET /api/staff/v1/images': (req) => {
      const url = new URL(req.url, 'http://x')
      const lib = url.searchParams.get('library_id')
      const all = lib ? w.images.filter((i) => i.library_id === lib) : w.images
      // ⚠ Newest-first and limited, because that is what the server does and
      // the drawer's merge DEPENDS on it: taking the newest 5 of a union is
      // only correct if each per-library page is that library's newest.
      // `/images` takes no sort parameter, so the client cannot ask — the
      // ordering is `app/staff_api/queries.py`'s constant, and a fake that
      // returned insertion order would let a broken merge pass.
      const limit = Number(url.searchParams.get('limit') ?? 25)
      const items = newestFirst(all, (i) => i.captured_at).slice(0, limit)
      return { items, total: all.length, offset: 0, limit, blobs_visible: true }
    },
    'GET /api/staff/v1/reads': () => [],
    'GET /api/v1/libraries': () => w.mine,
  })
}
