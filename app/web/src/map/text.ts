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
 * last time included *rename* — the one that writes. The per-floor and
 * per-section actions here name their floor or their section.
 *
 * ⚠ **`section` stays `section` in the CODE.** MAP_PLAN §3.6 argues the
 * English noun at length (not *unit*, not *tier*), and that argument is about
 * the identifier. The Hebrew the owner reads is *יחידה*, which is what modular
 * shelving is called in a shop — the two are allowed to differ, and this note
 * exists so the next reader does not "fix" one into the other.
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
  hint_overview: string
  no_drawing_here: string
  // menus
  menu_plan: string
  menu_edit: string
  menu_view: string
  reload: string
  undo: string
  redo: string
  /**
   * P6.4b's SERVER undo, and its own label on purpose.
   *
   * ⚠ It is not `undo`, and the two must never announce the same name. They
   * do different things: `undo` steps the DRAWING back one commit and can be
   * pressed two hundred times; this one asks the server to put back the rows
   * the last destructive edit destroyed — shelves, with their labels and the
   * books standing on them — and there is exactly one of it, with no redo.
   */
  undo_last_edit: string
  /** What just happened, said at the moment it is still true.
   *
   *  ⚠ This exists because the WRONG control is closer to hand. `undo` sits
   *  first in the same menu, becomes enabled the instant something is
   *  deleted, and re-DRAWS the slot — minting a new empty shelf while the
   *  owner's label and books stay behind on a detached row. It looks like it
   *  worked. No label on either row fixes that, because the owner never
   *  compares them; a sentence at the moment of the delete does. It also has
   *  to be said NOW rather than whenever they next open a menu, because the
   *  fingerprint gives this undo a shelf life. */
  undo_offered: string
  undo_done: (restored: number) => string
  undo_nothing: string
  undo_already: string
  undo_moved: (shelves: number, others: number) => string
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
  apply: string
  rows_deep: (n: number) => string
  shelf_at: (addr: string, col: number, level: number) => string
  /** P6.3.2b — a cell switched off. Named for what tapping it DOES, not
   *  for what it is: an accessible name has to name an action. */
  restore_cell: (addr: string, col: number, level: number) => string
  restore_cell_title: string
  marked_cells: (n: number) => string
  make_space: (n: number) => string
  make_space_title: string
  /** Named per CAUSE. A review pressed the control with a cell that was empty
   *  but two rows deep and read *"clear them first"* — a remedy that does not
   *  exist for that cause, which is CLAUDE.md's "a wrong stated reason is
   *  worse than none" exactly. */
  cells_have_books: (n: number) => string
  cells_have_photos: (n: number) => string
  cells_are_deep: (n: number) => string
  gaps_are_tappable: string
  add_more_cells: string
  adding_more_cells: string
  remove_level: (addr: string, col: number) => string
  add_level: (addr: string, col: number) => string
  // sites (§3.9) — a grouping above the floors, never part of an address
  site: string
  site_menu: string
  site_n: (n: number) => string
  add_site: string
  rename_site: (name: string) => string
  remove_site: (name: string) => string
  site_name: string
  site_not_removed: (rooms: number, cases: number) => string
  remove_site_confirm: (name: string, floors: number) => string
  site_removed: (name: string) => string
  site_added: (name: string) => string
  overview_of: (site: string) => string
  // floors
  floor: string
  floor_menu: string
  floor_n: (n: number) => string
  add_floor: string
  rename_floor: (name: string) => string
  remove_floor: (name: string) => string
  rename_floor_hint: string
  floor_name: string
  all_floors: string
  all_floors_long: string
  ghost_floors: string
  one_floor_at_least: string
  floor_not_removed: (rooms: number, cases: number) => string
  read_only_bar: string
  back_to: (floor: string) => string
  the_plan: string
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
  turn_to: (side: string) => string
  side: (s: 'N' | 'E' | 'S' | 'W') => string
  cases_attached: string
  too_small: (squares: number) => string
  nothing_to_see: string
  too_many_slots: (asked: number, max: number) => string
  too_many_sections: (max: number) => string
  copied: (n: number) => string
  // the panel
  selected_n: (n: number) => string
  selected_mix: (rooms: number, cases: number) => string
  selected_carried: (n: number) => string
  delete_all: (n: number) => string
  delete_cases_confirm: (cases: number, shelves: number, photos: number) => string
  delete_room: string
  delete_case: string
  rooms_keep_their_cases: string
  size_units: string
  room_width: string
  room_height: string
  case_width: string
  case_height: string
  room_name_example: string
  case_name_example: string
  unnamed: string
  unnamed_room: (w: number, h: number) => string
  unnamed_case: (w: number, h: number) => string
  select_case: (name: string) => string
  no_cases_yet: string
  cases_move_with_room: string
  case_details: string
  case_summary: (name: string, w: number, h: number, side: string) => string
  case_facts: (units: number, deep: number, shelves: number) => string
  in_room: (name: string) => string
  in_no_room: string
  in_sections: (n: number) => string
  free_measurement: string
  counts: (rooms: number, cases: number) => string
  step_room: string
  step_case: string
  step_edit: string
  // the elevation
  section_n: (n: number) => string
  section_on_floor: string
  section_on_top: string
  add_section_top: string
  add_section_top_long: string
  add_section_under: string
  add_section_under_long: string
  split_sections: string
  split_sections_long: string
  remove_section: (section: string) => string
  remove_section_title: (section: string, shelves: number) => string
  remove_section_confirm: (section: string, shelves: number) => string
  col_head: (col: number) => string
  column: string
  add_column: string
  add_column_of: (section: string) => string
  remove_column: string
  remove_column_of: (section: string) => string
  remove_column_confirm: (shelves: number) => string
  depth_kept: (n: number, section: string) => string
  apply_to_all: (shelves: number) => string
  pick_a_cell: string
  shelf_legend: (where: string, col: number, level: number) => string
  // binding a shelf to a slot (P6.4c)
  shelf_is_named: (label: string) => string
  shelf_take_off_map: string
  shelf_take_off_map_confirm: (books: number, photos: number) => string
  cell_has_no_shelf: string
  empty_cell_legend: (where: string, col: number, level: number) => string
  put_a_shelf_here: string
  pick_a_shelf: string
  pick_a_shelf_cancel: string
  no_shelves_off_the_map: string
  shelf_list_failed: string
  shelf_list_retry: string
  shelf_holds_nothing: string
  empty_cell: (where: string, col: number, level: number) => string
  shelf_unnamed: string
  shelf_holds: (books: number, photos: number) => string
  pick_shelf_option: (n: number, name: string, books: number,
                      photos: number) => string
  bound_here: (name: string) => string
  unbound_shelf: (name: string) => string
  slot_moved_on: string
  // merging two identities into one (P6.4d)
  merge_a_shelf_here: string
  merge_pick: string
  merge_pick_option: (n: number, name: string, books: number,
                      photos: number) => string
  merge_reading: string
  merge_read_failed: string
  merge_would_move: (name: string, here: string) => string
  merge_books: (n: number) => string
  merge_photos: (n: number) => string
  merge_answers: (n: number) => string
  merge_identities: (n: number) => string
  merge_depth_after: (n: number) => string
  merge_moves_nothing: string
  merge_clashes: (n: number) => string
  merge_strip: string
  merge_strip_absorbed_first: (name: string) => string
  merge_strip_survivor_first: (name: string) => string
  merge_confirm: string
  merge_cancel: string
  merge_refused: string
  /** One of the six `MergeRefused` codes, or '' for one this table does not
   *  know — the caller then falls back to the server's own sentence. */
  merge_reason: (code: string) => string
  merge_pick_order: string
  merge_none_off_the_map: string
  merge_already: string
  merged_into: (name: string) => string
  undo_merged: (books: number) => string
  own_depth: string
  photos_attached: string
  // --- the cell as a place you can go to (P6.5c) ---
  last_read: string
  rows_stale: (n: number) => string
  open_this_shelf: string
  // --- levels proposed from a photo (P6.6) ---
  propose_levels: string
  propose_levels_hint: string
  proposing_levels: string
  /** ⚠ ONE key, with its own singular branch — not a second key beside it.
   *  The counted-string guard reads the TYPE, so `(n: number) => string`
   *  is a declaration that this string agrees with a number, and it
   *  caught «נספרו 1 מדפים» the moment it was written. The singular
   *  is not just grammar here: counting one band means the photo showed a
   *  single shelf, which is worth saying rather than merely conjugating. */
  proposed_levels: (n: number) => string
  propose_failed: string
  // --- reordering a stack of sections (P6.7a) ---
  move_section_up: (label: string) => string
  move_section_down: (label: string) => string
  section_moved: (label: string) => string
  // --- saving the drawing to a file (P6.7e) ---
  save_to_file: string
  saved_to_file: (name: string) => string
  // --- restoring a saved drawing (P6.7f) ---
  open_from_file: string
  restore_upload: string
  restore_not_a_plan: string
  restore_other_site: string
  restore_removes_nothing: string
  restore_nothing_lost: (cases: number) => string
  restore_costs: (cases: number, shelves: number, books: number) => string
  restore_backup_first: string
  restored: string
  photos_are_captures: string
  shelf_depth: string
  // chrome
  black_bg: string
  white_bg: string
  trace: string
  trace_upload: string
  trace_remove: string
  trace_opacity: string
  trace_size: string
  trace_fade_short: string
  trace_size_short: string
  trace_loaded: string
  trace_not_an_image: string
  trace_unreadable: string
  panel_resize: string
  saving: string
  saved: string
  save_failed: string
  saved_hint: string
  save_failed_hint: string
  not_saved_yet: string
  not_done_lead: string
  ground_floor: string
  refused_lead: string
  dismiss: string
}

/** *22 ספרים · תמונה אחת* — the house rule for a counted Hebrew string,
 *  which every other one in this table already follows. Written once because
 *  two keys print it: the picker's option and the row it labels. */
const heHolds = (books: number, photos: number) =>
  `${books === 1 ? 'ספר אחד' : `${books} ספרים`} · ${
    photos === 1 ? 'תמונה אחת' : `${photos} תמונות`}`

const enHolds = (books: number, photos: number) =>
  `${books === 1 ? '1 book' : `${books} books`} · ${
    photos === 1 ? '1 photo' : `${photos} photos`}`

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
  hint_overview: 'כל הקומות, זו לצד זו. לחיצה כפולה על אחת כדי לעבוד עליה.',
  no_drawing_here: 'תצוגת כל הקומות — אי אפשר לצייר',
  menu_plan: 'תוכנית',
  menu_edit: 'עריכה',
  menu_view: 'תצוגה',
  reload: 'טעינה מחדש מהשרת',
  undo: 'ביטול',
  redo: 'ביצוע מחדש',
  // ⚠ הוסר ולא נמחק: העורך קורא *מחיקה* לכוננית ולחדר, אבל *הסרה* לעמודה,
  // ליחידה, לקומה ולאתר — וחמש מהפעולות שנרשמות ביומן הן הסרות. תווית
  // שאומרת "מחיקה" לא נראית שייכת למי שהרגע לחץ "הסרת העמודה האחרונה".
  undo_last_edit: 'שחזור מה שהוסר לאחרונה',
  undo_offered: 'אפשר לשחזר: עריכה ▸ שחזור מה שהוסר לאחרונה',
  undo_done: (n) => (n === 1 ? 'מדף אחד חזר למקומו'
    : n ? `${n} מדפים חזרו למקומם` : 'מה שהוסר חזר למקומו'),
  undo_nothing: 'אין מה לשחזר',
  undo_already: 'הכול כבר חזר למקומו',
  undo_moved: (shelves, others) => {
    const what = others || !shelves
      ? `${shelves + others} פריטים במפה השתנו`
      : shelves === 1 ? 'מדף אחד השתנה' : `${shelves} מדפים השתנו`
    return `${what} מאז, ושחזור עכשיו היה מוחק את מה שנעשה בהם.`
  },
  copy: 'העתקה',
  paste: 'הדבקה',
  delete: 'מחיקה',
  // ⚠ Hebrew counts too. A review found `1 פריטים` / `1 חדרים` where every
  // English counterpart handled the singular — the language of the product is
  // the one that had no plural rules.
  delete_many: (n) => (n === 1 ? 'מחיקת פריט אחד' : `מחיקת ${n} פריטים`),
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
  apply: 'החלה',
  // ⚠ Found by the singular guard, and PRE-EXISTING: this shipped reading
  // "1 שורות לעומק" — one ROWS deep — in the tooltip of every shelf whose
  // depth is its own.
  rows_deep: (n) => (n === 1 ? 'שורה אחת לעומק' : `${n} שורות לעומק`),
  shelf_at: (a, c, l) => `מדף, ${a}עמודה ${c}, גובה ${l}`,
  restore_cell: (a, c, l) => `החזרת מדף ב${a}עמודה ${c}, גובה ${l}`,
  restore_cell_title: 'כאן אין מדף. לחיצה מחזירה מדף ריק.',
  // ⚠ Singular branches, and the ⚠ on `delete_many` above is why: the same
  // defect shipped there once already. A review measured `1 תאים מסומנים`
  // here — and, because a phone cannot mark a second cell at all (below),
  // ONE is the only count a phone owner ever reads.
  marked_cells: (n) => (n === 1 ? 'תא אחד מסומן' : `${n} תאים מסומנים`),
  // ⚠ NOT `פינוי`. That is the verb the refusal beside it uses for *take the
  // books off*, so one word meant two things 40px apart — a review caught the
  // reader being told to do the thing the button claims to do.
  make_space: (n) => (n === 1 ? 'השארת מקום (תא אחד)' : `השארת מקום (${n} תאים)`),
  // ⚠ It does NOT promise reversibility. The address comes back; the shelf's
  // id does not, and standing decisions are keyed by it (see `apply_gaps`).
  // §3.11's alias makes the fuller promise true, in P6.4e.
  make_space_title: 'התאים יפסיקו להיות מדפים. הכוננית והגבהים נשארים.',
  cells_have_books: (n) => (n === 1
    ? 'על אחד התאים המסומנים עומדים ספרים. הסירו אותם קודם.'
    : `על ${n} מהתאים המסומנים עומדים ספרים. הסירו אותם קודם.`),
  cells_have_photos: (n) => (n === 1
    ? 'לאחד התאים המסומנים יש צילום. מחקו אותו במסך המדף קודם.'
    : `ל-${n} מהתאים המסומנים יש צילומים. מחקו אותם במסך המדף קודם.`),
  cells_are_deep: (n) => (n === 1
    ? 'אחד התאים המסומנים הוגדר עם שורה מאחור. שנו את העומק שלו קודם.'
    : `${n} מהתאים המסומנים הוגדרו עם שורה מאחור. שנו את העומק שלהם קודם.`),
  gaps_are_tappable: 'תא ריק — לחיצה מחזירה מדף.',
  add_more_cells: 'סימון תאים נוספים',
  adding_more_cells: 'לחיצה מוסיפה תאים לסימון',
  remove_level: (a, c) => `הסרת מדף מ${a}עמודה ${c}`,
  add_level: (a, c) => `הוספת מדף ל${a}עמודה ${c}`,
  // ⚠ אתר for a SITE — the property — and חדר for a Place, which is the room.
  // MAP_PLAN §3.9 retires the gloss that let one word mean both.
  site: 'אתר',
  site_menu: 'תפריט האתרים',
  site_n: (n) => `אתר ${n}`,
  add_site: 'הוספת אתר',
  rename_site: (name) => `שינוי שם האתר ${name}`,
  remove_site: (name) => `הסרת האתר ${name}`,
  site_name: 'שם האתר',
  // ⚠ The client says this, not the server. The server's own refusal names a
  // 32-character id and cites a planning document — true, and unreadable.
  site_not_removed: (rooms, cases) =>
    `לא הוסר — עדיין יש באתר הזה ${[
      rooms > 0 ? (rooms === 1 ? 'חדר אחד' : `${rooms} חדרים`) : '',
      cases > 0 ? (cases === 1 ? 'כוננית אחת' : `${cases} כונניות`) : '',
    ].filter(Boolean).join(' ו')}. אפשר למחוק אותם קודם.`,
  remove_site_confirm: (name, floors) =>
    `להסיר את ${name} ו${floors === 1 ? 'את הקומה שבו' : `-${floors} הקומות שבו`}?`,
  site_removed: (name) => `אתר הוסר: ${name}`,
  site_added: (name) => `נוסף אתר: ${name} — הלוח ריק, אפשר להתחיל לצייר.`,
  overview_of: (site) => `כל הקומות של ${site} — צפייה בלבד, אי אפשר לערוך`,
  floor: 'קומה',
  floor_menu: 'תפריט הקומות',
  floor_n: (n) => `קומה ${n}`,
  add_floor: 'הוספת קומה',
  rename_floor: (name) => `שינוי שם הקומה ${name}`,
  remove_floor: (name) => `הסרת הקומה ${name}`,
  rename_floor_hint: 'לחיצה כפולה לשינוי שם הקומה',
  floor_name: 'שם הקומה',
  all_floors: 'כל הקומות',
  all_floors_long: 'כל הקומות, זו לצד זו',
  ghost_floors: 'הצללת שאר הקומות',
  one_floor_at_least: 'בתוכנית יש לפחות קומה אחת.',
  floor_not_removed: (rooms, cases) =>
    `לא הוסרה — עדיין יש בקומה הזו ${[
      rooms > 0 ? (rooms === 1 ? 'חדר אחד' : `${rooms} חדרים`) : '',
      cases > 0 ? (cases === 1 ? 'כוננית אחת' : `${cases} כונניות`) : '',
    ].filter(Boolean).join(' ו')}.`,
  read_only_bar: 'כל הקומות — צפייה בלבד, אי אפשר לערוך',
  back_to: (floor) => `חזרה ל${floor}`,
  the_plan: 'תוכנית',
  plan_canvas: 'תוכנית הבית',
  nothing_selected: 'לא נבחר דבר',
  room: 'חדר',
  bookcase: 'כוננית',
  name: 'שם',
  moves_with: 'זזה עם',
  stands_alone: 'שום דבר — עומדת בפני עצמה',
  books_face: 'הספרים פונים אל',
  turn_case: 'סיבוב הכוננית',
  turn_to: (side) => `${side} ⟳ סיבוב`,
  side: (s) => ({ N: 'למעלה', E: 'ימינה', S: 'למטה', W: 'שמאלה' })[s],
  cases_attached: 'כונניות מחוברות',
  too_small: (squares) => `קטן מדי — יש לגרור לפחות ${squares} × ${squares} משבצות`,
  nothing_to_see: 'לא היה נשאר מה לראות',
  too_many_slots: (asked, max) =>
    `לא בוצע — כוננית מחזיקה עד ${max} מדפים, והשינוי הזה מגיע ל-${asked}. `
    + 'כוננית גדולה כל כך היא בדרך כלל שתי כונניות, או יחידה נוספת מעליה.',
  too_many_sections: (max) =>
    `לא בוצע — כוננית מחזיקה עד ${max} יחידות. כוננית נוספת ליד היא הדרך.`,
  copied: (n) => (n === 1 ? 'פריט אחד הועתק.' : `${n} פריטים הועתקו.`),
  selected_n: (n) => (n === 1 ? 'פריט אחד נבחר' : `${n} נבחרו`),
  selected_mix: (rooms, cases) =>
    `${rooms === 1 ? 'חדר אחד' : `${rooms} חדרים`} · ${
      cases === 1 ? 'כוננית אחת' : `${cases} כונניות`
    }. גרירה של אחד מהם מזיזה את כולם.`,
  selected_carried: (n) =>
    n === 1
      ? 'עוד כוננית אחת תזוז יחד, כי היא מחוברת לחדר שנבחר.'
      : `עוד ${n} כונניות יזוזו יחד, כי הן מחוברות לחדרים שנבחרו.`,
  delete_all: (n) => (n === 1 ? 'מחיקת הפריט' : `מחיקת כל ${n} הפריטים`),
  delete_cases_confirm: (cases, shelves, photos) =>
    `${cases === 1 ? 'למחוק את הכוננית' : `למחוק ${cases} כונניות`} ו${
      shelves === 1 ? 'את המדף שבה' : `-${shelves} המדפים שבהן`}?` +
    (photos > 0
      ? ` ל${photos === 1 ? 'מדף אחד' : `-${photos} מדפים`} מצורפות תמונות.`
      : '') +
    ' מדף שעומדים עליו ספרים או שמצורפות אליו תמונות מנותק מהכתובת ולא נמחק.',
  delete_room: 'מחיקת החדר הזה',
  delete_case: 'מחיקת הכוננית הזו',
  rooms_keep_their_cases:
    'מחיקת חדר לעולם אינה מוחקת את הכונניות שבו — הן נשארות במקומן ואינן שייכות לאף חדר.',
  size_units: 'גודל (יחידות)',
  room_width: 'רוחב החדר',
  room_height: 'עומק החדר',
  case_width: 'רוחב הכוננית',
  case_height: 'עומק הכוננית',
  room_name_example: 'סלון · living room',
  case_name_example: 'ארון הסלון',
  unnamed: 'ללא שם',
  unnamed_room: (w, h) => `חדר ${w}×${h}`,
  unnamed_case: (w, h) => `כוננית ${w}×${h}`,
  select_case: (name) => `בחירת הכוננית ${name}`,
  no_cases_yet:
    'עדיין אין. כוננית שמציירים בתוך החדר הזה מתחברת אליו מאליה, ומאז זזה איתו.',
  cases_move_with_room:
    'אלה זזות כשהחדר הזה זז — כולל אלה שעומדות עכשיו מחוץ למתאר שלו.',
  case_details: 'שם, גודל, חדר, כיוון',
  case_summary: (name, w, h, side) => `${name} · ${w}×${h} · פונה ${side}`,
  case_facts: (units, deep, shelves) =>
    `${units === 1 ? 'יחידה אחת' : `${units} יחידות`} של קיר, ${deep} לעומק כפי שצוירה · ${
      shelves === 1 ? 'מדף אחד' : `${shelves} מדפים`}`,
  in_room: (name) => ` · ב${name}`,   // caller passes a NAMED room

  in_no_room: ' · לא מחוברת לחדר',
  in_sections: (n) => (n === 1 ? ' ביחידה אחת' : ` ב-${n} יחידות`),
  free_measurement:
    'מדידה חופשית — יחסית לקירות החדר, לעולם לא בסנטימטרים, ושום דבר כאן אינו מסיק כמה ספרים נכנסים.',
  counts: (rooms, cases) =>
    `${rooms === 1 ? 'חדר אחד' : `${rooms} חדרים`} · ${
      cases === 1 ? 'כוננית אחת' : `${cases} כונניות`}.`,
  step_room: '— גררו מלבן. גררו את הבא לידו והם ייצמדו קיר אל קיר.',
  step_case:
    '— גררו מלבן בתוך חדר. הוא נצמד לקיר, מתחבר לחדר, וזז איתו.',
  step_edit:
    '— גררו כדי להזיז, גררו ידית כדי לשנות גודל, הקישו כדי לערוך כאן. Ctrl+לחיצה מוסיף לבחירה, וגרירה על שטח ריק בוחרת את כל מה שהיא נוגעת בו.',
  section_n: (n) => `יחידה ${n}`,
  section_on_floor: ' · על הרצפה',
  section_on_top: ' · למעלה',
  add_section_top: 'הוספת יחידה למעלה',
  add_section_top_long: '＋ עוד יחידה למעלה',
  add_section_under: 'הוספת יחידה מתחת',
  add_section_under_long: '＋ עוד יחידה מתחת',
  split_sections: 'פיצול הכוננית ליחידות',
  split_sections_long: '＋ יחידה שנייה למעלה (יחידה שעומדת על זו)',
  remove_section: (s) => `הסרת ${s}`,
  remove_section_title: (s, shelves) =>
    `הסרת ${s} ו${shelves === 1 ? 'המדף שבה' : `-${shelves} המדפים שבה`}`,
  remove_section_confirm: (s, shelves) =>
    `להסיר את ${s} ואת ${shelves === 1 ? 'המדף שבה' : `${shelves} המדפים שבה`}?`,
  col_head: (col) => `עמודה ${col}`,
  column: 'עמודה',
  add_column: 'הוספת עמודה',
  add_column_of: (s) => `הוספת עמודה ל${s}`,
  remove_column: 'הסרת העמודה האחרונה',
  remove_column_of: (s) => `הסרת העמודה האחרונה של ${s}`,
  remove_column_confirm: (shelves) =>
    `להסיר את העמודה האחרונה ואת ${
      shelves === 1 ? 'המדף שבה' : `${shelves} המדפים שבה`}?`,
  depth_kept: (n, s) =>
    `${n === 1 ? 'מדף קיים אחד' : `${n} מדפים קיימים`} ב${s} ${
      n === 1 ? 'שומר' : 'שומרים'} על העומק שלהם. שינוי ברירת המחדל לעולם אינו חוזר אליהם — זה היה מוחק את המיקום של כל ספר שעומד בשורה האחורית.`,
  apply_to_all: (shelves) =>
    (shelves === 1 ? 'החלה על המדף היחיד' : `החלה על כל ${shelves} המדפים`),
  pick_a_cell: 'בחרו תא למעלה כדי לקבוע עומק למדף אחד.',
  shelf_legend: (where, col, level) => `מדף · ${where}עמודה ${col} · גובה ${level}`,
  shelf_is_named: (label) => `שם המדף: ${label}`,
  shelf_take_off_map: 'הורדה מהמפה',
  // ⚠ `ו-`, not `heHolds`'s middot. That helper is the picker's two-COLUMN
  // separator; routing a sentence through it produced "מדף שעליו 22 ספרים ·
  // תמונה אחת?", which is a list where a conjunction belongs — in the one
  // string that guards a destructive act. A review caught it in the commit
  // that fixed the plural.
  shelf_take_off_map_confirm: (books, photos) =>
    `להוריד מהמפה מדף שעליו ${
      books === 1 ? 'ספר אחד' : `${books} ספרים`} ו${
      photos === 1 ? 'תמונה אחת' : `-${photos} תמונות`}? הם נשארים איתו; מה שהולך לאיבוד הוא המקום שלו בשרטוט. אפשר לשחזר.`,
  cell_has_no_shelf: 'אין כאן מדף.',
  // ⚠ A legend of its own. The fieldset printed "מדף · עמודה 1 · גובה 1"
  // directly above "אין כאן מדף." — one box making two contradictory claims.
  empty_cell_legend: (where, col, level) =>
    `תא ריק · ${where}עמודה ${col} · גובה ${level}`,
  put_a_shelf_here: 'שימו כאן מדף',
  pick_a_shelf: 'בחרו מדף שאינו על המפה:',
  pick_a_shelf_cancel: 'ביטול הבחירה',
  no_shelves_off_the_map: 'כל המדפים כבר על המפה.',
  // ⚠ NOT "כל המדפים כבר על המפה". Absent is not unknown: a review held
  // `GET /shelves` down and the picker announced that every shelf was placed
  // while forty stood nowhere — the same measurement CLAUDE.md records about
  // "no admin" beside a card saying two users, in a new surface. On a phone a
  // dropped request is the ordinary case.
  shelf_list_failed: 'לא הצלחנו לקרוא את רשימת המדפים.',
  shelf_list_retry: 'ניסיון נוסף',
  shelf_holds_nothing: 'ריק',
  // ⚠ Names the CELL's state, not "מדף". A screen reader announced *shelf*
  // for a cell holding none — the same rule the gap's own label follows one
  // branch above (`restore_cell` names the action, never the state).
  empty_cell: (where, col, level) =>
    `תא ריק · ${where}עמודה ${col} · גובה ${level}`,
  shelf_unnamed: 'מדף ללא שם',
  shelf_holds: heHolds,
  // ⚠ The same words the row SHOWS. A screen reader reading "0 ספרים · 0
  // תמונות" off a row whose visible text says "ריק" is two descriptions of
  // one shelf, and only one of them is the one on screen.
  pick_shelf_option: (n, name, books, photos) =>
    `${n}. ${name} — ${books + photos === 0 ? 'ריק' : heHolds(books, photos)}`,
  // ⚠ The UI's own words FIRST, and the name after. `unicode-bidi: plaintext`
  // resolves a paragraph from its first strong character, so a label starting
  // with a Latin letter (`A1`, `IKEA Billy` — free text, and plausible)
  // flipped the whole announcement to LTR: the Hebrew ran backwards relative
  // to the sentence and the full stop landed at its visual start. Measured on
  // the real flash box. The same rule `<LibraryName>` carries, applied to a
  // sentence instead of a pair of elements.
  bound_here: (name) => `נמצא עכשיו בתא הזה: ${name}`,
  unbound_shelf: (name) => `ירד מהמפה, ואפשר לשחזר: ${name}`,
  slot_moved_on: 'השרטוט השתנה מאז — הנה המצב העדכני. נסו שוב.',
  // ⚠ *מיזוג*, never *שיוך*. Binding a shelf into a free slot and merging two
  // identities into one are different acts (§3.14), and a UI that names them
  // alike is how the dangerous one gets pressed by accident — it moves a whole
  // population of books and looks like success either way, because the map
  // gets fuller.
  merge_a_shelf_here: 'מיזוג מדף אחר לכאן…',
  merge_pick: 'איזה מדף הוא בעצם המדף הזה?',
  merge_pick_option: (n, name, books, photos) =>
    `אפשרות ${n}: ${name} — ${books + photos === 0 ? 'ריק'
      : heHolds(books, photos)}`,
  merge_reading: 'בודקים מה יזוז…',
  merge_read_failed: 'לא הצלחנו לבדוק מה יזוז. לא נגענו בכלום.',
  // ⚠ Our words first, then the two names. `unicode-bidi: plaintext` resolves
  // a paragraph from its FIRST strong character, so a Hebrew sentence opening
  // with a Latin-initial shelf name flips whole.
  merge_would_move: (name, here) =>
    `מיזוג המדף שבחרתם (${name}) לתוך המדף שבתא הזה (${here}) יעביר:`,
  merge_books: (n) => (n === 1 ? 'ספר אחד' : `${n} ספרים`),
  merge_photos: (n) => (n === 1 ? 'תמונה אחת' : `${n} תמונות`),
  merge_answers: (n) =>
    n === 1 ? 'תשובה אחת שנתתם (למשל "לא, זה לא הספר הזה")'
            : `${n} תשובות שנתתם (למשל "לא, זה לא הספר הזה")`,
  merge_identities: (n) =>
    n === 1 ? 'זהות נוספת אחת שכבר מוזגה לכאן'
            : `${n} זהויות נוספות שכבר מוזגו לכאן`,
  merge_depth_after: (n) =>
    n === 1 ? 'המדף יישאר בשורה אחת' : `למדף יהיו ${n} שורות לעומק`,
  merge_moves_nothing: 'אין ספרים ואין תמונות לזוז — רק הזהות מתאחדת.',
  merge_clashes: (n) =>
    n === 1 ? 'תשובה אחת ניתנה בשני המקומות; התשובה החדשה יותר תנצח.'
            : `${n} תשובות ניתנו בשני המקומות; החדשות יותר ינצחו.`,
  merge_strip: 'איזה חצי של המדף שמאלי?',
  // ⚠ **The two say which SHELF, not only which name**, and that is a
  // measurement rather than a nicety: on the owner's own library both shelves
  // were unnamed, so both radios announced *"התמונות של מדף ללא שם ראשונות"*
  // — one accessible name on two controls, and the question unanswerable —
  // in the control that decides an ordering §5.7 says nothing can detect.
  // Naming the ROLE makes them distinct even when the owner has given two
  // shelves the same label, which is the case a fallback cannot fix.
  merge_strip_absorbed_first: (name) =>
    `התמונות של המדף שבחרתם (${name}) ראשונות`,
  merge_strip_survivor_first: (name) =>
    `התמונות של המדף שבתא הזה (${name}) ראשונות`,
  merge_confirm: 'מיזוג',
  merge_cancel: 'ביטול',
  merge_refused: 'אי אפשר למזג:',
  // ⚠ Six codes, six different next actions. Rendering the server's English
  // sentence put four lines and a 32-character hex id in front of a household
  // member; `MergeRefused` carries the code beside the sentence precisely so
  // a client can say this instead.
  merge_reason: (code) => ({
    same_shelf: 'זה אותו מדף.',
    other_library: 'המדפים שייכים לספריות שונות.',
    wishlist: 'רשימת המשאלות אינה מדף — היא לא עומדת בשום מקום.',
    survivor_absorbed: 'המדף שכאן כבר מוזג למדף אחר. מזגו לתוך זה שעונה בשמו.',
    read_running: 'קריאה של אחד המדפים עדיין רצה. נסו שוב כשתסתיים.',
    address_taken: 'זהות אחרת כבר זוכרת את התא הזה.',
  }[code] || ''),
  merge_pick_order: 'בחרו אחת מהשתיים כדי להמשיך.',
  merge_none_off_the_map: 'אין מדף שאינו על המפה. אפשר למזג רק מדף כזה.',
  merge_already: 'שני המדפים כבר מאוחדים.',
  merged_into: (name) => `מוזג לתוך המדף הזה, ואפשר לשחזר: ${name}`,
  undo_merged: (books) => (books === 1
    ? 'המיזוג בוטל. ספר אחד חזר למדף שלו.'
    : `המיזוג בוטל. ${books} ספרים חזרו למדף שלהם.`),
  own_depth: 'העומק שלו',
  photos_attached: 'תמונות מצורפות',
  last_read: 'נקרא לאחרונה',
  rows_stale: (n) => (n === 1
    ? 'שורה אחת לא נקראה מזמן — פתחו את המדף כדי לראות איזו'
    : `${n} שורות לא נקראו מזמן — פתחו את המדף כדי לראות אילו`),
  open_this_shelf: 'פתחו את המדף הזה →',
  propose_levels: 'הצעה מתמונה',
  propose_levels_hint:
    'צלמו את כל הכוננית — נספור את המדפים ונציע מספר. התמונה לא נשמרת, ולא משתנה כלום עד שתלחצו החלה.',
  proposing_levels: 'סופרים…',
  proposed_levels: (n) => (n === 1
    ? 'נספר מדף אחד — אם צילמתם מדף בודד, צלמו את כל הכוננית'
    : `נספרו ${n} מדפים בתמונה`),
  propose_failed: 'לא הצלחנו לקרוא את התמונה הזאת',
  move_section_up: (label) => `העלאת ${label} שלב אחד`,
  move_section_down: (label) => `הורדת ${label} שלב אחד`,
  section_moved: (label) => `הוזזה ${label}`,
  save_to_file: 'שמירת השרטוט לקובץ…',
  // ⚠ Our word first: `unicode-bidi: plaintext` resolves a paragraph from
  // its first strong character, and a filename is Latin.
  saved_to_file: (name) => `נשמר לקובץ ${name}`,
  open_from_file: 'שחזור שרטוט מקובץ…',
  restore_upload: 'קובץ שרטוט לשחזור',
  restore_not_a_plan: 'זה לא קובץ שרטוט של booksnap',
  restore_other_site:
    'הקובץ הזה שייך לאתר אחר — עברו אליו ונסו שוב',
  restore_removes_nothing:
    'לשחזר את השרטוט מהקובץ? שום דבר לא יוסר.',
  restore_nothing_lost: (cases) =>
    cases === 1
      ? 'לשחזר את השרטוט מהקובץ? כוננית אחת תימחק, ולא עומד עליה כלום.'
      : `לשחזר את השרטוט מהקובץ? ${cases} כונניות יימחקו, ולא עומד עליהן כלום.`,
  // ⚠ SHELVES and BOOKS, both, and in that order: a shelf losing its address
  // is the thing that happens, and the books standing on it are why it
  // matters. The books are not deleted — they stop having a place.
  restore_costs: (cases, shelves, books) =>
    `לשחזר את השרטוט מהקובץ? ${cases === 1 ? 'כוננית אחת תימחק' : `${cases} כונניות יימחקו`}, `
    + `${shelves === 1 ? 'מדף אחד יאבד את מיקומו' : `${shelves} מדפים יאבדו את מיקומם`}, `
    + `ו${books === 1 ? 'ספר אחד ישאר בלי מיקום' : `-${books} ספרים ישארו בלי מיקום`}.`,
  restore_backup_first:
    'השרטוט הנוכחי יישמר לקובץ קודם, כדי שתוכלו לחזור אליו.',
  restored: 'השרטוט שוחזר מהקובץ',
  photos_are_captures:
    'תמונות מגיעות מצילום המדף, לא מכאן. אפשר לצלם כמה תמונות לאותו מדף, ולכל אחת העומק שלה.',
  shelf_depth: 'עומק המדף הזה',
  black_bg: 'רקע שחור',
  white_bg: 'רקע לבן',
  trace: 'העתקה משרטוט…',
  trace_upload: 'העלאת תוכנית להעתקה',
  trace_remove: 'הסרת השרטוט',
  trace_opacity: 'שקיפות השרטוט',
  trace_size: 'גודל השרטוט',
  trace_fade_short: 'שקיפות',
  trace_size_short: 'גודל',
  trace_loaded: 'השרטוט נטען — ציירו מעליו, ואז הסירו אותו.',
  trace_not_an_image: 'הקובץ הזה לא נפתח כתמונה.',
  trace_unreadable: 'לא הצלחנו לקרוא את הקובץ.',
  panel_resize: 'גרירה לשינוי רוחב לוח ההגדרות',
  saving: 'שומר…',
  saved: 'נשמר',
  save_failed: 'לא נשמר',
  saved_hint: 'כל שינוי נשמר בספרייה מיד. אם כתוב "לא נשמר" — ההודעה למעלה אומרת למה.',
  save_failed_hint: 'לא הצלחנו לשמור את השינוי',
  // ⚠ True by construction: a push that failed to arrive leaves `confirmed`
  // where it was, so the next diff carries this change with it.
  not_saved_yet: 'לא נשמר — השינוי יישלח שוב יחד עם השינוי הבא.',
  // ⚠ No promise of a retry: a site is not in the document, so nothing
  // carries it along later.
  not_done_lead: 'לא בוצע — לא הצלחנו לפנות לשרת.',
  ground_floor: 'קומת קרקע',
  refused_lead: 'השרת סירב לשינוי:',
  dismiss: 'סגירת ההודעה',
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
  hint_overview: 'Every floor, side by side. Double-click one to work on it.',
  no_drawing_here: 'Viewing every floor — nothing can be drawn',
  menu_plan: 'Plan',
  menu_edit: 'Edit',
  menu_view: 'View',
  reload: 'Reload from the server',
  undo: 'Undo',
  redo: 'Redo',
  undo_last_edit: 'Restore what was last removed',
  undo_offered: 'Can be restored: Edit ▸ Restore what was last removed',
  undo_done: (n) => (n === 1 ? 'One shelf is back in place'
    : n ? `${n} shelves are back in place` : 'What was removed is back'),
  undo_nothing: 'There is nothing to restore',
  undo_already: 'Everything is already back in place',
  undo_moved: (shelves, others) => {
    const what = others || !shelves
      ? `${shelves + others} things on the map have changed`
      : shelves === 1 ? 'One shelf has changed'
        : `${shelves} shelves have changed`
    return `${what} since, and restoring now would overwrite that work.`
  },
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
  apply: 'apply',
  rows_deep: (n) => (n === 1 ? 'one row front-to-back' : `${n} rows front-to-back`),
  shelf_at: (a, c, l) => `shelf, ${a}column ${c}, level ${l}`,
  restore_cell: (a, c, l) => `put a shelf back at ${a}column ${c}, level ${l}`,
  restore_cell_title: 'No shelf here. Tap to put an empty one back.',
  marked_cells: (n) => (n === 1 ? 'one cell marked' : `${n} cells marked`),
  make_space: (n) => (n === 1 ? 'Leave a space (1 cell)' : `Leave a space (${n} cells)`),
  make_space_title: 'The cells stop being shelves. The bookcase and the levels stay.',
  cells_have_books: (n) => (n === 1
    ? 'One marked cell has books on it. Move them first.'
    : `${n} marked cells have books on them. Move them first.`),
  cells_have_photos: (n) => (n === 1
    ? 'One marked cell has a photograph. Delete it from the shelf screen first.'
    : `${n} marked cells have photographs. Delete them from the shelf screen first.`),
  cells_are_deep: (n) => (n === 1
    ? 'One marked cell was given a row behind it. Change its depth first.'
    : `${n} marked cells were given a row behind them. Change their depth first.`),
  gaps_are_tappable: 'An empty cell — tap to put a shelf back.',
  add_more_cells: 'Mark more cells',
  adding_more_cells: 'Tapping adds cells to the selection',
  remove_level: (a, c) => `remove a level from ${a}column ${c}`,
  add_level: (a, c) => `add a level to ${a}column ${c}`,
  site: 'Site',
  site_menu: 'Site menu',
  site_n: (n) => `Site ${n}`,
  add_site: 'Add a site',
  rename_site: (name) => `Rename the site ${name}`,
  remove_site: (name) => `Remove the site ${name}`,
  site_name: 'site name',
  site_not_removed: (rooms, cases) =>
    `Not removed — this site still has ${[
      rooms > 0 ? `${rooms} room${rooms > 1 ? 's' : ''}` : '',
      cases > 0 ? `${cases} bookcase${cases > 1 ? 's' : ''}` : '',
    ].filter(Boolean).join(' and ')}. Delete them first.`,
  remove_site_confirm: (name, floors) =>
    `Remove ${name} and ${floors === 1 ? 'its floor' : `its ${floors} floors`}?`,
  site_removed: (name) => `Site removed: ${name}`,
  site_added: (name) => `Site added: ${name} — an empty board, ready to draw.`,
  overview_of: (site) => `Every floor of ${site} — viewing only, nothing can be edited`,
  floor: 'Floor',
  floor_menu: 'Floor menu',
  floor_n: (n) => `Floor ${n}`,
  add_floor: 'Add a floor',
  rename_floor: (name) => `Rename the floor ${name}`,
  remove_floor: (name) => `Remove the floor ${name}`,
  rename_floor_hint: 'Double-click to rename this floor',
  floor_name: 'floor name',
  all_floors: 'All floors',
  all_floors_long: 'All floors, side by side',
  ghost_floors: 'Ghost the other floors',
  one_floor_at_least: 'A plan has at least one floor.',
  floor_not_removed: (rooms, cases) =>
    `Not removed — ${[
      rooms > 0 ? `${rooms} room${rooms > 1 ? 's' : ''}` : '',
      cases > 0 ? `${cases} bookcase${cases > 1 ? 's' : ''}` : '',
    ].filter(Boolean).join(' and ')} still on this floor.`,
  read_only_bar: 'Every floor — viewing only, nothing can be edited',
  back_to: (floor) => `Back to ${floor}`,
  the_plan: 'the plan',
  plan_canvas: 'floor plan',
  nothing_selected: 'Nothing selected',
  room: 'Room',
  bookcase: 'Bookcase',
  name: 'Name',
  moves_with: 'Moves with',
  stands_alone: 'nothing — stands alone',
  books_face: 'Books face',
  turn_case: 'turn the bookcase',
  turn_to: (side) => `${side} ⟳ turn`,
  side: (s) => ({ N: 'up', E: 'right', S: 'down', W: 'left' })[s],
  cases_attached: 'Bookcases attached',
  too_small: (squares) => `too small — drag out at least ${squares} × ${squares} squares`,
  nothing_to_see: 'that would leave nothing to see',
  too_many_slots: (asked, max) =>
    `Not done — a bookcase holds at most ${max} shelves, and this change reaches `
    + `${asked}. A bookcase that big is usually two bookcases, or one with `
    + 'another section on top.',
  too_many_sections: (max) =>
    `Not done — a bookcase holds at most ${max} sections. A second bookcase `
    + 'beside it is the way.',
  copied: (n) => `Copied ${n} item${n > 1 ? 's' : ''}.`,
  selected_n: (n) => `${n} selected`,
  selected_mix: (rooms, cases) =>
    `${rooms} room${rooms === 1 ? '' : 's'} · ${cases} bookcase${cases === 1 ? '' : 's'}. Drag any of them and they all move.`,
  selected_carried: (n) =>
    `${n} more bookcase${n === 1 ? '' : 's'} will travel along, attached to the selected rooms.`,
  delete_all: (n) => `Delete all ${n}`,
  delete_cases_confirm: (cases, shelves, photos) =>
    `Delete ${cases === 1 ? 'this bookcase' : `${cases} bookcases`} and ` +
    `${shelves === 1 ? 'its shelf' : `their ${shelves} shelves`}?` +
    (photos > 0
      ? ` ${photos === 1 ? 'One shelf has' : `${photos} shelves have`} photographs.`
      : '') +
    ' A shelf holding books or photographs is detached from its address, not destroyed.',
  delete_room: 'Delete this room',
  delete_case: 'Delete this bookcase',
  rooms_keep_their_cases:
    'Deleting a room never deletes its bookcases — they stay where they stand and belong to no room.',
  size_units: 'Size (units)',
  room_width: 'room width',
  room_height: 'room height',
  case_width: 'bookcase width',
  case_height: 'bookcase height',
  room_name_example: 'סלון · living room',
  case_name_example: 'ארון הסלון',
  unnamed: 'unnamed',
  unnamed_room: (w, h) => `room ${w}×${h}`,
  unnamed_case: (w, h) => `bookcase ${w}×${h}`,
  select_case: (name) => `select the bookcase ${name}`,
  no_cases_yet:
    'None yet. A bookcase drawn inside this room attaches to it automatically, and then moves with it.',
  cases_move_with_room:
    'These move when this room moves — including any that now stand outside its outline.',
  case_details: 'Name, size, room, facing',
  case_summary: (name, w, h, side) => `${name} · ${w}×${h} · faces ${side}`,
  case_facts: (units, deep, shelves) =>
    `${units === 1 ? '1 unit' : `${units} units`} of wall, ${deep} deep as drawn · ${
      shelves === 1 ? '1 shelf' : `${shelves} shelves`}`,
  in_room: (name) => ` · in ${name}`,
  in_no_room: ' · attached to no room',
  in_sections: (n) => (n === 1 ? ' in one section' : ` in ${n} sections`),
  free_measurement:
    'Free measurement — relative to this room’s walls, never centimetres, and nothing here infers how many books fit.',
  counts: (rooms, cases) =>
    `${rooms === 1 ? '1 room' : `${rooms} rooms`} · ${
      cases === 1 ? '1 bookcase' : `${cases} bookcases`}.`,
  step_room: '— drag a rectangle. Drag the next one near it and they attach edge to edge.',
  step_case:
    '— drag a rectangle inside a room. It snaps flush to the wall, attaches to that room, and moves with it.',
  step_edit:
    '— drag to move, drag a handle to resize, tap to edit here. Ctrl+click adds to the selection, and dragging empty space selects everything the band touches.',
  section_n: (n) => `Section ${n}`,
  section_on_floor: ' · on the floor',
  section_on_top: ' · on top',
  add_section_top: 'add a section on top',
  add_section_top_long: '＋ another section on top',
  add_section_under: 'add a section underneath',
  add_section_under_long: '＋ another section underneath',
  split_sections: 'split this bookcase into sections',
  split_sections_long: '＋ a second section on top (a unit standing on this one)',
  remove_section: (s) => `remove ${s.toLowerCase()}`,
  remove_section_title: (s, shelves) =>
    `Remove ${s.toLowerCase()} and its ${
      shelves === 1 ? 'one shelf' : `${shelves} shelves`}`,
  remove_section_confirm: (s, shelves) =>
    `Remove ${s.toLowerCase()} and its ${
      shelves === 1 ? 'one shelf' : `${shelves} shelves`}?`,
  col_head: (col) => `col ${col}`,
  column: 'column',
  add_column: 'add a column',
  add_column_of: (s) => `add a column to ${s.toLowerCase()}`,
  remove_column: 'remove the last column',
  remove_column_of: (s) => `remove the last column of ${s.toLowerCase()}`,
  remove_column_confirm: (shelves) =>
    `Remove the last column and its ${
      shelves === 1 ? 'one shelf' : `${shelves} shelves`}?`,
  depth_kept: (n, s) =>
    `${n} existing ${n === 1 ? 'shelf keeps its own depth' : 'shelves keep their own depth'} in ${s.toLowerCase()}. Changing the default never reaches back into them — that would delete the location of every book standing in a back row.`,
  apply_to_all: (shelves) =>
    (shelves === 1 ? 'Apply to the one shelf' : `Apply to all ${shelves} shelves`),
  pick_a_cell: 'Pick a cell above to set one shelf’s own depth.',
  shelf_legend: (where, col, level) => `Shelf · ${where}col ${col} · level ${level}`,
  shelf_is_named: (label) => `Named: ${label}`,
  shelf_take_off_map: 'Take off the map',
  shelf_take_off_map_confirm: (books, photos) =>
    `Take a shelf holding ${books === 1 ? '1 book' : `${books} books`} and ${
      photos === 1 ? '1 photo' : `${photos} photos`} off the map? They stay with it; what it loses is its place in the drawing. This can be restored.`,
  cell_has_no_shelf: 'No shelf stands here.',
  empty_cell_legend: (where, col, level) =>
    `Empty cell · ${where}col ${col} · level ${level}`,
  put_a_shelf_here: 'Put a shelf here',
  pick_a_shelf: 'Pick a shelf that is not on the map:',
  pick_a_shelf_cancel: 'Cancel',
  no_shelves_off_the_map: 'Every shelf is already on the map.',
  shelf_list_failed: 'The shelf list could not be read.',
  shelf_list_retry: 'Try again',
  shelf_holds_nothing: 'empty',
  empty_cell: (where, col, level) =>
    `empty cell · ${where}col ${col} · level ${level}`,
  shelf_unnamed: 'Unnamed shelf',
  shelf_holds: enHolds,
  pick_shelf_option: (n, name, books, photos) =>
    `${n}. ${name} — ${books + photos === 0 ? 'empty' : enHolds(books, photos)}`,
  bound_here: (name) => `Now standing in this cell: ${name}`,
  unbound_shelf: (name) => `Came off the map, and can be restored: ${name}`,
  slot_moved_on: 'The drawing has changed since — here it is as it stands. Try again.',
  merge_a_shelf_here: 'Merge another shelf into this one…',
  merge_pick: 'Which shelf is really this shelf?',
  merge_pick_option: (n, name, books, photos) =>
    `Option ${n}: ${name} — ${books + photos === 0 ? 'empty'
      : enHolds(books, photos)}`,
  merge_reading: 'Working out what would move…',
  merge_read_failed: 'We could not work out what would move. Nothing was touched.',
  merge_would_move: (name, here) =>
    `Merging the shelf you picked (${name}) into the shelf in this cell (${here}) would move:`,
  merge_books: (n) => (n === 1 ? '1 book' : `${n} books`),
  merge_photos: (n) => (n === 1 ? '1 photo' : `${n} photos`),
  merge_answers: (n) =>
    n === 1 ? '1 answer you gave (such as "no, that is not the book")'
            : `${n} answers you gave (such as "no, that is not the book")`,
  merge_identities: (n) =>
    n === 1 ? '1 further identity already merged into it'
            : `${n} further identities already merged into it`,
  merge_depth_after: (n) =>
    n === 1 ? 'The shelf stays one row deep' : `The shelf becomes ${n} rows deep`,
  merge_moves_nothing: 'No books and no photographs to move — only the identity joins.',
  merge_clashes: (n) =>
    n === 1 ? '1 answer was given in both places; the newer one wins.'
            : `${n} answers were given in both places; the newer ones win.`,
  merge_strip: 'Which half of the shelf is on the left?',
  merge_strip_absorbed_first: (name) =>
    `The photographs of the shelf you picked (${name}) come first`,
  merge_strip_survivor_first: (name) =>
    `The photographs of the shelf in this cell (${name}) come first`,
  merge_confirm: 'Merge',
  merge_cancel: 'Cancel',
  merge_refused: 'Cannot merge:',
  merge_reason: (code) => ({
    same_shelf: 'That is the same shelf.',
    other_library: 'The two shelves belong to different libraries.',
    wishlist: 'The wishlist is not a shelf — it stands nowhere.',
    survivor_absorbed: 'This shelf has itself been merged. Merge into the one that answers for it.',
    read_running: 'A read of one of these shelves is still running. Try again when it finishes.',
    address_taken: 'Another identity already remembers this cell.',
  }[code] || ''),
  merge_pick_order: 'Pick one of the two to continue.',
  merge_none_off_the_map: 'No shelf stands off the map. Only such a shelf can be merged in.',
  merge_already: 'These two shelves are already one.',
  merged_into: (name) => `Merged into this shelf, and can be taken back: ${name}`,
  undo_merged: (books) => (books === 1
    ? 'The merge was taken back. 1 book went back to its own shelf.'
    : `The merge was taken back. ${books} books went back to their own shelf.`),
  own_depth: 'Its own depth',
  photos_attached: 'Photos attached',
  last_read: 'Last read',
  rows_stale: (n) => (n === 1
    ? 'One row has not been read in a while — open the shelf to see which'
    : `${n} rows have not been read in a while — open the shelf to see which`),
  open_this_shelf: 'Open this shelf →',
  propose_levels: 'Propose from a photo',
  propose_levels_hint:
    'Photograph the WHOLE bookcase — we count the shelves and suggest a '
    + 'number. The photo is not stored, and nothing changes until you press '
    + 'apply.',
  proposing_levels: 'Counting…',
  proposed_levels: (n) => (n === 1
    ? 'Counted one shelf — if that was a photo of a single shelf, photograph '
      + 'the whole bookcase'
    : `Counted ${n} shelves in the photo`),
  propose_failed: "Couldn't read that photo",
  move_section_up: (label) => `Move ${label} up one`,
  move_section_down: (label) => `Move ${label} down one`,
  section_moved: (label) => `Moved ${label}`,
  save_to_file: 'Save the drawing to a file…',
  saved_to_file: (name) => `Saved to ${name}`,
  open_from_file: 'Restore a drawing from a file…',
  restore_upload: 'A drawing file to restore',
  restore_not_a_plan: 'That is not a booksnap drawing file',
  restore_other_site:
    'That file is of a different site — switch to it and try again',
  restore_removes_nothing: 'Restore the drawing from the file? Nothing is removed.',
  restore_nothing_lost: (cases) =>
    cases === 1
      ? 'Restore the drawing from the file? One bookcase goes, and nothing stands on it.'
      : `Restore the drawing from the file? ${cases} bookcases go, and nothing stands on them.`,
  restore_costs: (cases, shelves, books) =>
    `Restore the drawing from the file? ${cases === 1 ? 'One bookcase goes' : `${cases} bookcases go`}, `
    + `${shelves === 1 ? 'one shelf loses its place' : `${shelves} shelves lose their place`}, `
    + `and ${books === 1 ? 'one book is left with nowhere' : `${books} books are left with nowhere`}.`,
  restore_backup_first:
    'The drawing as it stands now is saved to a file first, so you can come back to it.',
  restored: 'The drawing was restored from the file',
  photos_are_captures:
    'Photos arrive by photographing the shelf, not from here. A shelf can have several, each with its own depth.',
  shelf_depth: "this shelf's depth",
  black_bg: 'Black background',
  white_bg: 'White background',
  trace: 'Trace a sketch…',
  trace_upload: 'upload a floor plan to trace',
  trace_remove: 'remove the underlay',
  trace_opacity: 'underlay opacity',
  trace_size: 'underlay size',
  trace_fade_short: 'fade',
  trace_size_short: 'size',
  trace_loaded: 'Traced sketch loaded — draw over it, then remove it.',
  trace_not_an_image: 'That file did not decode as an image.',
  trace_unreadable: 'Could not read that file.',
  panel_resize: 'drag to resize the settings panel',
  saving: 'Saving…',
  saved: 'Saved',
  save_failed: 'Not saved',
  saved_hint:
    'Every change is written to the library immediately. "Not saved" means the banner above says why.',
  save_failed_hint: 'We could not save that change',
  not_saved_yet: 'Not saved — it will be sent again with your next change.',
  not_done_lead: 'Not done — we could not reach the server.',
  ground_floor: 'Ground floor',
  refused_lead: 'The server refused:',
  dismiss: 'dismiss this message',
}

export const mapText = (lang: Lang): MapText => (lang === 'he' ? HE : EN)

/** Both tables, for the test that pins them to each other. */
export const TABLES = { he: HE, en: EN }
