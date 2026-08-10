import base from '@testing-library/user-event'
import type { UserEvent } from '@testing-library/user-event'

/**
 * `userEvent`, without the artificial pause between events.
 *
 * The direct API (`userEvent.click(el)`) builds a session per call — which is
 * free, 0.1ms — and gives it `delay: 0`, which is not: every sub-event of a
 * click, and every keystroke of a `type`, then awaits a macrotask. Measured on
 * this suite: **66ms per click, against 15ms with the delay off**, and a
 * twelve-character `type` went from 235ms to 31ms. Across ~116 interactions
 * that was most of the client ring's runtime, spent waiting on timers rather
 * than on the code under test.
 *
 * ⚠ It is `delay: null`, not a smaller number. `0` still schedules and awaits
 * a timer; `null` skips the wait entirely. Everything else is unchanged —
 * still a fresh session per call, exactly like the direct API, so keyboard and
 * pointer state cannot leak from one interaction into the next.
 *
 * The delay exists upstream to let debounced UI settle between keystrokes.
 * Nothing here depends on it: the one debounce this suite asserts on (the
 * author autocomplete's 250ms) is waited through explicitly, precisely because
 * a test that merely polled would go green against the bug it exists for.
 */
const OPTIONS = { delay: null } as const

export const userEvent: UserEvent = new Proxy({} as UserEvent, {
  get(_target, prop: string) {
    const method = (base.setup(OPTIONS) as unknown as Record<string, unknown>)[prop]
    return typeof method === 'function'
      ? (...args: unknown[]) => (method as (...a: unknown[]) => unknown)(...args)
      : method
  },
})

export default userEvent
