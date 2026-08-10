/**
 * A dropdown that looks the same in both applications.
 *
 * Owner's call, 2026-08-11, looking at the two clients side by side: the sort
 * control had a drawn chevron and every other `<select>` had the browser's,
 * so one dropdown on the page looked designed and the rest looked defaulted.
 * The fix is not to make the sort control less special — it is to give every
 * dropdown the same treatment.
 *
 * ⚠ It replaces the CHEVRON and nothing else. The box — radius, border,
 * padding, the surface it sits on — stays each app's own, because the two
 * palettes are deliberately different (a reading surface and a dense table
 * surface, argued at length in `app/ui/README.md`). The chevron is shared
 * because it is the one part a stylesheet cannot reach: Chrome pins the UA
 * arrow a fixed distance from the border and ignores `padding-inline-end`, so
 * the only way to control it is `appearance: none` plus one of our own.
 *
 * ⚠ Drawn from two borders, not a background-image data URI. A data URI
 * cannot read `var(--ui-muted)`, so it would need a second copy per colour
 * scheme and would go stale in one of them — the reason the sort control drew
 * its own in the first place.
 *
 * Every prop a `<select>` takes is forwarded, so this is a drop-in: the
 * wrapper exists only to give the chevron something to position against.
 */
import type { ReactNode, SelectHTMLAttributes } from 'react'

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  children: ReactNode
  /**
   * Fill the container instead of shrinking to the longest option — for a
   * select in a form column or an intake row. Off by default: a filter beside
   * other controls should be as wide as its content.
   */
  wide?: boolean
}

export function Select({ children, wide = false, className, ...rest }: SelectProps) {
  return (
    <span className={`uisel${wide ? ' wide' : ''}`}>
      <select className={className} {...rest}>
        {children}
      </select>
    </span>
  )
}
