/**
 * Loading the plan from the server, and writing every edit back to it.
 *
 * The one behaviour the port had to replace rather than move: the lab wrote
 * the whole document to `localStorage` on every edit, and a server cannot be
 * written that way. `sync.ts` decides what changed and `push.ts` issues the
 * calls; this hook is what the screen actually holds.
 *
 * ⚠ **The saved indicator keeps its meaning.** The lab showed *saving /
 * saved / failed* and said so on the toolbar, because "an autosave nobody can
 * see is indistinguishable from no autosave" (MAP_PLAN §4, third pass). It
 * means the same three things here — the difference is that the honest caveat
 * on the same line is gone, since this is no longer browser storage.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import type { Plan } from './core/model'
import { emptyPlan } from './core/model'
import { Ids, push, type Api, type Refusal } from './push'
import { planDiff, toPlan, type MapWire, type ShelfWire } from './sync'

export type Saved = 'saving' | 'saved' | 'failed'

export type MapSource = {
  /** The whole drawing, plus the shelves standing in it. */
  load: () => Promise<{ map: MapWire; shelves: ShelfWire[] }>
  api: Api
  /**
    * The site and storey the drawing hangs off, created if this library has
    * none. Sites arrive as a picker in P6.3b; until then there is one.
    *
    * ⚠ It must return a real FLOOR id too. The first version returned only
    * the site, `toPlan` synthesised a floor the server had never heard of,
    * and the first room drawn onto it was refused with a 404 for a floor id
    * that existed nowhere but the document. Found by opening the editor.
    */
   ensureHome: () => Promise<{ siteId: string; floorId: string }>
}

export type MapSync = {
  ready: boolean
  /** Bumps on every reload, so the editor remounts with the new document
   *  instead of adopting it. */
  generation: number
  error: string | null
  saved: Saved
  /** The refusal the server gave, in its own words, or null. */
  refusal: Refusal | null
  dismiss: () => void
  /** The plan as the server last confirmed it — the editor's starting doc. */
  initial: Plan | null
  /** Hand the current document over; the hook works out what to send. */
  record: (plan: Plan) => void
  reload: () => void
}

export function useMapSync(source: MapSource): MapSync {
  const [initial, setInitial] = useState<Plan | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<Saved>('saved')
  const [refusal, setRefusal] = useState<Refusal | null>(null)
  const [generation, setGeneration] = useState(0)

  /** The last state the SERVER confirmed. Every diff is against this, never
   *  against the previous render — a dropped call must not be forgotten. */
  const confirmed = useRef<Plan>(emptyPlan())
  const ids = useRef(new Ids())
  const site = useRef<string>('')
  /** ⚠ ONE `ensureHome` per mount, whatever React does with the effect.
   *  StrictMode invokes it twice in development, both calls read "no sites
   *  yet", and the editor opened on a library with TWO homes — measured on
   *  the first run. Holding the promise makes the second call join the
   *  first instead of racing it. */
  const homing = useRef<Promise<{ siteId: string; floorId: string }> | null>(null)
  const inflight = useRef<Promise<void>>(Promise.resolve())

  useEffect(() => {
    let alive = true
    setReady(false)
    setError(null)
    void (async () => {
      try {
        if (!homing.current) homing.current = source.ensureHome()
        site.current = (await homing.current).siteId
        const { map, shelves } = await source.load()
        if (!alive) return
        const plan = toPlan(map, shelves, site.current)
        confirmed.current = plan
        ids.current = new Ids()
        setInitial(plan)
        setReady(true)
      } catch (err) {
        if (alive) setError(messageOf(err))
      }
    })()
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generation])

  const record = useCallback((plan: Plan) => {
    const ops = planDiff(confirmed.current, plan)
    if (ops.length === 0) return
    setSaved('saving')
    // ⚠ SERIALISED. Two edits in flight at once would race on the id table —
    // the second could send a locally minted id the first has not yet
    // learned the server's answer for — and would also let a later gesture
    // land before an earlier one it assumes.
    inflight.current = inflight.current.then(async () => {
      try {
        const stopped = await push(source.api, ops, ids.current, site.current)
        if (stopped) {
          setRefusal(stopped)
          setSaved('failed')
          return
        }
        confirmed.current = plan
        setSaved('saved')
      } catch (err) {
        setError(messageOf(err))
        setSaved('failed')
      }
    })
  }, [source])

  return {
    generation,
    ready,
    error,
    saved,
    refusal,
    dismiss: () => setRefusal(null),
    initial,
    record,
    reload: () => setGeneration((g) => g + 1),
  }
}

function messageOf(err: unknown): string {
  const e = err as { detail?: string; message?: string }
  return e?.detail || e?.message || 'לא הצלחנו לשמור את השינוי'
}
