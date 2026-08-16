/**
 * The map editor's own vocabulary, he/en.
 *
 * A table of its own rather than more keys in `lib/i18n.tsx`, for the reason
 * `app/ui/src/strings.ts` gives about the line between a package's vocabulary
 * and an app's: these words describe a MECHANISM that arrived whole from
 * `planning/map-lab` — *draw room*, *turn the bookcase*, *ghost the other
 * floors* — and they change together with it. The app's own nouns (books,
 * shelves, capture) stay where they are.
 *
 * ⚠ Hebrew is the product's language (VISION §6), and the lab was English —
 * the port would have shipped an English island inside a Hebrew app. English
 * is kept for the same reason the rest of the app keeps it: a real LTR mode
 * is the only honest way to test that the layout mirrors.
 *
 * ⚠ **Every control gets its OWN label.** Two controls announcing the same
 * accessible name collide, and CLAUDE.md records that the pair left colliding
 * last time included *rename* — the one that writes. The per-floor actions
 * here (rename, remove) are the same shape, so they name their floor.
 */
import type { Lang } from '../lib/i18n'

export interface MapText {
  // tools
  tool: string
  arrow: string
  draw_room: string
  draw_case: string
  pan: string
  zoom_in: string
  zoom_out: string
  show_all: string
  hint_arrow: string
  hint_room: string
  hint_case: string
  hint_pan: string
  // menus
  menu_plan: string
  menu_edit: string
  menu_view: string
  menu_draw: string
  reload: string
  clear_plan: string
  undo: string
  redo: string
  copy: string
  paste: string
  delete: string
  delete_many: (n: number) => string
  new_depth: string
  default_depth: string
  default_depth_of: (section: string) => string
  apply_depth: string
  apply_depth_of: (section: string) => string
  new_levels: string
  default_levels: string
  default_levels_of: (section: string) => string
  apply_levels: string
  apply_levels_of: (section: string) => string
  rows_deep: (n: number) => string
  shelf_at: (addr: string, col: number, level: number) => string
  remove_level: (addr: string, col: number) => string
  add_level: (addr: string, col: number) => string
  // floors
  floor: string
  add_floor: string
  rename_floor: (name: string) => string
  remove_floor: (name: string) => string
  rename_floor_hint: string
  floor_name: string
  all_floors: string
  all_floors_long: string
  ghost_floors: string
  // the plan
  plan_canvas: string
  nothing_selected: string
  room: string
  bookcase: string
  name: string
  moves_with: string
  stands_alone: string
  books_face: string
  turn_case: string
  cases_attached: string
  // the elevation
  own_depth: string
  photos_attached: string
  shelf_depth: string
  shelf_photos: string
  // chrome
  black_bg: string
  white_bg: string
  trace: string
  trace_upload: string
  trace_remove: string
  trace_opacity: string
  trace_size: string
  panel_resize: string
  saving: string
  saved: string
  save_failed: string
}

const HE: MapText = {
  tool: 'כלי',
  arrow: 'חץ',
  draw_room: 'ציור חדר',
  draw_case: 'ציור כוננית',
  pan: 'הזזת התצוגה',
  zoom_in: 'הגדלה',
  zoom_out: 'הקטנה',
  show_all: 'הצגת הכול',
  hint_arrow: 'חץ — מנחש לפי נקודת הלחיצה: קו של חדר מזיז אותו, בתוך חדר מצייר כוננית, מחוץ לכל חדר מצייר חדר. Ctrl+גרירה בוחר כמה.',
  hint_room: 'ציור חדר — תמיד מצייר חדר, מכל נקודת התחלה.',
  hint_case: 'ציור כוננית — תמיד מצייר כוננית, מכל נקודת התחלה.',
  hint_pan: 'הזזת התצוגה — גם הכפתור האמצעי ושתי אצבעות עושים זאת.',
  menu_plan: 'תוכנית',
  menu_edit: 'עריכה',
  menu_view: 'תצוגה',
  menu_draw: 'הדירה',
  reload: 'טעינה מחדש מהשרת',
  clear_plan: 'מחיקת התוכנית',
  undo: 'ביטול',
  redo: 'ביצוע מחדש',
  copy: 'העתקה',
  paste: 'הדבקה',
  delete: 'מחיקה',
  delete_many: (n) => `מחיקת ${n} פריטים`,
  new_depth: 'עומק חדש',
  default_depth: 'עומק ברירת מחדל',
  default_depth_of: (s) => `עומק ברירת מחדל, ${s}`,
  apply_depth: 'החלת עומק ברירת המחדל על כל המדפים',
  apply_depth_of: (s) => `החלת עומק ברירת המחדל על כל המדפים של ${s}`,
  new_levels: 'מספר מדפים חדש',
  default_levels: 'מספר מדפים בעמודה, ברירת מחדל',
  default_levels_of: (s) => `מספר מדפים בעמודה, ברירת מחדל, ${s}`,
  apply_levels: 'החלת ברירת המחדל על כל העמודות',
  apply_levels_of: (s) => `החלת ברירת המחדל על כל העמודות של ${s}`,
  rows_deep: (n) => `${n} שורות לעומק`,
  shelf_at: (a, c, l) => `מדף, ${a}עמודה ${c}, גובה ${l}`,
  remove_level: (a, c) => `הסרת מדף מ${a}עמודה ${c}`,
  add_level: (a, c) => `הוספת מדף ל${a}עמודה ${c}`,
  floor: 'קומה',
  add_floor: 'הוספת קומה',
  rename_floor: (name) => `שינוי שם הקומה ${name}`,
  remove_floor: (name) => `הסרת הקומה ${name}`,
  rename_floor_hint: 'לחיצה כפולה לשינוי שם הקומה',
  floor_name: 'שם הקומה',
  all_floors: 'כל הקומות',
  all_floors_long: 'כל הקומות, זו לצד זו',
  ghost_floors: 'הצללת שאר הקומות',
  plan_canvas: 'תוכנית הבית',
  nothing_selected: 'לא נבחר דבר',
  room: 'חדר',
  bookcase: 'כוננית',
  name: 'שם',
  moves_with: 'זזה עם',
  stands_alone: 'שום דבר — עומדת בפני עצמה',
  books_face: 'הספרים פונים אל',
  turn_case: 'סיבוב הכוננית',
  cases_attached: 'כוננויות מחוברות',
  own_depth: 'העומק שלו',
  photos_attached: 'תמונות מצורפות',
  shelf_depth: 'עומק המדף הזה',
  shelf_photos: 'תמונות המצורפות למדף הזה',
  black_bg: 'רקע שחור',
  white_bg: 'רקע לבן',
  trace: 'העתקה משרטוט…',
  trace_upload: 'העלאת תוכנית להעתקה',
  trace_remove: 'הסרת השרטוט',
  trace_opacity: 'שקיפות השרטוט',
  trace_size: 'גודל השרטוט',
  panel_resize: 'גרירה לשינוי רוחב לוח ההגדרות',
  saving: 'שומר…',
  saved: 'נשמר',
  save_failed: 'לא נשמר',
}

const EN: MapText = {
  tool: 'tool',
  arrow: 'Arrow',
  draw_room: 'Draw room',
  draw_case: 'Draw bookcase',
  pan: 'Pan',
  zoom_in: 'Zoom in',
  zoom_out: 'Zoom out',
  show_all: 'Show all',
  hint_arrow: 'Arrow — guesses from where you press: a room’s border moves it, inside a room draws a bookcase, outside every room draws a room. Ctrl+drag selects several.',
  hint_room: 'Draw room — always draws a room, wherever you start.',
  hint_case: 'Draw bookcase — always draws a bookcase, wherever you start.',
  hint_pan: 'Pan — slide the plan. So do the middle button and two fingers.',
  menu_plan: 'Plan',
  menu_edit: 'Edit',
  menu_view: 'View',
  menu_draw: 'Apartment',
  reload: 'Reload from the server',
  clear_plan: 'Clear the plan',
  undo: 'Undo',
  redo: 'Redo',
  copy: 'Copy',
  paste: 'Paste',
  delete: 'Delete',
  delete_many: (n) => `Delete ${n}`,
  new_depth: 'new depth',
  default_depth: 'default depth',
  default_depth_of: (s) => `default depth, ${s.toLowerCase()}`,
  apply_depth: 'apply the depth default to every shelf',
  apply_depth_of: (s) => `apply the depth default to every shelf of ${s.toLowerCase()}`,
  new_levels: 'new levels',
  default_levels: 'default levels per column',
  default_levels_of: (s) => `default levels per column, ${s.toLowerCase()}`,
  apply_levels: 'apply the level default to every column',
  apply_levels_of: (s) => `apply the level default to every column of ${s.toLowerCase()}`,
  rows_deep: (n) => `${n} rows front-to-back`,
  shelf_at: (a, c, l) => `shelf, ${a}column ${c}, level ${l}`,
  remove_level: (a, c) => `remove a level from ${a}column ${c}`,
  add_level: (a, c) => `add a level to ${a}column ${c}`,
  floor: 'Floor',
  add_floor: 'Add a floor',
  rename_floor: (name) => `Rename the floor ${name}`,
  remove_floor: (name) => `Remove the floor ${name}`,
  rename_floor_hint: 'Double-click to rename this floor',
  floor_name: 'floor name',
  all_floors: 'All floors',
  all_floors_long: 'All floors, side by side',
  ghost_floors: 'Ghost the other floors',
  plan_canvas: 'floor plan',
  nothing_selected: 'Nothing selected',
  room: 'Room',
  bookcase: 'Bookcase',
  name: 'Name',
  moves_with: 'Moves with',
  stands_alone: 'nothing — stands alone',
  books_face: 'Books face',
  turn_case: 'turn the bookcase',
  cases_attached: 'Bookcases attached',
  own_depth: 'Its own depth',
  photos_attached: 'Photos attached',
  shelf_depth: "this shelf's depth",
  shelf_photos: 'photos attached to this shelf',
  black_bg: 'Black background',
  white_bg: 'White background',
  trace: 'Trace a sketch…',
  trace_upload: 'upload a floor plan to trace',
  trace_remove: 'remove the underlay',
  trace_opacity: 'underlay opacity',
  trace_size: 'underlay size',
  panel_resize: 'drag to resize the settings panel',
  saving: 'Saving…',
  saved: 'Saved',
  save_failed: 'Not saved',
}

export const mapText = (lang: Lang): MapText => (lang === 'he' ? HE : EN)
