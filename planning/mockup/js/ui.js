// Small DOM/format helpers shared by every view in the mock.
import { nm, t, lang } from './i18n.js';
import { shelfById, bcById, plById } from './data.js';

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function h(html) {
  const tpl = document.createElement('template');
  tpl.innerHTML = html.trim();
  return tpl.content.firstElementChild;
}
export const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/** A shelf's address inside its case: "Column 2 · Shelf 3". The column part is
    omitted for single-bay cases, exactly as depth is omitted for flat shelves —
    a user whose cases have one column never meets the concept. */
export function shelfLabel(sh) {
  if (!sh) return '';
  if (sh.virtual) return nm(sh.name);
  const bc = bcById[sh.bcId];
  const parts = [];
  if (bc && bc.columns > 1) parts.push(t('column_n', sh.col));
  parts.push(t('shelf_n', sh.level));
  return parts.join(' · ');
}

/** "Home · Living room case · Column 2 · Shelf 3 · back row" — "where is it". */
export function locationLabel(copy, { short = false } = {}) {
  if (!copy || !copy.shelfId) return t('no_shelf');
  const sh = shelfById[copy.shelfId];
  if (!sh) return t('no_shelf');
  if (sh.virtual) return nm(sh.name);          // wishlist etc. — no physical place
  const bc = bcById[sh.bcId];
  const pl = plById[bc.plId];
  const parts = short ? [shelfLabel(sh)] : [nm(pl.name), nm(bc.name), shelfLabel(sh)];
  if (sh.depthCount > 1) parts.push(depthLabel(copy.depth, sh.depthCount));
  return parts.join(' · ');
}
export function depthLabel(depth, depthCount) {
  if (depthCount <= 1) return '';
  const which = depth === 1 ? t('depth_front') : depth === depthCount ? t('depth_back') : '';
  return t('depth_n', depth) + (which ? ` (${which})` : '');
}

export function statusBadge(status) {
  const key = { auto: 'st_auto', approved: 'st_approved', manual: 'st_manual' }[status];
  return `<span class="badge b-${status}">${esc(t(key))}</span>`;
}

export function stars(n, interactive = false) {
  let out = '';
  for (let i = 1; i <= 5; i++) out += `<span class="${i <= n ? '' : 'off'}" data-star="${i}">★</span>`;
  return `<span class="stars"${interactive ? ' data-rate="1"' : ''}>${out}</span>`;
}

export function fmtDate(s) {
  if (!s) return '—';
  const [y, m, d] = s.slice(0, 10).split('-');
  return lang === 'he' ? `${+d}.${+m}.${y}` : `${y}-${m}-${d}`;
}

/** Same folding the matcher's normalize() does, in miniature — enough for the
    mock's search to behave like the real one (nikud, finals, prefixes, geresh). */
const FINALS = { 'ך': 'כ', 'ם': 'מ', 'ן': 'נ', 'ף': 'פ', 'ץ': 'צ' };
export function normalize(s) {
  return String(s || '')
    .replace(/[֑-ׇ]/g, '')
    .replace(/['"׳״]/g, '')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split('')
    .map(c => FINALS[c] || c)
    .join('')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}
export function searchHit(book, q) {
  if (!q) return true;
  const n = normalize(q);
  const hay = normalize(book.title + ' ' + book.author);
  // prefix-tolerant: a query word may be missing its ה/ו/ב/ל/מ/ש/כ prefix
  return n.split(' ').every(w => hay.includes(w) || hay.includes(w.replace(/^[הובלמשכ]/, '')));
}

export function toast(msg) {
  let el = $('#toast');
  if (!el) { el = h(`<div id="toast" class="mocknote" style="inset-inline-start:50%;transform:translateX(-50%);bottom:24px"></div>`); document.body.append(el); }
  el.textContent = msg;
  el.style.display = 'block';
  clearTimeout(el._tm);
  el._tm = setTimeout(() => { el.style.display = 'none'; }, 2200);
}
