/**
 * Running a plan diff against `/api/v1/map`.
 *
 * The half of the sync that talks; `sync.ts` is the half that decides, and it
 * is pure so it can be tested without a server. Split for the same reason
 * `app/domain/reconcile.py` is split from `app/reconcile_apply.py`.
 *
 * ⚠ **The id table.** A create mints its id on the SERVER, but the document
 * already holds a local one and so does the undo stack; rewriting either
 * would corrupt history. So the local id is kept and translated here, for the
 * session. The next load rebuilds the document from the server and the ids
 * simply are the server's.
 */

import type { Op } from './sync'
import { wireAddress } from './sync'

export type Api = {
  post: (path: string, body?: unknown) => Promise<any>
  patch: (path: string, body: unknown) => Promise<any>
  del: (path: string) => Promise<any>
}

/** What a push could not do, in the words the screen shows. */
export type Refusal = { op: Op; status: number; detail: string }

export class Ids {
  private readonly table = new Map<string, string>()

  learn(local: string, remote: string): void {
    this.table.set(local, remote)
  }

  /** The server's id for a document id — itself, unless it was minted here. */
  of(local: string): string {
    return this.table.get(local) ?? local
  }
}

/**
 * Issue one call per operation, in order, and stop at the first refusal.
 *
 * ⚠ Stops rather than continues, deliberately. The operations of one gesture
 * are ordered so that later ones assume earlier ones landed — a bookcase
 * attaches to a room the same pass created it — so pressing on after a
 * failure sends calls whose premise is gone. The caller reverts the document
 * to the last confirmed state and shows the refusal, which is the only
 * honest thing to do with a server that said no.
 */
export async function push(
  api: Api, ops: Op[], ids: Ids, siteId: string,
): Promise<Refusal | null> {
  for (const op of ops) {
    try {
      await run(api, op, ids, siteId)
    } catch (err) {
      const refusal = asRefusal(err)
      if (!refusal) throw err
      return { op, ...refusal }
    }
  }
  return null
}

async function run(api: Api, op: Op, ids: Ids, siteId: string): Promise<void> {
  switch (op.kind) {
    case 'floor.add': {
      const made = await api.post('/map/floors', {
        site_id: siteId, name: op.floor.name || '—',
      })
      ids.learn(op.floor.id, made.id)
      return
    }
    case 'floor.rename':
      await api.patch(`/map/floors/${ids.of(op.id)}`,
        { name: op.name || '—' })
      return
    case 'floor.remove':
      await api.del(`/map/floors/${ids.of(op.id)}`)
      return

    case 'room.add': {
      const made = await api.post('/map/places', {
        floor_id: ids.of(op.room.floorId),
        name: op.room.name,
        rect: op.room.rect,
      })
      ids.learn(op.room.id, made.id)
      return
    }
    case 'room.edit':
      // ⚠ The storey goes in the SAME request, and the server moves the
      // room's bookcases with it — a review measured a room that changed
      // floor alone leaving its case behind and bricking it.
      await api.patch(`/map/places/${ids.of(op.room.id)}`, {
        name: op.room.name,
        rect: op.room.rect,
        ...(op.movedStorey ? { floor_id: ids.of(op.room.floorId) } : {}),
      })
      return
    case 'room.remove':
      await api.del(`/map/places/${ids.of(op.id)}`)
      return

    case 'case.add': {
      const first = op.bookcase.sections[0]
      const made = await api.post('/map/bookcases', {
        floor_id: ids.of(op.bookcase.floorId),
        place_id: op.bookcase.roomId ? ids.of(op.bookcase.roomId) : null,
        name: op.bookcase.name,
        front: op.bookcase.front,
        rect: op.bookcase.rect,
        columns: first ? first.columnLevels.length : 1,
        levels: first ? first.defaultLevels : 5,
        depth: first ? first.defaultDepth : 1,
      })
      ids.learn(op.bookcase.id, made.id)
      // The server minted the first section too; the document's own id for it
      // is learned on the next load, and nothing addresses it before then.
      return
    }
    case 'case.edit':
      await api.patch(`/map/bookcases/${ids.of(op.bookcase.id)}`, {
        name: op.bookcase.name,
        front: op.bookcase.front,
        rect: op.bookcase.rect,
        // `place_id: null` means "unchanged" on the wire, so letting go is
        // its own flag — a JSON null cannot mean both.
        ...(op.roomChanged
          ? op.bookcase.roomId
            ? { place_id: ids.of(op.bookcase.roomId) }
            : { detach: true }
          : {}),
      })
      return
    case 'case.remove':
      // Emptying the slots is a separate, explicit call, and it reports what
      // it cost: an occupied shelf is DETACHED, never destroyed.
      await api.del(`/map/bookcases/${ids.of(op.id)}/slots`)
      await api.del(`/map/bookcases/${ids.of(op.id)}`)
      return

    case 'section.add': {
      const made = await api.post('/map/sections', {
        bookcase_id: ids.of(op.caseId),
        where: op.atBottom ? 'bottom' : 'top',
      })
      ids.learn(op.section.id, made.section.id)
      return
    }
    case 'section.columns':
      await api.patch(`/map/sections/${ids.of(op.section.id)}`,
        { columns: op.columns })
      return
    case 'section.levels':
      // 1-based on the wire; the document counts columns from 0.
      await api.patch(`/map/sections/${ids.of(op.section.id)}`,
        { column: op.col + 1, levels: op.levels })
      return
    case 'section.defaults':
      await api.patch(`/map/sections/${ids.of(op.section.id)}`, {
        default_levels: op.section.defaultLevels,
        default_depth: op.section.defaultDepth,
      })
      return
    case 'section.remove':
      await api.del(`/map/sections/${ids.of(op.id)}/slots`)
      await api.del(`/map/sections/${ids.of(op.id)}`)
      return

    case 'shelf.depth': {
      const at = wireAddress(op.section, {
        col: op.col, level: op.level, depth: op.depth, photos: 0,
      })
      await api.patch(
        `/map/sections/${ids.of(at.section_id)}/shelves/${at.col}/${at.level}`,
        { depth_count: op.depth })
      return
    }
  }
}

function asRefusal(err: unknown): { status: number; detail: string } | null {
  const e = err as { status?: number; detail?: string }
  if (typeof e?.status !== 'number') return null
  return { status: e.status, detail: e.detail ?? '' }
}
