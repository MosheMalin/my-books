/**
 * The Capture tab's own state — intake queue, shelf assignment, and the
 * runs it starts (P2.7, UI_PLAN §4).
 *
 * Hand-rolled, same call as `lib/books.tsx` (D3/CLAUDE.md): this is one
 * screen's state, not a cache several screens share, so a query library would
 * be pure API surface here too.
 *
 * **The intake queue is REBUILT from the server on mount** (P2.9 — fixing the
 * "background the tab / refresh mid-read and everything vanishes" bug: the
 * photos and the read were always durable server-side, P2.2/P2.3/P2.4 already
 * made sure of that; only this tab's OWN state forgot them). There is still
 * no dedicated "list photos waiting to be read" endpoint — a personal
 * library has tens of shelves (`ShelfStore.list_shelves`'s own docstring), so
 * `hydrate()` below just calls the existing per-shelf endpoints
 * (`GET /shelves`, then `GET /shelves/{id}/captures` and
 * `GET /shelves/{id}/reads` per shelf, concurrently) rather than adding a new
 * aggregate index for a call count that is a few dozen requests, once, on
 * mount or on returning to the tab — not the N+1-on-every-render shape that
 * would justify one. If the shelf count ever stops being "tens" this is the
 * place to add a purpose-built endpoint.
 *
 * Deliberately NOT rebuilt: the review panel of an already-SETTLED read. A
 * running read is re-attached (below) because there is real work to resume
 * watching; a finished one already did everything it was going to do — the
 * books it changed are in the library (server-side apply, P2.9's other half —
 * see `app/api/routers/reads.py`), and re-opening every past read's diff on
 * every tab visit forever would be clutter, not state recovery.
 *
 * That is NOT the same as having no route back to it — which is exactly the
 * bug §12.2 #10 named. A settled read is reached ON PURPOSE, by opening the
 * photo: `openImage` below, `useImageWorkspace` for the state, and
 * `ImageWorkspace` for the screen (P2.10). The photo is the durable object;
 * this hook only owns the queue and the reads it STARTS.
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
  applyDiff,
  createCapture,
  getRead,
  listShelfCaptures,
  listShelves,
  listReadHistory,
  patchCapture,
  startRead,
  stopRead,
  uploadImage,
  type CaptureDTO,
  type DiffDTO,
  type ReadSummaryDTO,
  type Shelf,
} from '../api/client'
import { approveAllPending, performFindingOp, type FindingOp } from './findingOps'

export type Mode = 'spines' | 'fullpage' | 'llmpage'
export type ReadStage = 'unread' | 'queued' | 'done'

export interface IntakeItem {
  localId: string
  /** `null` for an item rebuilt from the server on hydrate (see the module
   *  docstring) — its bytes already left this browser, possibly days ago, so
   *  there is nothing to re-POST. Only ever read by `retryItem`, and a
   *  hydrated item is never in `status: 'error'`, so that path never runs. */
  file: File | null
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
  // llmpage, not spines (owner, 2026-08-08). The measured gap is not close:
  // the Tesseract path is ~10s/spine and tops out around 76% title-correct,
  // and CLAUDE.md already records llmpage as the engine's own default. The
  // project's deterministic-first rule is about not paying an LLM for work
  // cheap code can do — it was never an argument for shipping the worse
  // reader as the one everybody meets first. Cost is stated on the control.
  const [mode, setMode] = useState<Mode>('llmpage')
  const [runs, setRuns] = useState<RunState[]>([])
  // Which photo's workspace is open (P2.10). Local id, not capture id — the
  // intake row is what was clicked, and it may still be uploading.
  const [openImageId, setOpenImageId] = useState<string | null>(null)

  // Guards `hydrate()` against React 18 StrictMode's dev-only double-invoke
  // of mount effects (setup → cleanup → setup, same component instance) —
  // without it, two concurrent hydrations can each miss the other's
  // in-flight `setItems` and double up every rebuilt row.
  const hydratedRef = useRef(false)

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

  const refreshShelves = useCallback(async (): Promise<Shelf[]> => {
    setShelvesLoading(true)
    try {
      const fresh = await listShelves()
      setShelves(fresh)
      return fresh
    } catch {
      // The select just offers fewer options; a capture's own auto-created
      // shelf still works even if the list failed to load.
      return []
    } finally {
      setShelvesLoading(false)
    }
  }, [])

  /**
   * Rebuild the intake list and re-attach any in-flight read (P2.9, Fix B —
   * see the module docstring). Runs once on mount and again whenever the tab
   * becomes visible (the `visibilitychange` effect below) — the exact moment
   * a backgrounded phone browser comes back and needs to catch up on a read
   * it slept through.
   *
   * `known` guards against clobbering an upload the user is mid-way through
   * RIGHT NOW: a capture already present locally (by id) is left alone rather
   * than replaced by the server's copy of itself.
   */
  const hydrate = useCallback(async () => {
    const allShelves = await refreshShelves()
    if (allShelves.length === 0) return

    const perShelf = await Promise.all(allShelves.map(async (shelf) => {
      const [captures, reads] = await Promise.all([
        listShelfCaptures(shelf.id).catch(() => [] as CaptureDTO[]),
        listReadHistory(shelf.id).catch(() => [] as ReadSummaryDTO[]),
      ])
      return { shelf, captures, reads }
    }))

    // `list_reads` is already most-recent-first (`ReadStore.list_reads`'s
    // own contract), so the first one seen per (shelf, depth) is the latest.
    const latestByDepth = new Map<string, ReadSummaryDTO>()
    for (const { shelf, reads } of perShelf) {
      for (const r of reads) {
        const key = `${shelf.id}:${r.depth}`
        if (!latestByDepth.has(key)) latestByDepth.set(key, r)
      }
    }

    const known = new Set(
      itemsRef.current.map((it) => it.captureId).filter((id): id is string => !!id),
    )
    const rebuilt: { item: IntakeItem; capturedAt: string }[] = []
    for (const { shelf, captures } of perShelf) {
      for (const cap of captures) {
        // No `image_id` yet (P2.2's recorded gap) or already tracked locally
        // (an upload this session already produced this exact capture) —
        // either way, nothing to add.
        if (!cap.image_id || known.has(cap.id)) continue
        const latest = latestByDepth.get(`${shelf.id}:${cap.depth}`)
        const readStage: ReadStage =
          latest?.status === 'running' ? 'queued' : latest ? 'done' : 'unread'
        rebuilt.push({
          capturedAt: cap.captured_at ?? '',
          item: {
            localId: cap.id,
            file: null,
            previewUrl: `/api/v1/images/${encodeURIComponent(cap.image_id)}/thumb`,
            // The server has no original filename to give back (`CaptureDTO`
            // never stored one) — showing the real storage key beats
            // inventing a friendlier-looking name that isn't true.
            filename: cap.image_id,
            status: 'ready',
            imageKey: cap.image_id,
            captureId: cap.id,
            shelfId: cap.shelf_id,
            depth: cap.depth,
            readStage,
          },
        })
      }
    }
    // Oldest first, so a hydrated queue reads top-to-bottom the same way it
    // would have if the browser had never lost it.
    rebuilt.sort((a, b) => a.capturedAt.localeCompare(b.capturedAt))
    if (rebuilt.length > 0) {
      setItems((s) => [...s, ...rebuilt.map((r) => r.item)])
    }

    // In-flight reads are RE-ATTACHED, never restarted (P2.9's explicit
    // requirement) — the job is already running server-side; this only
    // resumes watching it, the same `RunState` `start()` itself would create.
    const running = [...latestByDepth.values()].filter((r) => r.status === 'running')
    if (running.length > 0) {
      setRuns((rs) => {
        const existingKeys = new Set(rs.map((r) => r.key))
        const additions = running
          .map((r) => ({ key: `${r.shelf_id}:${r.depth}`, r }))
          .filter(({ key }) => !existingKeys.has(key))
          .map(({ key, r }): RunState => ({
            key, shelfId: r.shelf_id, depth: r.depth, readId: r.id,
            status: 'running', progress: null, error: r.error ?? null,
            diff: null, diffLoading: false, diffError: null,
            answeringClaimIds: new Set(), answerError: null,
          }))
        return additions.length > 0 ? [...rs, ...additions] : rs
      })
    }
  }, [refreshShelves])

  useEffect(() => {
    if (hydratedRef.current) return
    hydratedRef.current = true
    void hydrate()
    // Mount only — `hydrate` itself is stable (its one dependency,
    // `refreshShelves`, has an empty dependency array), and re-running it on
    // every `items`/`runs` change would fight the very state it just set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
    // A hydrated item (`file: null`) is never `'error'` — nothing server-side
    // ever reaches this tab's intake list without an `image_id` already
    // saved — so this guard is defence in depth, not a real path.
    if (!item?.file) return
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
    // Starting a read is the one moment the LIVE panels matter more than any
    // photo's history, so an open workspace steps aside for them.
    setOpenImageId(null)
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

  /**
   * Poll every running read once, then load its diff once it settles. Reads
   * `runsRef` rather than closing over `runs` — that is what makes it safe to
   * call from BOTH the interval below AND the `visibilitychange` handler
   * without either one working from a stale list.
   */
  const pollRunning = useCallback(() => {
    const running = runsRef.current.filter((r) => r.status === 'running')
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
  }, [commitDiff])

  // Re-arms whenever `runs` changes — cheap at this scale (a handful of
  // reads, not a list).
  useEffect(() => {
    if (!runs.some((r) => r.status === 'running')) return
    const timer = setInterval(pollRunning, 1000)
    return () => clearInterval(timer)
  }, [runs, pollRunning])

  // Mobile browsers throttle or fully suspend a background tab's timers
  // (CLAUDE.md's own diagnosis of the bug this file exists to fix) — the
  // `setInterval` above may not have ticked in minutes by the time the owner
  // switches back. Polling immediately on `visibilitychange` is what makes
  // "switch app, come back" feel instant rather than "wait up to a second
  // for the next tick", which was never really the bug but is worth not
  // reintroducing either.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') pollRunning()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [pollRunning])

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

  /**
   * P2.10's loop on a LIVE run's findings — approve / fix details / remove /
   * undo, on the rows the read just produced. The identical four ops the
   * image workspace offers days later, through the identical
   * `performFindingOp`: "right after the read" and "a week later" are the
   * same act, which is the whole of §12.2 #10.
   */
  const findingOnRun = useCallback(
    async (key: string, claimId: string, op: FindingOp) => {
      const run = runsRef.current.find((r) => r.key === key)
      if (!run) return
      setRuns((rs) => rs.map((r) => (r.key === key
        ? {
            ...r, answerError: null,
            answeringClaimIds: new Set(r.answeringClaimIds).add(claimId),
          }
        : r)))
      try {
        const diff = await performFindingOp(op, run.shelfId, run.readId, claimId)
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

  /** "Approve all" on a LIVE run — the same bulk act the workspace offers,
   *  through the same `approveAllPending`. */
  const approveAllOnRun = useCallback(
    async (key: string, claimIds: readonly string[]) => {
      const run = runsRef.current.find((r) => r.key === key)
      if (!run || claimIds.length === 0) return
      setRuns((rs) => rs.map((r) => (r.key === key
        ? {
            ...r, answerError: null,
            answeringClaimIds: new Set(r.answeringClaimIds).add('_all'),
          }
        : r)))
      try {
        const diff = await approveAllPending(run.shelfId, run.readId, claimIds)
        setRuns((rs) => rs.map((r) => {
          if (r.key !== key) return r
          const answeringClaimIds = new Set(r.answeringClaimIds)
          answeringClaimIds.delete('_all')
          return { ...r, diff, answeringClaimIds }
        }))
      } catch (err) {
        setRuns((rs) => rs.map((r) => {
          if (r.key !== key) return r
          const answeringClaimIds = new Set(r.answeringClaimIds)
          answeringClaimIds.delete('_all')
          return { ...r, answeringClaimIds, answerError: String(err) }
        }))
      }
    },
    [],
  )

  const openImage = useCallback((id: string | null) => setOpenImageId(id), [])

  return {
    items, selected, shelves, shelvesLoading, mode, runs, openImageId,
    setMode, addFiles, retryItem, assignShelf, assignDepth,
    toggleSelect, selectAll, selectNone, selectUnread, openImage, findingOnRun,
    approveAllOnRun,
    pendingGroupCount: pendingGroups().length,
    selectedReadyCount: items.filter(
      (it) => selected.has(it.localId) && it.status === 'ready',
    ).length,
    start, stopRun, answerClaim,
    running: runs.some((r) => r.status === 'running'),
  }
}

export type CaptureApi = ReturnType<typeof useCapture>
