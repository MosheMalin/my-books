/**
 * Member management (P4.3) — §4.2's MANAGE_MEMBERS row on screen.
 *
 * A modal over the app, reached from the switcher menu and only offered to
 * admins (the server enforces; the client simply does not dangle a door
 * that answers 403). Three parts: who is in the account, an invite link
 * minted on demand — shown ONCE, with the copy control beside it, because
 * nothing stored can reproduce it — and the open invites with revokes.
 *
 * ⚠ Accessible names: every per-row control carries the row's own name
 * (the collision trap — "I labelled the links" is not "I labelled the
 * buttons", and the pair left colliding last time included the one that
 * writes).
 */
import { useCallback, useEffect, useState } from 'react'

import { Select } from '@booksnap/ui'

import {
  inviteLink,
  listInvites,
  listMembers,
  mintInvite,
  removeMember,
  revokeInvite,
  setMemberRole,
  type InviteDTO,
  type MemberDTO,
} from '../api/client'
import { useI18n } from './i18n'

const ROLES = ['viewer', 'editor', 'admin'] as const

export function MembersPanel({ onClose }: { onClose: () => void }) {
  const { t } = useI18n()
  const [members, setMembers] = useState<MemberDTO[] | null>(null)
  const [invites, setInvites] = useState<InviteDTO[]>([])
  const [minted, setMinted] = useState<string | null>(null)
  const [inviteRole, setInviteRole] = useState<string>('editor')
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const load = useCallback(() => {
    Promise.all([listMembers(), listInvites()])
      .then(([m, i]) => {
        setMembers(m)
        setInvites(i)
      })
      .catch((err) => setError(String(err)))
  }, [])

  useEffect(load, [load])

  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      load()
    } catch (err) {
      // A 409 here is NoAdminLeft speaking — the server's sentence carries
      // the remedy ("promote someone else first") and is shown verbatim.
      setError(String(err))
    }
  }

  const mint = async () => {
    setError(null)
    try {
      const made = await mintInvite(inviteRole)
      setMinted(inviteLink(made.token))
      setCopied(false)
      load()
    } catch (err) {
      setError(String(err))
    }
  }

  const copy = async () => {
    if (!minted) return
    try {
      await navigator.clipboard.writeText(minted)
      setCopied(true)
    } catch {
      // No clipboard permission — the link is selectable text either way.
    }
  }

  return (
    <div className="modal on" role="dialog" aria-label={t.members_title}>
      <div className="modalbox">
        <h3 className="rtl-safe">{t.members_title}</h3>
        <div className="body">
          {error && (
            <p className="hint warn rtl-safe" role="alert">{error}</p>
          )}
          {members === null ? (
            <p className="hint rtl-safe">{t.members_loading}</p>
          ) : (
            <ul className="memberlist">
              {members.map((m) => {
                const name = m.display_name || m.user_id
                return (
                  <li key={m.user_id}>
                    <span className="rtl-safe">{name}</span>
                    <Select
                      aria-label={`${t.member_role_of} ${name}`}
                      value={m.role}
                      onChange={(e) =>
                        act(() => setMemberRole(m.user_id, e.target.value))
                      }
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {t.role[r]}
                        </option>
                      ))}
                    </Select>
                    <button
                      type="button"
                      className="btn ghost"
                      aria-label={`${t.member_remove} ${name}`}
                      onClick={() => act(() => removeMember(m.user_id))}
                    >
                      {t.member_remove}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}

          <h4 className="rtl-safe">{t.invite_title}</h4>
          <div className="invitemint">
            <Select
              aria-label={t.invite_role}
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {t.role[r]}
                </option>
              ))}
            </Select>
            <button type="button" className="btn primary" onClick={mint}>
              {t.invite_create}
            </button>
          </div>
          {minted && (
            <div className="invitelink">
              <p className="hint ok rtl-safe">{t.invite_once}</p>
              <input
                type="text"
                dir="ltr"
                readOnly
                value={minted}
                aria-label={t.invite_link}
                onFocus={(e) => e.target.select()}
              />
              <button type="button" className="btn" onClick={copy}>
                {copied ? t.invite_copied : t.invite_copy}
              </button>
            </div>
          )}
          {invites.length > 0 && (
            <ul className="invitelist">
              {invites.map((i) => (
                <li key={i.id}>
                  <span className="rtl-safe">
                    {t.role[i.role]} · {t.invite_expires} {i.expires_at}
                  </span>
                  <button
                    type="button"
                    className="btn ghost"
                    aria-label={`${t.invite_revoke} ${i.id.slice(0, 8)}`}
                    onClick={() => act(() => revokeInvite(i.id))}
                  >
                    {t.invite_revoke}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="modalfoot">
          <button type="button" className="btn" onClick={onClose}>
            {t.close}
          </button>
        </div>
      </div>
    </div>
  )
}
