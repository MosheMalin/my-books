/**
 * he/en strings and the document direction.
 *
 * Hebrew is the primary language (VISION §6: RTL-first, "not
 * internationalisation polish"). English is not there for English speakers —
 * it is there because a real LTR mode is the only honest way to test that the
 * layout mirrors and that mixed-script alignment holds in both directions
 * (UI_PLAN §7.1/§7.2). Deleting it would make the bidi rules untestable.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export type Lang = 'he' | 'en'

const HE = {
    app: 'booksnap',
    books: 'ספרים',
    search: 'חיפוש לפי כותרת או מחבר',
    sort: 'מיון',
    sort_title: 'כותרת',
    sort_author: 'מחבר',
    sort_recent: 'נוספו לאחרונה',
    sort_relevance: 'רלוונטיות',
    sort_ignored: 'בחיפוש התוצאות מסודרות לפי רלוונטיות',
    sort_asc: 'סדר עולה',
    sort_desc: 'סדר יורד',
    view_list: 'רשימה',
    view_grid: 'רשת',
    add_book: 'הוספת ספר',
    status: 'סטטוס',
    st_auto: 'זוהה אוטומטית',
    st_approved: 'אושר',
    st_manual: 'ידני',
    clear: 'ניקוי סינון',
    by_author: 'מאת',
    count: (shown: number, total: number) =>
      shown >= total ? `${total} ספרים` : `${shown} מתוך ${total} ספרים`,
    count_none: 'אין ספרים',
    empty: 'לא נמצאו ספרים',
    empty_hint: 'נסו לנקות את הסינון',
    loading: 'טוען…',
    load_error: 'אין חיבור לשרת',
    retry: 'נסו שוב',
    details: 'פרטי הספר',
    open_full: 'פתיחה בעמוד מלא',
    close: 'סגירה',
    back: 'חזרה',
    edit: 'עריכה',
    save: 'שמירה',
    cancel: 'ביטול',
    title_label: 'כותרת',
    author_label: 'מחבר',
    saved: 'נשמר',
    added_at: 'נוסף',
    last_seen: 'נראה לאחרונה',
    lent_only: 'מושאלים בלבד',
    // P2.6 — the "duplicates to resolve" queue (§5.4) as a filter chip,
    // exactly like lent_only: a boolean filter on `list`, nothing new for
    // this tab to render.
    duplicates_only: 'כפילויות לבירור',
    copies: 'עותקים',
    copy_n: (n: number) => `עותק ${n}`,
    copy_label: 'תווית',
    copy_label_placeholder: 'למשל כריכה רכה',
    copy_tags: 'תגיות',
    copy_tags_placeholder: 'מופרדות בפסיקים',
    copy_condition: 'מצב',
    copy_details: 'פרטים',
    add_copy: 'יש לי עותק נוסף',
    // Not just "עריכה" (t.edit) — that button already exists on the book
    // itself, and a screen reader announcing "Edit" twice on one screen
    // can't tell you which is which.
    copy_edit: 'עריכת פרטי העותק',
    lending: 'השאלה',
    lent_to: (who: string) => `מושאל ל${who}`,
    due: (date: string) => `להחזרה עד ${date}`,
    not_lent: 'בבית',
    lend_it: 'השאלת הספר',
    lend_to_label: 'למי',
    due_at_label: 'תאריך החזרה (רשות)',
    // Imperative, not "השאלה" (the kv row's label above) — the row names the
    // FACT, the button names the ACTION; same word for both reads as a typo.
    lend_save: 'השאילו',
    mark_returned: 'סמנו כהוחזר',
    delete_book: 'מחיקה מהספרייה',
    delete_confirm: 'למחוק את הספר מהספרייה? הפעולה מוחקת את כל העותקים.',
    delete_yes: 'מחקו',
    export: 'ייצוא',
    export_csv: 'ייצוא CSV',
    export_json: 'ייצוא JSON',
    conflict_edit: 'כבר יש ספר כזה בספרייה',
    conflict_add: 'הספר כבר קיים בספרייה',
    add_title: 'הוספת ספר',
    add_save: 'הוספה',
    dup_exact: 'הספר כבר קיים בספרייה',
    dup_similar: 'יש ספרים דומים בספרייה',
    dup_none: 'לא נמצא בספרייה',
    not_found: 'הספר לא נמצא',

    // --- Capture tab (P2.7, UI_PLAN §4) ---
    capture_tab: 'צילום וקריאה',
    drop_here: 'גררו לכאן תמונות מדף',
    drop_or_click: 'או לחצו לבחירה',
    phone_hint: (addr: string) => `מהטלפון (אותה רשת): פתחו ${addr} וצלמו ישירות`,
    select_all: 'בחר הכל',
    select_none: 'נקה',
    select_unread: 'רק חדשים',
    intake_empty: 'גררו לכאן תמונות של מדף כדי להתחיל',
    uploading: 'מעלה…',
    upload_failed: 'ההעלאה נכשלה',
    assign_shelf_label: 'לאיזה מדף?',
    unassigned: 'לא משויך',
    depth_n: (n: number) => `שורה ${n}`,
    add_row_behind: '+ הוספת שורה מאחור',
    mode_label: 'שיטת קריאה',
    mode_spines: 'פיצול לשדרות',
    mode_spines_d: 'Tesseract לכל שדרה · חינם · ~10 שנ׳ לשדרה',
    mode_full: 'תמונה שלמה',
    mode_full_d: 'קריאת Vision אחת לתמונה',
    mode_llm: 'קריאת LLM',
    mode_llm_d: 'Claude קורא אריחים · ~$0.15 לתמונה',
    run: (n: number) => `הרצה על הנבחרים (${n})`,
    stop_run: 'עצירה',
    reading_now: 'קורא…',
    review_now: 'מה נמצא — אישור מהיר',
    review_hint: 'אישור כאן הוא רק קיצור דרך. המדף הוא הבית של הספרים והיסטוריית הקריאות.',
    apply_to_shelf: 'החלה על המדף',
    read_added: 'נוספו',
    read_corrected: 'תוקנו',
    read_unchanged: 'ללא שינוי',
    read_unseen: (n: number) => `${n} לא נראו`,
    claim_unmatched: 'לא זוהה',
    tier_auto: 'זוהה',
    tier_review: 'לבדיקה',
    diff_added: 'חדש',
    diff_unchanged: 'היה כאן',
    diff_corrected: 'עודכן',
    diff_duplicate: 'כפילות?',
    diff_review: 'טעון אישור',
    diff_rejected: 'נדחה',
    diff_ignored: 'התעלמות',
    claim_confirm: 'אישור',
    claim_reject: 'לא נכון',
    why: 'למה?',
    alternatives: 'אפשרויות אחרות',
    alt_none: 'אין מועמדים נוספים',
    alt_candidate: 'מועמד',
    dup_q: (label: string) => `הספר הזה כבר רשום אצלכם — ${label}. זה…`,
    dup_same: 'אותו עותק',
    dup_another: 'עותק נוסף',
    dup_wrong: 'ספר שגוי',
    dup_default_note: 'ברירת המחדל: אותו עותק',
    staged_note: 'סומן — יוחל בלחיצה על "החלה על המדף"',
    run_failed: 'הקריאה נכשלה',
    open_shelf: 'פתחו את המדף →',

    // --- shelf detail (P2.8, UI_PLAN §3 level 3) ---
    shelf_not_found: 'המדף לא נמצא',
    shelf_untitled_photo_alt: 'תמונת המדף',
    shelf_last_read: (date: string) => `נקרא לאחרונה ב-${date}`,
    shelf_never_read: 'המדף הזה עדיין לא נקרא',
    stale_since: (row: string, date: string) => `${row} — לא נקרא מאז ${date}`,
    stale_never: (row: string) => `${row} — מעולם לא נקרא`,
    depth_bar_label: 'שורות המדף',
    shelf_books_title: 'הספרים בשורה זו',
    shelf_books_empty: 'אין ספרים ידועים בשורה הזו',
    not_seen_streak_one: 'לא נראה בקריאה האחרונה — עדיין שם?',
    not_seen_streak_n: (n: number) => `לא נראה ב-${n} הקריאות האחרונות — עדיין שם?`,
    shelf_history_title: 'היסטוריית קריאות',
    shelf_history_empty: 'אין עדיין קריאות למדף הזה',
    read_failed_short: 'נכשלה',
    read_stopped_short: 'נעצרה',

    // --- the image workspace (P2.10, §12.2 #10) ---
    open_image: 'מה נמצא בתמונה',
    workspace_title: 'התמונה וניתוחיה',
    workspace_hint: 'התמונה נשמרת. אפשר לחזור אליה מתי שרוצים — בלי לקרוא אותה שוב.',
    workspace_close: 'סגירת התמונה',
    workspace_runs: 'קריאות של התמונה הזו',
    workspace_no_runs: 'התמונה הזו עדיין לא נקראה',
    workspace_run_running: 'עדיין קוראת…',
    workspace_findings: 'מה נמצא',
    workspace_no_findings: 'הקריאה הזו לא מצאה ספרים בתמונה הזו',
    workspace_pick_run: 'בחרו קריאה כדי לראות מה היא מצאה',
    finding_approve: 'אישור הספר',
    finding_edit: 'תיקון פרטים',
    finding_retract: 'הסרה',
    finding_restore: 'ביטול ההסרה',
    finding_retracted_note: 'הוסר מכאן. קריאה נוספת של המדף לא תוסיף אותו שוב.',
    finding_approved_note: 'אושר',
    finding_fix_and_approve: 'תיקון ואישור',
    tier_manual: 'הוקלד ידנית',
    diff_pending: 'ממתין לאישור',
    read_pending: 'ממתינים לאישור',
    score_explained: 'ציון ההתאמה של המנוע, מתוך 130 — לא אחוזים',
    approve_all: (n: number) => `אישור כל הזיהויים האוטומטיים (${n})`,
    add_book_here: '+ הוספת ספר שהמנוע פספס',
    add_book_save: 'הוספה',
    workspace_pending_note: 'ספרים נכנסים לספרייה רק אחרי אישור.',
    try_match: 'התאמה אחרת?',
    alt_use: 'בחירה',
    raw_read: 'מה שנקרא:',
    read_removed: 'הוסרו',
    run_findings: (n: number) => `${n} ממצאים`,
    add_book_found: 'הקריאה הזו כבר מצאה:',
    finding_split: 'פיצול לכרכים',
    split_count: 'כמה כרכים',
    split_style: 'סימון',
    split_hebrew: 'אותיות (א, ב)',
    split_numbers: 'מספרים (1, 2)',
    split_roman: 'ספרות רומיות (I, II)',
    split_signal: 'כוכביות (*, **)',
    split_do: 'פיצול',
    author_known: 'מחברים בספרייה:',
  lang: 'EN',
}

/** The shape both languages must satisfy. Derived from Hebrew because Hebrew
 *  is the primary language (VISION §6), so a new string is added there first
 *  and English then FAILS TO COMPILE until it is translated. */
export type Strings = typeof HE

const EN: Strings = {
    app: 'booksnap',
    books: 'Books',
    search: 'Search by title or author',
    sort: 'Sort',
    sort_title: 'Title',
    sort_author: 'Author',
    sort_recent: 'Recently added',
    sort_relevance: 'Relevance',
    sort_ignored: 'Search results are ordered by relevance',
    sort_asc: 'Ascending',
    sort_desc: 'Descending',
    view_list: 'List',
    view_grid: 'Grid',
    add_book: 'Add a book',
    status: 'Status',
    st_auto: 'Auto',
    st_approved: 'Approved',
    st_manual: 'Manual',
    clear: 'Clear filters',
    by_author: 'by',
    count: (shown: number, total: number) =>
      shown >= total ? `${total} books` : `${shown} of ${total} books`,
    count_none: 'No books',
    empty: 'No books found',
    empty_hint: 'Try clearing the filters',
    loading: 'Loading…',
    load_error: 'Cannot reach the server',
    retry: 'Retry',
    details: 'Book details',
    open_full: 'Open full page',
    close: 'Close',
    back: 'Back',
    edit: 'Edit',
    save: 'Save',
    cancel: 'Cancel',
    title_label: 'Title',
    author_label: 'Author',
    saved: 'Saved',
    added_at: 'Added',
    last_seen: 'Last seen',
    lent_only: 'Lent out only',
    duplicates_only: 'Duplicates to resolve',
    copies: 'Copies',
    copy_n: (n: number) => `Copy ${n}`,
    copy_label: 'Label',
    copy_label_placeholder: 'e.g. paperback',
    copy_tags: 'Tags',
    copy_tags_placeholder: 'comma-separated',
    copy_condition: 'Condition',
    copy_details: 'Details',
    add_copy: 'I have another copy',
    // Not just "Edit" (t.edit) — that button already exists on the book
    // itself, and a screen reader announcing "Edit" twice on one screen
    // can't tell you which is which.
    copy_edit: 'Edit copy details',
    lending: 'Lending',
    lent_to: (who: string) => `Lent to ${who}`,
    due: (date: string) => `due ${date}`,
    not_lent: 'On the shelf',
    lend_it: 'Lend it out',
    lend_to_label: 'Lent to',
    due_at_label: 'Due date (optional)',
    lend_save: 'Lend',
    mark_returned: 'Mark returned',
    delete_book: 'Delete from library',
    delete_confirm: 'Delete this book from the library? This removes every copy.',
    delete_yes: 'Delete',
    export: 'Export',
    export_csv: 'Export CSV',
    export_json: 'Export JSON',
    conflict_edit: 'You already have a book with that title and author',
    conflict_add: 'That book is already in your library',
    add_title: 'Add a book',
    add_save: 'Add',
    dup_exact: 'Already in your library',
    dup_similar: 'Similar books already in your library',
    dup_none: 'Not in your library',
    not_found: 'Book not found',

    // --- Capture tab (P2.7, UI_PLAN §4) ---
    capture_tab: 'Capture',
    drop_here: 'Drop shelf photos here',
    drop_or_click: 'or click to choose',
    phone_hint: (addr: string) =>
      `From your phone (same Wi-Fi): open ${addr} and shoot straight into the app`,
    select_all: 'select all',
    select_none: 'clear',
    select_unread: 'only unread',
    intake_empty: 'Drop shelf photos here to get started',
    uploading: 'Uploading…',
    upload_failed: 'Upload failed',
    assign_shelf_label: 'Which shelf?',
    unassigned: 'Unassigned',
    depth_n: (n: number) => `Row ${n}`,
    add_row_behind: '+ Add a row behind',
    mode_label: 'Reading mode',
    mode_spines: 'Split to spines',
    mode_spines_d: 'Tesseract per spine · free · ~10s each',
    mode_full: 'Whole image',
    mode_full_d: '1 Vision call per photo',
    mode_llm: 'LLM read',
    mode_llm_d: 'Claude reads tiles · ~$0.15/photo',
    run: (n: number) => `Read selected (${n})`,
    stop_run: 'Stop',
    reading_now: 'Reading…',
    review_now: 'What we found — quick confirm',
    review_hint: 'Confirming here is a shortcut. The shelf is the durable home for these books and their history.',
    apply_to_shelf: 'Apply to shelf',
    read_added: 'added',
    read_corrected: 'corrected',
    read_unchanged: 'unchanged',
    read_unseen: (n: number) => `${n} not seen`,
    claim_unmatched: 'Unmatched',
    tier_auto: 'Auto',
    tier_review: 'Review',
    diff_added: 'new',
    diff_unchanged: 'already here',
    diff_corrected: 'updated',
    diff_duplicate: 'duplicate?',
    diff_review: 'needs confirm',
    diff_rejected: 'rejected',
    diff_ignored: 'ignored',
    claim_confirm: 'Confirm',
    claim_reject: 'Not right',
    why: 'why?',
    alternatives: 'Other candidates',
    alt_none: 'No other candidates',
    alt_candidate: 'candidate',
    dup_q: (label: string) => `This book is already listed — ${label}. Is this…`,
    dup_same: 'The listed copy',
    dup_another: 'Another copy',
    dup_wrong: 'Wrong book',
    dup_default_note: 'Default: the listed copy',
    staged_note: 'staged — applied when you click "Apply to shelf"',
    run_failed: 'The read failed',
    open_shelf: 'Open the shelf →',

    // --- shelf detail (P2.8, UI_PLAN §3 level 3) ---
    shelf_not_found: 'Shelf not found',
    shelf_untitled_photo_alt: 'Shelf photo',
    shelf_last_read: (date: string) => `Last read ${date}`,
    shelf_never_read: 'This shelf has never been read',
    stale_since: (row: string, date: string) => `${row} — not read since ${date}`,
    stale_never: (row: string) => `${row} — never read`,
    depth_bar_label: 'Shelf rows',
    shelf_books_title: 'Books on this row',
    shelf_books_empty: 'No known books on this row',
    not_seen_streak_one: 'Not seen in the last read — still there?',
    not_seen_streak_n: (n: number) => `Not seen in the last ${n} reads — still there?`,
    shelf_history_title: 'Read history',
    shelf_history_empty: 'No reads of this shelf yet',
    read_failed_short: 'failed',
    read_stopped_short: 'stopped',

    // --- the image workspace (P2.10, §12.2 #10) ---
    open_image: 'What this photo found',
    workspace_title: 'The photo and its reads',
    workspace_hint: 'The photo is kept. Come back to it whenever you like — it is never re-read just to look.',
    workspace_close: 'Close the photo',
    workspace_runs: 'Reads of this photo',
    workspace_no_runs: 'This photo has not been read yet',
    workspace_run_running: 'still reading…',
    workspace_findings: 'What it found',
    workspace_no_findings: 'This read found no books in this photo',
    workspace_pick_run: 'Pick a read to see what it found',
    finding_approve: 'Approve',
    finding_edit: 'Fix details',
    finding_retract: 'Remove',
    finding_restore: 'Undo the removal',
    finding_retracted_note: 'Removed from here. Another read of this shelf will not add it back.',
    finding_approved_note: 'Approved',
    finding_fix_and_approve: 'Fix and approve',
    tier_manual: 'Typed in',
    diff_pending: 'Awaiting approval',
    read_pending: 'awaiting approval',
    score_explained: "The engine's match score, out of 130 — not a percentage",
    approve_all: (n: number) => `Approve all auto (${n})`,
    add_book_here: '+ Add a book the engine missed',
    add_book_save: 'Add',
    workspace_pending_note: 'Books only join the library once you approve them.',
    try_match: 'Try a better match?',
    alt_use: 'Use this',
    raw_read: 'Read as:',
    read_removed: 'removed',
    run_findings: (n: number) => `${n} findings`,
    add_book_found: 'This read already found:',
    finding_split: 'Split into volumes',
    split_count: 'How many',
    split_style: 'Marked with',
    split_hebrew: 'Letters (א, ב)',
    split_numbers: 'Numbers (1, 2)',
    split_roman: 'Roman (I, II)',
    split_signal: 'Signal (*, **)',
    split_do: 'Split',
    author_known: 'Authors in your library:',
  lang: 'עב',
}

const STRINGS: Record<Lang, Strings> = { he: HE, en: EN }

interface I18nApi {
  lang: Lang
  dir: 'rtl' | 'ltr'
  t: Strings
  setLang: (lang: Lang) => void
  toggleLang: () => void
}

const Ctx = createContext<I18nApi | null>(null)
const STORAGE_KEY = 'booksnap.lang'

function initialLang(): Lang {
  try {
    const saved = globalThis.localStorage?.getItem(STORAGE_KEY)
    if (saved === 'he' || saved === 'en') return saved
  } catch {
    /* private mode; the default is fine */
  }
  return 'he'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang)
  const dir = lang === 'he' ? 'rtl' : 'ltr'

  // The whole layout mirrors off this one attribute, because every rule uses
  // logical properties (UI_PLAN §7.1) — and the two explicit `[dir=…]`
  // selectors that make mixed-script alignment work read it too (§7.2).
  useEffect(() => {
    document.documentElement.lang = lang
    document.documentElement.dir = dir
  }, [lang, dir])

  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    try {
      globalThis.localStorage?.setItem(STORAGE_KEY, next)
    } catch {
      /* nothing to do; the choice just won't persist */
    }
  }, [])

  const value = useMemo<I18nApi>(
    () => ({
      lang,
      dir,
      t: STRINGS[lang],
      setLang,
      toggleLang: () => setLang(lang === 'he' ? 'en' : 'he'),
    }),
    [lang, dir, setLang],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useI18n(): I18nApi {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useI18n outside <I18nProvider>')
  return ctx
}
