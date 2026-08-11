/**
 * The default two-service fake every screen test starts from.
 *
 * ⚠ The console talks to TWO backends and the tests must too, or they prove
 * the wrong thing: reading comes from `/api/staff/v1` (cross-tenant) and
 * writing from `/api/v1` (the operator's own memberships). A fake that served
 * both from one set of rows would let a screen mix the scopes and still pass.
 */
import {
  fakeServer, makeAccount, makeOverview, makeStaffBook, makeStaffImage,
  makeStaffLibrary, makeStaffWork, makeLibrary, type FakeServer,
} from './harness'
import type {
  StaffAccount, StaffBook, StaffImage, StaffLibrary, StaffOverview, StaffWork,
} from '../api/staff'
import type { LibraryDTO } from '../api/schema'

export interface World {
  overview: StaffOverview
  libraries: StaffLibrary[]
  accounts: StaffAccount[]
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
    accounts: 2, libraries: 2, memberships: 3, books: 3, copies: 3,
    auto: 1, approved: 1, manual: 1, shelves: 2, captures: 4, reads: 2,
    duplicates: 1, lent_out: 1,
  }),
  libraries: [
    makeStaffLibrary({ id: 'lib-1', label: 'הבית', members: 2, admins: 1,
                       books: 2, auto: 1, approved: 1, shelves: 1, captures: 3 }),
    makeStaffLibrary({ id: 'lib-2', label: 'ההורים', members: 1, admins: 1,
                       books: 1, manual: 1, shelves: 1, captures: 1 }),
  ],
  accounts: [
    makeAccount({ id: 'acc-1', display_name: 'משה', memberships: [
      { library_id: 'lib-1', role: 'admin', joined_at: '2026-01-01' },
    ] }),
    makeAccount({ id: 'acc-2', display_name: 'שכן', memberships: [
      { library_id: 'lib-1', role: 'viewer', joined_at: '2026-01-02' },
      { library_id: 'lib-2', role: 'admin', joined_at: '2026-01-03' },
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
  ],
  // ⚠ Only lib-1. The operator SEES both libraries and may WRITE to one, which
  // is the console's central asymmetry and therefore the default fixture.
  mine: [makeLibrary({ id: 'lib-1', label: 'הבית', role: 'admin' })],
}

export function bothServices(world: Partial<World> = {}): FakeServer {
  const w: World = { ...DEFAULT_WORLD, ...world }
  return fakeServer({
    'GET /api/staff/v1/overview': () => w.overview,
    'GET /api/staff/v1/libraries': () => w.libraries,
    'GET /api/staff/v1/accounts': () => w.accounts,
    'GET /api/staff/v1/books': (req) => {
      const url = new URL(req.url, 'http://x')
      const lib = url.searchParams.get('library_id')
      const items = lib ? w.books.filter((b) => b.library_id === lib) : w.books
      return { items, total: items.length, offset: 0, limit: 25,
               truncated: false }
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
      const lib = new URL(req.url, 'http://x').searchParams.get('library_id')
      const items = lib ? w.images.filter((i) => i.library_id === lib) : w.images
      return { items, total: items.length, offset: 0, limit: 25,
               blobs_visible: true }
    },
    'GET /api/staff/v1/reads': () => [],
    'GET /api/v1/libraries': () => w.mine,
  })
}
