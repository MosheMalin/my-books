/**
 * The map editor, wired to this library's drawing.
 *
 * A thin wrapper, deliberately: everything below it came from
 * `planning/map-lab` and must keep working the way nine passes made it work.
 * What is here is the data source and the states an editor over a network has
 * that an editor over `localStorage` did not — loading, a failed load, and a
 * refusal the server gave.
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import { useI18n } from '../lib/i18n'

import MapScreen from './MapScreen'
import type { Plan } from './core/model'
import type { Selection } from './ui/types'
import { EMPTY } from './ui/types'
import { mapText, type MapText } from './text'
import type { MapSource } from './useMapSync'
import { useMapSync } from './useMapSync'
import {
  getMap,
  getUndoOffer,
  listShelves,
  mapDelete,
  mapPatch,
  mapPost,
  mapPut,
} from '../api/client'

/**
 * Which site this library was last drawing.
 *
 * ⚠ Keyed by LIBRARY. One key would make the parents' place the answer for
 * every customer's map, and the id would resolve to nothing in all but one of
 * them — the loader falls back, so it would read as "the picker forgets",
 * which is worse than not remembering at all.
 */
const SITE_KEY = (library: string) => `booksnap.map.site.${library}`

export function PlanScreen({ library }: { library: string }) {
  const { t, lang } = useI18n()
  const T = mapText(lang)

  const source: MapSource = useMemo(() => ({
    load: async () => {
      const [map, shelves] = await Promise.all([getMap(), listShelves()])
      return { map: map as never, shelves: shelves as never }
    },
    undoOffer: async () => await getUndoOffer(),
    api: {
      post: (path, body) => mapPost(path, body),
      put: (path, body) => mapPut(path, body),
      patch: (path, body) => mapPatch(path, body),
      del: (path) => mapDelete(path),
    },
    /**
     * The shelves standing nowhere (P6.4c) — the photo-born half of the
     * population, which is most of it until somebody starts binding.
     *
     * ⚠ The wishlist is excluded by the ROUTE's own default, not by a filter
     * here: `GET /shelves` leaves out virtual shelves unless asked, because
     * counting them inflates the apparent size of the library. It stands
     * nowhere by construction (§5.7) and offering it a slot would be offering
     * a refusal.
     */
    offTheMap: async () => (await listShelves())
      .filter((s) => !s.address)
      .map((s) => ({
        id: s.id, label: s.label,
        capture_count: s.capture_count, book_count: s.book_count,
      })),
    /**
     * The FIRST site, made on first use rather than at sign-up: a household
     * that never draws anything should not carry a "Home" nobody typed. Every
     * site after it comes from the picker (P6.3.1).
     *
     * ⚠ It does NOT mint the storey any more. "Every site has a floor" is one
     * rule with one implementation, in the loader, because that is the only
     * place that also catches a site which never got one (a create that failed
     * half-way) or which lost its last one to another tab.
     *
     * ⚠ **The floor is not optional.** Without it `toPlan` synthesises one,
     * and the first room drawn is refused with a 404 for a floor id that
     * exists only in the document — measured by opening the editor.
     *
     * Reads before it writes. Two tabs opening an undrawn library at the same
     * instant could still mint two sites — the loader then picks the first
     * deterministically, and the picker is where the duplicate becomes
     * visible and removable, which is why it does not need to be prevented
     * here at the cost of a lock nothing else in this app takes.
     */
    rememberedSite: () => {
      try {
        return window.localStorage.getItem(SITE_KEY(library)) ?? ''
      } catch {
        return ''
      }
    },
    rememberSite: (id: string) => {
      try {
        if (id) window.localStorage.setItem(SITE_KEY(library), id)
        else window.localStorage.removeItem(SITE_KEY(library))
      } catch {
        /* a full or blocked localStorage must not stop the switch */
      }
    },
    ensureHome: async () => {
      const map = await getMap()
      const site = map.sites[0]
        ?? await mapPost('/map/sites', { name: t.plan_site_default, order: 0 })
      return { siteId: site.id as string }
    },
  }), [t.plan_site_default, library])

  const sync = useMapSync(source, T)

  /**
   * The document currently ON SCREEN, and the generation it was mounted with.
   *
   * ⚠⚠ **A refresh is not a first load** — CLAUDE.md's own trap, and P6.4c
   * attached it to a PER-CELL gesture. `startOver` lowers `ready`, this
   * screen answered it with `טוען…`, and a review measured 1.42 seconds of
   * BLANK on localhost for one tap on a picker row: plan, bookcase,
   * elevation and panel all gone, then back with nothing selected. On mobile
   * data that is seconds, and an owner taking three shelves off one bookcase
   * pays it three times.
   *
   * So the previous editor stays on screen until the new document arrives,
   * and it is held at the generation it was MOUNTED with — never at
   * `sync.generation`, which has already been bumped. Re-keying it now would
   * remount over the stale `initial` and push it, which is the whole reason
   * the blank was there.
   */
  const [shown, setShown] = useState<{ gen: number; plan: Plan } | null>(null)
  useEffect(() => {
    if (sync.ready && sync.initial)
      setShown({ gen: sync.generation, plan: sync.initial })
  }, [sync.ready, sync.initial, sync.generation])

  /** What the owner had selected when the document was last replaced. */
  const selection = useRef<Selection>(EMPTY)

  if (sync.error) {
    return (
      <main className="mapstate">
        <p className="mapbanner" role="alert">{sync.error}</p>
        <button type="button" onClick={sync.reload}>{t.retry}</button>
      </main>
    )
  }
  /**
   * One banner, two things it can be saying.
   *
   * A REFUSAL is a rule the owner met — "a bookcase holds at most 400
   * shelves", "3 rooms still on this floor". The server's numbers are kept
   * verbatim because they are what makes it actionable; the LEAD is in the
   * reader's language, because `no such bookcase` in English is not an audit
   * artefact like an engine rejection reason, it is what a household member
   * reads at the moment something went wrong. (Translating the whole thing
   * needs a machine-readable code on the wire — recorded for P6.4 rather than
   * guessed at with a regex over English prose.)
   *
   * TROUBLE is a push that never arrived, and it says what happens next,
   * which is true by construction: `confirmed` did not advance, so the change
   * rides along with the next diff.
   *
   * ⚠ Rendered ABOVE the loading branch, because a refusal is exactly when
   * the editor is re-deriving: hiding the reason while the screen it refers
   * to is rebuilt would make the one informative message the briefest thing
   * on screen.
   */
  // ⚠ `say` before `detail`: a notice whose words are OURS carries the
  // function, so it re-renders in the locale on screen now rather than the
  // one that was active when it was raised (see `Said`).
  const detail = sync.notice
    && (sync.notice.say ? sync.notice.say(T) : sync.notice.detail)
  const said = sync.notice && `${
    sync.notice.kind === 'refused' ? T.refused_lead
      : sync.notice.kind === 'undelivered' ? T.not_saved_yet
        : T.not_done_lead
  } ${detail}`
  const banner = said && (
    <div className="mapbanner" role="alert">
      <span className="rtl-safe">{said}</span>
      <button type="button" aria-label={T.dismiss} onClick={sync.dismiss}>
        ✕
      </button>
    </div>
  )
  // An acknowledgment, in the neutral tone: it is not a problem, and it must
  // outlive the re-derive it is about (see `MapSync.flash`).
  const flash = sync.flash && (
    <p className="mapflash rtl-safe" role="status">{sync.flash}</p>
  )
  // ⚠ The loading screen is still the answer for a FIRST load and for every
  // re-derive that changes which document this is. What it stopped being the
  // answer to is a per-cell gesture — see `MapSync.refreshing`.
  // ⚠ When the document is READY it is read from `sync`, never from `shown`.
  // `shown` is set in an effect, so it lags by one render — and that render
  // MOUNTS the editor with the previous document, which then pushes its own
  // reverse. Measured: `DELETE /map/floors/...` after a plain reload, which
  // is the exact failure `PlanScreen`'s module note exists about. `shown` is
  // only ever the answer while re-deriving, when it is what is on screen
  // already and re-keying it is precisely what must not happen.
  const live = sync.ready && sync.initial
    ? { gen: sync.generation, plan: sync.initial }
    : shown
  if (!live || (!sync.ready && !sync.refreshing)) {
    return <main className="mapstate">{banner}{flash}<p>{t.loading}</p></main>
  }
  const refreshing = !sync.ready
  return (
    <>
      {banner}
      {flash}
      {refreshing && <p className="mapflash rtl-safe" role="status">{t.loading}</p>}
      {/* ⚠ MOUNTED with its document. The editor must never exist before its
          data does — see `useMapSync`'s note and the storey this cost. `key`
          makes a reload a fresh mount rather than an adoption. */}
      <MapScreen
        key={live.gen}
        initialPlan={live.plan}
        refreshing={refreshing}
        initialSelection={selection.current}
        onSelectionChange={(s) => { selection.current = s }}
        onChange={sync.record}
        saved={sync.saved}
        onReload={sync.reload}
        site={{
          sites: sync.sites,
          siteId: sync.siteId,
          onSite: sync.chooseSite,
          // A default name, then rename it in place — the same gesture as a
          // new storey, and for the same reason: a prompt for a name is a
          // dialog in front of a thing you can see and edit.
          //
          // ⚠ The number steps past a name already taken. `sites.length + 1`
          // repeats one as soon as anything is removed — [Home, אתר 2], remove
          // Home, add — and two rows announcing one accessible name is the
          // collision CLAUDE.md records. The ORDER is the count, which makes
          // "the first site" mean the oldest rather than the alphabetically
          // first.
          onAddSite: () => sync.addSite(freeSiteName(T, sync.sites),
                                        sync.sites.length),
          onRenameSite: sync.renameSite,
          onRemoveSite: sync.removeSite,
          onUndoLastEdit: sync.undoLastEdit,
        }}
        shelves={{
          offTheMap: sync.shelvesOffTheMap,
          bind: sync.bindShelf,
          unbind: sync.unbindShelf,
          previewMerge: sync.previewMerge,
          merge: sync.mergeShelf,
        }}
      />
    </>
  )
}

/** `אתר 2`, or the first number after it that nothing is called. */
function freeSiteName(T: MapText, sites: { name: string }[]): string {
  const taken = new Set(sites.map((s) => s.name))
  for (let n = sites.length + 1; ; n += 1)
    if (!taken.has(T.site_n(n))) return T.site_n(n)
}

export default PlanScreen
