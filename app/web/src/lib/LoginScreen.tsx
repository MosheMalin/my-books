/**
 * The sign-in screen (P4.1b) — the whole app, when nobody is signed in.
 *
 * One field, one button, and the honest answer: the server says the same
 * thing whether the address is known or not (anti-enumeration is ITS rule;
 * this screen just repeats the sentence it was given). What the server DOES
 * say is how the link travels (`delivery` on the 202 — a fact about the
 * transport, not the address): the dev build has no mail, and a screen
 * claiming "check your inbox" while the link sits in a server log was the
 * UX review's sharpest finding.
 *
 * The send button never disappears (MAJOR 4, same review): mail is slow,
 * mail goes to spam, addresses get typo'd — after a send it relabels to
 * "send again", and editing the address re-arms it. The language toggle is
 * HERE too (MAJOR 5): this is the first screen a new device ever shows,
 * and a Hebrew-only door with the switch behind it locks out exactly the
 * person it was added for.
 *
 * ⚠ The email input is `dir="ltr"` INSIDE an RTL page: an address is a
 * Latin-script string. Direction per string, alignment per container.
 */
import { useState, type FormEvent } from 'react'

import { ApiError, requestLoginLink } from '../api/client'
import { useI18n } from './i18n'

export function LoginScreen({ linkError = false }: { linkError?: boolean }) {
  const { t, lang, toggleLang } = useI18n()
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [delivery, setDelivery] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [showLinkError, setShowLinkError] = useState(linkError)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!email.trim() || sending) return
    setSending(true)
    setError(null)
    setShowLinkError(false)
    try {
      const answer = await requestLoginLink(email)
      setSent(true)
      setDelivery(answer.delivery ?? '')
    } catch (err) {
      // Localized by CLASS of failure, never String(err): the raw
      // exception put "ApiError: POST /api/v1/auth/link failed: 502" in
      // English on a Hebrew family screen (UX review, MAJOR 3).
      setError(err instanceof ApiError && err.status === 429
        ? t.login_rate
        : t.login_error)
    } finally {
      setSending(false)
    }
  }

  return (
    <main className="login">
      <form onSubmit={submit} aria-label={t.login_title}>
        <div className="loginbar">
          <h1 className="rtl-safe">{t.login_title}</h1>
          <button
            type="button"
            className="langswitch"
            onClick={toggleLang}
            aria-label={lang === 'he' ? 'Switch to English' : 'עברו לעברית'}
          >
            {t.lang}
          </button>
        </div>
        <p className="hint rtl-safe">{t.login_intro}</p>
        <label className="field">
          <span>{t.login_email}</span>
          <input
            type="email"
            dir="ltr"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value)
              // Editing the address re-arms the flow: the previous "on
              // its way" no longer describes what will happen next.
              setSent(false)
            }}
            autoFocus
            autoComplete="email"
            inputMode="email"
            name="email"
          />
        </label>
        {showLinkError && (
          <p className="hint warn rtl-safe" role="alert">{t.login_link_bad}</p>
        )}
        {error && (
          <p className="hint warn rtl-safe" role="alert">{error}</p>
        )}
        {sent && (
          <>
            <p className="hint ok rtl-safe">{t.login_sent}</p>
            {delivery === 'server-log' && (
              <p className="hint rtl-safe">{t.login_sent_log}</p>
            )}
          </>
        )}
        <button
          type="submit"
          className="btn primary"
          disabled={sending || !email.trim()}
        >
          {sending ? t.login_sending : sent ? t.login_again : t.login_send}
        </button>
      </form>
    </main>
  )
}
