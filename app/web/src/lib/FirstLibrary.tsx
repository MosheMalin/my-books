/**
 * The first-library screen (P4.1c, §4.3 step 2) — what a signed-in user
 * with NO library sees instead of the tabs.
 *
 * Naming the library IS the sign-up's second half: the server mints the
 * Account with it, so pressing create turns a bare identity into a
 * customer with somewhere to put a book. Exactly ONE library, and no
 * "add another" anywhere on this screen — a second library is a later,
 * deliberate act carrying the switcher's own guidance (§4.1).
 */
import { useState, type FormEvent } from 'react'

import { useI18n } from './i18n'
import { useLibrary } from './library'

export function FirstLibrary() {
  const { t } = useI18n()
  const { create } = useLibrary()
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!label.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      await create(label)
      // The provider switches to it and the tabs take over — this screen
      // simply stops being rendered.
    } catch (err) {
      setError(String(err))
      setBusy(false)
    }
  }

  return (
    <main className="login">
      <form onSubmit={submit} aria-label={t.onboard_title}>
        <h1 className="rtl-safe">{t.onboard_title}</h1>
        <p className="hint rtl-safe">{t.onboard_intro}</p>
        <label className="field">
          <span>{t.library_name}</span>
          <input
            className="rtl-safe"
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            autoFocus
            placeholder={t.library_name_placeholder}
          />
        </label>
        {error && (
          <p className="hint warn rtl-safe" role="alert">{error}</p>
        )}
        <button
          type="submit"
          className="btn primary"
          disabled={busy || !label.trim()}
        >
          {t.onboard_create}
        </button>
      </form>
    </main>
  )
}
