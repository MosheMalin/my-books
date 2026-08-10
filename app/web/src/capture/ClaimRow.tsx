/**
 * One finding, reviewed inline (P2.7, extended by P2.10): crop, title/author,
 * the raw read in guillemets, tier badge + score, a diff badge, the actions,
 * and *why?*.
 *
 * What each row's action means is driven entirely by
 * `app.domain.reconcile.OutcomeKind`/`reason` (`ClaimOutcomeDTO`), not
 * guessed at here:
 *   - `needs_decision` + `new_book_unconfirmed` — a book the library has
 *     never heard of, waiting for a human. Since 2026-08-09 this covers
 *     AUTO-tier claims too, not only REVIEW ones (nothing enters the library
 *     unapproved), which is also why an AUTO and a REVIEW finding wear the
 *     same three controls: the owner's own item 7 — *"a review book should
 *     have the same available controls as an auto book"*. Tier is shown, and
 *     changes nothing about what you can do.
 *   - `needs_decision` + `ambiguous_location` — §5.4's three-way prompt, its
 *     default ("the listed copy") stated on screen. Leaving it alone is a
 *     real choice: the claim lands in the Books tab's duplicates queue.
 *   - `added` / `corrected` / `unchanged` — already in the library. Same
 *     three controls, pointed at the BOOK rather than at the pending answer:
 *     approve is offered only while the record still sits on the `auto` rung
 *     (a legacy import a read has re-found), ✎ patches the book, ✕ retracts
 *     the finding.
 *   - `rejected` — a standing decision suppresses it. Shown with its reason
 *     and an ↩, never hidden: "why isn't my book showing up" deserves an
 *     answer, and the undo has to live somewhere.
 *
 * **"Alternatives" is READ-ONLY, not "one-click acceptable"
 * (UI_PLAN §4's phrase).** The domain has no operation to re-point an
 * already-classified claim at a different catalog candidate — accepting one
 * would need a new domain-level "override this claim's match" op, which is
 * out of scope for both P2.7 and P2.10 (a real write path, not a display
 * tweak). So the ranked list explain() produces is shown for transparency
 * inside *why?*, with no accept button — absent, not a button that does
 * nothing. The nearest thing that DOES exist is ✎ *fix details*, which is a
 * human typing the right answer rather than the machine picking a runner-up.
 */
import { useState } from 'react'
import { imageUrl, type ClaimOutcomeDTO } from '../api/client'
import { useI18n } from '../lib/i18n'
import { vouchedFor, Select } from '@booksnap/ui'
import {
  DEFAULT_VOLUMES,
  MAX_VOLUMES,
  volumeTitles,
  type FindingOp,
  type VolumeStyle,
} from './findingOps'

const TIER_CLASS: Record<string, string> = {
  auto: 'b-auto', review: 'b-review', unmatched: 'b-none', manual: 'b-manual',
}

/** `booksnap/match.py`'s score is a weighted sum, not a percentage:
 *  60·tcov_c + 25·tcov + 15·acov + 0.30·title_sim, so a flawless match scores
 *  130. Named here rather than inlined because the number is meaningless
 *  without the formula it comes from. */
const MAX_SCORE = 130
const DIFF_CLASS: Record<string, string> = {
  added: 'b-auto', unchanged: 'b-manual', corrected: 'b-approved',
  ambiguous_location: 'b-review', new_book_unconfirmed: 'b-review',
  rejected: 'b-none', ignored: 'b-none',
}

export interface ClaimRowProps {
  outcome: ClaimOutcomeDTO
  answering: boolean
  onAnswer: (kind: string, copyId?: string | null) => void
  /** P2.10's loop. Absent while a read is still running, or wherever the
   *  findings are shown read-only — and then no action buttons are drawn at
   *  all, rather than disabled ones (the "absent, not disabled" rule). */
  onFinding?: (op: FindingOp) => void
  /** *"This one spine is really N volumes"* — hands back every volume title,
   *  part 1 first. The caller re-titles this finding to part 1 and adds the
   *  rest by hand; see `volumeTitles`. */
  onSplit?: (titles: string[]) => void
}

export function ClaimRow({
  outcome, answering, onAnswer, onFinding, onSplit,
}: ClaimRowProps) {
  const { t } = useI18n()
  const [showWhy, setShowWhy] = useState(false)
  const [editing, setEditing] = useState(false)
  const [splitting, setSplitting] = useState(false)
  const { claim } = outcome

  const tierClass = TIER_CLASS[claim.tier] ?? 'b-none'
  const tierLabel = claim.tier === 'auto' ? t.tier_auto
    : claim.tier === 'review' ? t.tier_review
    : claim.tier === 'manual' ? t.tier_manual : t.claim_unmatched

  const diffKey = outcome.kind === 'needs_decision' ? outcome.reason : outcome.kind
  const diffClass = DIFF_CLASS[diffKey] ?? 'b-none'
  const diffLabel = {
    added: t.diff_added, unchanged: t.diff_unchanged, corrected: t.diff_corrected,
    ambiguous_location: t.diff_duplicate, new_book_unconfirmed: t.diff_pending,
    rejected: t.diff_rejected, ignored: t.diff_ignored,
  }[diffKey] ?? diffKey

  const needsDup = outcome.kind === 'needs_decision'
    && outcome.reason === 'ambiguous_location'

  // The settled buckets are where P2.10's loop applies. `existing_book` is
  // what makes approve/edit possible at all — a claim that never became a
  // book has no record to raise or correct, though it can still be retracted
  // (that only records the standing "no").
  const settled = ['added', 'corrected', 'unchanged'].includes(outcome.kind)
  const pending = outcome.kind === 'needs_decision'
    && outcome.reason === 'new_book_unconfirmed'
  const book = outcome.existing_book
  const canAct = Boolean(onFinding) && (settled || pending)
  const retracted = outcome.kind === 'rejected'

  // What this row IS, now. Once a finding has become a book, the BOOK's
  // title/author is the answer — the claim keeps the engine's own text
  // forever (it is evidence, and `Claim` is frozen for that reason), so a
  // row that kept showing it would still show the typo minutes after
  // someone fixed it. Not for a `needs_decision` row, though: there
  // `existing_book` is a DIFFERENT book — the one already on another shelf
  // that §5.4 is asking about — and showing its title as this spine's would
  // be a lie.
  const shownTitle = settled && book ? book.title : claim.title
  const shownAuthor = settled && book ? book.author : claim.author

  /** Accept one of `explain()`'s runners-up (owner, 2026-08-09). Two writes,
   *  one meaning: a pending finding is CONFIRMED as that candidate (the
   *  approve-as-corrected path), a settled one has its book re-titled. */
  const useAlternative = (title: string, author: string) => {
    if (!onFinding) return
    onFinding(pending
      ? { kind: 'confirm', title, author }
      : { kind: 'edit', bookId: book!.id, title, author })
  }

  return (
    <div className={`rrow${retracted ? ' retracted' : ''}`}>
      <div className="top">
        {claim.crop_key ? (
          <img className="spine" src={imageUrl(claim.crop_key)} alt="" />
        ) : (
          <span className="spine" aria-hidden="true" />
        )}
        <div className="m">
          {/* Title then author, the same two lines a book row shows and with
              the same classes (`books.css`'s `.t`/`.a`) — a finding IS a book
              claim, so reading it should not feel like reading a log line.
              The raw OCR text used to sit here in guillemets; it is
              EXPLANATION, not identity, so it moved into the panel below
              (owner, 2026-08-09). */}
          <div className="t rtl-safe">{shownTitle || t.claim_unmatched}</div>
          <div className="a rtl-safe">{shownAuthor || `— ${t.author_label} —`}</div>
          <div className="chiprow" style={{ marginTop: 5 }}>
            {/* The matcher's score is NOT a percentage — `booksnap/match.py`
                computes 60·tcov_c + 25·tcov + 15·acov + 0.30·title_sim, so a
                perfect match is 130. A bare "130" next to a tier reads as a
                broken percentage, which is exactly what the owner asked
                about; the denominator is the cheapest honest fix, and the
                tooltip says what the number is. */}
            <span className={`badge ${tierClass}`}
                  title={claim.score ? t.score_explained : undefined}>
              {tierLabel}
              {claim.score ? ` ${Math.round(claim.score)}/${MAX_SCORE}` : ''}
            </span>
            <span className={`badge ${diffClass}`}>{diffLabel}</span>
            {/* Anything a human has vouched for, not only the literal
                `approved` rung. A book the owner TYPED IN is `manual` —
                stronger evidence than approval, §5.1's ladder — and showing
                no badge for it made a hand-added finding look like the one
                thing nobody had confirmed (owner, 2026-08-09). The status
                itself is left alone: downgrading manual to approved would
                throw away which of the two actually happened. */}
            {book && vouchedFor(book.status) && (
              <span className="badge b-approved">{t.finding_approved_note}</span>
            )}
            <button type="button" className="linkish"
                    onClick={() => setShowWhy((s) => !s)}>
              {t.try_match}
            </button>
            {/* A link, not a button, and on this side: it OPENS A PANEL, which
                is what *try a better match?* does, rather than committing
                anything — which is what the three coloured buttons do (owner,
                2026-08-09). The caption is one word; the tooltip carries the
                rest. */}
            {canAct && onSplit && (
              <button type="button" className="linkish" title={t.finding_split}
                      onClick={() => setSplitting((v) => !v)}>
                {t.finding_split_short}
              </button>
            )}
          </div>
          {retracted && (
            <div className="tiny muted" style={{ marginTop: 5 }}>
              {t.finding_retracted_note}
            </div>
          )}
        </div>
        {canAct && !editing && (
          <div className="acts findingacts">
            {/* Approve means two different writes for the two states, and
                the SAME thing to the person clicking it: "yes, this book".
                Pending -> confirm the finding (creates it, approved);
                settled -> raise a record still on the `auto` rung. */}
            {(pending || (book && !vouchedFor(book.status))) && (
              <button
                type="button"
                className="btn sm act-approve"
                disabled={answering}
                onClick={() => onFinding!(pending
                  ? { kind: 'confirm' }
                  : { kind: 'approve', bookId: book!.id })}
              >
                {t.finding_approve}
              </button>
            )}
            <button
              type="button"
              className="btn sm act-fix"
              disabled={answering}
              onClick={() => setEditing(true)}
            >
              {t.finding_edit}
            </button>
            <button
              type="button"
              className="btn sm act-remove"
              disabled={answering}
              onClick={() => onFinding!({ kind: 'retract' })}
            >
              {t.finding_retract}
            </button>
          </div>
        )}
        {retracted && onFinding && (
          <div className="acts findingacts">
            <button
              type="button"
              className="btn sm"
              disabled={answering}
              onClick={() => onFinding({ kind: 'restore' })}
            >
              {t.finding_restore}
            </button>
          </div>
        )}
      </div>

      {splitting && onSplit && (
        <SplitIntoVolumes
          title={shownTitle}
          busy={answering}
          onCancel={() => setSplitting(false)}
          onSplit={(titles) => {
            setSplitting(false)
            onSplit(titles)
          }}
        />
      )}

      {editing && (
        <FixDetails
          title={book?.title ?? claim.title}
          author={book?.author ?? claim.author}
          busy={answering}
          saveLabel={pending ? t.finding_fix_and_approve : t.save}
          onCancel={() => setEditing(false)}
          onSave={(title, author) => {
            setEditing(false)
            // A pending finding has no book yet, so ✎ is not a patch — it is
            // "yes, as corrected", one human act and one write (`AnswerIn`'s
            // own title/author). The claim keeps the engine's text either way.
            onFinding!(pending
              ? { kind: 'confirm', title, author }
              : { kind: 'edit', bookId: book!.id, title, author })
          }}
        />
      )}

      {needsDup && (
        <DupPrompt outcome={outcome} answering={answering} onAnswer={onAnswer} />
      )}

      {showWhy && (
        <WhyPanel
          outcome={outcome}
          {...(canAct && (pending || book) ? { onUse: useAlternative } : {})}
          busy={answering}
        />
      )}
    </div>
  )
}

/** The ✎ — an inline form, not a modal, exactly like the book drawer's own
 *  title/author edit (P1.6's idiom): correcting what the engine read should
 *  cost no more UI than reading it. Saving marks the book `manual`, which is
 *  the server's rule, not this form's. */
function FixDetails({ title, author, busy, saveLabel, onSave, onCancel }: {
  title: string
  author: string
  busy: boolean
  saveLabel: string
  onSave: (title: string, author: string) => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const [t1, setT1] = useState(title)
  const [a1, setA1] = useState(author)
  return (
    <form
      className="fixbox"
      onSubmit={(e) => {
        e.preventDefault()
        if (t1.trim()) onSave(t1.trim(), a1.trim())
      }}
    >
      <label>
        <span className="tiny muted">{t.title_label}</span>
        <input className="rtl-safe" value={t1} onChange={(e) => setT1(e.target.value)}
               aria-label={t.title_label} />
      </label>
      <label>
        <span className="tiny muted">{t.author_label}</span>
        <input className="rtl-safe" value={a1} onChange={(e) => setA1(e.target.value)}
               aria-label={t.author_label} />
      </label>
      <div className="chiprow">
        <button type="submit" className="btn sm act-approve"
                disabled={busy || !t1.trim()}>
          {saveLabel}
        </button>
        <button type="button" className="btn sm" onClick={onCancel}>{t.cancel}</button>
      </div>
    </form>
  )
}

/** *"One spine, several volumes"* — pick how many and how they are marked,
 *  and see the result before committing to it. The preview is the control's
 *  whole justification: "א/ב" versus "1/2" versus "I/II" is a choice about
 *  what is printed on the owner's own books, and no label describes that as
 *  well as showing it. */
function SplitIntoVolumes({ title, busy, onSplit, onCancel }: {
  title: string
  busy: boolean
  onSplit: (titles: string[]) => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const [count, setCount] = useState(DEFAULT_VOLUMES)
  const [style, setStyle] = useState<VolumeStyle>('hebrew')
  const titles = volumeTitles(title, count, style)

  return (
    <div className="dupbox splitbox">
      <div className="chiprow">
        <label className="tiny muted">
          {t.split_count}
          <Select value={count} aria-label={t.split_count}
                  onChange={(e) => setCount(Number(e.target.value))}>
            {Array.from({ length: MAX_VOLUMES - 1 }, (_, i) => i + 2).map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </Select>
        </label>
        <label className="tiny muted">
          {t.split_style}
          <Select value={style} aria-label={t.split_style}
                  onChange={(e) => setStyle(e.target.value as VolumeStyle)}>
            <option value="hebrew">{t.split_hebrew}</option>
            <option value="numbers">{t.split_numbers}</option>
            <option value="roman">{t.split_roman}</option>
            <option value="signal">{t.split_signal}</option>
          </Select>
        </label>
        <button type="button" className="btn sm act-approve" disabled={busy}
                onClick={() => onSplit(titles)}>
          {t.split_do}
        </button>
        <button type="button" className="btn sm" onClick={onCancel}>
          {t.cancel}
        </button>
      </div>
      <div className="tiny muted rtl-safe" style={{ marginTop: 6 }}>
        {titles.join(' · ')}
      </div>
    </div>
  )
}


function DupPrompt({ outcome, answering, onAnswer }: ClaimRowProps) {
  const { t } = useI18n()
  const book = outcome.existing_book
  const copies = book?.copies ?? []
  const [copyId, setCopyId] = useState(copies[0]?.id ?? '')

  return (
    <div className="dupbox">
      <div className="rtl-safe" style={{ marginBottom: 7 }}>
        {t.dup_q(book?.title ?? '')}
      </div>
      <div className="chiprow">
        {copies.length > 1 && (
          <Select
            aria-label={t.dup_same}
            value={copyId}
            onChange={(e) => setCopyId(e.target.value)}
          >
            {copies.map((c, i) => (
              <option key={c.id} value={c.id}>
                {c.label || t.copy_n(i + 1)}
              </option>
            ))}
          </Select>
        )}
        <button
          type="button"
          className="chip"
          disabled={answering}
          onClick={() => onAnswer('already_listed', copyId || undefined)}
        >
          {t.dup_same}
        </button>
        <button
          type="button"
          className="chip"
          disabled={answering}
          onClick={() => onAnswer('another_copy')}
        >
          {t.dup_another}
        </button>
        <button
          type="button"
          className="chip"
          disabled={answering}
          onClick={() => onAnswer('wrong_book')}
        >
          {t.dup_wrong}
        </button>
      </div>
      <div className="tiny muted" style={{ marginTop: 6 }}>{t.dup_default_note}</div>
    </div>
  )
}

/**
 * *"Try a better match"* — the raw read, and `explain()`'s ranked runners-up
 * with a **use this** on each (owner, 2026-08-09).
 *
 * P2.7 shipped this list read-only and said why: UI_PLAN §4 asked for
 * "one-click acceptable" and the domain had no operation to re-point an
 * already-classified claim at a different candidate. **That operation now
 * exists**, and it arrived from somewhere else entirely — "nothing enters the
 * library unapproved" made every machine finding a pending question, and
 * `AnswerKind.CONFIRM` carries an optional title/author so a human can
 * approve one AS CORRECTED. Accepting a runner-up is exactly that, with the
 * candidate's text instead of typed text. A settled finding takes the other
 * existing door, `PATCH /books/{id}`.
 *
 * So there is still no "override this claim's match" domain op, and there
 * does not need to be: the CLAIM keeps the engine's own reading either way
 * (it is evidence), and the BOOK gets the human's answer. That is the same
 * split `Answer`'s docstring already describes.
 *
 * The rejection reasons stay on screen. They are the panel's other half —
 * "why not this one" is what makes a ranked list judgeable rather than a
 * lottery — and they are ENGLISH always, hardcoded in `booksnap/match.py`,
 * shown verbatim rather than mistranslated by guessing at their meaning.
 */
function WhyPanel({ outcome, onUse, busy }: {
  outcome: ClaimOutcomeDTO
  onUse?: (title: string, author: string) => void
  busy?: boolean
}) {
  const { t } = useI18n()
  const alts = outcome.claim.alternatives ?? []
  const raw = outcome.claim.text
  return (
    <div className="altbox">
      {/* The raw read, moved off the row itself: it explains the finding, it
          does not identify it (owner, 2026-08-09). */}
      {raw && (
        <div className="tiny muted rtl-safe rawread">{t.raw_read} «{raw}»</div>
      )}
      <div className="tiny muted" style={{ marginBottom: 5 }}>{t.alternatives}</div>
      {alts.length === 0 ? (
        <p className="tiny muted">{t.alt_none}</p>
      ) : (
        <table>
          <tbody>
            {alts.map((a, i) => (
              // No stable id on an AlternativeDTO (it is display data, not an
              // entity) — index is fine, the list is a fixed snapshot per row.
              // eslint-disable-next-line react/no-array-index-key
              <tr key={i}>
                <td className="rtl-safe">{a.title}</td>
                <td className="rtl-safe muted">{a.author}</td>
                <td className="mono">{Math.round(a.score)}</td>
                <td className="tiny muted rtl-safe">{a.reason || t.alt_candidate}</td>
                <td>
                  {onUse && (
                    <button
                      type="button"
                      className="btn sm act-approve"
                      disabled={busy}
                      onClick={() => onUse(a.title, a.author)}
                    >
                      {t.alt_use}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
