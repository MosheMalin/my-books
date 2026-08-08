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
 * *"Approve all"* — every pending finding in one call (the POC's own bulk
 * action, restored 2026-08-09).
 *
 * Two rules the POC learned the hard way and this keeps:
 *   - it approves exactly the set the button counted. A finding already
 *     answered — or one the human marked wrong — must never ride along;
 *   - it is the ordinary apply route with N confirms, not a bulk endpoint.
 *     A second door would be a second place to get that first rule wrong.
 */
export async function approveAllPending(
  shelfId: string, readId: string, claimIds: readonly string[],
): Promise<DiffDTO> {
  return applyDiff(shelfId, readId, {
    answers: claimIds.map((claim_id) => ({
      claim_id, kind: 'confirm', copy_id: null, title: null, author: null,
    })),
  })
}

/** The findings *"approve all"* would act on: pending new-book questions
 *  only, optionally narrowed to one photo. Exported so the button's COUNT and
 *  its ACTION are computed from one function and cannot disagree. */
export function pendingApprovals(
  diff: DiffDTO, captureId?: string,
): string[] {
  return diff.needs_decision
    .filter((o) => o.reason === 'new_book_unconfirmed')
    .filter((o) => captureId === undefined || o.claim.capture_id === captureId)
    .map((o) => o.claim.id)
}
