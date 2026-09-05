/**
 * An explanation you have to ask for (P6.8b).
 *
 * The owner, walking the bookcase panel: *"explanation messages should be
 * tooltips, and not 'in the face' of the users… the feeling is that it's too
 * crowded."*
 *
 * ⚠ **Not a `title`.** CLAUDE.md records the measurement that rules it out:
 * *"On screen, not in a `title`. The hole's own explanation lived in a hover
 * tooltip, which a phone never shows — and the phone is the device this is
 * catalogued from."* A hover tooltip would not tuck these sentences away, it
 * would delete them on the one device that matters. So this is a DISCLOSURE:
 * hidden until pressed, pressable with a thumb, and hoverable on a desktop
 * because that costs one CSS rule.
 *
 * ⚠ **What belongs behind it, and what does not.** An EXPLANATION — a rule
 * you could not guess, said the same way every time, true of every bookcase.
 * Not a refusal (*"they hold books"*), not a state (*"the front is the short
 * side"*), not a count. Those are about the thing in front of you and have
 * earned their place on screen; hiding them would be the opposite of this
 * item, which is about noise rather than about saying less.
 *
 * ⚠ The revealed text is rendered only while open, so a screen reader meets
 * it once and in the order a sighted reader does. The button carries the
 * subject in its accessible name — twenty ⓘ buttons all called "info" is the
 * accessible-name collision this repo keeps meeting.
 */
import { useId, useState } from 'react'

import { useI18n } from './i18n'

export function Hint({ about, children }: {
  /** What this explains, for the button's accessible name. Never omitted:
   *  a panel has several, and "more information" ×5 names nothing. */
  about: string
  children: React.ReactNode
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <span className="hint">
      <button
        type="button"
        className="hint-ask"
        aria-label={t.explain(about)}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
      >
        ⓘ
      </button>
      {open && (
        <p className="note hint-said rtl-safe" id={id}>{children}</p>
      )}
    </span>
  )
}
