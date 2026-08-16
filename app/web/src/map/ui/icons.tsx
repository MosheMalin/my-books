/**
 * Tool icons, drawn rather than typed.
 *
 * The first pair were `▭` and `▬` — *"simply white and black rects"* (owner,
 * 2026-08-16), which is exactly what they were: the same shape twice, told
 * apart only by fill. A room is now an outline **with a door gap**, and a
 * bookcase is a box **with shelves in it**. Neither needs the tooltip to be
 * understood.
 */

const box = { viewBox: '0 0 16 16', width: 16, height: 16, 'aria-hidden': true } as const

export function ArrowIcon() {
  return (
    <svg {...box} className="ic">
      <path d="M3 2 L3 13 L6.2 10.2 L8.3 14.2 L10.2 13.2 L8.2 9.4 L12.5 9.2 Z" />
    </svg>
  )
}

/** A room: four walls and the gap you walk through. */
export function RoomIcon() {
  return (
    <svg {...box} className="ic stroke">
      <path d="M2.5 3.5 H13.5 V12.5 H9.5 M6.5 12.5 H2.5 V3.5" />
    </svg>
  )
}

/** A bookcase: a carcass with shelves. */
export function CaseIcon() {
  return (
    <svg {...box} className="ic stroke">
      <rect x="3" y="2.5" width="10" height="11" rx="0.6" />
      <path d="M3 6.2 H13 M3 9.9 H13" />
    </svg>
  )
}

/** Pan: four ways out, which is what sliding the plan does. A hand at 16 px is
 *  a smudge. */
export function PanIcon() {
  return (
    <svg {...box} className="ic stroke">
      <path d="M8 2 V14 M2 8 H14" />
      <path d="M8 2 L6.2 4 M8 2 L9.8 4 M8 14 L6.2 12 M8 14 L9.8 12" />
      <path d="M2 8 L4 6.2 M2 8 L4 9.8 M14 8 L12 6.2 M14 8 L12 9.8" />
    </svg>
  )
}
