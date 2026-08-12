/**
 * he/en strings and the document direction, for the console.
 *
 * Hebrew is the primary language (VISION §6: RTL-first). English is not here
 * for English speakers — it is the only honest way to see that the layout
 * mirrors, which is a correctness property of a screen full of mixed Hebrew
 * library names and Latin ids, not internationalisation polish. Deleting it
 * would make the bidi rules untestable, exactly as `app/web` records.
 *
 * A separate table from the product's on purpose: this vocabulary is an
 * administrator's (accounts, roles, totals), and a shared file would grow two
 * intents. The IDIOM is deliberately identical, so a reader of one recognises
 * the other.
 */
import { createI18n, type Lang } from '@booksnap/ui'

export type { Lang }

const HE = {
  app: 'booksnap',
  console: 'ניהול',
  nav_dashboard: 'סקירה',
  nav_accounts: 'חשבונות',
  nav_books: 'ספרים',
  nav_images: 'תמונות',
  nav_access: 'גישה',
  lang_toggle: 'English',

  none: 'אין',
  cancel: 'ביטול',
  save: 'שמירה',
  close: 'סגירה',
  refresh: 'רענון',

  // dashboard
  dash_title: 'סקירת המערכת',
  stat_books: 'ספרים',
  stat_duplicates: 'כפילויות לבירור',
  stat_lent: 'מושאלים',
  stat_approved: 'אושרו',
  stat_manual: 'הוזנו ידנית',
  stat_unapproved: 'ממתינים לאישור',
  dash_per_account: 'לפי חשבון',
  stat_accounts_tenants: 'חשבונות',
  stat_people: 'אנשים',
  stat_memberships: 'חברויות',
  stat_copies: 'עותקים',
  stat_reads: 'קריאות',
  sys_scope: 'כל הנתונים כאן חוצים את כל הדיירים במערכת',
  sys_orphans: (n: number) =>
    `${n} ספריות שלחשבון הבעלים שלהן אין אף חבר — איש אינו יכול לראות או לנהל אותן`,
  staff_unreachable: 'שירות הניהול אינו זמין. ודאו שהוא רץ על פורט 8758.',
  token_title: 'אסימון ניהול',
  token_needed: 'שירות הניהול דורש אסימון. הזינו אותו כדי להמשיך.',
  token_hint: 'הערך של BOOKSNAP_STAFF_TOKEN בשרת. נשמר בדפדפן הזה בלבד.',
  token_save: 'שמירה',
  token_clear: 'ניקוי',
  token_open_warning:
    'שירות הניהול פועל ללא אסימון: כל מי שמגיע לפורט 8758 קורא את כל הדיירים. הגדירו BOOKSNAP_STAFF_TOKEN והפעילו מחדש.',
  token_ok: 'מוגן באסימון',
  th_library: 'ספרייה',
  // ⚠ A shelf column is NOT the library column. Reusing `th_library` for it
  // (the first draft did) puts the word "library" over a list of shelf names,
  // on a screen whose whole subject is one library — which reads as a bug in
  // the data rather than in the heading.
  //
  // ⚠⚠ THREE headers, not one. Until P3.7e `th_account` sat over three
  // different entities — customers (the accounts table, the dashboard),
  // people (the unaffiliated list, the drawer's members) and libraries (the
  // images table and panel). One string over three nouns is what let the
  // console keep saying "account" while showing a `Library`, and since P3.7b
  // an Account is a real record that a library belongs to. Splitting them was
  // a PREREQUISITE of the screens' rewrite, not a cleanup after it.
  th_account: 'חשבון',
  th_user: 'משתמש',
  th_email: 'דוא״ל',
  th_users: 'משתמשים',
  th_admins: 'מנהלים',
  th_activity: 'פעילות אחרונה',
  th_findings: 'ממצאים',
  th_role: 'תפקיד',
  th_books: 'ספרים',
  th_duplicates: 'כפילויות',
  th_lent: 'מושאלים',
  // ⚠ TWO verbs, because Hebrew agrees with its subject. `ספרייה` is
  // feminine, `חשבון` is masculine, and this key sat over a library until
  // P3.7e put a customer under it — the same mistake as `th_account` over
  // three nouns, one part of speech along.
  th_created: 'נוצרה',
  th_created_m: 'נוצר',
  th_status: 'סטטוס',
  th_title: 'כותרת',
  th_author: 'מחבר',
  th_copies: 'עותקים',
  th_added: 'נוסף',
  // A WORK's spread. Deliberately not `th_library` — that one names ONE
  // library and this counts them, and the console's whole revision-4 point
  // is that a book does not have a library.
  th_libraries: 'ספריות',
  th_first_found: 'נמצא לראשונה',
  th_images: 'תמונות',
  th_storage: 'אחסון',

  // libraries
  lib_mine: 'שלי',
  lib_readonly: 'קריאה בלבד — אינכם חברים בספרייה הזו',
  lib_create_note: 'ספרייה חדשה נוצרת תחת החשבון שלכם, ואתם הופכים למנהל שלה. אין דרך ליצור ספרייה עבור חשבון אחר.',
  lib_new: 'ספרייה חדשה',
  lib_name: 'שם הספרייה',
  lib_name_hint: 'לספרייה חייב להיות שם — היא נבחרת מרשימה, ושתי שורות ריקות אי אפשר להבחין ביניהן',
  lib_create: 'יצירה',
  lib_rename: 'שינוי שם',
  lib_empty: 'אין ספריות',
  lib_export_csv: 'CSV',
  lib_export_json: 'JSON',
  // ⚠ שלושת הפעולות שיושבות על שורת ספרייה זקוקות לשם נגיש ייחודי. שתי שורות
  // שמכריזות "שינוי שם" מתנגשות — והמתנגשת שכותבת היא זו שמשנה שם.
  lib_rename_of: (name: string) => `שינוי השם של ${name}`,
  lib_csv_of: (name: string) => `ייצוא ${name} כ-CSV`,
  lib_json_of: (name: string) => `ייצוא ${name} כ-JSON`,
  lib_id: 'מזהה',
  lib_unnamed: 'ללא שם',
  // ⚠ מדף ללא שם אינו ספרייה ללא שם. שימוש חוזר ב-lib_unnamed מציב את המילה
  // "ספרייה" מעל שם מדף, בטבלה שיש בה עמודת ספרייה אמיתית שני תאים משם.
  shelf_unnamed: 'מדף ללא שם',
  lib_no_delete: 'אין מחיקת ספרייה: המחיקה גוררת כל ספר, מדף, קריאה ותצלום שבתוכה, והשרת אינו מציע אותה.',

  // library detail
  ld_never_read: 'לא נקראה',
  ld_no_members: 'אין חברים — איש אינו יכול לראות את החשבון הזה או לנהל אותו',

  // books
  books_title: 'כל הספרים במערכת',
  books_all_libraries: 'כל הספריות',
  books_search: 'חיפוש לפי כותרת או מחבר',
  books_status_any: 'כל הסטטוסים',
  books_sort: 'מיון',
  sort_title: 'כותרת',
  sort_author: 'מחבר',
  sort_first_found: 'נמצאו לראשונה',
  sort_spread: 'במספר הספריות הגדול ביותר',
  books_sort_ignored: 'בחיפוש התוצאות מסודרות לפי רלוונטיות',
  // What the box READS while the server is ignoring the key — the
  // ordering actually in force, not a stale choice nobody applies.
  books_sort_relevance: 'רלוונטיות',
  books_empty: 'לא נמצאו ספרים',
  books_truncated: 'החיפוש נעצר במגבלת הסריקה של השרת. צמצמו את החיפוש כדי להגיע לשאר.',
  books_readonly: 'לא ניתן לערוך: אינכם חברים בספרייה הזו. הפעולות זמינות רק בספריות שלכם.',
  books_count: (shown: number, total: number) =>
    shown >= total ? `${total} ספרים` : `${shown} מתוך ${total} ספרים`,
  books_prev: 'הקודם',
  books_next: 'הבא',

  // works — books, aggregated across כל הדיירים
  works_sub: 'שורה אחת לכל ספר, בכל המערכת. הספרייה אינה תכונה של ספר — היא רשימה שלו.',
  works_mixed: 'סטטוס מעורב',
  works_where: 'איפה הוא נמצא',
  works_gone: 'אף ספרייה אינה מחזיקה את הספר הזה כרגע',
  works_last_added: 'נוסף לאחרונה',
  works_open_spread: (n: number) =>
    n === 1 ? 'הצגת הספרייה שמחזיקה את הספר'
            : `הצגת ${n} הספריות שמחזיקות את הספר`,
  works_copies_here: (n: number) => (n === 1 ? 'עותק אחד' : `${n} עותקים`),
  works_on_shelves: (n: number) => (n === 1 ? 'על מדף אחד' : `על ${n} מדפים`),
  works_display_title:
    'הכותרת למעלה היא האיות של אחת הספריות — החזק ביותר, ובמקרה של תיקו הוותיק ביותר. לכל ספרייה מופיע האיות שלה למטה.',
  works_edit_rekeys:
    'שינוי כותרת או מחבר משנה את זהות הספר, ולכן העותק הזה עשוי לעבור לשורה אחרת ברשימה.',
  works_filter_keeps_spread:
    'הסינון בוחר אילו ספרים מוצגים; מספר הספריות שבשורה נשאר המספר האמיתי.',

  // images — התמונה היא הישות; המדף הוא שיוך זמני (VISION §4.1a)
  img_title: 'כל התמונות במערכת',
  img_sub: 'התמונה היא הישות. השיוך למדף הוא זמני — המפה הפיזית (בקשה 6) תחליף אותו.',
  img_panel: 'פרטי התמונה',
  img_empty: 'אין תמונות',
  img_taken: 'צולמה',
  img_undated: 'ללא תאריך',
  img_filed_at: 'מתויקת ב',
  img_depth_n: (n: number) => `שורה ${n}`,
  img_order_n: (n: number) => `מיקום ${n}`,
  img_runs: 'קריאות',
  img_last_read: 'קריאה אחרונה',
  img_missing: 'הקבצים חסרים',
  img_missing_long: 'הקובץ אינו נמצא בדיסק. התמונה הזו אבדה מבחינת בעלי הספרייה.',
  img_no_preview: 'התצוגה המקדימה זמינה רק בספריות שאתם חברים בהן. הנתונים חוצים דיירים; התצלומים לא.',
  img_alt: 'תצלום המדף',
  img_filename: 'שם הקובץ',
  img_key: 'כתובת תוכן',
  img_read_nothing: 'הקריאה עברה על התמונה הזו ולא מצאה דבר — כנראה נושא לבדיקה.',
  img_readonly: 'קריאה בלבד: שירות הניהול אינו כותב. מחיקה או שיוך מחדש נעשים באפליקציה של הבית.',
  img_tiers: (auto: number, review: number, unmatched: number) =>
    `${auto} אוטומטי · ${review} לבדיקה · ${unmatched} ללא התאמה`,
  img_count: (shown: number, total: number) =>
    shown >= total ? `${total} תמונות` : `${shown} מתוך ${total} תמונות`,
  img_blind:
    'השירות אינו רואה את ספריית הקבצים, ולכן כל התמונות מדווחות כחסרות ואין נתוני נפח. זה אומר "לא בדקנו", לא "אבד".',

  // accounts — הלקוח של המפעיל, ומאז P3.7b גם רשומה אמיתית שהספרייה שייכת לה.
  acct_title: 'חשבונות',
  acct_sub: 'כל לקוח במערכת: מי מנהל אותו, כמה משתמשים, כמה ספריות הוא מחזיק, כמה ספרים וכמה מקום התמונות תופסות.',
  acct_panel: 'פרטי החשבון',
  acct_unnamed: 'חשבון ללא שם',
  acct_empty: 'אין חשבונות',
  // ⚠ מזהה שאינו מצביע על כלום. שתיקה מלמדת את המפעיל שהקישור נשבר, וזו בדיוק
  // ההודעה שהניתוב הזה קיים כדי למנוע.
  acct_unknown: 'המזהה בקישור אינו מתאים לאף חשבון ואף ספרייה במערכת.',
  // ⚠ "אין" מול "לא ידוע" — שני מצבים שונים לגמרי. ראו peopleKnown.
  acct_people_unknown: 'רשימת האנשים אינה זמינה כרגע, ולכן אי אפשר לומר מי מנהל את החשבון הזה.',
  acct_libs_unknown: 'רשימת הספריות אינה זמינה כרגע.',
  acct_no_admin: 'אין מנהל',
  acct_users: 'משתמשים',
  acct_books: 'ספרים',
  acct_images: 'תמונות',
  acct_joined: 'הצטרף',
  // ⚠ הספריות של החשבון — הרשימה שהחליפה את תווית המיפוי `acct_library_id`.
  // התווית ההיא הסבירה שאנחנו אומרים "חשבון" ומאחסנים Library; היום זה פשוט
  // לא נכון, והמיפוי הוא נתון: לכל ספרייה שורה משלה עם המזהה שלה.
  acct_lib_sub: 'האוספים שהחשבון הזה מחזיק. שינוי שם וייצוא הם פעולות על ספרייה, ולכן הם כאן ולא על שורת החשבון.',
  acct_lib_none: 'החשבון הזה אינו מחזיק אף ספרייה',
  acct_books_of: (name: string) => `הספרים של ${name}`,
  acct_images_of: (name: string) => `התמונות של ${name}`,
  acct_recent: 'נוסף לאחרונה, בכל ספריות החשבון',
  acct_no_member_management:
    'הזמנה, הסרה ושינוי תפקיד אינם קיימים באף אחד משני השירותים — הם מחכים להתחברות (P4.1) ולזרימת ההזמנה (P4.3).',
  acct_unaffiliated: 'משתמשים ללא שיוך',
  acct_unaffiliated_why:
    'אנשים שאינם חברים באף חשבון. עד שתהיה התחברות איש אינו יכול להגיע אליהם, וזה המקום היחיד שבו הם מופיעים.',

  // book panel
  bp_title: 'פרטי הספר',
  bp_library: 'ספרייה',
  bp_status: 'סטטוס',
  bp_copies: 'עותקים',
  bp_unshelved: 'לא משויך למדף',
  bp_approve: 'אישור',
  bp_edit: 'עריכת כותרת ומחבר',
  bp_delete: 'מחיקה מהספרייה',
  bp_delete_confirm: 'למחוק את הספר מהספרייה? הפעולה מוחקת כל עותק ורושמת דחייה, כך שקריאה הבאה של המדף לא תחזיר אותו.',
  bp_delete_yes: 'מחיקה',
  bp_title_label: 'כותרת',
  bp_author_label: 'מחבר',

  // access
  acc_title: 'גישה',
  acc_memberships: 'חברויות',
  users_unnamed: 'ללא שם',
  acc_system_admin: 'מנהל מערכת',
  acc_account_admin: 'מנהל חשבון',
  // ⚠ "בתוך ספרייה אחת" היה נכון עד P3.7b וכבר אינו: תפקיד נקבע ברמת החשבון
  // ומכסה כל ספרייה שהחשבון מחזיק. משפט שמצמצם אותו לספרייה אחת הוא בדיוק
  // הסוג של נימוק שגוי שגורם לקורא הבא למחוק את השמירה הנכונה.
  acc_two_admins:
    'יש כאן שני תפקידים שונים. מנהל המערכת — הכלי הזה — רואה את כל הלקוחות ואינו חבר באף חשבון. מנהל חשבון הוא תפקיד בתוך חשבון אחד, והוא חל על כל הספריות שהחשבון מחזיק; הוא זה שמזמין בני משפחה. השרת עדיין אינו אוכף אף אחד מהם.',
  acc_gap_title: 'מה שאין עדיין',
  acc_gap_intro:
    'ניהול משתמשים אינו קיים בשרת, ולכן אינו מופיע כאן. אלה הפערים, ומה נדרש כדי לסגור אותם:',
  // ⚠ לחשבון, לא לספרייה: מאז P3.7b חברות מצביעה על חשבון, והזמנה אחת נותנת
  // גישה לכל מה שהחשבון מחזיק. השורה הזו סתרה את הפסקה שמעליה.
  acc_gap_invite: 'הזמנת משתמש לחשבון — נדרש מנגנון התחברות (P4.1) וזרימת הזמנה (P4.3).',
  acc_gap_roles: 'שינוי תפקיד או הסרת חבר — אין נקודת קצה, וההרשאות עצמן עדיין אינן נאכפות (P3.2).',
  acc_gap_list: 'משתמש עדיין אינו יכול להתחבר — אין מנגנון התחברות, ולכן כל בקשה מגיעה כאותו משתמש פיתוח (P4.1).',
  // ⚠ שלושה מספרים שונים. עד P3.7e הראשון היה מספר האנשים בתווית "חשבונות"
  // והשני מספר הספריות — שני שמות למה שהיה אז ישות אחת. מאז P3.7b אלה שלוש
  // ישויות, ולכן שלוש ספירות.
  acc_gap_counts: (accounts: number, users: number, libraries: number) =>
    `כרגע: ${accounts} חשבונות, ${users} משתמשים, ${libraries} ספריות.`,
  acc_gap_delete: 'מחיקת ספרייה — פעולה חוצת שישה אגרגטים, ממתינה למדיניות (P3.2) ולפינוי קבצים (P3.5).',
  acc_no_auth:
    'אין כאן התחברות. הכלי חשוף לכל מי שנמצא ברשת המקומית, בדיוק כמו שאר המערכת עד פילר 4.',
}
// ⚠ No `as const`. It would give every entry a LITERAL type, and the English
// table — typed as `typeof HE` so a missing translation is a build error —
// would then have to equal the Hebrew strings themselves.

export type Strings = typeof HE

const EN: Strings = {
  app: 'booksnap',
  console: 'admin',
  nav_dashboard: 'Overview',
  nav_accounts: 'Accounts',
  nav_books: 'Books',
  nav_images: 'Images',
  nav_access: 'Access',
  lang_toggle: 'עברית',

  none: 'None',
  cancel: 'Cancel',
  save: 'Save',
  close: 'Close',
  refresh: 'Refresh',

  dash_title: 'System overview',
  stat_books: 'Books',
  stat_duplicates: 'Duplicates to resolve',
  stat_lent: 'Lent out',
  stat_approved: 'Approved',
  stat_manual: 'Entered by hand',
  stat_unapproved: 'Awaiting approval',
  dash_per_account: 'By account',
  stat_accounts_tenants: 'Accounts',
  stat_people: 'People',
  stat_memberships: 'Memberships',
  stat_copies: 'Copies',
  stat_reads: 'Reads',
  sys_scope: 'Everything here spans every tenant in the system',
  sys_orphans: (n: number) =>
    `${n} librar${n === 1 ? 'y' : 'ies'} whose owning account has no member at all — nobody can see or administer ${n === 1 ? 'it' : 'them'}`,
  staff_unreachable: 'The staff service is unreachable. Check that it is running on port 8758.',
  token_title: 'Staff token',
  token_needed: 'The staff service requires a token. Enter it to continue.',
  token_hint: "The server's BOOKSNAP_STAFF_TOKEN value. Stored in this browser only.",
  token_save: 'Save',
  token_clear: 'Clear',
  token_open_warning:
    'The staff service is running with no token: anyone who can reach port 8758 reads every tenant. Set BOOKSNAP_STAFF_TOKEN and restart.',
  token_ok: 'Token protected',
  th_library: 'Library',
  th_account: 'Account',
  th_user: 'User',
  th_email: 'Email',
  th_users: 'Users',
  th_admins: 'Admins',
  th_activity: 'Last activity',
  th_findings: 'Findings',
  th_role: 'Role',
  th_books: 'Books',
  th_duplicates: 'Duplicates',
  th_lent: 'Lent',
  th_created: 'Created',
  th_created_m: 'Created',
  th_status: 'Status',
  th_title: 'Title',
  th_author: 'Author',
  th_copies: 'Copies',
  th_added: 'Added',
  th_libraries: 'Libraries',
  th_first_found: 'First found',
  th_images: 'Images',
  th_storage: 'Storage',

  lib_mine: 'mine',
  lib_readonly: 'Read-only — you are not a member of this library',
  lib_create_note: 'A new library is created under YOUR account, with you as its admin. There is no way to create one for another account.',
  lib_new: 'New library',
  lib_name: 'Library name',
  lib_name_hint:
    'A library must be named — it is chosen from a list, and two blank rows cannot be told apart',
  lib_create: 'Create',
  lib_rename: 'Rename',
  lib_empty: 'No libraries',
  lib_export_csv: 'CSV',
  lib_export_json: 'JSON',
  lib_rename_of: (name: string) => `Rename ${name}`,
  lib_csv_of: (name: string) => `Export ${name} as CSV`,
  lib_json_of: (name: string) => `Export ${name} as JSON`,
  lib_id: 'Id',
  lib_unnamed: 'Unnamed',
  shelf_unnamed: 'Unnamed shelf',
  lib_no_delete:
    'No library deletion: it would take every book, shelf, read and photo inside it, and the server does not offer it.',

  ld_never_read: 'Never read',
  ld_no_members: 'No members — nobody can see or administer this account',

  books_title: 'Every book in the system',
  books_all_libraries: 'All libraries',
  books_search: 'Search by title or author',
  books_status_any: 'Any status',
  books_sort: 'Sort',
  sort_title: 'Title',
  sort_author: 'Author',
  sort_first_found: 'First found',
  sort_spread: 'In most libraries',
  books_sort_ignored: 'While searching, results are ordered by relevance',
  books_sort_relevance: 'Relevance',
  books_empty: 'No books found',
  books_truncated: "The search stopped at the server's scan cap. Narrow it to reach the rest.",
  books_readonly: 'Not editable: you are not a member of this library. Actions are offered only in your own.',
  books_count: (shown: number, total: number) =>
    shown >= total ? `${total} books` : `${shown} of ${total} books`,
  books_prev: 'Previous',
  books_next: 'Next',

  works_sub: 'One row per book, across the whole system. A library is not a property of a book — it is a list of them.',
  works_mixed: 'mixed',
  works_where: 'Where it stands',
  works_gone: 'No library holds this book right now',
  works_last_added: 'Last added',
  works_open_spread: (n: number) =>
    n === 1 ? 'Show the library holding this book'
            : `Show the ${n} libraries holding this book`,
  works_copies_here: (n: number) => (n === 1 ? '1 copy' : `${n} copies`),
  works_on_shelves: (n: number) => (n === 1 ? 'on 1 shelf' : `on ${n} shelves`),
  works_display_title:
    "The title above is one library's spelling — the strongest claim, oldest first on a tie. Each library's own spelling is shown below.",
  works_edit_rekeys:
    "Editing the title or author changes the book's identity, so this copy may move to a different row in the list.",
  works_filter_keeps_spread:
    'A filter selects which books are listed; the library count on a row stays the true one.',

  img_title: 'Every image in the system',
  img_sub: 'The image is the entity. Filing it at a shelf is a placeholder — the physical map (pillar 6) replaces it.',
  img_panel: 'Image details',
  img_empty: 'No images',
  img_taken: 'Taken',
  img_undated: 'No date',
  img_filed_at: 'Filed at',
  img_depth_n: (n: number) => `depth ${n}`,
  img_order_n: (n: number) => `position ${n}`,
  img_runs: 'Runs',
  img_last_read: 'Last read',
  img_missing: 'bytes gone',
  img_missing_long: 'The file is not on disk. This photograph is lost as far as the household is concerned.',
  img_no_preview: 'A preview is shown only for libraries you belong to. Metadata crosses tenants; photographs do not.',
  img_alt: 'The shelf photograph',
  img_filename: 'File name',
  img_key: 'Content address',
  img_read_nothing: 'A run consumed this image and found nothing — usually worth a look.',
  img_readonly: 'Read-only: the staff service does not write. Deleting or re-filing is done in the household app.',
  img_tiers: (auto: number, review: number, unmatched: number) =>
    `${auto} auto · ${review} review · ${unmatched} unmatched`,
  img_count: (shown: number, total: number) =>
    shown >= total ? `${total} images` : `${shown} of ${total} images`,
  img_blind:
    'This service cannot see the blob tree, so every image reports as missing and there are no size figures. That means "we did not look", not "they are gone".',

  acct_title: 'Accounts',
  acct_sub: 'Every customer in the system: who administers it, how many users, how many libraries it keeps, how many books, and how much room the images take.',
  acct_panel: 'Account details',
  acct_unnamed: 'Unnamed account',
  acct_empty: 'No accounts',
  acct_unknown: 'The id in this link matches no account and no library in the system.',
  acct_people_unknown: 'The people list is unavailable right now, so who administers this account cannot be said.',
  acct_libs_unknown: 'The library list is unavailable right now.',
  acct_no_admin: 'no admin',
  acct_users: 'Users',
  acct_books: 'Books',
  acct_images: 'Images',
  acct_joined: 'Joined',
  acct_lib_sub: 'The collections this account keeps. Renaming and exporting act on a library, so they live here rather than on the account row.',
  acct_lib_none: 'This account keeps no library',
  acct_books_of: (name: string) => `Books in ${name}`,
  acct_images_of: (name: string) => `Images in ${name}`,
  acct_recent: 'Most recently added, across every library of this account',
  acct_no_member_management:
    'Invite, remove and re-role exist in neither service — they wait on the login (P4.1) and the invite flow (P4.3).',
  acct_unaffiliated: 'Unaffiliated users',
  acct_unaffiliated_why:
    'People who belong to no account. Until there is a login nobody can reach them, and this is the only place they appear.',

  bp_title: 'Book details',
  bp_library: 'Library',
  bp_status: 'Status',
  bp_copies: 'Copies',
  bp_unshelved: 'Not on a shelf',
  bp_approve: 'Approve',
  bp_edit: 'Edit title and author',
  bp_delete: 'Delete from library',
  bp_delete_confirm:
    'Delete this book from the library? It removes every copy and records a rejection, so the next read of the shelf will not put it back.',
  bp_delete_yes: 'Delete',
  bp_title_label: 'Title',
  bp_author_label: 'Author',

  acc_title: 'Access',
  acc_memberships: 'Memberships',
  users_unnamed: 'Unnamed',
  acc_system_admin: 'System admin',
  acc_account_admin: 'Account admin',
  acc_two_admins:
    'These are two different jobs. The SYSTEM admin — this tool — sees every customer and is a member of none. An ACCOUNT admin is a role inside one account, and it covers every library that account keeps; they are who invites family members. The server enforces neither yet.',
  acc_gap_title: 'What is not here yet',
  acc_gap_intro:
    'User management does not exist on the server, so it does not appear here. These are the gaps, and what would close each:',
  acc_gap_invite:
    'Invite a user to an account — needs a login (P4.1) and an invite flow (P4.3).',
  acc_gap_roles:
    'Change a role or remove a member — no endpoint, and roles are not enforced yet (P3.2).',
  acc_gap_list:
    'A user cannot sign in yet — there is no login, so every request arrives as the same dev user (P4.1).',
  acc_gap_counts: (accounts: number, users: number, libraries: number) =>
    `Right now: ${accounts} accounts, ${users} users, ${libraries} libraries.`,
  acc_gap_delete:
    'Delete a library — a cascade across six aggregates, waiting on policy (P3.2) and a blob purge (P3.5).',
  acc_no_auth:
    'There is no login here. The tool is open to anyone on the local network, exactly like the rest of the system until pillar 4.',
}

/**
 * The provider and the hook come from `@booksnap/ui` — the mechanism was
 * identical in both clients down to the comments, so it is written once now.
 * What stays here is the TABLE: an administrator's vocabulary (accounts,
 * roles, totals), which is exactly what this file's own note said should not
 * be shared. It was right about that and wrong about the provider under it.
 *
 * ⚠ Its own storage key, distinct from the product's. The day both are served
 * from one origin, a shared key would mean switching language in the console
 * silently switched the household's app too.
 */
export const { I18nProvider, useI18n } = createI18n<Strings>(
  { he: HE, en: EN },
  { storageKey: 'booksnap.admin.lang' },
)
