/**
 * One diff, rendered as findings — the headline counts and a row per claim
 * (P2.7's review list, extracted at P2.10 so the LIVE review panel and the
 * IMAGE WORKSPACE render the same thing from the same code).
 *
 * Two P2.10 decisions live here:
 *
 *  - **`captureId` narrows to one photo.** A read covers every capture at its
 *    (shelf, depth) — §5.7 #1 forbids a partial read of a row — but the
 *    workspace is opened from ONE image, and showing the whole row's findings
 *    there would answer a question nobody asked. Each claim names the capture
 *    it came from, so the narrowing is a filter, not a second request. The
 *    live panel passes nothing and shows the whole read;
 *  - **`rejected` findings are listed.** They were invisible before P2.10,
 *    which meant a suppressed book had no explanation and its undo had
 *    nowhere to live (`DiffDTO.rejected`'s own contract: "kept for
 *    transparency so a suppressed book has a visible reason"). `ignored` is
 *    still not listed — a within-read duplicate or a titleless spine is noise
 *    on this screen, not a decision anybody made.
 */
import { useEffect, useRef, useState } from 'react'
import type { ClaimOutcomeDTO, DiffDTO, FindingMatchDTO } from '../api/client'
import { useI18n } from '../lib/i18n'
import { ClaimRow } from './ClaimRow'
import { pendingApprovals, type FindingOp } from './findingOps'

export interface FindingListProps {
  diff: DiffDTO
  /** Show only the findings that came from this photo. Omit for the whole read. */
  captureId?: string
  busy: Set<string>
  onAnswer: (claimId: string, kind: string, copyId?: string | null) => void
  onFinding?: (claimId: string, op: FindingOp) => void
  /** Approve every pending finding at once — the POC's own bulk action. The
   *  ids it is handed are exactly the ones the button counted. */
  onApproveAll?: (claimIds: string[]) => void
  /** *"The engine missed this book"*. Absent on the live review panel: a
   *  read that is still settling has no stable set of findings to add to. */
  onAddByHand?: (title: string, author: string) => void
  /** *"Did this read already find it?"*, asked as the title is typed. Absent
   *  wherever adding is (the two arrive together). */
  onLookup?: (q: string) => Promise<FindingMatchDTO[]>
  /** Rendered when the (possibly narrowed) list is empty. */
  emptyText: string
}

export function FindingList({
  diff, captureId, busy, onAnswer, onFinding, onApproveAll, onAddByHand,
  onLookup, emptyText,
}: FindingListProps) {
  const { t } = useI18n()
  const [adding, setAdding] = useState(false)
  const pending = pendingApprovals(diff, captureId)
  const mine = (o: ClaimOutcomeDTO) =>
    captureId === undefined || o.claim.capture_id === captureId

  const rows = [
    ...diff.added, ...diff.corrected, ...diff.needs_decision,
    ...diff.unchanged, ...diff.rejected,
  ].filter(mine)

  return (
    <>
      <div className="chiprow diffbits">
        <span className="g">+{diff.added.filter(mine).length} {t.read_added}</span>
        {diff.corrected.filter(mine).length > 0 && (
          <span className="m">
            {diff.corrected.filter(mine).length} {t.read_corrected}
          </span>
        )}
        <span className="m">
          {diff.unchanged.filter(mine).length} {t.read_unchanged}
        </span>
        {pending.length > 0 && (
          <span className="p">{pending.length} {t.read_pending}</span>
        )}
        {/* Removals were invisible here until the owner asked for them
            (2026-08-09): a retracted finding left the pending count and
            appeared in no other, so the line silently under-reported what had
            happened to the photo. */}
        {diff.rejected.filter(mine).length > 0 && (
          <span className="r">
            {diff.rejected.filter(mine).length} {t.read_removed}
          </span>
        )}
        {/* not_seen is about the SHELF, not about any one photo — a copy
            nothing reconfirmed has no claim and so no capture to belong to.
            Reported only on the whole-read view for that reason. */}
        {captureId === undefined && diff.not_seen.length > 0 && (
          <span className="r">{t.read_unseen(diff.not_seen.length)}</span>
        )}
      </div>

      {(onApproveAll && pending.length > 0) || onAddByHand ? (
        <div className="chiprow findingbar">
          {onApproveAll && pending.length > 0 && (
            <button
              type="button"
              className="btn sm act-approve"
              disabled={busy.has('_all')}
              onClick={() => onApproveAll(pending)}
            >
              {t.approve_all(pending.length)}
            </button>
          )}
          {onAddByHand && !adding && (
            <button type="button" className="linkish"
                    onClick={() => setAdding(true)}>
              {t.add_book_here}
            </button>
          )}
        </div>
      ) : null}

      {adding && onAddByHand && (
        <AddByHand
          busy={busy.has('_add')}
          {...(onLookup ? { onLookup } : {})}
          onCancel={() => setAdding(false)}
          onSave={(title, author) => {
            setAdding(false)
            onAddByHand(title, author)
          }}
        />
      )}

      {rows.length === 0 ? (
        <p className="empty">{emptyText}</p>
      ) : (
        rows.map((outcome) => (
          <ClaimRow
            key={outcome.claim.id}
            outcome={outcome}
            answering={busy.has(outcome.claim.id)}
            onAnswer={(kind, copyId) => onAnswer(outcome.claim.id, kind, copyId)}
            {...(onFinding
              ? { onFinding: (op: FindingOp) => onFinding(outcome.claim.id, op) }
              : {})}
          />
        ))
      )}
    </>
  )
}

/** The owner typing in a book the reader missed. Inline, like every other
 *  form on this screen — a modal for two fields would be the heavier of the
 *  two options and buy nothing. */
function AddByHand({ busy, onLookup, onSave, onCancel }: {
  busy: boolean
  onLookup?: (q: string) => Promise<FindingMatchDTO[]>
  onSave: (title: string, author: string) => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [found, setFound] = useState<FindingMatchDTO[]>([])
  // Ignore out-of-order replies — typing outruns the network, and a slow
  // answer to "מל" landing after the answer to "מלכי" would show the wrong
  // hint. Exactly the guard `booksnap/static/index.html`'s own version uses
  // (`const mine = ++seq`), and the same one `lib/books.tsx` documents.
  const seq = useRef(0)

  useEffect(() => {
    if (!onLookup) return
    const q = title.trim()
    if (q.length < 2) { setFound([]); return }
    const mine = ++seq.current
    // Debounced: this asks the server on every keystroke otherwise, and the
    // answer is only interesting once a word is half-typed.
    const timer = setTimeout(() => {
      void onLookup(q)
        .then((hits) => { if (mine === seq.current) setFound(hits) })
        .catch(() => { if (mine === seq.current) setFound([]) })
    }, 250)
    return () => clearTimeout(timer)
  }, [title, onLookup])

  return (
    <form
      className="fixbox"
      onSubmit={(e) => {
        e.preventDefault()
        if (title.trim()) onSave(title.trim(), author.trim())
      }}
    >
      <label>
        <span className="tiny muted">{t.title_label}</span>
        <input className="rtl-safe" value={title} aria-label={t.title_label}
               onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label>
        <span className="tiny muted">{t.author_label}</span>
        <input className="rtl-safe" value={author} aria-label={t.author_label}
               onChange={(e) => setAuthor(e.target.value)} />
      </label>
      <div className="chiprow">
        <button type="submit" className="btn sm act-approve"
                disabled={busy || !title.trim()}>
          {t.add_book_save}
        </button>
        <button type="button" className="btn sm" onClick={onCancel}>
          {t.cancel}
        </button>
      </div>
      {/* The expensive human error this exists for: hand-adding a book the
          read DID find, on a forty-row shelf, in a language read
          right-to-left. Shown, never enforced — sometimes the right answer
          really is "add it anyway". */}
      {found.length > 0 && (
        <div className="foundhint tiny muted">
          <div>{t.add_book_found}</div>
          <ul>
            {found.map((f) => (
              <li key={f.claim_id} className="rtl-safe">
                {f.title}{f.author ? ` · ${f.author}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    </form>
  )
}
