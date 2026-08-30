/**
 * he/en strings and the document direction.
 *
 * Hebrew is the primary language (VISION §6: RTL-first, "not
 * internationalisation polish"). English is not there for English speakers —
 * it is there because a real LTR mode is the only honest way to test that the
 * layout mirrors and that mixed-script alignment holds in both directions
 * (UI_PLAN §7.1/§7.2). Deleting it would make the bidi rules untestable.
 */
import { createI18n, type Lang } from '@booksnap/ui'

export type { Lang }

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
    view_list: 'רשימה',
    view_grid: 'רשת',
    add_book: 'הוספת ספר',
    status: 'סטטוס',
    clear: 'ניקוי סינון',
    by_author: 'מאת',
    // ⚠ The singular, in the app's most-read sentence. `1 ספרים` / `1 books`
    // shipped live in both languages — the SEVENTH instance of this defect,
    // and it survived because the guard that ends the class reads only the
    // MAP's string table. It reads every table now.
    count: (shown: number, total: number) =>
      shown >= total
        ? (total === 1 ? 'ספר אחד' : `${total} ספרים`)
        : `${shown} מתוך ${total === 1 ? 'ספר אחד' : `${total} ספרים`}`,
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
    plan_tab: 'המפה',
    plan_site_default: 'הבית',
    plan_floor_default: 'קומת קרקע',
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
    // ⚠ FUNCTIONS, and they were three bare nouns joined to a number in
    // JSX — which is the one shape the counted-string guard cannot see,
    // because there is no parameter to declare. `1 תוקנו` and `+1 נוספו`
    // were live in the read history. A number and its noun belong in the
    // same string, where the rule can reach them.
    read_added: (n: number) => (n === 1 ? 'נוסף אחד' : `${n} נוספו`),
    read_corrected: (n: number) => (n === 1 ? 'תוקן אחד' : `${n} תוקנו`),
    read_unchanged: (n: number) => (n === 1 ? 'אחד ללא שינוי' : `${n} ללא שינוי`),
    read_unseen: (n: number) => (n === 1 ? 'אחד לא נראה' : `${n} לא נראו`),
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

    // --- where is it (P6.5b, VISION §7, UI_PLAN §1.1) ---
    // ⚠ Three axes, three words that must never be shared: **column**
    // across, **level** down, **depth** back. `segment.py` already owns
    // *band* for the horizontal shelf rows inside one photo, which is a
    // vertical concept where depth is front-to-back.
    where_title: 'איפה זה עומד',
    where_nowhere: 'עדיין לא על המפה',
    where_unknown: 'לא הצלחנו לברר איפה זה עומד',
    where_unshelved: 'לא על מדף',
    where_case_unnamed: 'כוננית ללא שם',
    where_room_unnamed: 'חדר ללא שם',
    where_put_on_map: 'מקמו אותו על השרטוט →',
    where_col: (n: number) => `עמודה ${n}`,
    where_level: (n: number) => `גובה ${n}`,
    where_section: (n: number) => `יחידה ${n}`,
    // §5.7's reason for naming the row at all: reaching it means moving the
    // row in front of it. Said once, quietly, and only when there IS one.
    where_behind: 'צריך להזיז את השורה שלפניו',
    // → for onward and ← for back, the same way round in both languages:
    // the table's own `open_shelf` and the shelf screen's `← חזרה` already
    // agree on that, and an arrow is a glyph rather than something bidi
    // mirrors.
    where_open_shelf: 'למדף שלו →',
    where_show_on_map: 'הצגה על השרטוט →',

    // --- shelf detail (P2.8, UI_PLAN §3 level 3) ---
    shelf_not_found: 'המדף לא נמצא',
    shelf_unreachable: 'לא הצלחנו לטעון את המדף — נראה שאין חיבור לשרת',
    shelf_untitled_photo_alt: 'תמונת המדף',
    // --- filing a photo without reading it (P6.7d) ---
    attach_photo: 'הוספת תמונה',
    attach_photo_at: (depth: number) => `הוספת תמונה לשורה ${depth}`,
    // ⚠ The promise the Capture tab cannot make, and the reason this
    // control exists at all.
    attach_photo_hint: 'התמונה נשמרת למדף בלבד. לא נקראת, לא עולה כלום, ולא מוסיפה ספרים.',
    attaching_photo: 'שומרים…',
    photo_attached: 'התמונה נשמרה למדף',
    attach_photo_failed: 'לא הצלחנו לשמור את התמונה',
    shelf_last_read: (date: string) => `נקרא לאחרונה ב-${date}`,
    shelf_never_read: 'המדף הזה עדיין לא נקרא',
    // ⚠ Our words FIRST — `unicode-bidi: plaintext` resolves a paragraph from
    // its first strong character, so a Latin-initial shelf name would flip the
    // whole line. The same rule the map's own flashes carry.
    shelf_formerly: (name: string) => `היה גם: ${name}`,
    // The fallback for an unnamed shelf: the address is what a person reads
    // off the drawing, and §3.11 records it rather than deriving it for
    // exactly this moment.
    shelf_formerly_at: (col: number, level: number) =>
      `המדף שהיה בעמודה ${col} · גובה ${level}`,
    stale_since: (row: string, date: string) => `${row} — לא נקרא מאז ${date}`,
    stale_never: (row: string) => `${row} — מעולם לא נקרא`,
    depth_bar_label: 'שורות המדף',
    shelf_books_title: 'הספרים בשורה זו',
    shelf_books_empty: 'אין ספרים ידועים בשורה הזו',
    not_seen_streak_one: 'לא נראה בקריאה האחרונה — עדיין שם?',
    not_seen_streak_n: (n: number) => (n === 1
      ? 'לא נראה בקריאה האחרונה — עדיין שם?'
      : `לא נראה ב-${n} הקריאות האחרונות — עדיין שם?`),
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
    run_findings: (n: number) => (n === 1 ? 'ממצא אחד' : `${n} ממצאים`),
    add_book_found: 'הקריאה הזו כבר מצאה:',
    finding_split: 'פיצול לכרכים',
    finding_split_short: 'פיצול',
    split_count: 'כמה כרכים',
    split_style: 'סימון',
    split_hebrew: 'אותיות (א, ב)',
    split_numbers: 'מספרים (1, 2)',
    split_roman: 'ספרות רומיות (I, II)',
    split_signal: 'כוכביות (*, **)',
    split_do: 'צרו כרכים',
    author_known: 'מחברים בספרייה:',
    // P3.1 — the library switcher (§4.1, UI_PLAN §1). "ספרייה" is the
    // TENANCY boundary, the household's collection; a place you keep books
    // is a different word and arrives with the map (pillar 6).
    // The engine has always reported these; the tab used to show one static
    // "reading…" for minutes, which is indistinguishable from a hung job.
    run_busy: 'קריאה כבר רצה',
    stage_reading: (done: number, total: number) =>
      `קורא את התמונה… ${done}/${total}`,
    stage_page_read: (n: number) => (n === 1
      ? 'נקרא ספר אחד מהתמונה' : `נקראו ${n} ספרים מהתמונה`),
    stage_segmented: (n: number) => (n === 1 ? 'זוהתה שדרה אחת' : `זוהו ${n} שדרות`),
    stage_ocr: (done: number, total: number) => `קורא שדרות… ${done}/${total}`,
    stage_matching: (done: number, total: number) =>
      `מזהה ספרים בקטלוג… ${done}/${total}`,
    stage_stopping: 'עוצר…',
    stage_queued: 'ממתין בתור…',
    library_switch: 'החלפת ספרייה',
    library_new: '+ ספרייה חדשה',
    library_create_hint:
      'ספרייה נפרדת היא אוסף נפרד — של אדם או משק בית אחר. חדרים ומקומות ' +
      'בבית אינם ספריות; הם יגיעו עם המפה.',
    library_name: 'שם הספרייה',
    library_name_placeholder: 'למשל משפחת מלין',
    library_create: 'יצירה',
    library_unnamed: 'ספרייה',
    library_unknown: 'ספרייה',
    role: {
      viewer: 'צפייה',
      editor: 'עריכה',
      admin: 'ניהול',
    } as Record<string, string>,

  // --- members and invites (P4.3, §4.1) ---
  members_open: 'משתתפים',
  members_title: 'משתתפי החשבון',
  members_loading: 'טוען…',
  member_role_of: 'תפקיד של',
  member_remove: 'הסרה',
  invite_title: 'הזמנה לחשבון',
  invite_role: 'תפקיד למוזמן',
  invite_create: 'יצירת קישור הזמנה',
  invite_once: 'העתיקו עכשיו — הקישור לא יוצג שוב.',
  invite_link: 'קישור ההזמנה',
  invite_copy: 'העתקה',
  invite_copied: 'הועתק',
  invite_expires: 'בתוקף עד',
  invite_revoke: 'ביטול',
  invite_dead: 'ההזמנה פגה, נוצלה או בוטלה — בקשו קישור חדש.',

  // --- sign-in (P4.1b/P4.1c, VISION §3/§4.3) ---
  onboard_title: 'הספרייה הראשונה שלך',
  onboard_intro: 'תנו שם לאוסף — למשל שם המשפחה. מדפים וספרים מצטרפים מיד אחר כך.',
  onboard_create: 'יצירת הספרייה',
  login_title: 'כניסה',
  login_intro: 'הזינו את כתובת האימייל ונשלח קישור כניסה.',
  login_email: 'אימייל',
  login_send: 'שליחת קישור',
  login_sending: 'שולח…',
  login_sent: 'אם הכתובת יכולה להיכנס לכאן, קישור בדרך אליה. פתחו אותו מהמכשיר הזה.',
  login_link_bad: 'הקישור פג תוקף או שכבר נוצל — בקשו קישור חדש.',
  login_provider_failed: 'הכניסה דרך הספק לא הושלמה — נסו שוב או בקשו קישור.',
  login_or: 'או',
  login_with_google: 'כניסה עם Google',
  login_with_apple: 'כניסה עם Apple',
  login_sent_log: 'בגרסת הפיתוח אין דואר: הקישור מודפס ביומן השרת, במחשב שמריץ אותו.',
  login_again: 'שליחה שוב',
  login_rate: 'יותר מדי בקשות — נסו שוב בעוד כשעה.',
  login_error: 'אין חיבור לשרת — נסו שוב.',
  account_menu: 'חשבון',
  sign_out: 'התנתקות',
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
    view_list: 'List',
    view_grid: 'Grid',
    add_book: 'Add a book',
    status: 'Status',
    clear: 'Clear filters',
    by_author: 'by',
    count: (shown: number, total: number) =>
      shown >= total
        ? (total === 1 ? '1 book' : `${total} books`)
        : `${shown} of ${total === 1 ? '1 book' : `${total} books`}`,
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
    plan_tab: 'Map',
    plan_site_default: 'Home',
    plan_floor_default: 'Ground floor',
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
    read_added: (n: number) => (n === 1 ? '1 added' : `${n} added`),
    read_corrected: (n: number) => (n === 1 ? '1 corrected' : `${n} corrected`),
    read_unchanged: (n: number) => (n === 1 ? '1 unchanged' : `${n} unchanged`),
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

    // --- where is it (P6.5b, VISION §7, UI_PLAN §1.1) ---
    where_title: 'Where it is',
    where_nowhere: 'Not on the map yet',
    where_unknown: "Couldn't find out where it is",
    where_unshelved: 'Not on a shelf',
    where_case_unnamed: 'unnamed bookcase',
    where_room_unnamed: 'unnamed room',
    where_put_on_map: 'Put it on the drawing →',
    where_col: (n: number) => `column ${n}`,
    where_level: (n: number) => `level ${n}`,
    where_section: (n: number) => `section ${n}`,
    where_behind: 'the row in front has to be moved',
    where_open_shelf: 'Open its shelf →',
    where_show_on_map: 'Show it on the drawing →',

    // --- shelf detail (P2.8, UI_PLAN §3 level 3) ---
    shelf_not_found: 'Shelf not found',
    shelf_unreachable: "Couldn't load the shelf — the server looks unreachable",
    shelf_untitled_photo_alt: 'Shelf photo',
    attach_photo: 'Add a photo',
    attach_photo_at: (depth: number) => `Add a photo of row ${depth}`,
    attach_photo_hint:
      'The photo is filed against this shelf. It is not read, it costs '
      + 'nothing, and it adds no books.',
    attaching_photo: 'Saving…',
    photo_attached: 'The photo is filed against this shelf',
    attach_photo_failed: "Couldn't save that photo",
    shelf_last_read: (date: string) => `Last read ${date}`,
    shelf_never_read: 'This shelf has never been read',
    shelf_formerly: (name: string) => `Formerly also: ${name}`,
    shelf_formerly_at: (col: number, level: number) =>
      `the shelf that was at column ${col} · level ${level}`,
    stale_since: (row: string, date: string) => `${row} — not read since ${date}`,
    stale_never: (row: string) => `${row} — never read`,
    depth_bar_label: 'Shelf rows',
    shelf_books_title: 'Books on this row',
    shelf_books_empty: 'No known books on this row',
    not_seen_streak_one: 'Not seen in the last read — still there?',
    not_seen_streak_n: (n: number) => (n === 1
      ? 'Not seen in the last read — still there?'
      : `Not seen in the last ${n} reads — still there?`),
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
    run_findings: (n: number) => (n === 1 ? '1 finding' : `${n} findings`),
    add_book_found: 'This read already found:',
    finding_split: 'Split into volumes',
    finding_split_short: 'Split',
    split_count: 'How many',
    split_style: 'Marked with',
    split_hebrew: 'Letters (א, ב)',
    split_numbers: 'Numbers (1, 2)',
    split_roman: 'Roman (I, II)',
    split_signal: 'Signal (*, **)',
    split_do: 'Create volumes',
    author_known: 'Authors in your library:',
    run_busy: 'A read is already running',
    stage_reading: (done: number, total: number) =>
      `Reading the photo… ${done}/${total}`,
    stage_page_read: (n: number) => (n === 1
      ? 'Read 1 book off the photo' : `Read ${n} books off the photo`),
    stage_segmented: (n: number) => (n === 1 ? 'Found 1 spine' : `Found ${n} spines`),
    stage_ocr: (done: number, total: number) => `Reading spines… ${done}/${total}`,
    stage_matching: (done: number, total: number) =>
      `Matching against the catalogue… ${done}/${total}`,
    stage_stopping: 'Stopping…',
    stage_queued: 'Waiting in the queue…',
    library_switch: 'Switch library',
    library_new: '+ New library',
    library_create_hint:
      "A separate library is a separate collection — another person's or "
      + "household's. Rooms and places in the house are not libraries; those "
      + 'arrive with the Map.',
    library_name: 'Library name',
    library_name_placeholder: 'e.g. The Malin family',
    library_create: 'Create',
    library_unnamed: 'Library',
    library_unknown: 'Library',
    role: {
      viewer: 'Viewer',
      editor: 'Editor',
      admin: 'Admin',
    },

  // --- members and invites (P4.3, §4.1) ---
  members_open: 'People',
  members_title: 'Account members',
  members_loading: 'Loading…',
  member_role_of: 'Role of',
  member_remove: 'Remove',
  invite_title: 'Invite to the account',
  invite_role: 'Role for the invitee',
  invite_create: 'Create invite link',
  invite_once: 'Copy it now — the link will not be shown again.',
  invite_link: 'Invite link',
  invite_copy: 'Copy',
  invite_copied: 'Copied',
  invite_expires: 'Valid until',
  invite_revoke: 'Revoke',
  invite_dead: 'That invite has expired, was used, or was revoked — ask for a new link.',

  // --- sign-in (P4.1b/P4.1c, VISION §3/§4.3) ---
  onboard_title: 'Your first library',
  onboard_intro: 'Name the collection — the family name works well. Shelves and books come right after.',
  onboard_create: 'Create the library',
  login_title: 'Sign in',
  login_intro: 'Enter your email address and we will send a sign-in link.',
  login_email: 'Email',
  login_send: 'Send link',
  login_sending: 'Sending…',
  login_sent: 'If that address can sign in here, a link is on its way. '
    + 'Open it on this device.',
  login_link_bad: 'That link has expired or was already used — request a '
    + 'new one.',
  login_provider_failed: 'That sign-in did not complete — try again, or '
    + 'ask for a link.',
  login_or: 'or',
  login_with_google: 'Sign in with Google',
  login_with_apple: 'Sign in with Apple',
  login_sent_log: 'The dev build has no mail: the link is printed in the '
    + 'server log, on the machine running it.',
  login_again: 'Send again',
  login_rate: 'Too many requests — try again in about an hour.',
  login_error: 'Cannot reach the server — try again.',
  account_menu: 'Account',
  sign_out: 'Sign out',
  lang: 'עב',
}

/**
 * The provider and the hook come from `@booksnap/ui` now — the mechanism
 * (the toggle, the `dir`/`lang` mirroring, the persistence) was identical in
 * both clients down to the comments. What stays here is the TABLE, which is
 * this app's vocabulary and deliberately not shared: the console speaks about
 * accounts and totals, and one merged table would serve two intents.
 *
 * ⚠ `'booksnap.lang'` is this app's own key, and the console has another. The
 * day both are served from one origin, one key would mean switching language
 * in the console silently switched the household's app too.
 */
/** Both tables, so a guard can read every string rather than one table.
 *
 *  ⚠ Exported for `i18n.test.tsx`, which enforces the counted-string and
 *  name-first rules over BOTH — the map's own table has carried those guards
 *  since P6.3.2 and this one had neither, which is how `1 books` reached a
 *  real browser in the most-read sentence in the product. */
export const STRINGS = { he: HE, en: EN }

export const { I18nProvider, useI18n } = createI18n<Strings>(
  STRINGS,
  { storageKey: 'booksnap.lang' },
)
