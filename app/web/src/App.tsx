import { useEffect, useState } from 'react'
import { getMeta, type Meta } from './api/client'
import './App.css'

type State =
  | { status: 'loading' }
  | { status: 'ready'; meta: Meta }
  | { status: 'error'; message: string }

export interface AppProps {
  /** Injected in tests. Production uses the real typed client. */
  load?: () => Promise<Meta>
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
export function App({ load = getMeta }: AppProps) {
  const [state, setState] = useState<State>({ status: 'loading' })

  useEffect(() => {
    let live = true
    load()
      .then((meta) => live && setState({ status: 'ready', meta }))
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
          <p className="library">{state.meta.library.label}</p>
          <p className="build">
            {state.meta.app} {state.meta.version} · API {state.meta.api_version}
          </p>
        </section>
      )}
    </main>
  )
}
