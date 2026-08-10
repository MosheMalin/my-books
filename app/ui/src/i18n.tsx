/**
 * The language/direction machinery both clients were writing twice.
 *
 * What is shared is the MECHANISM — the provider, the `he`/`en` toggle, the
 * `dir`/`lang` attributes on `<html>`, and the persistence — plus the handful
 * of strings the shared CONTROLS themselves render. What is not shared is
 * either app's vocabulary: the product speaks about books and shelves, the
 * console about accounts and totals, and a merged table would grow two
 * intents (`app/admin/src/lib/i18n.tsx` argued exactly this when it declined
 * to import the product's, and it was right about the table and wrong about
 * the provider under it).
 *
 * So there are two string surfaces on one context:
 *
 *   `t`  — the app's own table, typed by the app, unknown here.
 *   `ui` — this package's strings, for the controls this package draws.
 *
 * Two surfaces rather than one merged object on purpose: a merge makes a key
 * collision silent, and the loser would be whichever side the spread happened
 * to put first.
 *
 * ⚠ Hebrew is the default and English is not here for English speakers. It is
 * the only honest way to see that the layout mirrors — a correctness property
 * of every screen in this repo (UI_PLAN §7.1/§7.2), not internationalisation
 * polish. Both client rings assert against it; deleting it would make the bidi
 * rules untestable.
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

import { UI_STRINGS, type UiStrings } from './strings'

export type Lang = 'he' | 'en'
export type Dir = 'rtl' | 'ltr'

/** What every consumer of the context gets, whatever its own table is. */
export interface I18nBase {
  lang: Lang
  dir: Dir
  /** Strings for the controls THIS package draws. */
  ui: UiStrings
  setLang: (lang: Lang) => void
  toggleLang: () => void
}

interface Ctx extends I18nBase {
  /** The app's own table. Typed as `unknown` here and narrowed by the hook
   *  `createI18n` returns — this module cannot know an app's vocabulary. */
  t: unknown
}

/**
 * ⚠ ONE context, at module level, deliberately.
 *
 * A shared control has to reach the same provider the app mounted, and a
 * context created per `createI18n` call would leave `useUi()` reading a
 * different one — the classic two-copies-of-React bug in a smaller costume,
 * and just as invisible (the control renders, in the wrong language, with no
 * error). One app calls `createI18n` once, so the sharing costs nothing.
 */
const I18nCtx = createContext<Ctx | null>(null)

function readStored(key: string): Lang | null {
  try {
    const saved = globalThis.localStorage?.getItem(key)
    if (saved === 'he' || saved === 'en') return saved
  } catch {
    /* private mode; the default is fine */
  }
  return null
}

export interface I18nOptions {
  /**
   * Where the choice is remembered.
   *
   * ⚠ Distinct per app, and it matters the day both are served from one
   * origin: the product and the console are separate tools a person may well
   * want in different languages, and one key would make switching in either
   * silently switch the other.
   */
  storageKey: string
}

/**
 * Build an app's `<I18nProvider>` and `useI18n()` over its own string table.
 *
 * The returned hook is typed to that table, so `t.whatever` is checked at
 * compile time exactly as it was when each app owned the whole file.
 */
export function createI18n<T>(
  tables: Record<Lang, T>,
  { storageKey }: I18nOptions,
): {
  I18nProvider: (props: { children: ReactNode }) => ReactNode
  useI18n: () => I18nBase & { t: T }
} {
  function I18nProvider({ children }: { children: ReactNode }): ReactNode {
    const [lang, setLangState] = useState<Lang>(() => readStored(storageKey) ?? 'he')
    const dir: Dir = lang === 'he' ? 'rtl' : 'ltr'

    // The whole layout mirrors off this one attribute, because every rule
    // uses logical properties (UI_PLAN §7.1) — and the explicit `[dir=…]`
    // selectors that make mixed-script alignment work read it too (§7.2).
    useEffect(() => {
      document.documentElement.lang = lang
      document.documentElement.dir = dir
    }, [lang, dir])

    const setLang = useCallback((next: Lang) => {
      setLangState(next)
      try {
        globalThis.localStorage?.setItem(storageKey, next)
      } catch {
        /* nothing to do; the choice just won't persist */
      }
    }, [])

    const value = useMemo<Ctx>(
      () => ({
        lang,
        dir,
        t: tables[lang],
        ui: UI_STRINGS[lang],
        setLang,
        toggleLang: () => setLang(lang === 'he' ? 'en' : 'he'),
      }),
      [lang, dir, setLang],
    )

    return <I18nCtx.Provider value={value}>{children}</I18nCtx.Provider>
  }

  function useI18n(): I18nBase & { t: T } {
    const ctx = useContext(I18nCtx)
    if (!ctx) throw new Error('useI18n outside <I18nProvider>')
    return ctx as I18nBase & { t: T }
  }

  return { I18nProvider, useI18n }
}

/**
 * What a SHARED control reads. Same context, without the app's table — a
 * component in this package has no business knowing an app's vocabulary, and
 * a type that admitted it would let one leak in by accident.
 */
export function useUi(): I18nBase {
  const ctx = useContext(I18nCtx)
  if (!ctx) throw new Error('a @booksnap/ui control rendered outside <I18nProvider>')
  return ctx
}
