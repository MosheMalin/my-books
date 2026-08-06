/* ---------------- author autocomplete ---------------------------------------
   Replaces <datalist>: its popup is positioned by the browser alone, with no
   CSS hook, and on these RIGHT-TO-LEFT inputs it rendered far off to the
   left. This one is a plain absolutely-positioned list anchored to the input.
   It lives on <body> so no ancestor's `overflow: hidden` (the results panel
   has one) can clip it; stale popups are cleared on every results render. */
import { escapeHtml } from './dom.js';
import { S } from './state.js';

export function clearAuthorPopups() {
  document.querySelectorAll('.ac-pop').forEach(p => p.remove());
}

export function attachAuthorComplete(inp) {
  if (!inp) return;
  const pop = document.createElement('div');
  pop.className = 'ac-pop';
  document.body.appendChild(pop);
  let items = [], sel = -1;

  const place = () => {
    const r = inp.getBoundingClientRect();
    pop.style.left = (r.left + window.scrollX) + 'px';
    pop.style.top = (r.bottom + window.scrollY + 2) + 'px';
    pop.style.width = r.width + 'px';
  };
  const hide = () => { pop.style.display = 'none'; sel = -1; };
  const paint = () => {
    pop.innerHTML = items.map((a, i) =>
      `<div class="${i === sel ? 'sel' : ''}" data-i="${i}">${escapeHtml(a)}</div>`).join('');
  };
  const open = () => {
    const q = inp.value.trim();
    items = (q ? S.libAuthors.filter(a => a.includes(q)) : S.libAuthors).slice(0, 8);
    if (!items.length) return hide();
    sel = -1;
    paint();
    place();
    pop.style.display = 'block';
  };
  const pick = i => {
    if (i < 0 || i >= items.length) return;
    inp.value = items[i];
    hide();
    inp.focus();
  };

  inp.addEventListener('input', open);
  inp.addEventListener('focus', open);
  inp.addEventListener('blur', () => setTimeout(hide, 120));
  inp.addEventListener('keydown', ev => {
    if (pop.style.display === 'none') return;
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      sel = (sel + 1) % items.length;
      paint();
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      sel = (sel <= 0 ? items.length : sel) - 1;
      paint();
    } else if (ev.key === 'Enter' && sel >= 0) {
      ev.preventDefault();
      pick(sel);
    } else if (ev.key === 'Escape') {
      hide();
    }
  });
  // mousedown, not click: blur fires first on click and would close the list
  pop.addEventListener('mousedown', ev => {
    const d = ev.target.closest('[data-i]');
    if (d) { ev.preventDefault(); pick(+d.dataset.i); }
  });
  window.addEventListener('scroll', () => {
    if (pop.style.display !== 'none') place();
  }, true);
}
