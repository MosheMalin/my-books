/**
 * One claim, reviewed inline (P2.7, UI_PLAN §4): crop, title/author, the raw
 * read in guillemets, tier badge + score, a diff badge, ✓/✕ or the §5.4
 * three-way prompt, and *why?*.
 *
 * What each row's action means is driven entirely by
 * `app.domain.reconcile.OutcomeKind`/`reason` (`ClaimOutcomeDTO`), not
 * guessed at here:
 *   - `added` / `corrected` / `unchanged` — `reconcile()` already decided
 *     these; nothing to confirm, so no action buttons (they are committed
 *     automatically the moment the diff loads — see `useCapture.commitDiff`).
 *   - `needs_decision` + `review_tier_new_book` — a REVIEW-tier claim with no
 *     prior record anywhere: ✓ confirms (files it as `approved`), ✕ rejects.
 *   - `needs_decision` + `ambiguous_location` — §5.4's three-way prompt, its
 *     default ("the listed copy") stated on screen. Leaving it alone is a
 *     real choice: the claim lands in the Books tab's duplicates queue.
 *
 * **"Alternatives" is READ-ONLY here, not "one-click acceptable"
 * (UI_PLAN §4's phrase).** The domain has no operation to re-point an
 * already-classified claim at a different catalog candidate — accepting one
 * would need a new domain-level "override this claim's match" op, which is
 * out of P2.7's scope (a real write path, not a display tweak). So the
 * ranked list explain() produces is shown for transparency inside *why?*,
 * with no accept button — absent, not a button that does nothing.
 */
import { useState } from 'react'
import type { ClaimOutcomeDTO } from '../api/client'
import { useI18n } from '../lib/i18n'

const TIER_CLASS: Record<string, string> = {
  auto: 'b-auto', review: 'b-review', unmatched: 'b-none',
}
const DIFF_CLASS: Record<string, string> = {
  added: 'b-auto', unchanged: 'b-manual', corrected: 'b-approved',
  ambiguous_location: 'b-review', review_tier_new_book: 'b-review',
}

export interface ClaimRowProps {
  outcome: ClaimOutcomeDTO
  answering: boolean
  onAnswer: (kind: string, copyId?: string | null) => void
}

export function ClaimRow({ outcome, answering, onAnswer }: ClaimRowProps) {
  const { t } = useI18n()
  const [showWhy, setShowWhy] = useState(false)
  const { claim } = outcome

  const tierClass = TIER_CLASS[claim.tier] ?? 'b-none'
  const tierLabel = claim.tier === 'auto' ? t.tier_auto
    : claim.tier === 'review' ? t.tier_review : t.claim_unmatched

  const diffKey = outcome.kind === 'needs_decision' ? outcome.reason : outcome.kind
  const diffClass = DIFF_CLASS[diffKey] ?? 'b-none'
  const diffLabel = {
    added: t.diff_added, unchanged: t.diff_unchanged, corrected: t.diff_corrected,
    ambiguous_location: t.diff_duplicate, review_tier_new_book: t.diff_review,
  }[diffKey] ?? diffKey

  const needsConfirm = outcome.kind === 'needs_decision'
    && outcome.reason === 'review_tier_new_book'
  const needsDup = outcome.kind === 'needs_decision'
    && outcome.reason === 'ambiguous_location'

  return (
    <div className="rrow">
      <div className="top">
        {claim.crop_key ? (
          <img className="spine" src={`/api/v1/images/${claim.crop_key}/thumb`} alt="" />
        ) : (
          <span className="spine" aria-hidden="true" />
        )}
        <div className="m">
          <div className="t rtl-safe">{claim.title || t.claim_unmatched}</div>
          <div className="tiny muted rtl-safe">
            {claim.author}
            {claim.text ? ` · «${claim.text}»` : ''}
          </div>
          <div className="chiprow" style={{ marginTop: 5 }}>
            <span className={`badge ${tierClass}`}>
              {tierLabel}{claim.score ? ` ${Math.round(claim.score)}` : ''}
            </span>
            <span className={`badge ${diffClass}`}>{diffLabel}</span>
            <button type="button" className="linkish" onClick={() => setShowWhy((s) => !s)}>
              {t.why}
            </button>
          </div>
        </div>
        {needsConfirm && (
          <div className="acts">
            <button
              type="button"
              className="btn sm primary"
              disabled={answering}
              onClick={() => onAnswer('confirm')}
            >
              ✓
            </button>
            <button
              type="button"
              className="btn sm"
              disabled={answering}
              onClick={() => onAnswer('reject')}
            >
              ✕
            </button>
          </div>
        )}
      </div>

      {needsDup && (
        <DupPrompt outcome={outcome} answering={answering} onAnswer={onAnswer} />
      )}

      {showWhy && <WhyPanel outcome={outcome} />}
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
          <select
            aria-label={t.dup_same}
            value={copyId}
            onChange={(e) => setCopyId(e.target.value)}
          >
            {copies.map((c, i) => (
              <option key={c.id} value={c.id}>
                {c.label || t.copy_n(i + 1)}
              </option>
            ))}
          </select>
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

function WhyPanel({ outcome }: { outcome: ClaimOutcomeDTO }) {
  const { t } = useI18n()
  const alts = outcome.claim.alternatives ?? []
  return (
    <div className="altbox">
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
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
