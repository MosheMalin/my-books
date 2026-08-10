/**
 * `@booksnap/ui` — what both clients share.
 *
 * The rule for what belongs here, so the package does not become a dumping
 * ground: **a mechanism both apps need, or a rule both apps must not
 * disagree about.** The sort control is the first kind; §5.1's status ladder
 * and §7.2's mixed-script alignment are the second — two implementations of
 * either is two chances for one to be wrong, silently, on a screen nobody was
 * looking at.
 *
 * What deliberately does NOT belong here: either app's vocabulary, either
 * app's route table, either app's palette, and anything that talks to a
 * server. The console reads a different service from the product (see
 * `planning/ADMIN_CONSOLE_PLAN.md`), and a shared API client would be the one
 * dependency that makes that split meaningless.
 */
export { createI18n, useUi, type Dir, type I18nBase, type Lang } from './i18n'
export { UI_STRINGS, type UiStrings } from './strings'
export { formatDate, formatDateTime, formatNumber, libraryName } from './format'
export { backOr, navigateHash, useHash } from './hash'
export { useAsync, type AsyncState } from './useAsync'
export { SortControl, type SortControlProps, type SortOption } from './SortControl'
export { StatusBadge, vouchedFor, type BookStatus } from './StatusBadge'
export { Empty, ErrorBox, Loading } from './states'
