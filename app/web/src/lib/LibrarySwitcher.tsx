/**
 * The library switcher in the app bar (UI_PLAN §1, P3.1).
 *
 * §4.1 makes Library the tenancy boundary and an account may belong to
 * several, so the app bar has to say which one you are looking at — that is
 * why this replaces the plain label P1.0 put there.
 *
 * ⚠ A button and a panel, not a `<select>`. The list ends in *"+ new
 * library"*, which is an ACTION, and an `<option>` that performs one is a
 * control that lies about what it is (the sort control's own chevron trap is
 * the same family: a native select is the wrong element the moment its
 * options stop being values). It also lets the current row carry a check
 * mark, which a select cannot.
 *
 * ⚠ **Absent, not disabled, while there is only one library**: the switcher
 * still renders — it is the app bar's name for where you are — but a single
 * library means the panel is a list of one plus *new*, which is exactly what
 * it should say. Nothing is greyed out.
 */
import { useEffect, useRef, useState } from 'react'
import { useI18n } from './i18n'
import { useLibrary } from './library'

export function LibrarySwitcher() {
  const { t } = useI18n()
  const { libraries, current, currentId, failed, switchTo, create } = useLibrary()
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLInputElement>(null)

  // Click-away and Escape both close it. A menu that can only be closed by
  // picking something is a menu you cannot cancel.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => {
    if (adding) field.current?.focus()
  }, [adding])

  const close = () => {
    setOpen(false)
    setAdding(false)
    setLabel('')
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = label.trim()
    if (!name || busy) return
    setBusy(true)
    try {
      await create(name)
      close()
    } catch {
      // The form stays open with what was typed still in it — a 409 or a
      // dropped connection must not eat the name the owner just chose.
    } finally {
      setBusy(false)
    }
  }

  // The name of a library the server has not told us about yet, or could not.
  // Never blank: the app bar with an empty slot reads as a rendering bug.
  const name = current?.label || t.library_unnamed

  return (
    <div className="libswitch" ref={box}>
      <button
        type="button"
        className="libswitch-btn rtl-safe"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t.library_switch}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <span className="rtl-safe">{failed ? t.library_unknown : name}</span>
        <span className="libswitch-caret" aria-hidden="true" />
      </button>

      {open && (
        <div className="libswitch-menu" role="menu">
          {libraries.map((lib) => (
            <button
              key={lib.id}
              type="button"
              role="menuitemradio"
              aria-checked={lib.id === currentId}
              className={lib.id === currentId ? 'on rtl-safe' : 'rtl-safe'}
              onClick={() => {
                switchTo(lib.id)
                close()
              }}
            >
              <span className="rtl-safe">{lib.label || t.library_unnamed}</span>
              <span className="muted libswitch-role">{t.role[lib.role] ?? lib.role}</span>
            </button>
          ))}

          {adding ? (
            <form className="libswitch-new" onSubmit={submit}>
              <input
                ref={field}
                className="rtl-safe"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t.library_name_placeholder}
                aria-label={t.library_name}
              />
              <button type="submit" disabled={busy || !label.trim()}>
                {t.library_create}
              </button>
              <button type="button" onClick={() => setAdding(false)}>
                {t.cancel}
              </button>
            </form>
          ) : (
            <button
              type="button"
              role="menuitem"
              className="libswitch-add"
              onClick={() => setAdding(true)}
            >
              {t.library_new}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
