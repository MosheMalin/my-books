/**
 * Test harness for the Capture tab — same idiom as `test/harness.tsx`: a fake
 * SERVER (mocks `fetch`), not a fake store, so the hook's own request wiring
 * is what gets exercised.
 *
 * Deliberately does NOT reimplement `reconcile()`/`apply_diff` — that logic
 * is Python's, tested exhaustively in `tests/test_reconcile_apply.py` and
 * friends. Each test hands this fake the exact `DiffDTO` it wants a
 * `POST .../apply` call to answer with (`server.diffFor`), the same way the
 * Python API tests inject a `StubReader` instead of a real engine.
 */
import { vi } from 'vitest'
import type {
  CaptureDTO,
  ClaimOutcomeDTO,
  DiffDTO,
  Shelf,
} from '../api/client'

export interface FakeCaptureServer {
  calls: string[]
  shelves: Shelf[]
  captures: Record<string, CaptureDTO>
  /** status the NEXT `POST .../reads` returns — most tests want 'done' so
   *  no fake-timer polling is needed to reach the review panel. */
  nextReadStatus: 'running' | 'done' | 'stopped' | 'failed'
  /** What `POST .../reads/{id}/apply` answers with, given the answers it
   *  was called with — the test's own stand-in for `reconcile()`. */
  diffFor: (readId: string, answers: { claim_id: string; kind: string }[]) => DiffDTO
  uploadShouldFail: boolean
}

let shelfSeq = 0
let readSeq = 0

export function emptyDiff(shelfId: string, depth: number, readId: string): DiffDTO {
  return {
    shelf_id: shelfId, depth, read_id: readId, added: [], corrected: [],
    unchanged: [], needs_decision: [], not_seen: [], rejected: [], ignored: [],
  }
}

export function outcome(over: Partial<ClaimOutcomeDTO> & {
  claim: ClaimOutcomeDTO['claim']
}): ClaimOutcomeDTO {
  return { kind: 'added', book_key: '', reason: '', ...over }
}

export function claim(over: Partial<ClaimOutcomeDTO['claim']> & { id: string }):
  ClaimOutcomeDTO['claim'] {
  return {
    spine_id: `sp-${over.id}`, capture_id: 'cap1', text: '', title: '',
    author: '', tier: 'auto', score: 0, alternatives: [], ...over,
  }
}

export function fakeCaptureServer(
  initialShelves: Shelf[] = [],
): FakeCaptureServer {
  const server: FakeCaptureServer = {
    calls: [],
    shelves: [...initialShelves],
    captures: {},
    nextReadStatus: 'done',
    diffFor: (readId, _answers) => emptyDiff('sh1', 1, readId),
    uploadShouldFail: false,
  }

  const respond = (body: unknown, status = 200) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status, headers: { 'Content-Type': 'application/json' },
    })

  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    server.calls.push(url)
    const method = init?.method ?? 'GET'
    const u = new URL(url, 'http://test')
    const parts = u.pathname.split('/').filter(Boolean) // ['api','v1',...]

    if (u.pathname === '/api/v1/images' && method === 'POST') {
      if (server.uploadShouldFail) return respond({ detail: 'boom' }, 500)
      const key = `img${++shelfSeq}`
      return respond({
        key, sha256: '', size: 1, content_type: 'image/png', filename: '',
        width: 1, height: 1,
      }, 201)
    }

    if (u.pathname === '/api/v1/captures' && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as
        { image_id?: string; shelf_id?: string | null; depth?: number }
      let shelf: Shelf
      let shelfCreated = false
      if (body.shelf_id) {
        const found = server.shelves.find((s) => s.id === body.shelf_id)
        if (!found) return respond({ detail: 'no such shelf' }, 404)
        shelf = found
      } else {
        shelf = {
          id: `sh${++shelfSeq}`, label: '', depth_count: 1, virtual: false,
          created_at: null, capture_count: 0,
        }
        server.shelves.push(shelf)
        shelfCreated = true
      }
      const cap: CaptureDTO = {
        id: `cap${shelfSeq}`, shelf_id: shelf.id, depth: body.depth ?? 1,
        order: 0, image_id: body.image_id ?? null, captured_at: null,
      }
      server.captures[cap.id] = cap
      return respond({ capture: cap, shelf, shelf_created: shelfCreated }, 201)
    }

    if (parts[2] === 'captures' && parts[3] && method === 'PATCH') {
      const cap = server.captures[parts[3]]
      if (!cap) return respond({ detail: 'no such capture' }, 404)
      const body = JSON.parse(String(init?.body)) as
        { shelf_id?: string | null; depth?: number | null }
      const shelfId = body.shelf_id ?? cap.shelf_id
      const shelf = server.shelves.find((s) => s.id === shelfId)
      if (!shelf) return respond({ detail: 'no such shelf' }, 404)
      const depth = body.depth ?? cap.depth
      if (depth > shelf.depth_count) {
        return respond({ detail: `undeclared depth ${depth}` }, 409)
      }
      const updated = { ...cap, shelf_id: shelfId, depth }
      server.captures[cap.id] = updated
      return respond({ capture: updated, shelf, shelf_created: false })
    }

    if (u.pathname === '/api/v1/shelves' && method === 'GET') {
      return respond(server.shelves)
    }

    if (parts[2] === 'shelves' && parts[3] && parts[4] === 'depths' && method === 'POST') {
      const idx = server.shelves.findIndex((s) => s.id === parts[3])
      if (idx === -1) return respond({ detail: 'no such shelf' }, 404)
      const grown = { ...server.shelves[idx]!, depth_count: server.shelves[idx]!.depth_count + 1 }
      server.shelves[idx] = grown
      return respond(grown)
    }

    if (parts[2] === 'shelves' && parts[4] === 'reads' && !parts[5] && method === 'POST') {
      const shelfId = parts[3]!
      const body = JSON.parse(String(init?.body)) as { depth: number; mode: string }
      const id = `rd${++readSeq}`
      return respond({
        id, shelf_id: shelfId, depth: body.depth, capture_ids: [],
        mode: body.mode, status: server.nextReadStatus, code_version: null,
        config: null, started_at: null, finished_at: null, error: null,
        claims: [], progress: null,
      }, 202)
    }

    if (parts[2] === 'shelves' && parts[4] === 'reads' && parts[6] === 'apply' && method === 'POST') {
      const readId = parts[5]!
      const body = JSON.parse(String(init?.body)) as
        { answers: { claim_id: string; kind: string }[] }
      return respond(server.diffFor(readId, body.answers))
    }

    if (parts[2] === 'shelves' && parts[4] === 'reads' && parts[6] === 'stop' && method === 'POST') {
      const shelfId = parts[3]!
      const readId = parts[5]!
      return respond({
        id: readId, shelf_id: shelfId, depth: 1, capture_ids: [], mode: 'spines',
        status: 'stopped', code_version: null, config: null, started_at: null,
        finished_at: null, error: null, claims: [], progress: null,
      })
    }

    if (parts[2] === 'shelves' && parts[4] === 'reads' && parts[5] && !parts[6] && method === 'GET') {
      const shelfId = parts[3]!
      const readId = parts[5]!
      return respond({
        id: readId, shelf_id: shelfId, depth: 1, capture_ids: [], mode: 'spines',
        status: server.nextReadStatus, code_version: null, config: null,
        started_at: null, finished_at: null, error: null, claims: [],
        progress: null,
      })
    }

    return respond({ detail: `unhandled ${method} ${u.pathname}` }, 404)
  })

  return server
}
