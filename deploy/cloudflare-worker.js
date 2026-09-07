/**
 * malinvishne.com/booksnap → the VPS, through a Cloudflare Worker.
 *
 * The apex domain already hosts the family's site, so the product cannot
 * own the domain's DNS record — it lives on a PATH. A Worker on the route
 * `malinvishne.com/booksnap*` forwards every request under that path to the
 * VPS's own hostname (`booksnap.malinvishne.com`, a plain A record that
 * Caddy holds a certificate for) and hands the answer back. Nothing else on
 * the domain sees the Worker, and the origin's Caddy still terminates TLS
 * exactly as at a domain root — the prefix travels UNTOUCHED all the way to
 * uvicorn, where Starlette strips it (`create_app(root_path=…)`).
 *
 * Chosen over an Origin Rule because a Worker's behaviour is a page of
 * code that can be read, and over pointing the apex at the VPS because
 * that would take the family's site down with the first `docker compose
 * down`.
 *
 * Bound as a Worker "variable": BOOKSNAP_ORIGIN — the origin hostname.
 */
const PREFIX = '/booksnap'

export default {
  async fetch(request, env) {
    const url = new URL(request.url)
    const publicHost = url.host

    // `/booksnap` with no slash: the page is at `/booksnap/`, and the origin
    // would answer the same redirect naming ITS host — so it is answered
    // here, naming ours.
    if (url.pathname === PREFIX) {
      url.pathname = `${PREFIX}/`
      return Response.redirect(url.toString(), 301)
    }

    url.host = env.BOOKSNAP_ORIGIN
    const upstream = new Request(url.toString(), request)
    // The visitor's address, offered to the origin for its sign-in rate
    // door. ⚠ NOT believed there yet: Caddy hands uvicorn the peer's
    // address, and the peer is this Worker — so every visitor shares one
    // per-source window (15 links/hour) until Caddy is taught to trust
    // this header from Cloudflare's addresses only. Believing it from
    // anyone is the "whatever the caller types" hole the Dockerfile
    // records; the measurement of what actually arrives comes first.
    const visitor = request.headers.get('CF-Connecting-IP')
    if (visitor) upstream.headers.set('X-Booksnap-Visitor', visitor)

    const answer = await fetch(upstream)
    const out = new Response(answer.body, answer)

    // An absolute redirect naming the origin host would send the browser
    // AROUND the Worker; rewrite it to the host the visitor came in on.
    const location = out.headers.get('Location')
    if (location) {
      try {
        const target = new URL(location, url)
        if (target.host === env.BOOKSNAP_ORIGIN) {
          target.host = publicHost
          out.headers.set('Location', target.toString())
        }
      } catch {
        // not a URL we can parse: leave it alone
      }
    }
    // Caddy sends a year-long HSTS with includeSubDomains — the ORIGIN
    // host's policy. Forwarded, it would pin the whole apex domain from
    // one path; that decision belongs to the zone, not to this app.
    out.headers.delete('Strict-Transport-Security')
    return out
  },
}
