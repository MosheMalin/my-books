/**
 * The URL prefix the product is served under (`/booksnap/` on
 * malinvishne.com/booksnap), from the SAME variable the server reads for its
 * `root_path` (`app/main.py:base_path`). Normalised here to Vite's spelling —
 * leading and trailing slash — so `/booksnap`, `/booksnap/` and `booksnap`
 * all build the same page; empty or `/` is the domain root. The server
 * refuses at start-up to serve a build whose baked asset URLs disagree with
 * its own prefix (`check_web_base`), so the two cannot drift silently.
 *
 * Its own module, not a line in `vite.config.ts`: the config resolves the
 * sibling `app/ui` from `import.meta.url`, which a jsdom test cannot import —
 * and this rule is the one thing in there worth a test.
 *
 * ⚠ On Windows, `BOOKSNAP_BASE_PATH=/booksnap npm run build` from Git Bash
 * arrives as `/C:/Program Files/Git/booksnap` — MSYS rewrites a leading `/`
 * into a Windows path. Prefix the command with `MSYS_NO_PATHCONV=1`, or
 * build from PowerShell. The image build runs on Linux and has no such step.
 */
export function basePathFromEnv(raw: string | undefined): string {
  const trimmed = (raw ?? '').trim().replace(/^\/+|\/+$/g, '')
  return trimmed ? `/${trimmed}/` : '/'
}
