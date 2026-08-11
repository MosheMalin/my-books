/**
 * The images screen: the photograph is the entity, the shelf is a binding, and
 * the bytes never cross a tenant boundary.
 */
import { screen, within } from '@testing-library/react'
import { userEvent } from '@booksnap/ui/testing/user'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ImagesPage } from './ImagesPage'
import { renderApp } from '../test/harness'
import { bothServices, DEFAULT_WORLD } from '../test/servers'

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('ImagesPage', () => {
  /**
   * ⚠⚠ The owner's correction, made visible: *"rather than Shelf, the images
   * are images"*. A shelf today is an identity minted per photograph
   * (VISION §4.1a's recorded placeholder), so the column names the BINDING and
   * the row is the picture.
   */
  it('leads with the photograph and reports the shelf as a binding', async () => {
    bothServices()
    renderApp(<ImagesPage initialLibraryId={undefined} />)

    const table = await screen.findByRole('table')
    expect(within(table).getByText(/מתויקת ב|Filed at/)).toBeInTheDocument()
    // No column, anywhere, calls it a shelf.
    expect(within(table).queryByText(/^מדף$|^Shelf$/)).not.toBeInTheDocument()
  })

  /** ⚠ The engine figures come from the image side: `reads.capture_ids` for
   *  runs, `claims.capture_id` for findings. "1 run, 0 findings" is a real row
   *  and the one an operator debugging the reader is looking for. */
  it('shows what each run made of the image, tier by tier', async () => {
    bothServices()
    renderApp(<ImagesPage initialLibraryId={undefined} />)
    await screen.findByRole('table')

    expect(screen.getByText(/2 אוטומטי|2 auto/)).toBeInTheDocument()
  })

  it('narrows to one library through the server', async () => {
    const s = bothServices()
    renderApp(<ImagesPage initialLibraryId="lib-2" />)

    await screen.findByRole('table')
    expect(s.calls.some((c) => c.url.includes('/api/staff/v1/images')
                            && c.url.includes('library_id=lib-2'))).toBe(true)
    expect(screen.getAllByRole('row')).toHaveLength(2) // header + one image
  })

  /**
   * ⚠⚠ Metadata crosses tenants; photographs do not. The staff service serves
   * no bytes at all, so a preview is an ordinary product-API fetch — and for a
   * household the operator does not belong to there is simply no picture.
   */
  it('never asks the staff service for bytes, and previews only its own', async () => {
    bothServices()
    const user = userEvent.setup()
    renderApp(<ImagesPage initialLibraryId={undefined} />)
    await screen.findByRole('table')

    // lib-1 is in `mine`.
    await user.click(screen.getAllByRole('button', { name: /2026/ })[0]!)
    const panel = await screen.findByRole('dialog')
    const img = within(panel).getByRole('img')
    expect(img).toHaveAttribute('src', expect.stringContaining('/api/v1/images/'))
    expect(img.getAttribute('src')).not.toContain('/api/staff/')
  })

  it('offers no preview for a household the operator is not a member of', async () => {
    bothServices({ images: [DEFAULT_WORLD.images[1]!] })  // lib-2, not in `mine`
    const user = userEvent.setup()
    renderApp(<ImagesPage initialLibraryId={undefined} />)
    await screen.findByRole('table')

    await user.click(screen.getAllByRole('button', { name: /2026/ })[0]!)
    const panel = await screen.findByRole('dialog')
    expect(within(panel).queryByRole('img')).not.toBeInTheDocument()
  })

  /**
   * ⚠⚠ Three states, not two. With no blob tree in sight every row reports
   * `present: false` — which means "we did not look", not "they are gone". A
   * console that conflated them would announce that every photograph in every
   * tenant was lost, and hide a real loss in the noise.
   */
  it('says the disk is not visible rather than crying that every image is lost', async () => {
    const s = bothServices()
    s.route('GET /api/staff/v1/images', () => ({
      items: DEFAULT_WORLD.images.map((i) => ({ ...i, present: false, bytes: 0 })),
      total: 2, offset: 0, limit: 25, blobs_visible: false,
    }))
    renderApp(<ImagesPage initialLibraryId={undefined} />)

    expect(await screen.findByText(/לא בדקנו|did not look/)).toBeInTheDocument()
    expect(screen.queryByText(/^הקבצים חסרים$|^bytes gone$/)).not.toBeInTheDocument()
  })

  /** …and when the disk IS visible, a missing blob is a real finding and says
   *  so, because it is a photograph the household can no longer see. */
  it('flags a genuinely missing blob when the disk is visible', async () => {
    bothServices()
    renderApp(<ImagesPage initialLibraryId={undefined} />)
    await screen.findByRole('table')

    // cap-2 in the default world has present: false.
    expect(screen.getByText(/הקבצים חסרים|bytes gone/)).toBeInTheDocument()
  })
})
