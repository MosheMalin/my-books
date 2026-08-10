/** The one repeated piece that is this console's own.
 *
 *  `Loading` / `ErrorBox` / `Empty` / `StatusBadge` moved to `@booksnap/ui`:
 *  the three async states and §5.1's ladder are things BOTH clients render,
 *  and the two apps had already drifted on the ladder's wording (the console
 *  said `auto` in English, which reads like a raw enum value rather than a
 *  state). A stat card, by contrast, exists only on a dashboard.
 */
export function StatCard({ label, value, warn }: {
  label: string
  value: string
  warn?: boolean
}) {
  return (
    <div className={`card stat${warn ? ' warn' : ''}`}>
      <div className="n">{value}</div>
      <div className="k">{label}</div>
    </div>
  )
}
