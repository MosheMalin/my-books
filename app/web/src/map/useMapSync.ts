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
import { Ids, push, type Api } from './push'
import { planDiff, toPlan, type MapWire, type ShelfWire } from './sync'
import type { MapText } from './text'

export type Saved = 'saving' | 'saved' | 'failed'

export type MapSource = {
  /** The whole drawing, plus the shelves standing in it. */
  load: () => Promise<{ map: MapWire; shelves: ShelfWire[] }>
  api: Api
  /**
    * The FIRST site, created if this library has none. Which site is then
    * being drawn is `siteId`, and the picker moves it.
    *
    * ⚠ The STOREY is not its business. An early version returned only a site,
    * `toPlan` synthesised a floor the server had never heard of, and the first
    * room drawn onto it was refused with a 404 — so this used to mint one too.
    * That fixed the first site and no other: the loader guarantees it now, for
    * whichever site is being drawn, which is the same rule in the one place
    * that can also heal a site that never got a floor or lost its last.
    */
   ensureHome: () => Promise<{ siteId: string }>
  /** Which site this library was last drawing, if anything remembers. Kept
   *  outside the hook because "where" is the app's business (one library's
   *  choice must not become another's) and the hook has no library id. */
  rememberedSite?: () => string
  rememberSite?: (id: string) => void
  /**
   * Why the server would refuse to undo — read only AFTER a refusal (P6.4b).
   *
   * ⚠ It exists because the three refusals are three different sentences and
   * the 409 carries only one string, in English. *Nothing was recorded*,
   * *you already took that back* and *things have moved since* must not be
   * shown as each other: a wrong stated reason is worse than a vague one,
   * because it is the thing that makes the next person distrust the control.
   * One extra request, on the failure path only.
   */
  undoOffer?: () => Promise<{
    reason?: string
    restores?: Record<string, number>
    changed?: string[]
  }>
  /**
   * The shelves that stand NOWHERE — read when the picker opens (P6.4c).
   *
   * ⚠ Fetched then, not taken from the load. The list is what the owner is
   * about to choose from, and the one in `initial` is as old as the document:
   * a shelf photographed on the phone five minutes ago would be missing from
   * it, which is exactly the shelf somebody opens this picker to place.
   */
  offTheMap?: () => Promise<OffMapShelf[]>
}

/** A shelf with no address, as the picker shows it. */
export type OffMapShelf = {
  id: string
  label: string
  capture_count: number
  book_count: number
}

/** Which shelf's photographs come first on the merged strip (§3.12). */
export type StripOrder = 'absorbed_first' | 'survivor_first'

/**
 * What a merge would move — the answer to `POST .../merge/preview` (P6.4d).
 *
 * ⚠ `refused` arrives with a **200**, carrying a stable `reason` beside the
 * sentence. A preview that answered 409 could not show the owner why, which
 * is the only thing it is for — and reading a `detail` string would be this
 * client parsing English, which is the finding P6.4c left on this item.
 */
export type MergePreview = {
  absorbed_id: string
  survivor_id: string
  refused: { reason: string; say: string } | null
  already: boolean
  depth: number
  books: number
  copies: { depth: number; count: number }[]
  photos: { depth: number; count: number }[]
  clashes: {
    depth: number
    book_key: string
    winner: string
    absorbed_kind: string
    survivor_kind: string
  }[]
  answers_moved: number
  identities_moved: number
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
/**
 * ⚠ `detail` is a string FROZEN at the moment of the notice, so a notice
 * built from our own vocabulary is frozen in the locale that was active
 * then — and `PlanScreen` recomputes its LEAD from the live table on every
 * render, so switching language mid-notice split the banner down the middle:
 * *"The server refused: אין מחיקה לשחזר"*. Measured.
 *
 * It never showed before P6.4b because a `refused` detail was always the
 * SERVER's own English, so each reader got one coherent language. `say` is
 * the fix: a notice whose words come from `text.ts` carries the function, not
 * the sentence, and re-renders in whatever locale is on screen now.
 */
export type Said = (words: MapText) => string

type Words = { detail?: string; say?: Said }

export type Notice =
  /** The server answered, and the answer was no — a rule the owner met. */
  | ({ kind: 'refused' } & Words)
  /** The request never arrived, and the edit is still in the document — the
   *  next diff carries it, because `confirmed` did not advance. */
  | ({ kind: 'undelivered' } & Words)
  /**
   * The request never arrived and NOTHING will retry it.
   *
   * ⚠ A site gesture is not in the document (§3.9), so there is no later diff
   * to carry it — telling the owner "it will be sent again with your next
   * change" would be a promise this code cannot keep, which is worse than
   * saying nothing. A review found that exact sentence on this path.
   */
  | ({ kind: 'dropped' } & Words)

export type MapSync = {
  ready: boolean
  /** Bumps on every reload, so the editor remounts with the new document
   *  instead of adopting it. */
  generation: number
  /**
   * A re-derive that must NOT blank the screen (P6.4c).
   *
   * ⚠ True only for the per-cell gestures. A site switch or a *reload from
   * the server* replaces WHICH document this is, and showing the previous
   * one meanwhile would be showing another site's rooms; binding a shelf
   * changes one cell of the document already on screen, and a review measured
   * 1.42 seconds of blank for it — after which the owner must find an 11×88
   * pixel bookcase on a 375px plan again. Same mechanism, opposite right
   * answer, so it is a flag rather than a rule.
   */
  refreshing: boolean
  /** The LOAD failed: there is no document, so there is nothing to edit. */
  error: string | null
  saved: Saved
  /** What the last write ran into, in the server's own words, or null. */
  notice: Notice | null
  /**
   * A site gesture that WORKED, said out loud.
   *
   * ⚠ It lives here rather than in the editor's own toast because every site
   * gesture re-derives, which remounts the editor and takes any message it was
   * holding with it — measured: removing a site said nothing at all, the board
   * simply changed. This hook survives the remount, which is exactly the
   * property the acknowledgment needs.
   */
  flash: string | null
  dismiss: () => void
  /**
   * Every SITE of this library, and the one being drawn (§3.9).
   *
   * A site is a grouping — "home", "the parents' place" — never part of an
   * address, so switching does not re-address one shelf: it changes which
   * floors, rooms and bookcases the document is made of. One site renders no
   * chrome at all, the way one library renders as a label.
   */
  sites: { id: string; name: string }[]
  siteId: string
  chooseSite: (id: string) => void
  /** A new site, and a switch to it. Its storey is minted by the LOADER —
   *  the one place that also heals a site which has lost its last one. */
  addSite: (name: string, order: number) => void
  renameSite: (id: string, name: string) => void
  removeSite: (id: string) => void
  /** P6.4b: ask the server to take back the last DESTRUCTIVE map edit.
   *  Not the drawing history — see the implementation. */
  undoLastEdit: () => void
  /** P6.4c. The shelves standing nowhere, for the picker. */
  shelvesOffTheMap: () => Promise<OffMapShelf[]>
  previewMerge: (absorbedId: string, survivorId: string,
                 strip: StripOrder) => Promise<MergePreview>
  mergeShelf: (absorbedId: string, survivorId: string, strip: StripOrder,
               name: string) => void
  /** Put an unaddressed shelf into a free slot. Server-owned: the document
   *  has no way to say "this cell is THAT shelf" (§3.1 — a slot IS a shelf,
   *  so the document holds slots, never identities). */
  bindShelf: (shelfId: string, sectionId: string, col: number,
              level: number, name: string) => void
  /**
   * Take a shelf off the drawing. Undoable on the server (§3.15).
   *
   * ⚠ It NAMES the cell it is emptying. Without that, a panel that has not
   * seen the shelf move detaches it from wherever it now stands and is
   * answered 200 — a review measured the two-device case: the confirmation
   * quoted a label and counts belonging to a cell nobody was acting on.
   */
  unbindShelf: (shelfId: string, sectionId: string, col: number, level: number,
                name: string) => void
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
  const [notice, setNotice] = useState<Notice | null>(null)
  const [flash, setFlash] = useState<string | null>(null)
  const [sites, setSites] = useState<{ id: string; name: string }[]>([])
  const [siteId, setSiteId] = useState<string>('')
  const [generation, setGeneration] = useState(0)
  const [refreshing, setRefreshing] = useState(false)

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
  const homing = useRef<Promise<{ siteId: string }> | null>(null)
  /** The site the OWNER picked, which outlives a re-derive. Empty means "the
   *  one `ensureHome` found", which is what every one-site library gets. */
  const chosen = useRef<string>(source.rememberedSite?.() ?? '')
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

  /** Say something happened, and stop saying it after a while. */
  const announce = useCallback((text: string, ms = 3200) => {
    setFlash(text)
    // ⚠ The duration is a parameter because one caller outlives a re-derive.
    // A successful undo re-reads the map and the shelves — 41 KB on the
    // owner's library — and on a phone that can outlast a 3.2s timer, so the
    // owner would watch the map blank, come back, and say NOTHING about the
    // thing they just asked for. Measured at 1.28s on localhost, which is
    // exactly the kind of margin that does not survive mobile data.
    window.setTimeout(() => setFlash((m) => (m === text ? null : m)), ms)
  }, [])

  /** Throw the session's document away and re-derive it from the server.
   *
   *  ``keepPlace`` says the screen must not go blank while it happens — see
   *  :data:`MapSync.refreshing`. */
  const startOver = useCallback((keepPlace = false) => {
    era.current += 1
    setRefreshing(keepPlace)
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
        const home = await homing.current
        let { map, shelves } = await source.load()
        if (!alive) return
        // ⚠ A remembered site that is no longer there falls back rather than
        // showing an empty plan — the same rule the library switcher holds for
        // a stale stored id. A site can go while another tab is looking at it.
        const wanted = chosen.current || home.siteId
        site.current = map.sites.some((s) => s.id === wanted)
          ? wanted
          : map.sites[0]?.id ?? home.siteId
        /**
         * ⚠ **The storey is guaranteed HERE, for whichever site is being
         * drawn** — not where a site is created.
         *
         * `toPlan` synthesises `f1` for a site with no floors, and the first
         * room drawn onto that is refused with a 404 for a floor that exists
         * nowhere but the document. A review measured every way in: creating a
         * site is two calls with no transaction, so a failure between them left
         * the site standing and floorless FOREVER — invisible in the picker,
         * unremovable, and a 404 waiting for whoever selected it. Two tabs can
         * do it, and so can another tab deleting a site's last storey. One rule
         * at the point of USE closes all three; a rule at each point of
         * creation closes none of them.
         */
        if (!map.floors.some((f) => f.site_id === site.current)) {
          await source.api.post('/map/floors',
                                { site_id: site.current, name: T.ground_floor })
          if (!alive) return
          const again = await source.load()
          if (!alive) return
          map = again.map
          shelves = again.shelves
        }
        // Pinned, so which site opens stops depending on the order the server
        // returns them in — see `addSite` for why that order is not "oldest".
        chosen.current = site.current
        source.rememberSite?.(site.current)
        setSites(map.sites.map((s) => ({ id: s.id, name: s.name })))
        setSiteId(site.current)
        const plan = toPlan(map, shelves, site.current)
        confirmed.current = plan
        ids.current = new Ids()
        setInitial(plan)
        setReady(true)
      setRefreshing(false)
      } catch (err) {
        if (alive) setError(messageOf(err, T))
      }
    })()
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generation])

  /**
   * The four site gestures.
   *
   * ⚠ None of them go through `planDiff`. A site is not IN the document — it
   * decides which document there is — so there is nothing to diff, and putting
   * it in the op language would mean a create whose failure leaves the editor
   * drawing a plan that hangs off nothing. Each writes, then re-derives, which
   * is also how the picker cleans up the duplicate site two tabs can mint.
   */
  const afterSite = useCallback(async (work: Promise<unknown>) => {
    // ⚠ **Drain first.** Every site gesture ends in a re-derive, and
    // re-deriving over an edit that has not reached the server is how it
    // disappears — measured: with one storey queued behind a held push,
    // pressing *add a site* took the drawing from two storeys to one, with no
    // banner and the indicator still reading "saved". *Plan ▸ Reload* is
    // allowed to discard, because the owner asked for exactly that; adding a
    // site is not that.
    setNotice(null)
    // ⚠ And the toolbar says something while two round trips go out. A review
    // measured 147ms of nothing at all after pressing *add a site*, with the
    // indicator reading "saved" the whole time, and the row one reopen away
    // from a second tap that mints a second site.
    setSaved('saving')
    await inflight.current
    try {
      await work
      startOver()
    } catch (err) {
      // A refusal here is a rule — "a site keeps its last storey", "3 rooms
      // still on this floor" — in the server's own words. Anything else never
      // arrived, and NOTHING will carry it later: a site is not in the
      // document, so there is no next diff to ride (see `Notice`).
      const e = err as { status?: number; detail?: string; message?: string }
      setNotice({
        kind: typeof e?.status === 'number' ? 'refused' : 'dropped',
        detail: e?.detail || e?.message || T.save_failed_hint,
      })
      setSaved('failed')
      // ⚠ RE-DERIVE ANYWAY. A gesture that failed part-way can still have
      // changed the library, and an editor showing the `sites` list from
      // before that is how an orphan becomes invisible AND unremovable.
      startOver()
    }
  }, [startOver, T])

  const chooseSite = useCallback((id: string) => {
    if (id === site.current) return
    chosen.current = id
    source.rememberSite?.(id)
    startOver()
  }, [source, startOver])

  const addSite = useCallback((name: string, order: number) => {
    void afterSite((async () => {
      // ⚠ An explicit `order`. `load_map` sorts by `("order", name, id)` and
      // every site created without one is 0 — so "the first site" was really
      // "whichever name sorts first". Measured with the real household shape:
      // `א` precedes `ה`, so a fresh tab opened on *the parents' place* rather
      // than on *home*. The storey the new site needs is minted by the loader,
      // which is the one place that can also heal a site that lost its last.
      const made = await source.api.post('/map/sites', { name, order })
      chosen.current = made.id
      source.rememberSite?.(made.id)
      // The board is about to be replaced by an empty one — correct, since it
      // is a different property, and silent without this.
      announce(T.site_added(name))
    })())
  }, [afterSite, announce, source, T])

  /**
   * ⚠ NO re-derive. A name changes no floor, room or bookcase, so there is
   * nothing to re-read — and re-deriving unmounts the editor, which took the
   * rename box with it: a review measured the box vanishing after ONE
   * keystroke, six PATCHes each built from the stale name plus one character,
   * and the rest of the word landing on the board's own key handler, where
   * Backspace deletes whatever is selected. The list is patched in place and
   * the server is told once, on Enter or blur.
   */
  const renameSite = useCallback((id: string, name: string) => {
    setSites((was) => was.map((s) => (s.id === id ? { ...s, name } : s)))
    void (async () => {
      await inflight.current
      try {
        await source.api.patch(`/map/sites/${id}`, { name })
      } catch (err) {
        const e = err as { status?: number; detail?: string; message?: string }
        setNotice({
          kind: typeof e?.status === 'number' ? 'refused' : 'dropped',
          detail: e?.detail || e?.message || T.save_failed_hint,
        })
        // The name on screen is now a claim the server never accepted.
        startOver()
      }
    })()
  }, [source, startOver, T])

  const removeSite = useCallback((id: string) => {
    // ⚠ The editor stops writing into this site BEFORE the call goes out, not
    // after it comes back. Measured with the DELETE held open: a storey added
    // in that window was created inside the doomed site and then swept away
    // with it — the drawing accepted the edit and the server destroyed it,
    // with nothing said. Bumping `era` is what stops the queue.
    if (id === site.current) era.current += 1
    const name = sites.find((s) => s.id === id)?.name
    void afterSite((async () => {
      await source.api.del(`/map/sites/${id}`)
      if (id === chosen.current || id === site.current) {
        chosen.current = ''
        source.rememberSite?.('')
      }
      if (name) announce(T.site_removed(name))
    })())
  }, [afterSite, announce, sites, source, T])

  /**
   * P6.4b: ask the SERVER to take back the last destructive map edit.
   *
   * ⚠ A different thing from the editor's own `undo`, which steps this
   * session's drawing back one commit. That one cannot bring a shelf back —
   * it re-DRAWS the slot, and the server mints a new empty shelf for it, so
   * the label the owner typed and the books that stood there stay behind on a
   * detached row. This asks for the recorded inverse instead.
   *
   * Goes through `afterSite` for its drain: an undo re-derives the whole
   * document, and re-deriving over an edit that has not reached the server is
   * how that edit disappears (measured, on the site gestures).
   *
   * The refusal is shown in OUR words, never the server's — the server's
   * sentence is English by construction, and `text.ts` is where the Hebrew
   * lives. `reason` is what the words are chosen from.
   */
  const undoLastEdit = useCallback(() => {
    void (async () => {
      // ⚠ NOT through `afterSite`, and the difference is the whole finding.
      // `afterSite` re-derives on BOTH paths, which is right for a site
      // gesture (a half-failed one can still have changed the library) and
      // wrong here: a refused undo wrote nothing, so re-deriving buys nothing
      // and costs the owner their drawing history. Measured — the refusal
      // path replaced the whole editor for 1.28s and swapped the SVG node,
      // discarding this session's Ctrl+Z stack, the selection and the
      // viewport, for a press that changed nothing.
      //
      // The DRAIN is kept, for `afterSite`'s own reason: a successful undo
      // ends in a re-derive, and re-deriving over an edit that has not
      // reached the server is how that edit disappears.
      setNotice(null)
      setSaved('saving')
      await inflight.current

      let offer: { restores?: Record<string, number> } | undefined
      try {
        offer = await source.api.post('/map/undo', undefined)
      } catch (err) {
        const e = err as { status?: number; detail?: string; message?: string }
        if (e?.status === 409) {
          // Ask WHY, and say that — a blanket answer would tell an owner who
          // had simply already pressed undo that their shelves had changed
          // underneath them, which is a false claim about their data.
          const said = await source.undoOffer?.()
            .catch(() => ({} as Awaited<ReturnType<
              NonNullable<MapSource['undoOffer']>>>))
          const reason = said?.reason
          if (reason === 'nothing_recorded' || reason === 'already_undone') {
            // ⚠ The FLASH, not the banner. Both are statements about a
            // healthy library — nothing was refused, because nothing was
            // ever proposed — and `role="alert"` under a lead reading "the
            // server refused the change" reports a fault where there is
            // none. It is also the reply the owner meets most often, since
            // it is what every exploratory press returns.
            announce(reason === 'nothing_recorded'
              ? T.undo_nothing : T.undo_already)
          } else {
            // The one refusal where something really is in the way — and it
            // now NAMES what, which is what §3.15 asks of it. `changed`
            // arrives as `table:id`; the shelves are the part an owner can
            // go and look at.
            const changed: string[] = said?.changed ?? []
            const shelves = changed.filter((t) => t.startsWith('shelves:'))
            setNotice({
              // ⚠ The parameter SHADOWS the outer `T` on purpose: the words
              // must come from whichever table is live when this renders,
              // never the one captured here (see `Said`). It also keeps the
              // key visible to the dead-key scan, which anchors on `T.`.
              kind: 'refused',
              say: (T) =>
                T.undo_moved(shelves.length, changed.length - shelves.length),
            })
          }
        } else {
          setNotice({
            kind: typeof e?.status === 'number' ? 'refused' : 'dropped',
            detail: e?.detail || e?.message || T.save_failed_hint,
          })
        }
        // Nothing on the server moved, so nothing here is unsaved.
        setSaved('saved')
        return
      }

      // It worked. NOW the re-derive is owed: the server has changed rows
      // this session's document knows nothing about.
      const restored = offer?.restores?.shelves ?? 0
      announce(T.undo_done(restored), 9000)
      startOver()
    })()
  }, [announce, source, startOver, T])

  /**
   * The two halves of P6.4c, and one implementation because they differ only
   * in the request.
   *
   * Shaped after `undoLastEdit` rather than after `record`: what these change
   * is not in the document (§3.1 — the document holds SLOTS, and which shelf
   * stands in one is a row only the server has), so there is no diff to
   * carry them and no optimistic state to roll back.
   *
   * ⚠ **The drain, then the re-derive.** The drain is `afterSite`'s reason —
   * re-deriving over an edit that has not reached the server is how that edit
   * disappears. The re-derive is owed on SUCCESS because `free` and `id` are
   * server facts this document now has wrong, and on FAILURE for a different
   * reason: every refusal these two can meet means the drawing moved under
   * the owner, so the document is stale either way. That is the opposite of
   * `undoLastEdit`, where a refusal wrote nothing and re-deriving would cost
   * the owner their drawing history for a press that changed nothing.
   */
  const slotWrite = useCallback((
    work: (api: Api) => Promise<unknown>, said: string,
  ) => {
    void (async () => {
      setNotice(null)
      setSaved('saving')
      await inflight.current
      try {
        await work(source.api)
      } catch (err) {
        const e = err as { status?: number; detail?: string; message?: string }
        // ⚠ OUR words for the refusals that MEAN the drawing moved, and the
        // server's for everything else. The client only offers a bind into a
        // slot it was told was free, for a shelf it was told stood nowhere,
        // so 400 / 404 / 409 are all *somebody edited this since you looked*
        // — and the English underneath ("column 2, level 3 already holds
        // shelf 9f3a…") is true and unusable.
        //
        // ⚠⚠ The first version said that of EVERY status. A review measured a
        // 403 answering "the drawing has changed since — try again", and the
        // same sentence covered 401 (a session that expired while the tab was
        // backgrounded, which is the ordinary phone flow), 429 and every 5xx.
        // Every one of those is a lie, and "try again" is an instruction that
        // will fail identically forever. A wrong stated reason is worse than
        // none.
        const moved = e?.status === 400 || e?.status === 404
          || e?.status === 409
        setNotice(moved
          ? { kind: 'refused', say: (T) => T.slot_moved_on }
          : { kind: typeof e?.status === 'number' ? 'refused' : 'dropped',
              detail: e?.detail || e?.message || T.save_failed_hint })
        setSaved('saved')
        startOver(true)
        return
      }
      announce(said)
      startOver(true)
    })()
  }, [announce, source, startOver, T])

  const shelvesOffTheMap = useCallback(
    () => source.offTheMap?.() ?? Promise.resolve([]), [source])

  /**
   * What absorbing one shelf into another would move. Writes nothing.
   *
   * ⚠ NOT routed through `slotWrite`. That helper re-derives the whole
   * document after every call, because every refusal a bind or an unbind can
   * meet means the drawing moved — and a preview meets refusals that mean
   * nothing of the sort (*a read is running*, *the wishlist stands nowhere*).
   * Re-deriving here would also blank the panel the owner is reading the
   * preview in.
   */
  const previewMerge = useCallback(
    (absorbedId: string, survivorId: string, strip: StripOrder) =>
      source.api.post(
        `/map/shelves/${encodeURIComponent(absorbedId)}/merge/preview`,
        { into: survivorId, strip }) as Promise<MergePreview>,
    [source])

  /**
   * Absorb one shelf into another — **the dangerous half of P6.4**.
   *
   * A `slotWrite` like the bind and the unbind, and for the strongest version
   * of that helper's reason: this one moves a population of copies and deletes
   * a shelf row, so the document on screen is wrong in more places than the
   * cell that was pressed. §3.14 keeps it a separate gesture from the bind —
   * never one button — and §3.14 is also why the panel shows the preview
   * first: a ✓ given without seeing what moves is not one.
   */
  const mergeShelf = useCallback(
    (absorbedId: string, survivorId: string, strip: StripOrder,
     name: string) =>
      slotWrite(
        (api) => api.post(
          `/map/shelves/${encodeURIComponent(absorbedId)}/merge`,
          { into: survivorId, strip }),
        T.merged_into(name)),
    [slotWrite, T])

  const bindShelf = useCallback(
    (shelfId: string, sectionId: string, col: number, level: number,
     name: string) =>
      slotWrite(
        (api) => api.put(`/map/shelves/${encodeURIComponent(shelfId)}/address`,
          // 1-based on the wire, 0-based in the document — the pillar's one
          // off-by-one, applied here exactly as `toPlan` applies it back.
          { section_id: sectionId, col: col + 1, level: level + 1 }),
        T.bound_here(name)),
    [slotWrite, T])

  const unbindShelf = useCallback(
    (shelfId: string, sectionId: string, col: number, level: number,
     name: string) =>
      slotWrite(
        (api) => api.del(
          `/map/shelves/${encodeURIComponent(shelfId)}/address`
          + `?section_id=${encodeURIComponent(sectionId)}`
          // 1-based on the wire, as everywhere else in this pillar.
          + `&col=${col + 1}&level=${level + 1}`),
        T.unbound_shelf(name)),
    [slotWrite, T])

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
      // ⚠ Which of these DESTROY something, so the owner can be told the
      // removal is reversible while that is still true. See `undo_offered`
      // for why saying nothing was the real defect: the control one row
      // above is closer, enabled, and looks like it worked.
      //
      // Not in the `confirm()` — that dialog exists to provoke a moment of
      // doubt, and "don't worry, this can be taken back" is a reason to say
      // yes at exactly the wrong moment.
      // ⚠ The list must match what the SERVER journals, or the hint is a
      // promise the undo cannot keep — or, as first written, silence where it
      // could have kept one. `remove_record` covers site, floor, place,
      // bookcase and section; the two section editors cover columns, levels
      // and gaps. Removing a ROOM and removing a FLOOR were missing here and
      // are journalled, so both are in. (A site is not in the document, so
      // it never reaches this diff — `removeSite` announces its own.)
      const destroyed = ops.some((o) => o.kind === 'case.remove'
        || o.kind === 'room.remove' || o.kind === 'floor.remove'
        || o.kind === 'section.remove' || o.kind === 'section.columns'
        || o.kind === 'section.levels' || o.kind === 'section.gaps')
      if (ops.length === 0) {
        setSaved('saved')
        return
      }
      // ⚠ The banner is about the LAST write, so the next REAL one clears it
      // — a review measured a refusal surviving a successful floor add, a trip
      // through the overview and the removal of the very site it named. But
      // clearing it in `record` itself wiped it instantly: every re-derive
      // remounts the editor, and every mount hands its document straight to
      // `record`, so the refusal that CAUSED the re-derive was erased by the
      // no-op diff that followed it. A write with nothing to say says nothing.
      setNotice(null)
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
          setNotice({ kind: 'refused', detail: stopped.detail })
          setSaved('failed')
          startOver()
          return
        }
        confirmed.current = plan
        setSaved('saved')
        // The removal landed. Say — once, neutrally, in the surface built
        // for exactly this — that it can be taken back, and NAME the
        // control. `undo_offered` carries the argument.
        if (destroyed) announce(T.undo_offered, 6000)
      } catch (err) {
        // ⚠ NOT `setError`. See `Notice`: the drawing is still on screen and
        // still the truth about what the owner drew; what failed is the
        // delivery. `confirmed` is left where it was, so the next edit's diff
        // carries this one with it — which is the whole point of diffing
        // against the last CONFIRMED state rather than the last render.
        setNotice({ kind: 'undelivered', detail: messageOf(err, T) })
        setSaved('failed')
      }
    })
  }, [source, startOver, T])

  return {
    generation,
    refreshing,
    ready,
    error,
    saved,
    notice,
    flash,
    dismiss: () => setNotice(null),
    sites,
    siteId,
    chooseSite,
    addSite,
    renameSite,
    removeSite,
    undoLastEdit,
    shelvesOffTheMap,
    previewMerge,
    mergeShelf,
    bindShelf,
    unbindShelf,
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
