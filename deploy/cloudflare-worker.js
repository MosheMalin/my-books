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
/** The one host this Worker answers for. Cloudflare routes it by hostname
 *  already; pinning it means a redirect is never rewritten onto a host a
 *  caller chose (security review). */
const PUBLIC_HOST = 'malinvishne.com'

export default {
  async fetch(request, env) {
    const url = new URL(request.url)
    const publicHost = PUBLIC_HOST

    // `/booksnap` with no slash: the page is at `/booksnap/`, and the origin
    // would answer the same redirect naming ITS host — so it is answered
    // here, naming ours.
    if (url.pathname === PREFIX) {
      url.pathname = `${PREFIX}/`
      return Response.redirect(url.toString(), 301)
    }

    url.host = env.BOOKSNAP_ORIGIN
    const upstream = new Request(url.toString(), request)
    // The visitor's address, for the origin's sign-in rate door: Caddy
    // believes it from Cloudflare's ranges only (deploy/Caddyfile) and
    // the api keys the door on it (BOOKSNAP_VISITOR_HEADER).
    // Stamped, never maybe-stamped: `new Request(url, request)` copied the
    // caller's headers, so a caller-supplied X-Booksnap-Visitor must be
    // deleted BEFORE the edge's value is set — unconditionally, or the
    // origin trusts whatever was typed on the one request the edge header
    // is missing (security review).
    upstream.headers.delete('X-Booksnap-Visitor')
    const visitor = request.headers.get('CF-Connecting-IP')
    if (visitor) upstream.headers.set('X-Booksnap-Visitor', visitor)

    const answer = await fetch(upstream)
    const out = new Response(answer.body, answer)

    // An absolute redirect naming the origin host would send the browser
    // AROUND the Worker; rewrite it to the host the visitor came in on.
    // Any OTHER host passes through on purpose: a provider sign-in is a
    // legitimate redirect to accounts.google.com, and the origin builds no
    // Location from caller input (`auth.py:_root` is configuration).
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
