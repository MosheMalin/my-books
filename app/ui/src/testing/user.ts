import base from '@testing-library/user-event'
import type { UserEvent } from '@testing-library/user-event'

/**
 * `userEvent`, without the artificial pause between events.
 *
 * The direct API (`userEvent.click(el)`) builds a session per call — which is
 * free, 0.1ms — and gives it `delay: 0`, which is not: every sub-event of a
 * click, and every keystroke of a `type`, then awaits a macrotask. Measured on
 * the product's suite: **66ms per click, against 15ms with the delay off**, and
 * a twelve-character `type` went from 235ms to 31ms. Across ~116 interactions
 * that was most of the client ring's runtime, spent waiting on timers rather
 * than on the code under test.
 *
 * ⚠ It is `delay: null`, not a smaller number. `0` still schedules and awaits
 * a timer; `null` skips the wait entirely. Everything else is unchanged —
 * still a fresh session per call, exactly like the direct API, so keyboard and
 * pointer state cannot leak from one interaction into the next.
 *
 * The delay exists upstream to let debounced UI settle between keystrokes.
 * Nothing here depends on it: a debounce a test actually asserts on must be
 * waited through EXPLICITLY, because a test that merely polled with `waitFor`
 * passes on its first tick and would go green against the very bug it exists
 * for (the product's author autocomplete found that the hard way).
 */
const OPTIONS = { delay: null } as const

/**
 * A session's own `setup` takes a required argument; the default export's does
 * not. This proxy answers as the default export, so the type has to say so —
 * otherwise `userEvent.setup()`, which a whole ring may be written in, is a
 * compile error against a call that works perfectly at runtime.
 */
type FastUserEvent = Omit<UserEvent, 'setup'> & { setup: typeof base.setup }

export const userEvent: FastUserEvent = new Proxy({} as FastUserEvent, {
  get(_target, prop: string) {
    // ⚠ `setup` is intercepted rather than forwarded. Forwarding reaches the
    // SESSION's `setup`, which takes a required argument and returns a nested
    // session — so `userEvent.setup()`, the form a whole ring may be written
    // in, would be a type error and, at runtime, a session that never got
    // `delay: null`. This makes the proxy behave like the real default export,
    // only faster.
    if (prop === 'setup') {
      return (options?: Parameters<typeof base.setup>[0]) =>
        base.setup({ ...OPTIONS, ...options })
    }
    const method = (base.setup(OPTIONS) as unknown as Record<string, unknown>)[prop]
    return typeof method === 'function'
      ? (...args: unknown[]) => (method as (...a: unknown[]) => unknown)(...args)
      : method
  },
})

export default userEvent
