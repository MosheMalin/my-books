import { useEffect, useState } from 'react'
import { getMeta, listBooks, type Meta } from './api/client'
import './App.css'

/** What the placeholder page needs: who we are, and how many books exist. */
export interface Overview {
  meta: Meta
  bookCount: number
}

const loadOverview = async (): Promise<Overview> => {
  const [meta, page] = await Promise.all([
    getMeta(),
    // limit=1: the count comes from `total`, so the page itself is waste.
    listBooks({ query: { limit: 1 } }),
  ])
  return { meta, bookCount: page.total }
}

type State =
  | { status: 'loading' }
  | { status: 'ready'; overview: Overview }
  | { status: 'error'; message: string }

export interface AppProps {
  /** Injected in tests. Production uses the real typed client. */
  load?: () => Promise<Overview>
}

/**
 * P1.0's one page. It renders the library the server resolved for this
 * caller — deliberately the tenant, not a greeting: the client is
 * tenant-aware from the first screen (§1.3), so the library switcher of P3.1
 * has somewhere to switch.
 *
 * Loading and error are explicit states rather than a blank page, because
 * every screen from here on talks to a real API and "it showed nothing" is
 * the failure mode a mock-backed UI never teaches you to handle.
 */
export function App({ load = loadOverview }: AppProps) {
  const [state, setState] = useState<State>({ status: 'loading' })

  useEffect(() => {
    let live = true
    load()
      .then((overview) => live && setState({ status: 'ready', overview }))
      .catch((err: unknown) =>
        live &&
        setState({
          status: 'error',
          message: err instanceof Error ? err.message : String(err),
        }),
      )
    return () => {
      live = false
    }
  }, [load])

  return (
    <main className="app">
      <h1>booksnap</h1>
      {state.status === 'loading' && <p role="status">טוען…</p>}
      {state.status === 'error' && (
        <p role="alert" className="error">
          אין חיבור לשרת — {state.message}
        </p>
      )}
      {state.status === 'ready' && (
        <section aria-label="library">
          <p className="library">{state.overview.meta.library.label}</p>
          {/* Placeholder, replaced wholesale by the Books tab in P1.6
              (UI_PLAN §2). It is here so P1.4's endpoint is verifiable in a
              browser and not only under TestClient. */}
          <p className="count">{state.overview.bookCount} ספרים</p>
          <p className="build">
            {state.overview.meta.app} {state.overview.meta.version} · API{' '}
            {state.overview.meta.api_version}
          </p>
        </section>
      )}
    </main>
  )
}
