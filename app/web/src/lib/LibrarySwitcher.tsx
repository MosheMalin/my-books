/**
 * The library switcher in the app bar (UI_PLAN §1, P3.1).
 *
 * §4.1 makes Library the tenancy boundary and an account may belong to
 * several, so the app bar has to say which one you are looking at — as a
 * plain label while there is one library (the P1.0 shape, reinstated by the
 * ⚠ below), and as this switcher the moment a second one exists.
 *
 * ⚠ A button and a panel, not a `<select>`. The list ends in *"+ new
 * library"*, which is an ACTION, and an `<option>` that performs one is a
 * control that lies about what it is (the sort control's own chevron trap is
 * the same family: a native select is the wrong element the moment its
 * options stop being values). It also lets the current row carry a check
 * mark, which a select cannot.
 *
 * ⚠ **One library renders as a plain LABEL, not a switcher** (owner,
 * 2026-08-10, settling §4.1's tenancy rule). A tenant is an ownership
 * boundary, never a geography: rooms and sites are pillar-6 Places, and
 * until Place exists a Library is the only noun this UI offers — so an
 * always-present "+ new library" was actively inviting "child room" to be
 * modelled as a TENANT, with the silent cost §4.1 records (a second copy of
 * a book you own would never be flagged across the boundary). The menu, and
 * with it creation, appears once a second library GENUINELY exists (another
 * household's, via membership — or made through the API for the rare
 * separate-collection case). Same "absent, not disabled" reasoning as every
 * other control that waits for its pillar; P4.3's invites are the real
 * multi-library path.
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
  // ONE failure presentation, used by both branches below — the two strings
  // are identical today, and the day they differ a second copy would let the
  // label's title disagree with its own visible text (quality review).
  const shown = failed ? t.library_unknown : name

  // See the module note: one library = a label, not an invitation.
  // `title` because the label ellipsizes at 34ch and — unlike the button —
  // there is no menu behind it to show the full name (review finding).
  if (libraries.length <= 1) {
    return (
      <div className="libswitch">
        <span className="libswitch-label rtl-safe" title={shown}>
          {shown}
        </span>
      </div>
    )
  }

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
        <span className="rtl-safe">{shown}</span>
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
                aria-describedby="libswitch-create-hint"
              />
              {/* §4.1's settled rule, stated where the choice is made (the
                  same principle as the mode selector's cost note): a library
                  is a separate collection, and rooms are not libraries.
                  Linked to the input so a screen reader hears it at the
                  moment it was written for (review finding). */}
              <p id="libswitch-create-hint" className="tiny muted rtl-safe">
                {t.library_create_hint}
              </p>
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
