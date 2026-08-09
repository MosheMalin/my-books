/**
 * One photo's workspace state (P2.10, §12.2 #10): its runs, the run currently
 * open, and that run's findings.
 *
 * > *"The heart of this tab are the images and the analysis. In Books we see
 * > the list and act on books. In Map we arrange the physical aspects. But
 * > here, in Capture and Read, we focus on the images."* — owner, settling
 * > §12.2 #10
 *
 * So: **the image is the durable object, runs hang off the image, findings
 * hang off the run.** This hook is that hierarchy and nothing else. It is
 * separate from `useCapture` (which owns the intake queue and the reads it
 * STARTS) because it is a different question — *what did this photo find?* —
 * asked of state the server already has, and folding it in would have made
 * one hook own two unrelated lifecycles.
 *
 * **It never starts a read.** That is the behaviour §12.2 #10 is about: the
 * only visible action on a processed photo used to be *re-run*, which costs
 * money, costs time and invites re-deciding answered questions. Every call
 * below is a GET, or a write about a finding — never `POST .../reads`.
 *
 * The findings come from `GET .../diff`, recomputed live (`diff_for`'s own
 * contract), NOT from the archived `diff_summary` a history row shows. The
 * two answer different questions and P2.8 argues the distinction at length:
 * a history row must say what the read DID (a snapshot, or every `added`
 * repaints to `unchanged` the moment it is applied), while a workspace must
 * say what each finding IS NOW — because that is what the ✓/✎/✕ act on.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  addFindingByHand,
  applyDiff,
  getDiff,
  listCaptureReads,
  listAuthors,
  lookupFindings,
  type DiffDTO,
  type ReadSummaryDTO,
} from '../api/client'
import {
  approvableCount,
  approveAll as approveAllRemote,
  performFindingOp,
  type Approvable,
  type FindingOp,
} from './findingOps'

export interface ImageWorkspaceState {
  runs: ReadSummaryDTO[]
  runsLoading: boolean
  error: string | null
  openRunId: string | null
  diff: DiffDTO | null
  diffLoading: boolean
  /** Set while the open run is still `running` — its findings do not exist
   *  yet, and `GET .../diff` answers 409 rather than a half-diff. */
  runInFlight: boolean
  diffError: string | null
  busy: Set<string>
}

/**
 * Note what is NOT a parameter: the photo's shelf. Every write below goes to
 * the shelf the RUN was filed under (`run.shelf_id`), because a capture can
 * be re-bound after it was read (P2.2) and its old runs stay, correctly, on
 * the shelf they read. Taking the photo's CURRENT shelf would address a
 * finding to a shelf that read has nothing to do with.
 */
export function useImageWorkspace(captureId: string | null) {
  const [runs, setRuns] = useState<ReadSummaryDTO[]>([])
  const [runsLoading, setRunsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [openRunId, setOpenRunId] = useState<string | null>(null)
  const [diff, setDiff] = useState<DiffDTO | null>(null)
  const [diffLoading, setDiffLoading] = useState(false)
  const [diffError, setDiffError] = useState<string | null>(null)
  const [runInFlight, setRunInFlight] = useState(false)
  const [busy, setBusy] = useState<Set<string>>(new Set())

  // Which capture the in-flight responses belong to. Clicking through several
  // photos quickly would otherwise let a slow first response paint its
  // findings under a photo the owner has already moved on from — the same
  // race `lib/books.tsx` guards with a request id, and the same reason.
  const wantRef = useRef<string | null>(captureId)

  const openRun = useCallback(async (run: ReadSummaryDTO) => {
    setOpenRunId(run.id)
    setDiff(null)
    setDiffError(null)
    setRunInFlight(run.status === 'running')
    if (run.status === 'running') return
    const want = wantRef.current
    setDiffLoading(true)
    try {
      const fresh = await getDiff(run.shelf_id, run.id)
      if (wantRef.current !== want) return
      setDiff(fresh)
    } catch (err) {
      if (wantRef.current === want) setDiffError(String(err))
    } finally {
      if (wantRef.current === want) setDiffLoading(false)
    }
  }, [])

  useEffect(() => {
    wantRef.current = captureId
    setRuns([])
    setOpenRunId(null)
    setDiff(null)
    setDiffError(null)
    setError(null)
    if (!captureId) return
    const want = captureId
    setRunsLoading(true)
    void (async () => {
      try {
        const rows = await listCaptureReads(want)
        if (wantRef.current !== want) return
        setRuns(rows)
        // The newest run is the one the owner means — `list_reads_for_capture`
        // is most-recent-first, so it is simply the first. Opened
        // automatically because a workspace whose whole point is "see what
        // this photo found" should not need a second click to show it.
        if (rows.length > 0) void openRun(rows[0]!)
      } catch (err) {
        if (wantRef.current === want) setError(String(err))
      } finally {
        if (wantRef.current === want) setRunsLoading(false)
      }
    })()
  }, [captureId, openRun])

  const withBusy = useCallback(
    async (claimId: string, work: () => Promise<DiffDTO>) => {
      setBusy((s) => new Set(s).add(claimId))
      setDiffError(null)
      try {
        setDiff(await work())
      } catch (err) {
        setDiffError(String(err))
      } finally {
        setBusy((s) => {
          const next = new Set(s)
          next.delete(claimId)
          return next
        })
      }
    },
    [],
  )

  const run = runs.find((r) => r.id === openRunId)

  /** One human answer to one still-open claim — the SAME `POST .../apply`
   *  the live review panel sends, days later. A §5.4 question does not
   *  expire, and `apply_diff` is idempotent by `Provenance.sighting`
   *  (P2.9's finding), so answering here is neither a special case nor a
   *  duplicate-write risk. */
  const answer = useCallback(
    (claimId: string, kind: string, copyId?: string | null) => {
      if (!run) return
      void withBusy(claimId, () => applyDiff(run.shelf_id, run.id, {
        answers: [{ claim_id: claimId, kind, copy_id: copyId ?? null }],
      }))
    },
    [run, withBusy],
  )

  const finding = useCallback((claimId: string, op: FindingOp) => {
    if (!run) return
    void withBusy(claimId, () =>
      performFindingOp(op, run.shelf_id, run.id, claimId))
  }, [run, withBusy])

  /** *"Approve all"* — the findings the button COUNTED, computed by the same
   *  function that renders the count (`pendingApprovals`), so the two cannot
   *  drift. `_all` is a single busy key rather than one per claim: the whole
   *  batch is one request and one thing to wait for. */
  const approveAll = useCallback((what: Approvable) => {
    if (!run || approvableCount(what) === 0) return
    void withBusy('_all', () => approveAllRemote(run.shelf_id, run.id, what))
  }, [run, withBusy])

  /** *"The engine missed this book"* — files a MANUAL claim on this read and
   *  returns the diff with the book already in it (no approval step: typing
   *  the title IS the approval). */
  const addByHand = useCallback((title: string, author: string) => {
    if (!run) return
    void withBusy('_add', () =>
      addFindingByHand(run.shelf_id, run.id, { title, author }))
  }, [run, withBusy])

  /**
   * *"This one spine is really N volumes"* (owner, 2026-08-09).
   *
   * Part 1 IS this finding, re-titled — confirm-as-corrected while it is
   * still pending, a plain book patch once it has landed, which are the two
   * doors ✎ already uses. Parts 2..N are ordinary hand-added findings on the
   * same read, so they arrive at `manual` and need no approval of their own.
   *
   * Sequential, not parallel: every call returns the diff, and the last one
   * to answer is the one that must win. Firing them together would let the
   * response to part 2 land after part 5 and paint a list missing three
   * volumes that are, in fact, already saved.
   */
  const split = useCallback((claimId: string, titles: string[]) => {
    if (!run || titles.length === 0) return
    const outcome = [...(diff?.added ?? []), ...(diff?.corrected ?? []),
                     ...(diff?.unchanged ?? []), ...(diff?.needs_decision ?? [])]
      .find((o) => o.claim.id === claimId)
    if (!outcome) return
    const book = outcome.existing_book
    const settled = ['added', 'corrected', 'unchanged'].includes(outcome.kind)
    const author = settled && book ? (book.author ?? '') : outcome.claim.author

    void withBusy(claimId, async () => {
      let latest = await performFindingOp(
        settled && book
          ? { kind: 'edit', bookId: book.id, title: titles[0]!, author }
          : { kind: 'confirm', title: titles[0]!, author },
        run.shelf_id, run.id, claimId,
      )
      for (const title of titles.slice(1)) {
        // `after_spine_id` is what puts the new parts NEXT TO the part they
        // were split from instead of at the bottom of the photo (owner,
        // 2026-08-09) — the server mints `<parent>~m<n>` and `FindingList`
        // orders on it.
        latest = await addFindingByHand(run.shelf_id, run.id, {
          title, author, after_spine_id: outcome.claim.spine_id,
        })
      }
      return latest
    })
  }, [run, diff, withBusy])

  /** *"Did this read already find it?"* while typing a title in by hand.
   *  A plain pass-through to the server — the matching rules live there
   *  (`app.domain.search`), not in this hook. */
  const lookup = useCallback(async (q: string) => {
    if (!run) return []
    return lookupFindings(run.shelf_id, run.id, q)
  }, [run])

  return {
    runs, runsLoading, error, openRunId, diff, diffLoading, diffError,
    runInFlight, busy,
    openRun, answer, finding, approveAll, addByHand, lookup, split,
    authors: listAuthors,
  }
}

export type ImageWorkspaceApi = ReturnType<typeof useImageWorkspace>
