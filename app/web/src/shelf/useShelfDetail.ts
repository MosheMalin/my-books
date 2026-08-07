/**
 * The shelf-detail screen's own state (P2.8, UI_PLAN §3 level 3) — declared
 * depth, the staleness line, the books at the SELECTED depth, and that
 * depth's read history.
 *
 * Hand-rolled, same call as `lib/books.tsx` and `capture/useCapture.ts`
 * (D3/CLAUDE.md): this is one screen's state, not a cache several screens
 * share.
 *
 * **Depth is a client-side selection, not part of the URL.** `#/map/<id>`
 * names the SHELF; which row is showing is local state that resets to 1 on
 * every fresh mount, same as the Books tab's filters are not encoded in the
 * hash. Nothing in UI_PLAN asks for a deep link straight to one row, and
 * inventing one would be scope this item does not need.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  addShelfDepth,
  getShelfBooks,
  getShelfOverview,
  listShelfCaptures,
  listReadHistory,
  type Book,
  type DepthStatusDTO,
  type ReadSummaryDTO,
  type Shelf,
} from '../api/client'

export type ShelfState =
  | { kind: 'loading' }
  | { kind: 'missing' }
  | { kind: 'ready'; shelf: Shelf; depths: DepthStatusDTO[]; lastReadAt: string | null }

export function useShelfDetail(shelfId: string) {
  const [state, setState] = useState<ShelfState>({ kind: 'loading' })
  const [depth, setDepth] = useState(1)
  const [photoImageId, setPhotoImageId] = useState<string | null>(null)
  const [books, setBooks] = useState<Book[]>([])
  const [booksLoading, setBooksLoading] = useState(true)
  const [booksError, setBooksError] = useState<string | null>(null)
  const [history, setHistory] = useState<ReadSummaryDTO[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [addingRow, setAddingRow] = useState(false)

  // Reset to depth 1 whenever the shelf itself changes (opening a different
  // shelf from a stale `depth` would silently ask for a row this one may not
  // even have).
  const shelfRef = useRef(shelfId)
  useEffect(() => {
    if (shelfRef.current !== shelfId) {
      shelfRef.current = shelfId
      setDepth(1)
    }
  }, [shelfId])

  const loadOverview = useCallback(async () => {
    setState({ kind: 'loading' })
    try {
      const o = await getShelfOverview(shelfId)
      setState({ kind: 'ready', shelf: o.shelf, depths: o.depths,
                lastReadAt: o.last_read_at ?? null })
    } catch {
      setState({ kind: 'missing' })
    }
  }, [shelfId])

  useEffect(() => {
    void loadOverview()
  }, [loadOverview])

  useEffect(() => {
    let live = true
    setBooksLoading(true)
    setBooksError(null)
    Promise.all([
      getShelfBooks(shelfId, depth),
      listShelfCaptures(shelfId, depth),
    ])
      .then(([b, caps]) => {
        if (!live) return
        setBooks(b)
        // The FIRST photo at this depth (order 0) is the shelf's identity
        // here (UI_PLAN §7 decision 3: "the shelf photo is the shelf's
        // identity") — later captures of the same row exist (§5.3) but the
        // leading one is the representative frame.
        setPhotoImageId(caps[0]?.image_id ?? null)
      })
      .catch((err: unknown) => {
        if (live) setBooksError(String(err))
      })
      .finally(() => {
        if (live) setBooksLoading(false)
      })
    return () => {
      live = false
    }
  }, [shelfId, depth])

  useEffect(() => {
    let live = true
    setHistoryLoading(true)
    listReadHistory(shelfId, depth)
      .then((h) => live && setHistory(h))
      .catch(() => live && setHistory([]))
      .finally(() => live && setHistoryLoading(false))
    return () => {
      live = false
    }
  }, [shelfId, depth])

  const addRowBehind = useCallback(async () => {
    if (addingRow) return
    setAddingRow(true)
    try {
      await addShelfDepth(shelfId)
      await loadOverview()
    } finally {
      setAddingRow(false)
    }
  }, [shelfId, addingRow, loadOverview])

  return {
    state, depth, setDepth, photoImageId, books, booksLoading, booksError,
    history, historyLoading, addRowBehind, addingRow,
  }
}

export type ShelfDetailApi = ReturnType<typeof useShelfDetail>
