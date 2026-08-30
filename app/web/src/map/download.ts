/**
 * Hand a file to the browser (P6.7e).
 *
 * ⚠ **An object URL, revoked.** A `data:` URL would be simpler and is capped
 * at a couple of megabytes in some browsers; the owner's drawing is 13
 * bookcases today and there is no ceiling on it. Not revoking is a leak that
 * lasts as long as the tab, which for this app is a whole cataloguing session.
 *
 * ⚠ The anchor is appended to the document before it is clicked and removed
 * after. A detached `<a>` is ignored by Firefox, which is the kind of thing
 * that works everywhere it is tested and fails on the one machine that matters.
 */
export function downloadText(filename: string, text: string,
                             type = 'application/json'): void {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  // ⚠ Deferred: revoking in the same tick can cancel the download in Safari,
  // which starts fetching the URL after the click handler returns.
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
