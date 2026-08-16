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
import type { MapSource } from './useMapSync'
import { useMapSync } from './useMapSync'
import { getMap, listShelves, mapDelete, mapPatch, mapPost } from '../api/client'

export function PlanScreen() {
  const { t } = useI18n()

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
     * A drawing needs a site AND a storey to hang off, and until P6.3.1 there
     * is exactly one of each. Created on first use rather than at sign-up: a
     * household that never draws anything should not carry a "Home" nobody
     * typed.
     *
     * ⚠ **The floor is not optional.** Without it `toPlan` synthesises one,
     * and the first room drawn is refused with a 404 for a floor id that
     * exists only in the document — measured by opening the editor.
     *
     * Reads before it writes. Two tabs opening an undrawn library at the same
     * instant could still mint two sites; the picker in P6.3.1 is where an
     * extra one gets deleted, and the loader picks the first deterministically
     * meanwhile.
     */
    ensureHome: async () => {
      const map = await getMap()
      const site = map.sites[0]
        ?? await mapPost('/map/sites', { name: t.plan_site_default })
      const floor = map.floors.find((f) => f.site_id === site.id)
        ?? await mapPost('/map/floors',
                         { site_id: site.id, name: t.plan_floor_default })
      return { siteId: site.id as string, floorId: floor.id as string }
    },
  }), [t.plan_site_default])

  const sync = useMapSync(source)

  if (sync.error) {
    return (
      <main className="screen">
        <p role="alert">{sync.error}</p>
        <button type="button" onClick={sync.reload}>{t.retry}</button>
      </main>
    )
  }
  /* The server's own words. A refusal here is a rule the owner met — "a
     bookcase holds at most 400 shelves", "3 rooms still on this floor" — and
     paraphrasing it would lose the count that makes it actionable.

     ⚠ Rendered ABOVE the loading branch, because a refusal is exactly when
     the editor is re-deriving: hiding the reason while the screen it refers
     to is rebuilt would make the one informative message the briefest thing
     on screen. */
  const banner = sync.refusal && (
    <p className="mapbanner" role="alert" onClick={sync.dismiss}>
      {sync.refusal.detail}
    </p>
  )
  if (!sync.ready || !sync.initial) {
    return <main className="screen">{banner}<p>{t.loading}</p></main>
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
      />
    </>
  )
}

export default PlanScreen
