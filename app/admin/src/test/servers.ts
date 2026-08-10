/**
 * The default two-service fake every screen test starts from.
 *
 * ⚠ The console talks to TWO backends and the tests must too, or they prove
 * the wrong thing: reading comes from `/api/staff/v1` (cross-tenant) and
 * writing from `/api/v1` (the operator's own memberships). A fake that served
 * both from one set of rows would let a screen mix the scopes and still pass.
 */
import {
  fakeServer, makeAccount, makeOverview, makeStaffBook, makeStaffLibrary,
  makeLibrary, type FakeServer,
} from './harness'
import type { StaffAccount, StaffBook, StaffLibrary, StaffOverview } from '../api/staff'
import type { LibraryDTO } from '../api/schema'

export interface World {
  overview: StaffOverview
  libraries: StaffLibrary[]
  accounts: StaffAccount[]
  books: StaffBook[]
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
  books: [
    makeStaffBook({ id: 'b1', library_id: 'lib-1', title: 'אבא', author: 'א' }),
    makeStaffBook({ id: 'b2', library_id: 'lib-1', title: 'בבא', author: 'ב',
                    status: 'approved' }),
    makeStaffBook({ id: 'b3', library_id: 'lib-2', title: 'גגא', author: 'ג',
                    status: 'manual' }),
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
    'GET /api/staff/v1/reads': () => [],
    'GET /api/v1/libraries': () => w.mine,
  })
}
