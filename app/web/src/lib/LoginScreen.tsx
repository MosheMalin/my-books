/**
 * The sign-in screen (P4.1b) — the whole app, when nobody is signed in.
 *
 * One field, one button, and the honest answer: the server says the same
 * thing whether the address is known or not (anti-enumeration is ITS rule;
 * this screen just repeats the sentence it was given). In dev the "mail"
 * is the server log — the ConsoleMailer prints the link — and the screen
 * does not say so, because the screen cannot know which mailer is bound.
 *
 * ⚠ The email input is `dir="ltr"` INSIDE an RTL page: an address is a
 * Latin-script string, and typing one into an RTL input renders the caret
 * dancing around the @. Direction per string, alignment per container —
 * the `.rtl-safe` rule's other half.
 */
import { useState, type FormEvent } from 'react'

import { requestLoginLink } from '../api/client'
import { useI18n } from './i18n'

export function LoginScreen({ linkError = false }: { linkError?: boolean }) {
  const { t } = useI18n()
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!email.trim() || sending) return
    setSending(true)
    setError(null)
    try {
      await requestLoginLink(email)
      setSent(true)
    } catch (err) {
      setError(String(err))
    } finally {
      setSending(false)
    }
  }

  return (
    <main className="login">
      <form onSubmit={submit} aria-label={t.login_title}>
        <h1 className="rtl-safe">{t.login_title}</h1>
        <p className="hint rtl-safe">{t.login_intro}</p>
        <label className="field">
          <span>{t.login_email}</span>
          <input
            type="email"
            dir="ltr"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
            autoComplete="email"
            inputMode="email"
            name="email"
          />
        </label>
        {linkError && !sent && (
          <p className="hint warn rtl-safe" role="alert">{t.login_link_bad}</p>
        )}
        {error && (
          <p className="hint warn rtl-safe" role="alert">{error}</p>
        )}
        {sent ? (
          <p className="hint ok rtl-safe">{t.login_sent}</p>
        ) : (
          <button
            type="submit"
            className="btn primary"
            disabled={sending || !email.trim()}
          >
            {sending ? t.login_sending : t.login_send}
          </button>
        )}
      </form>
    </main>
  )
}
