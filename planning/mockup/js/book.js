// The ONE book surface. Rendered identically into a side drawer (default) and
// into a full page (#/book/<id>, deep-linkable and returnable). Editing here
// mutates the single book record, so every list showing it re-renders.
import { t, nm } from './i18n.js';
import { books, byId, shelves, shelfById, bcById, plById, reads } from './data.js';
import { h, esc, locationLabel, shelfLabel, depthLabel, statusBadge, stars, fmtDate, toast, $ } from './ui.js';

let editing = false;

export function bookChanged() { window.dispatchEvent(new CustomEvent('book:changed')); }

function shelfOptions(sel) {
  return shelves.filter(s => !s.virtual).map(s => {
    const bc = bcById[s.bcId], pl = plById[bc.plId];
    return `<option value="${s.id}"${s.id === sel ? ' selected' : ''}>${esc(nm(pl.name))} · ${esc(nm(bc.name))} · ${esc(shelfLabel(s))}</option>`;
  }).join('');
}

export function detailHTML(b, { full = false } = {}) {
  const c0 = b.copies[0];
  const multi = b.copies.length > 1;

  const head = editing ? `
    <div style="flex:1">
      <label class="fld"><span>${esc(t('f_title'))}</span>
        <input type="text" id="edTitle" class="rtl-safe" value="${esc(b.title)}"></label>
      <label class="fld" style="margin-bottom:0"><span>${esc(t('f_author'))}</span>
        <input type="text" id="edAuthor" class="rtl-safe" value="${esc(b.author)}"></label>
      <div style="display:flex;gap:8px;margin-top:10px">
        <button class="btn primary sm" data-act="saveEdit">${esc(t('save'))}</button>
        <button class="btn sm" data-act="cancelEdit">${esc(t('cancel'))}</button>
      </div>
    </div>` : `
    <div style="flex:1;min-width:0">
      <h2 class="rtl-safe">${esc(b.title)}</h2>
      <div class="a rtl-safe">${esc(b.author)}</div>
      <div class="chiprow" style="margin-top:9px">
        ${statusBadge(b.status)}
        ${c0.lending ? `<span class="badge b-lent">${esc(t('lent_to', c0.lending.lentTo))}</span>` : ''}
        ${b.unseenReads ? `<span class="badge b-warn">${esc(t('unseen_warn', b.unseenReads))}</span>` : ''}
        <button class="btn sm ghost" data-act="edit">✎ ${esc(t('edit'))}</button>
      </div>
    </div>`;

  const copiesSect = `
    <div class="sect">
      <h4>${esc(multi ? t('copies') + ` (${b.copies.length})` : t('where'))}</h4>
      ${b.copies.map((c, i) => `
        <div class="copybox">
          ${multi ? `<div style="font-weight:600;font-size:13px;margin-bottom:6px">${esc(t('copy_n', i + 1))}${c.label ? ' · ' + esc(c.label) : ''}</div>` : ''}
          <div class="kv"><span class="k">${esc(t('shelf'))}</span>
            <span class="rtl-safe" style="flex:1">${esc(locationLabel(c))}</span></div>
          <div class="kv"><span class="k">${esc(t('lending'))}</span><span style="flex:1">
            ${c.lending
              ? `${esc(t('lent_to', c.lending.lentTo))} · ${esc(t('due', fmtDate(c.lending.dueAt)))}
                 <button class="btn sm ghost" data-act="return" data-copy="${c.id}">${esc(t('mark_returned'))}</button>`
              : `<span class="muted">${esc(t('not_lent'))}</span>
                 <button class="btn sm ghost" data-act="lend" data-copy="${c.id}">${esc(t('lend_it'))}</button>`}
          </span></div>
          <div class="kv"><span class="k">${esc(t('last_seen'))}</span><span>${esc(fmtDate(c.lastSeen))}</span></div>
          <div style="margin-top:8px;display:flex;gap:7px;flex-wrap:wrap">
            <button class="btn sm ghost" data-act="movecopy" data-copy="${c.id}">↔ ${esc(t('shelf'))}</button>
            <button class="btn sm ghost" data-act="removeshelf" data-copy="${c.id}">${esc(t('remove_shelf'))}</button>
          </div>
        </div>`).join('')}
      <button class="btn sm" data-act="addcopy">＋ ${esc(t('add_copy'))}</button>
    </div>`;

  const mine = `
    <div class="sect">
      <h4>${esc(t('my_fields'))}</h4>
      <div class="kv"><span class="k">${esc(t('rating'))}</span>${stars(b.work.rating, true)}</div>
      <div class="kv"><span class="k">${esc(t('read_status'))}</span>
        <select id="rs" style="width:auto">
          ${['unread', 'reading', 'read'].map(v =>
            `<option value="${v}"${b.work.readStatus === v ? ' selected' : ''}>${esc(t('rs_' + v))}</option>`).join('')}
        </select></div>
      <label class="fld" style="margin-top:10px"><span>${esc(t('notes'))}</span>
        <textarea id="notes" rows="2" class="rtl-safe" placeholder="…">${esc(b.work.notes)}</textarea></label>
    </div>`;

  const shelfReads = reads.filter(r => r.shelfId === c0.shelfId).slice(0, 3);
  const history = `
    <div class="sect">
      <h4>${esc(t('history'))}</h4>
      ${shelfReads.length ? shelfReads.map(r => `
        <div class="kv"><span class="k">${esc(fmtDate(r.at))}</span>
          <span class="rtl-safe">${esc(shelfLabel(shelfById[r.shelfId]))}${shelfById[r.shelfId].depthCount > 1 ? ' · ' + esc(depthLabel(r.depth, shelfById[r.shelfId].depthCount)) : ''}</span></div>`).join('')
        : `<div class="muted tiny">${esc(t('never_read'))}</div>`}
      <button class="linkish" data-act="why" style="margin-top:6px">${esc(t('why'))}</button>
    </div>`;

  return `
    <div class="dbody">
      <div class="bhero"><img src="${esc(b.spine)}" alt="">${head}</div>
      <div class="savednote" id="savednote">${esc(t('saved_note'))}</div>
      ${copiesSect}${mine}${history}
      <div class="sect" style="display:flex;gap:8px;flex-wrap:wrap">
        ${full ? '' : `<button class="btn sm ghost" data-act="full">⤢ ${esc(t('open_full'))}</button>`}
        <span style="flex:1"></span>
        <button class="btn sm ghost dangertext" data-act="delete">🗑 ${esc(t('delete_book'))}</button>
      </div>
    </div>`;
}

// ---------------- drawer ----------------
export function openDrawer(id) {
  editing = false;
  const b = byId[id];
  if (!b) return;
  const scrim = $('#scrim'), drawer = $('#drawer');
  drawer.dataset.book = id;
  drawer.innerHTML = `
    <div class="dhead">
      <button class="iconbtn" data-act="close">✕</button>
      <span class="ttl">${esc(t('book_detail'))}</span>
      <button class="iconbtn" data-act="full" title="${esc(t('open_full'))}">⤢</button>
    </div>${detailHTML(b)}`;
  scrim.classList.add('on');
  drawer.classList.add('on');
}
export function closeDrawer() {
  $('#scrim').classList.remove('on');
  $('#drawer').classList.remove('on');
  $('#drawer').dataset.book = '';
}
export function isDrawerOpen() { return $('#drawer').classList.contains('on'); }

// ---------------- full page ----------------
export function renderBookPage(id, back) {
  editing = false;
  const b = byId[id];
  if (!b) return `<div class="empty">?</div>`;
  return `<div class="bookpage" data-book="${id}">
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:14px">
      <button class="btn sm ghost" data-act="back" data-back="${esc(back || '#/map')}">← ${esc(t('back_to'))}</button>
      <span class="muted tiny mono">${esc(location.hash || '#/book/' + id)}</span>
    </div>
    <div class="panel"><div style="padding:16px">${detailHTML(b, { full: true })}</div></div>
  </div>`;
}

// ---------------- shared interactions ----------------
export function wireDetail(root, { onNav } = {}) {
  root.addEventListener('click', e => {
    const el = e.target.closest('[data-act], [data-star]');
    if (!el) return;
    const host = root.dataset.book ? root : root.querySelector('[data-book]');
    if (!host) return;                       // not a book surface — ignore the click
    const id = host.dataset.book;
    const b = byId[id];
    if (!b) return;

    if (el.dataset.star && el.closest('[data-rate]')) {
      b.work.rating = +el.dataset.star; rerender(root, b); flashSaved(root); bookChanged(); return;
    }
    const act = el.dataset.act;
    if (act === 'close') return closeDrawer();
    if (act === 'full') { closeDrawer(); onNav && onNav('#/book/' + id); return; }
    if (act === 'back') { onNav && onNav(el.dataset.back); return; }
    if (act === 'edit') { editing = true; rerender(root, b); return; }
    if (act === 'cancelEdit') { editing = false; rerender(root, b); return; }
    if (act === 'saveEdit') {
      b.title = root.querySelector('#edTitle').value.trim() || b.title;
      b.author = root.querySelector('#edAuthor').value.trim() || b.author;
      b.status = 'manual';
      editing = false; rerender(root, b); flashSaved(root); bookChanged(); return;
    }
    if (act === 'addcopy') {
      b.copies.push({ id: b.id + 'c' + (b.copies.length + 1), label: '', shelfId: null, depth: 1, tags: [], lastSeen: null, lending: null, provenance: [] });
      rerender(root, b); bookChanged(); toast(t('add_copy')); return;
    }
    if (act === 'return') {
      b.copies.find(c => c.id === el.dataset.copy).lending = null; rerender(root, b); flashSaved(root); bookChanged(); return;
    }
    if (act === 'lend') {
      const who = prompt(t('lend_it'), 'דנה');
      if (who) { b.copies.find(c => c.id === el.dataset.copy).lending = { lentTo: who, lentAt: '2026-08-07', dueAt: '2026-09-07' }; rerender(root, b); flashSaved(root); bookChanged(); }
      return;
    }
    // Removing from a shelf keeps the book (it may have moved); deleting it
    // from the library is a separate, confirmed action (owner's call 2026-08-07).
    if (act === 'removeshelf') {
      b.copies.find(c => c.id === el.dataset.copy).shelfId = null;
      rerender(root, b); flashSaved(root); bookChanged(); toast(t('removed_shelf')); return;
    }
    if (act === 'delete') {
      if (!confirm(t('delete_confirm', b.title))) return;
      books.splice(books.indexOf(b), 1); delete byId[b.id];
      closeDrawer(); bookChanged(); toast(t('delete_done'));
      if (root.id !== 'drawer') onNav && onNav('#/map');
      return;
    }
    if (act === 'movecopy') {
      const c = b.copies.find(x => x.id === el.dataset.copy);
      const box = h(`<div class="modal on"><div class="box"><h3>${esc(t('bind_shelf'))}</h3>
        <div class="body"><select id="mvShelf">${shelfOptions(c.shelfId)}</select>
        <div id="mvDepth" style="margin-top:10px"></div></div>
        <div class="foot"><button class="btn" data-x>${esc(t('cancel'))}</button>
        <button class="btn primary" data-ok>${esc(t('save'))}</button></div></div></div>`);
      document.body.append(box);
      const drawDepth = () => {
        const sh = shelfById[box.querySelector('#mvShelf').value];
        box.querySelector('#mvDepth').innerHTML = sh.depthCount > 1
          ? `<select id="mvD">${Array.from({ length: sh.depthCount }, (_, i) =>
              `<option value="${i + 1}"${c.depth === i + 1 ? ' selected' : ''}>${esc(depthLabel(i + 1, sh.depthCount))}</option>`).join('')}</select>` : '';
      };
      drawDepth();
      box.querySelector('#mvShelf').onchange = drawDepth;
      box.querySelector('[data-x]').onclick = () => box.remove();
      box.querySelector('[data-ok]').onclick = () => {
        c.shelfId = box.querySelector('#mvShelf').value;
        c.depth = +(box.querySelector('#mvD')?.value || 1);
        box.remove(); rerender(root, b); flashSaved(root); bookChanged();
      };
      return;
    }
    if (act === 'why') { toast('explain() — ' + t('set_audit')); return; }
  });

  root.addEventListener('change', e => {
    const host = root.dataset.book ? root : root.querySelector('[data-book]');
    const b = host && byId[host.dataset.book];
    if (!b) return;
    if (e.target.id === 'rs') { b.work.readStatus = e.target.value; flashSaved(root); bookChanged(); }
    if (e.target.id === 'notes') { b.work.notes = e.target.value; flashSaved(root); bookChanged(); }
  });
}

function rerender(root, b) {
  const isDrawer = root.id === 'drawer';
  const body = root.querySelector('.dbody');
  const fresh = h(detailHTML(b, { full: !isDrawer }));
  body.replaceWith(fresh);
}
function flashSaved(root) {
  const n = root.querySelector('#savednote');
  if (!n) return;
  n.classList.add('on');
  clearTimeout(n._t); n._t = setTimeout(() => n.classList.remove('on'), 2200);
}
