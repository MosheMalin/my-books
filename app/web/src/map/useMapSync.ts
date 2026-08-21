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
import type { MapText } from './text'

export type Saved = 'saving' | 'saved' | 'failed'

export type MapSource = {
  /** The whole drawing, plus the shelves standing in it. */
  load: () => Promise<{ map: MapWire; shelves: ShelfWire[] }>
  api: Api
  /**
    * The site and storey the drawing hangs off, created if this library has
    * none. Sites arrive as a picker in P6.3.1; until then there is one.
    *
    * ⚠ It must return a real FLOOR id too. The first version returned only
    * the site, `toPlan` synthesised a floor the server had never heard of,
    * and the first room drawn onto it was refused with a 404 for a floor id
    * that existed nowhere but the document. Found by opening the editor.
    */
   ensureHome: () => Promise<{ siteId: string; floorId: string }>
}

/**
 * Why a push failure is NOT the load's `error`.
 *
 * A UX review measured the asymmetry and it was backwards: a REFUSAL — the
 * server saying no, the more serious event — kept the editor and showed a
 * banner, while a dropped connection mid-save answered the load's error
 * screen. That unmounts the editor: the drawing, the selection, the undo stack
 * and every edit since the last successful push are replaced by one line and a
 * *retry* button which re-derives from the server, so the un-pushed work is not
 * recovered, it is discarded. One thrown fetch on a phone in a lift.
 *
 * So `error` stays what it always meant — the document never arrived, there is
 * nothing to edit — and a push that could not be delivered says so beside a
 * drawing that is still on screen.
 */
export type Trouble = { detail: string }

export type MapSync = {
  ready: boolean
  /** Bumps on every reload, so the editor remounts with the new document
   *  instead of adopting it. */
  generation: number
  /** The LOAD failed: there is no document, so there is nothing to edit. */
  error: string | null
  saved: Saved
  /** The refusal the server gave, in its own words, or null. */
  refusal: Refusal | null
  /** A push that never reached the server. The editor stays. */
  trouble: Trouble | null
  dismiss: () => void
  /** The plan as the server last confirmed it — the editor's starting doc. */
  initial: Plan | null
  /** Hand the current document over; the hook works out what to send. */
  record: (plan: Plan) => void
  reload: () => void
}

export function useMapSync(source: MapSource, T: MapText): MapSync {
  const [initial, setInitial] = useState<Plan | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<Saved>('saved')
  const [refusal, setRefusal] = useState<Refusal | null>(null)
  const [trouble, setTrouble] = useState<Trouble | null>(null)
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
  /**
   * ⚠ **Nothing is written while the document is being re-derived**, and this
   * is the guard that says so.
   *
   * `initial` is the last plan the server was ASKED for; `confirmed` is the
   * last plan it was TOLD. They agree until the first successful push and
   * never again. A data-integrity review measured what that cost: bumping
   * `generation` re-keys `MapScreen`, which REMOUNTS with the stale `initial`
   * and — as every mount does — hands its starting document to `record`. That
   * diffs the plan from before the session's edits against everything the
   * server was told, and pushes the REVERSE: `DELETE /map/bookcases/<id>/
   * slots` (which detaches the shelves books stand on) and then the case
   * itself. Two triggers, both measured: *Plan ▸ Reload from the server*, and
   * every refusal — the path this hook uses to RECOVER from one.
   *
   * `setReady(false)` closes the mount: the editor is gone for that render
   * instead of mounting over stale data. `era` closes the other half — a
   * write QUEUED before the reload, which would otherwise run afterwards
   * against a `confirmed` the server is about to contradict, and be re-issued
   * by the next diff because the load's own GET went out before it landed.
   * A counter rather than a flag, because "is a reload pending" is false again
   * the moment the new document arrives, and the task may run after that.
   */
  const era = useRef(0)

  /** Throw the session's document away and re-derive it from the server. */
  const startOver = useCallback(() => {
    era.current += 1
    setReady(false)
    setGeneration((g) => g + 1)
  }, [])

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
        if (alive) setError(messageOf(err, T))
      }
    })()
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generation])

  const record = useCallback((plan: Plan) => {
    setSaved('saving')
    // ⚠ SERIALISED, and the diff is computed INSIDE the task.
    //
    // A review measured the previous shape, where the diff ran at call time:
    // `confirmed` only advances when a push resolves, so a second edit
    // arriving during the round trip diffed against the STALE confirmed state
    // and re-issued the first edit's creates. Two rooms, one of them
    // orphaned, from drawing a room and typing one letter of its name.
    //
    // Serialised for the id table too: a second push could otherwise send a
    // locally minted id the first has not yet learned the server's answer for.
    const era_ = era.current
    inflight.current = inflight.current.then(async () => {
      // ⚠ Checked HERE rather than at call time: this task may have waited
      // behind a push that was still in flight when the reload was asked for,
      // and reassigning `inflight` does not cancel a chain that is already
      // running. The document this plan described is gone either way.
      if (era_ !== era.current) return
      const ops = planDiff(confirmed.current, plan)
      if (ops.length === 0) {
        setSaved('saved')
        return
      }
      try {
        const { done, refusal: stopped } = await push(
          source.api, ops, ids.current, site.current)
        if (era_ !== era.current) {
          // ⚠ The document was re-derived WHILE this push was in flight, so
          // `confirmed` now describes the server's answer and this plan
          // describes a drawing nobody is looking at. Writing it here is what
          // put a `DELETE` for a locally minted id on the wire — measured.
          //
          // `done` is why this is not simply a `return`: operations that
          // landed after the reload's own GET went out are on the server and
          // NOT in the document just derived, so the screen would be missing
          // what this push created. Ask again — the second load happens after
          // the writes, so it converges.
          if (done > 0) startOver()
          return
        }
        if (stopped) {
          // ⚠ RE-DERIVE, do not guess. Some operations landed and the rest did
          // not, and there is no honest way to compute the document that
          // describes — so the server is asked again and the editor remounts
          // with the truth. A review measured the alternative: leaving
          // `confirmed` untouched made every later edit replay the creates
          // that HAD succeeded, and the library grew phantom rooms.
          //
          // The cost is the undo stack for that session, which is the right
          // thing to lose when the drawing on screen and the drawing in the
          // library have diverged. `startOver` — not a bare bump — because
          // the bump ALONE was the second half of the same defect.
          setRefusal(stopped)
          setSaved('failed')
          startOver()
          return
        }
        confirmed.current = plan
        setSaved('saved')
      } catch (err) {
        // ⚠ NOT `setError`. See `Trouble`: the drawing is still on screen and
        // still the truth about what the owner drew; what failed is the
        // delivery. `confirmed` is left where it was, so the next edit's diff
        // carries this one with it — which is the whole point of diffing
        // against the last CONFIRMED state rather than the last render.
        setTrouble({ detail: messageOf(err, T) })
        setSaved('failed')
      }
    })
  }, [source, startOver, T])

  return {
    generation,
    ready,
    error,
    saved,
    refusal,
    trouble,
    dismiss: () => {
      setRefusal(null)
      setTrouble(null)
    },
    initial,
    record,
    reload: startOver,
  }
}

/**
 * ⚠ The fallback comes from the TABLE, handed in, because a hook cannot call
 * `useI18n`. It used to be a Hebrew string literal here — so an English reader
 * met one Hebrew sentence when the network dropped, and the dead-key scan
 * could not see it, since it was never a key. That is the exact second half of
 * the failure the scan was written for: a string that never entered the table.
 */
function messageOf(err: unknown, T: MapText): string {
  const e = err as { detail?: string; message?: string }
  return e?.detail || e?.message || T.save_failed_hint
}
