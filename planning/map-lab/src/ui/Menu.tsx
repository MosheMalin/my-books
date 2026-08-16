/**
 * A small dropdown menu.
 *
 * It exists so the edit commands can stop occupying five toolbar slots once
 * they are all reachable from the keyboard (owner, 2026-08-16). Each row
 * prints its own shortcut, which is also how anyone discovers that the
 * shortcuts exist at all.
 */

import { useEffect, useRef, useState } from 'react'

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
        <div className="menu-pop" role="menu">
          {items.map((it) => (
            <button
              key={it.label}
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
              <span>
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
