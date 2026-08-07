import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { App, type Overview } from './App'
import type { Meta } from './api/client'

/**
 * The client test ring (D3). Same standard as the Python rings: test what
 * encodes a DECISION, not layout and not DTO plumbing.
 *
 * The decision under test here is that the page shows the library the SERVER
 * resolved — not a hardcoded name — and that a failed call produces a visible
 * error rather than a blank page. Those are the two behaviours P1.6's screens
 * inherit.
 */
const meta: Meta = {
  app: 'booksnap',
  version: '0.1.0',
  api_version: 'v1',
  library: { id: 'lib-test', label: 'ספרייה לבדיקה' },
}
const overview: Overview = { meta, bookCount: 251 }

describe('App', () => {
  it('renders the library resolved by the server', async () => {
    render(<App load={async () => overview} />)
    expect(await screen.findByText('ספרייה לבדיקה')).toBeInTheDocument()
    expect(screen.getByText(/booksnap 0\.1\.0 · API v1/)).toBeInTheDocument()
  })

  it('shows the book count the API reported, not a hardcoded one', async () => {
    render(<App load={async () => overview} />)
    expect(await screen.findByText('251 ספרים')).toBeInTheDocument()
  })

  it('shows an error instead of a blank page when the API is down', async () => {
    render(
      <App
        load={async () => {
          throw new Error('GET /api/v1/meta failed: 503')
        }}
      />,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('503')
  })
})
