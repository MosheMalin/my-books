/**
 * The map editor, wired to this library's drawing.
 *
 * A thin wrapper, deliberately: everything below it came from
 * `planning/map-lab` and must keep working the way nine passes made it work.
 * What is here is the data source and the states an editor over a network has
 * that an editor over `localStorage` did not — loading, a failed load, and a
 * refusal the server gave.
 */
import { useMemo } from 'react'

import { useI18n } from '../lib/i18n'

import MapScreen from './MapScreen'
import { mapText } from './text'
import type { MapSource } from './useMapSync'
import { useMapSync } from './useMapSync'
import { getMap, listShelves, mapDelete, mapPatch, mapPost } from '../api/client'

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
    api: {
      post: (path, body) => mapPost(path, body),
      patch: (path, body) => mapPatch(path, body),
      del: (path) => mapDelete(path),
    },
    /**
     * A drawing needs a site AND a storey to hang off. This makes the FIRST
     * of each, on first use rather than at sign-up: a household that never
     * draws anything should not carry a "Home" nobody typed. Every one after
     * that comes from the picker (P6.3.1).
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
        ?? await mapPost('/map/sites', { name: t.plan_site_default })
      const floor = map.floors.find((f) => f.site_id === site.id)
        ?? await mapPost('/map/floors',
                         { site_id: site.id, name: t.plan_floor_default })
      return { siteId: site.id as string, floorId: floor.id as string }
    },
  }), [t.plan_site_default, t.plan_floor_default, library])

  const sync = useMapSync(source, T)

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
  const said = sync.notice && (sync.notice.kind === 'refused'
    ? `${T.refused_lead} ${sync.notice.detail}`
    : `${T.not_saved_yet} ${sync.notice.detail}`)
  const banner = said && (
    <div className="mapbanner" role="alert">
      <span className="rtl-safe">{said}</span>
      <button type="button" aria-label={T.dismiss} onClick={sync.dismiss}>
        ✕
      </button>
    </div>
  )
  if (!sync.ready || !sync.initial) {
    return <main className="mapstate">{banner}<p>{t.loading}</p></main>
  }
  return (
    <>
      {banner}
      {/* ⚠ MOUNTED with its document. The editor must never exist before its
          data does — see `useMapSync`'s note and the storey this cost. `key`
          makes a reload a fresh mount rather than an adoption. */}
      <MapScreen
        key={sync.generation}
        initialPlan={sync.initial}
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
          onAddSite: () => sync.addSite(T.site_n(sync.sites.length + 1)),
          onRenameSite: sync.renameSite,
          onRemoveSite: sync.removeSite,
        }}
      />
    </>
  )
}

export default PlanScreen
