import { useEffect, useState } from 'react'

/**
 * A boolean that survives a reload.
 *
 * For panel state — is the details fold open? — where losing the answer on
 * every refresh is a papercut and storing it in the document would be wrong:
 * it describes this person's screen, not the plan.
 */
export function useSticky(key: string, initial: boolean): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const raw = window.localStorage.getItem(key)
      return raw === null ? initial : raw === '1'
    } catch {
      return initial
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(key, value ? '1' : '0')
    } catch {
      /* a full or blocked localStorage must not break the panel */
    }
  }, [key, value])

  return [value, setValue]
}
