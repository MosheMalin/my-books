/**
 * Accepts an invite link for a signed-in user (P4.3).
 *
 * Two arrival paths, one consumer: the hash right now (`#/invite?token=…`
 * opened while signed in), or the stash `AuthProvider` left when the link
 * was opened signed OUT and the sign-in detour navigated away. Either way
 * the token is consumed exactly once, the joined account's libraries are
 * absorbed into the switcher, and the first new one becomes the selection
 * — "show me what just opened up".
 *
 * Renders nothing except while it has something to say: accepting, or the
 * one honest refusal (expired, used, revoked and invented are the same
 * answer, by the server's design).
 */
import { useEffect, useState } from 'react'

import { replaceHash, useHash } from '@booksnap/ui'

import { acceptInvite } from '../api/client'
import { PENDING_INVITE_KEY } from './auth'
import { useI18n } from './i18n'
import { useLibrary } from './library'
import { LIBRARY_HASH, parseHash } from './route'

export function InviteGate() {
  const { t } = useI18n()
  const { absorb } = useLibrary()
  const hash = useHash()
  const [failed, setFailed] = useState(false)

  const route = parseHash(hash)
  const pending = route.name === 'invite' && route.token
    ? route.token
    : localStorage.getItem(PENDING_INVITE_KEY)

  useEffect(() => {
    if (!pending) return
    let live = true
    // Consumed BEFORE the request goes out: a failed accept must not
    // retry itself on every remount — the link is single-use server-side
    // anyway, and a loop of 404s helps nobody.
    localStorage.removeItem(PENDING_INVITE_KEY)
    acceptInvite(pending)
      .then((rows) => {
        if (!live) return
        setFailed(false)
        absorb(rows)
        // replaceHash, never navigate: a raw token must not stay in the
        // address bar, in history, or one Back-press behind the app —
        // the login token's own lesson (P4.1b, CRITICAL 1). `absorb`
        // already moves the hash when it selects a NEW library; this
        // covers the "nothing new" case, which is most of them.
        replaceHash(LIBRARY_HASH)
      })
      .catch(() => {
        if (!live) return
        setFailed(true)
        replaceHash(LIBRARY_HASH)
      })
    return () => {
      live = false
    }
    // `pending` collapses both arrival paths; re-running on its change is
    // exactly the once-per-token rule.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending])

  if (failed) {
    return (
      <p className="hint warn rtl-safe" role="alert">
        {t.invite_dead}
      </p>
    )
  }
  return null
}
