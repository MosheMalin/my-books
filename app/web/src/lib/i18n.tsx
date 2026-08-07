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
