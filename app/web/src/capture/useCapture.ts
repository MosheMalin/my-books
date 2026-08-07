/**
 * The Capture tab's own state — intake queue, shelf assignment, and the
 * runs it starts (P2.7, UI_PLAN §4).
 *
 * Hand-rolled, same call as `lib/books.tsx` (D3/CLAUDE.md): this is one
 * screen's state, not a cache several screens share, so a query library would
 * be pure API surface here too.
 *
 * **The intake queue is SESSION state, not a server resource.** Each dropped
 * photo becomes a REAL `Image` + `Capture` on the server the moment it
 * uploads — P2.2/P2.3 already made that durable — but there is no "list
 * photos waiting to be read" endpoint (P2.1-P2.6 never built one; a shelf's
 * captures are only listable BY shelf, `GET /shelves/{id}/captures`, and
 * nothing indexes "every capture with no read yet" across the library). So
 * a page refresh loses this queue's ordering/selection, though nothing it
 * already uploaded is lost — the shelf and its captures are still there,
 * just not re-listed here. Building that index is a P2.8/shelf-view concern
 * (browsing a shelf's own capture history), not this tab's.
 *
 * **A read is scoped to exactly one (shelf, depth)** (`app.domain.read.new_read`).
 * Selecting photos here is a per-PHOTO convenience for the human, but
 * `POST /shelves/{id}/reads` always reads every capture filed at that
 * shelf+depth, selected or not (§5.7 #1 — a read cannot be partial within
 * its own row). `start()` below turns the selection into the DISTINCT set of
 * (shelf, depth) pairs it touches and starts one read per pair — checking
 * one photo of a pair queues its siblings too, which is the honest behaviour
 * given the domain's own granularity, not a shortcut this file invented.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  addShelfDepth,
  applyDiff,
  createCapture,
  getRead,
  listShelves,
  patchCapture,
  startRead,
  stopRead,
  uploadImage,
  type DiffDTO,
  type Shelf,
} from '../api/client'

export type Mode = 'spines' | 'fullpage' | 'llmpage'
export type ReadStage = 'unread' | 'queued' | 'done'

export interface IntakeItem {
  localId: string
  file: File
  previewUrl: string
  filename: string
  status: 'uploading' | 'ready' | 'error'
  error?: string | undefined
  imageKey?: string
  captureId?: string
  shelfId?: string
  depth: number
  readStage: ReadStage
}

export interface RunState {
  /** `${shelfId}:${depth}` — one row's read, and the review panel that grows
   *  from it. */
  key: string
  shelfId: string
  depth: number
  readId: string
  status: 'running' | 'done' | 'stopped' | 'failed'
  progress: Record<string, unknown> | null
  error: string | null
  diff: DiffDTO | null
  diffLoading: boolean
  diffError: string | null
  /** Claim ids with an answer in flight — disables their row's buttons so a
   *  double click cannot fire the same answer twice while the first is still
   *  on the wire (harmless per `answerClaim`'s idempotency note, but a
   *  button that visibly does nothing on a second click is a bad look). */
  answeringClaimIds: Set<string>
  answerError: string | null
}

function localId(): string {
  return `f${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

export function useCapture() {
  const [items, setItems] = useState<IntakeItem[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [shelves, setShelves] = useState<Shelf[]>([])
  const [shelvesLoading, setShelvesLoading] = useState(true)
  const [mode, setMode] = useState<Mode>('spines')
  const [runs, setRuns] = useState<RunState[]>([])

  const itemsRef = useRef(items)
  useEffect(() => {
    itemsRef.current = items
  }, [items])
  const runsRef = useRef(runs)
  useEffect(() => {
    runsRef.current = runs
  }, [runs])

  // Preview URLs are local object URLs (createObjectURL) — released once,
  // on unmount, from whatever the queue holds at that moment.
  useEffect(
    () => () => itemsRef.current.forEach((it) => URL.revokeObjectURL(it.previewUrl)),
    [],
  )

  const refreshShelves = useCallback(async () => {
    setShelvesLoading(true)
    try {
      setShelves(await listShelves())
    } catch {
      // The select just offers fewer options; a capture's own auto-created
      // shelf still works even if the list failed to load.
    } finally {
      setShelvesLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshShelves()
  }, [refreshShelves])

  const uploadOne = useCallback((id: string, file: File) => {
    void (async () => {
      try {
        const image = await uploadImage(file, file.name)
        const bound = await createCapture({ image_id: image.key, depth: 1 })
        setItems((s) => s.map((it) => (it.localId === id
          ? {
              ...it, status: 'ready' as const, error: undefined,
              imageKey: image.key, captureId: bound.capture.id,
              shelfId: bound.shelf.id, depth: bound.capture.depth,
            }
          : it)))
        setShelves((s) => (s.some((sh) => sh.id === bound.shelf.id)
          ? s.map((sh) => (sh.id === bound.shelf.id ? bound.shelf : sh))
          : [...s, bound.shelf]))
        // Freshly uploaded photos start selected — the common case is "read
        // what I just dropped", and an unchecked photo silently left out of
        // a run is a worse default than one the user has to opt OUT of.
        setSelected((s) => new Set(s).add(id))
      } catch (err) {
        setItems((s) => s.map((it) => (it.localId === id
          ? { ...it, status: 'error' as const, error: String(err) }
          : it)))
      }
    })()
  }, [])

  const addFiles = useCallback((files: File[]) => {
    for (const file of files) {
      const id = localId()
      setItems((s) => [...s, {
        localId: id, file, previewUrl: URL.createObjectURL(file),
        filename: file.name, status: 'uploading', depth: 1,
        readStage: 'unread',
      }])
      uploadOne(id, file)
    }
  }, [uploadOne])

  const retryItem = useCallback((id: string) => {
    const item = itemsRef.current.find((it) => it.localId === id)
    if (!item) return
    setItems((s) => s.map((it) => (it.localId === id
      ? { ...it, status: 'uploading' as const, error: undefined } : it)))
    uploadOne(id, item.file)
  }, [uploadOne])

  const assignShelf = useCallback(async (id: string, shelfId: string) => {
    const item = itemsRef.current.find((it) => it.localId === id)
    if (!item?.captureId) return
    try {
      // Depth reset to 1 explicitly: the target shelf may not have declared
      // as many rows as the one this photo is leaving, and the server
      // refuses an undeclared depth with a 409 (§5.7) rather than clamping —
      // 1 always exists.
      const bound = await patchCapture(item.captureId, { shelf_id: shelfId, depth: 1 })
      setItems((s) => s.map((it) => (it.localId === id
        ? { ...it, shelfId: bound.capture.shelf_id, depth: bound.capture.depth }
        : it)))
    } catch (err) {
      setItems((s) => s.map((it) => (it.localId === id
        ? { ...it, error: String(err) } : it)))
    }
  }, [])

  const assignDepth = useCallback(async (id: string, depth: number) => {
    const item = itemsRef.current.find((it) => it.localId === id)
    if (!item?.captureId) return
    try {
      const bound = await patchCapture(item.captureId, { depth })
      setItems((s) => s.map((it) => (it.localId === id
        ? { ...it, depth: bound.capture.depth } : it)))
    } catch (err) {
      setItems((s) => s.map((it) => (it.localId === id
        ? { ...it, error: String(err) } : it)))
    }
  }, [])

  /** *"Add a row behind this one"* (§5.7) — surfaced from the intake row even
   *  at `depth_count` 1, because most owners never learn depth exists unless
   *  it is offered before they need it. */
  const addRowBehind = useCallback(async (shelfId: string) => {
    const grown = await addShelfDepth(shelfId)
    setShelves((s) => s.map((sh) => (sh.id === shelfId ? grown : sh)))
    return grown
  }, [])

  const toggleSelect = useCallback((id: string) => {
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])
  const selectAll = useCallback(() => {
    setSelected(new Set(itemsRef.current
      .filter((it) => it.status === 'ready').map((it) => it.localId)))
  }, [])
  const selectNone = useCallback(() => setSelected(new Set()), [])
  const selectUnread = useCallback(() => {
    setSelected(new Set(itemsRef.current
      .filter((it) => it.status === 'ready' && it.readStage === 'unread')
      .map((it) => it.localId)))
  }, [])

  /**
   * Load a settled read's diff AND commit it, in one call.
   *
   * `POST .../apply` (not `GET .../diff`) is what actually runs here, with
   * an EMPTY answers list. That looks like an odd way to "load" something,
   * but it is exactly right: `reconcile()` already decided the `added` /
   * `corrected` / `unchanged` buckets with no human input needed — apply
   * persists those UNCONDITIONALLY regardless of `answers` — so there is
   * nothing to wait for a click on. Only `needs_decision` rows are real
   * questions, and they come back in the SAME response, still open, for
   * `answerClaim` below to resolve inline.
   *
   * Calling this (and `answerClaim`) more than once for the same read is
   * SAFE: `Provenance.sighting` (`run_id`, `spine_id`) makes `observe()`
   * idempotent (`app/domain/book.py`), and a claim already resolved to a
   * `Book` reconciles as `unchanged` on the next call rather than being
   * re-added under a fresh id. That is what makes committing automatically
   * here — and re-answering safe against a flaky network — sound instead of
   * a duplicate-data risk.
   */
  const commitDiff = useCallback(async (key: string, shelfId: string, readId: string) => {
    setRuns((rs) => rs.map((r) => (r.key === key
      ? { ...r, diffLoading: true, diffError: null } : r)))
    try {
      const diff = await applyDiff(shelfId, readId, { answers: [] })
      setRuns((rs) => rs.map((r) => (r.key === key
        ? { ...r, diff, diffLoading: false } : r)))
    } catch (err) {
      setRuns((rs) => rs.map((r) => (r.key === key
        ? { ...r, diffLoading: false, diffError: String(err) } : r)))
    }
  }, [])

  /** The distinct (shelf, depth) pairs the current selection touches —
   *  see the module docstring for why this is the real unit of a run. */
  const pendingGroups = useCallback(() => {
    const byKey = new Map<string, { shelfId: string; depth: number }>()
    for (const it of items) {
      if (!selected.has(it.localId) || it.status !== 'ready' || !it.shelfId) continue
      const key = `${it.shelfId}:${it.depth}`
      if (!byKey.has(key)) byKey.set(key, { shelfId: it.shelfId, depth: it.depth })
    }
    return [...byKey.entries()]
  }, [items, selected])

  const start = useCallback(async () => {
    const groups = pendingGroups()
    for (const [key, g] of groups) {
      try {
        const read = await startRead(g.shelfId, { depth: g.depth, mode })
        // Read the STATUS the server actually reports rather than assuming
        // 'running': a real read is async by nature, but a tiny/stub engine
        // (tests; conceivably a trivial future one) can settle inside the
        // request itself, and treating that as "running" would flash a
        // spinner the poll loop would never resolve (it only watches runs
        // already marked running).
        const status = read.status as RunState['status']
        setRuns((rs) => [
          ...rs.filter((r) => r.key !== key),
          {
            key, shelfId: g.shelfId, depth: g.depth, readId: read.id, status,
            progress: (read.progress ?? null) as Record<string, unknown> | null,
            error: read.error ?? null, diff: null, diffLoading: false,
            diffError: null, answeringClaimIds: new Set(), answerError: null,
          },
        ])
        setItems((s) => s.map((it) => (it.shelfId === g.shelfId && it.depth === g.depth
          ? { ...it, readStage: status === 'running' ? 'queued' as const : 'done' as const }
          : it)))
        if (status !== 'running') void commitDiff(key, g.shelfId, read.id)
      } catch (err) {
        setRuns((rs) => [
          ...rs.filter((r) => r.key !== key),
          {
            key, shelfId: g.shelfId, depth: g.depth, readId: '',
            status: 'failed', progress: null, error: String(err), diff: null,
            diffLoading: false, diffError: null, answeringClaimIds: new Set(),
            answerError: null,
          },
        ])
      }
    }
  }, [pendingGroups, mode, commitDiff])

  const stopRun = useCallback(async (key: string) => {
    const run = runsRef.current.find((r) => r.key === key)
    if (!run || run.status !== 'running') return
    try {
      await stopRead(run.shelfId, run.readId)
    } catch {
      // The next poll reflects reality either way (§ app.domain.read: stop
      // is cooperative, never immediate).
    }
  }, [])

  // Poll every running read until it settles, then load its diff. Re-arms
  // whenever `runs` changes — cheap at this scale (a handful of reads, not a
  // list) and keeps the closure's view of `runs` current without a second
  // ref-vs-state reconciliation.
  useEffect(() => {
    const running = runs.filter((r) => r.status === 'running')
    if (running.length === 0) return
    const timer = setInterval(() => {
      running.forEach((r) => {
        void getRead(r.shelfId, r.readId).then((read) => {
          setRuns((rs) => rs.map((x) => (x.key === r.key
            ? {
                ...x, status: read.status as RunState['status'],
                progress: (read.progress ?? null) as Record<string, unknown> | null,
                error: read.error ?? null,
              }
            : x)))
          if (read.status !== 'running') {
            setItems((s) => s.map((it) => (it.shelfId === r.shelfId && it.depth === r.depth
              ? { ...it, readStage: 'done' as const } : it)))
            void commitDiff(r.key, r.shelfId, r.readId)
          }
        }).catch(() => undefined)
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [runs, commitDiff])

  /**
   * One human answer to one still-open claim — confirm/reject a REVIEW-tier
   * new-book claim, or the §5.4 three-way prompt (already listed / another
   * copy / wrong book) for an ambiguous-location one. Fires immediately, not
   * staged: see `commitDiff`'s docstring for why a real network call per
   * click is safe here. Not answering a row at all is a real, supported
   * choice — §5.4: an unanswered ambiguous-location claim lands in the
   * Books tab's "duplicates to resolve" queue instead of being lost, and an
   * unanswered review-tier claim simply stays open in this diff.
   */
  const answerClaim = useCallback(
    async (key: string, claimId: string, kind: string, copyId?: string | null) => {
      const run = runsRef.current.find((r) => r.key === key)
      if (!run) return
      setRuns((rs) => rs.map((r) => (r.key === key
        ? {
            ...r, answerError: null,
            answeringClaimIds: new Set(r.answeringClaimIds).add(claimId),
          }
        : r)))
      try {
        const diff = await applyDiff(run.shelfId, run.readId, {
          answers: [{ claim_id: claimId, kind, copy_id: copyId ?? null }],
        })
        setRuns((rs) => rs.map((r) => {
          if (r.key !== key) return r
          const answeringClaimIds = new Set(r.answeringClaimIds)
          answeringClaimIds.delete(claimId)
          return { ...r, diff, answeringClaimIds }
        }))
      } catch (err) {
        setRuns((rs) => rs.map((r) => {
          if (r.key !== key) return r
          const answeringClaimIds = new Set(r.answeringClaimIds)
          answeringClaimIds.delete(claimId)
          return { ...r, answeringClaimIds, answerError: String(err) }
        }))
      }
    },
    [],
  )

  return {
    items, selected, shelves, shelvesLoading, mode, runs,
    setMode, addFiles, retryItem, assignShelf, assignDepth, addRowBehind,
    toggleSelect, selectAll, selectNone, selectUnread,
    pendingGroupCount: pendingGroups().length,
    selectedReadyCount: items.filter(
      (it) => selected.has(it.localId) && it.status === 'ready',
    ).length,
    start, stopRun, answerClaim,
    running: runs.some((r) => r.status === 'running'),
  }
}

export type CaptureApi = ReturnType<typeof useCapture>
