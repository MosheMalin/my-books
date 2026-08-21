/**
 * A small dropdown menu.
 *
 * It exists so the edit commands can stop occupying five toolbar slots once
 * they are all reachable from the keyboard (owner, 2026-08-16). Each row
 * prints its own shortcut, which is also how anyone discovers that the
 * shortcuts exist at all.
 */

import { useEffect, useRef, useState } from 'react'

import { useI18n } from '../../lib/i18n'

export type MenuItem = {
  label: string
  shortcut?: string
  disabled?: boolean
  danger?: boolean
  /** Present makes the row a toggle, and it renders its state. Absent leaves
   *  it a plain command — `false` and "not a toggle" are different things. */
  checked?: boolean
  onSelect: () => void
}

export function Menu({
  label,
  items,
  title,
}: {
  label: string
  items: MenuItem[]
  title?: string
}) {
  const [open, setOpen] = useState(false)
  const dir = useI18n().lang === 'he' ? 'rtl' : 'ltr'
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const away = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    // `pointerdown`, not `click`: the canvas acts on pointerdown, so a click
    // listener would close the menu only after the plan had already reacted
    // to the same press.
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  return (
    <div className="menu" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label || title}
        title={title}
        className={open ? 'on' : ''}
        onClick={() => setOpen((o) => !o)}
      >
        {label} ▾
      </button>
      {open && (
        // ⚠ `dir` stated, because this menu is mounted in two places with two
        // directions: the toolbar inherits the UI's, and the floor badge sits
        // inside the plan, which is pinned LTR (MAP_PLAN §3.5). A review
        // measured the badge's rows left-aligned in Hebrew while the toolbar's
        // were right-aligned — one component, two answers, on one screen. The
        // rows carry the owner's own site and floor names.
        <div className="menu-pop" role="menu" dir={dir}>
          {items.map((it, at) => (
            <button
              // ⚠ By POSITION, not by label. Two sites can be called the same
              // thing — a two-tab race mints two `הבית`, and the picker is
              // where that duplicate is supposed to become removable — and
              // React answered a duplicate key by dropping one of the rows,
              // which is the one state in which the picker cannot fix it.
              key={at}
              type="button"
              disabled={it.disabled}
              className={it.danger ? 'danger' : ''}
              aria-checked={it.checked}
              role={it.checked === undefined ? 'menuitem' : 'menuitemcheckbox'}
              onClick={() => {
                setOpen(false)
                it.onSelect()
              }}
            >
              {/* ⚠ `rtl-safe`: a row's label can carry USER text — a floor's
                  name is interpolated into *rename* and *remove* — and a
                  mixed-script name in a menu resolves its own direction only
                  if something says so. The panel's own lists have carried this
                  class since the lab; the menu had not. */}
              <span className="rtl-safe">
                {it.checked !== undefined && (
                  <span className="tick" aria-hidden="true">
                    {it.checked ? '✓' : ' '}
                  </span>
                )}
                {it.label}
              </span>
              {it.shortcut && <kbd>{it.shortcut}</kbd>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
