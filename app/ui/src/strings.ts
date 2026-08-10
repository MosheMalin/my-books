/**
 * Strings for the controls this package draws, and nothing else.
 *
 * The line is: **this package owns the vocabulary of a mechanism; an app owns
 * the vocabulary of its subject.** "Ascending order" describes a button that
 * exists here; "awaiting approval" describes a state the product has opinions
 * about. So a sort control's direction labels live here and its OPTIONS are
 * passed in — the list of what a screen can sort by is a product question, and
 * two screens genuinely differ on it.
 *
 * ⚠ The status ladder is here as an exception worth naming: `auto < approved <
 * manual` is VISION §5.1, and BOTH clients render it as a badge. One table
 * means the console and the product cannot come to disagree about what
 * "manual" is called — which is a real risk, because they already disagreed
 * about whether `manual` counts as vouched-for (the product shipped that bug;
 * see CLAUDE.md, "A hand-typed book wears the approved badge too").
 */
import type { Lang } from './i18n'

export interface UiStrings {
  /** The sort control's direction toggle. */
  sort_asc: string
  sort_desc: string
  /** The async states shared by every screen. */
  loading: string
  load_error: string
  retry: string
  /** VISION §5.1's ladder. */
  st_auto: string
  st_approved: string
  st_manual: string
}

const HE: UiStrings = {
  sort_asc: 'סדר עולה',
  sort_desc: 'סדר יורד',
  loading: 'טוען…',
  load_error: 'אין חיבור לשרת',
  retry: 'נסו שוב',
  st_auto: 'זוהה אוטומטית',
  st_approved: 'אושר',
  st_manual: 'ידני',
}

const EN: UiStrings = {
  sort_asc: 'Ascending',
  sort_desc: 'Descending',
  loading: 'Loading…',
  load_error: 'No connection to the server',
  retry: 'Try again',
  // ⚠ The PRODUCT's exact words, both languages, because that is the app
  // the owner has actually used. Note the asymmetry between them is the
  // product's own and is kept deliberately: the Hebrew says "was
  // auto-detected" and the English says "Auto". Changing either is a
  // product decision, made HERE now, once, for both clients.
  st_auto: 'Auto',
  st_approved: 'Approved',
  st_manual: 'Manual',
}

export const UI_STRINGS: Record<Lang, UiStrings> = { he: HE, en: EN }
