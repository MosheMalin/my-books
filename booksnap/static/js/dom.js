/* Small DOM helpers shared by every view module. */

export const $ = s => document.querySelector(s);

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// image names and spine ids go inside attribute selectors; CSS.escape is the
// only correct quoting (a bare "." in "IMG_8139.jpeg" would read as a class)
export const cssEsc = s => (window.CSS && CSS.escape) ? CSS.escape(s) : s;

/** Re-render without the page jumping: rows change height as their controls
 *  change, so the element you were looking at slides away under the cursor.
 *  Pins `selector`'s element to the same viewport offset across `fn`. */
export async function keepInPlace(selector, fn) {
  const before = document.querySelector(selector)?.getBoundingClientRect().top;
  await fn();
  const el = document.querySelector(selector);
  if (el && before != null) {
    const delta = el.getBoundingClientRect().top - before;
    if (delta) window.scrollBy(0, delta);
  }
}

export function showViewer(src) { $('#viewerImg').src = src; $('#viewer').showModal(); }

// Row crops are rendered via an inline onclick="showViewer(...)" attribute
// inside a template string. Inline handlers resolve against the global scope,
// which ES modules do not share — so this one function must be published
// explicitly. (The other inline handlers in row markup are self-contained
// expressions and need nothing.)
window.showViewer = showViewer;
