/**
 * The staff credential: entering it, and saying loudly when there isn't one.
 *
 * ⚠ Two different states, and conflating them would be the bug worth avoiding:
 *
 *   - **the service demands a token and we have none or a wrong one** — the
 *     console cannot show anything, so this is a blocking form;
 *   - **the service demands nothing** — everything works, and that is the
 *     dangerous case: a port anyone on the LAN can read every tenant through.
 *     It gets a warning banner, not silence, because the product's own
 *     "no login until pillar 4" trade does NOT extend to a cross-tenant
 *     surface, and an operator should be told rather than discover it.
 */
import { useState } from 'react'

import { getStaffToken, setStaffToken } from '../api/staff'
import { useI18n } from './i18n'

export function StaffTokenForm({ onSaved }: { onSaved: () => void }) {
  const { t } = useI18n()
  const [value, setValue] = useState(getStaffToken() ?? '')

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setStaffToken(value)
    onSaved()
  }

  return (
    <form className="card" onSubmit={submit} style={{ maxWidth: 460 }}>
      <h2 style={{ marginTop: 0 }}>{t.token_title}</h2>
      <p className="sub">{t.token_needed}</p>
      <label className="field">
        {t.token_title}
        {/* `type=password`: it is a shared secret, and an admin console is
            exactly the screen someone screen-shares while debugging. */}
        <input type="password" value={value} autoFocus autoComplete="off"
               onChange={(e) => setValue(e.target.value)} />
      </label>
      <p className="sub" style={{ margin: '6px 0 10px' }}>{t.token_hint}</p>
      <div className="row">
        <button type="submit" className="btn primary" disabled={!value.trim()}>
          {t.token_save}
        </button>
        <button type="button" className="btn" onClick={() => {
          setStaffToken(undefined)
          setValue('')
          onSaved()
        }}>
          {t.token_clear}
        </button>
      </div>
    </form>
  )
}

/** Shown on every screen while the staff service has no credential at all. */
export function OpenServiceWarning() {
  const { t } = useI18n()
  return <p className="note warn" style={{ marginBottom: 12 }}>{t.token_open_warning}</p>
}
