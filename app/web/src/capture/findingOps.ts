/**
 * The four things a human can do to one finding (P2.10, §12.2 #10), in one
 * place so the LIVE review panel and the IMAGE WORKSPACE cannot drift apart.
 *
 * They are the same four actions on the same rows — the only difference is
 * when you are looking (right after the read, or a week later), which is
 * exactly the difference §12.2 #10 says should stop mattering. Two copies of
 * "what does ✕ do" would be two chances for one of them to be wrong.
 *
 * Every op resolves to the diff RECOMPUTED after the write, so a caller
 * replaces one object and every badge on screen follows:
 *   - `retract`/`restore` get it from the endpoint itself (their own
 *     contract, same as `POST .../apply`);
 *   - `approve`/`edit` are ordinary BOOK routes — they return a `Book`, not a
 *     diff — so this refetches. Deliberately a plain `GET .../diff` and not
 *     an apply: opening or editing a finding must never write provenance.
 */
import { vouchedFor } from '@booksnap/ui'
import {
  applyDiff,
  approveBook,
  getDiff,
  patchBook,
  restoreFinding,
  retractFinding,
  type DiffDTO,
} from '../api/client'

export type FindingOp =
  /** A finding that already became a book: raise it off the `auto` rung. Only
   *  reachable for a record that predates the approval rule — anything this
   *  tab confirms is created `approved` already. */
  | { kind: 'approve'; bookId: string }
  /** A finding still waiting: yes, this is a real book. Optionally with the
   *  title corrected, which is ✎-then-✓ as ONE act (`AnswerIn.title`). */
  | { kind: 'confirm'; title?: string; author?: string }
  /** A finding that already became a book: fix its title/author. */
  | { kind: 'edit'; bookId: string; title: string; author: string }
  | { kind: 'retract' }
  | { kind: 'restore' }

export async function performFindingOp(
  op: FindingOp,
  shelfId: string,
  readId: string,
  claimId: string,
): Promise<DiffDTO> {
  switch (op.kind) {
    case 'approve':
      await approveBook(op.bookId)
      return getDiff(shelfId, readId)
    case 'confirm':
      return applyDiff(shelfId, readId, {
        answers: [{
          claim_id: claimId, kind: 'confirm', copy_id: null,
          title: op.title ?? null, author: op.author ?? null,
        }],
      })
    case 'edit':
      await patchBook(op.bookId, { title: op.title, author: op.author })
      return getDiff(shelfId, readId)
    case 'retract':
      return retractFinding(shelfId, readId, claimId)
    case 'restore':
      return restoreFinding(shelfId, readId, claimId)
  }
}

/**
 * *"Approve all auto"* — the POC's own bulk action, restored 2026-08-09 and
 * corrected the same day when the owner went looking for it and did not find
 * one that covered what he meant.
 *
 * It covers everything sitting UNVOUCHED-FOR, which is two states, not one:
 *   - an AUTO-tier finding still waiting for a yes (confirm it — creates the
 *     book, approved);
 *   - a finding that already became a book still on the `auto` rung, because
 *     it entered before "nothing enters the library unapproved", or because
 *     an older read placed it (raise that book).
 *
 * REVIEW-tier findings are deliberately NOT swept up. That is the POC's rule
 * and the reason for it has not changed: a bulk click is not the place to
 * accept the engine's low-confidence guesses, and those rows keep their own
 * ✓ one tap away. §5.4's duplicate questions are excluded for the stronger
 * reason that they are a different question entirely.
 *
 * Two invariants the POC learned the hard way and this keeps: it approves
 * EXACTLY the set the button counted (a finding already answered, or marked
 * wrong, never rides along), and it is composed from the ordinary routes
 * rather than a bulk endpoint — a second door would be a second place to get
 * that first rule wrong.
 */
export interface Approvable {
  /** Pending AUTO-tier findings — confirmed through `POST .../apply`. */
  claimIds: string[]
  /** Books already in the library but still `auto` — raised through
   *  `POST /books/{id}/approve`. */
  bookIds: string[]
}

export function approvableFindings(
  diff: DiffDTO, captureId?: string,
): Approvable {
  const mine = (o: { claim: { capture_id: string } }) =>
    captureId === undefined || o.claim.capture_id === captureId

  const claimIds = diff.needs_decision
    .filter((o) => o.reason === 'new_book_unconfirmed')
    .filter((o) => o.claim.tier === 'auto')
    .filter(mine)
    .map((o) => o.claim.id)

  const bookIds = [...diff.added, ...diff.corrected, ...diff.unchanged]
    .filter(mine)
    .map((o) => o.existing_book)
    .filter((b): b is NonNullable<typeof b> => !!b && !vouchedFor(b.status))
    .map((b) => b.id)

  // One book can back two findings (two spines of one title); approving it
  // twice is harmless but the COUNT would lie about how much is left.
  return { claimIds, bookIds: [...new Set(bookIds)] }
}

export function approvableCount(a: Approvable): number {
  return a.claimIds.length + a.bookIds.length
}

export async function approveAll(
  shelfId: string, readId: string, what: Approvable,
): Promise<DiffDTO> {
  // The book approvals first: they are independent of the read, and doing
  // them before the apply means the diff this returns already reflects them.
  await Promise.all(what.bookIds.map((id) => approveBook(id)))
  if (what.claimIds.length === 0) return getDiff(shelfId, readId)
  return applyDiff(shelfId, readId, {
    answers: what.claimIds.map((claim_id) => ({
      claim_id, kind: 'confirm', copy_id: null, title: null, author: null,
    })),
  })
}


/* --- one spine, several volumes (owner, 2026-08-09) -----------------------
 *
 * A shelf holds "X א" and "X ב" side by side and the read produced ONE
 * finding for X. Splitting it files the volumes as the separate books they
 * are, and it needs no new server surface at all: part 1 IS the original
 * finding, answered with a corrected title (confirm-as-corrected for a
 * pending one, a patch for a settled one — the same two doors ✎ already
 * uses), and parts 2..N are ordinary hand-added findings on the same read.
 *
 * That the original finding stays SETTLED afterwards, even though its book
 * is now called something else, is the sighting rule doing its job
 * (`app.domain.reconcile`): a claim is answered by the book its own
 * (read_id, spine_id) produced, whatever that book ended up being called.
 */

export type VolumeStyle = 'hebrew' | 'numbers' | 'roman' | 'signal'

/** How far a set can be split in one go. Two is the overwhelming case; five
 *  is where "type them by hand" becomes the better tool anyway. */
export const MAX_VOLUMES = 5
export const DEFAULT_VOLUMES = 2

const HEBREW = ['א', 'ב', 'ג', 'ד', 'ה']
const ROMAN = ['I', 'II', 'III', 'IV', 'V']

/** The suffix for volume `n` (1-based) in the chosen style. Hebrew letters
 *  are the default because that is how Hebrew volumes are actually marked on
 *  a spine — the other three exist because the owner's shelves have all of
 *  them. */
export function volumeMark(n: number, style: VolumeStyle): string {
  if (style === 'numbers') return String(n)
  if (style === 'roman') return ROMAN[n - 1] ?? String(n)
  if (style === 'signal') return '*'.repeat(n)
  return HEBREW[n - 1] ?? String(n)
}

export function volumeTitles(
  title: string, count: number, style: VolumeStyle,
): string[] {
  return Array.from({ length: count },
                    (_, i) => `${title} ${volumeMark(i + 1, style)}`)
}
