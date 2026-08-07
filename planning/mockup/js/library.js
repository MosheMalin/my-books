// Tab 1 — the books inventory. Endless scroll, search (normalized Hebrew),
// sort, filters, grid/list, quick "snap a shelf" and manual add.
import { t, nm } from './i18n.js';
import { books, shelves, shelfById, bcById, plById } from './data.js';
import { h, esc, $, $$, locationLabel, shelfLabel, statusBadge, searchHit, normalize, fmtDate, toast } from './ui.js';
import { openDrawer } from './book.js';

const PAGE = 30;
// list is the default view and carries NO image: the spine crop is a slice of a
// shelf, not a cover, and a column of them is noise. The crop stays where it is
// evidence — the book detail and the review rows (owner's call, 2026-08-07).
const state = { q: '', sort: 'added', status: 'all', shelf: 'all', lent: false, author: '',
                wish: false, dups: false, view: 'list', shown: PAGE };

export function setAuthorFilter(a) { state.author = a || ''; state.q = ''; state.shown = PAGE; }

const onWishlist = b => b.copies.some(c => shelfById[c.shelfId] && shelfById[c.shelfId].virtual);

function filtered() {
  let out = books.filter(b =>
    (state.wish ? onWishlist(b) : !onWishlist(b)) &&
    (!state.dups || b.dupPending) &&
    searchHit(b, state.q) &&
    (state.status === 'all' || b.status === state.status) &&
    (state.shelf === 'all' || b.copies.some(c => c.shelfId === state.shelf)) &&
    (!state.lent || b.copies.some(c => c.lending)) &&
    (!state.author || normalize(b.author) === normalize(state.author)));
  const coll = new Intl.Collator(['he', 'en']);
  const cmp = {
    title: (a, b) => coll.compare(a.title, b.title),
    author: (a, b) => coll.compare(a.author, b.author) || coll.compare(a.title, b.title),
    added: (a, b) => (b.addedAt || '').localeCompare(a.addedAt || ''),
    shelf: (a, b) => (a.copies[0].shelfId || 'zz').localeCompare(b.copies[0].shelfId || 'zz') || coll.compare(a.title, b.title),
  }[state.sort];
  return out.sort(cmp);
}

const flags = b => `${b.copies[0].lending ? `<span class="badge b-lent">${esc(t('lent_to', b.copies[0].lending.lentTo))}</span>` : ''}
  ${b.copies.length > 1 ? `<span class="badge b-manual">×${b.copies.length}</span>` : ''}
  ${b.dupPending ? `<span class="badge b-review">${esc(t('dups_pending'))}</span>` : ''}
  ${b.unseenReads ? `<span class="badge b-warn">?</span>` : ''}`;

function cardHTML(b) {
  return `<div class="card noimg" data-open="${b.id}">
    <div class="meta">
      <div class="t rtl-safe">${esc(b.title)}</div>
      <div class="a rtl-safe">${esc(b.author)}</div>
      <div class="loc rtl-safe">${esc(locationLabel(b.copies[0]))}</div>
      <div class="foot">${statusBadge(b.status)}${flags(b)}</div>
    </div></div>`;
}
function rowHTML(b) {
  return `<div class="brow" data-open="${b.id}">
    <div class="meta">
      <div class="t rtl-safe">${esc(b.title)}</div>
      <div class="a rtl-safe">${esc(b.author)}</div>
    </div>
    <div class="chiprow" style="flex:none">${flags(b)}</div>
    <div class="side rtl-safe">${esc(locationLabel(b.copies[0]))}</div>
    <div style="flex:none">${statusBadge(b.status)}</div>
  </div>`;
}

export function render(mount) {
  const list = filtered();
  // authors of the collection you actually own — the wishlist isn't part of it
  const authors = new Set(books.filter(b => !onWishlist(b)).map(b => normalize(b.author)));

  mount.innerHTML = `
    <div class="toolbar">
      <div class="searchwrap"><span class="mag">⌕</span>
        <input type="search" id="q" class="rtl-safe" placeholder="${esc(t('search_ph'))}" value="${esc(state.q)}"></div>
      <select id="sort" style="width:auto">
        ${['title', 'author', 'added', 'shelf'].map(s =>
          `<option value="${s}"${state.sort === s ? ' selected' : ''}>${esc(t('sort'))}: ${esc(t('sort_' + s))}</option>`).join('')}
      </select>
      <div class="seg">
        <button data-view="list" class="${state.view === 'list' ? 'on' : ''}">☰ ${esc(t('view_list'))}</button>
        <button data-view="grid" class="${state.view === 'grid' ? 'on' : ''}">▦ ${esc(t('view_grid'))}</button>
      </div>
      <button class="btn primary" data-go="#/capture">📷 ${esc(t('upload_shelf'))}</button>
      <button class="btn" id="addBook">＋ ${esc(t('add_book'))}</button>
    </div>

    <div class="filterbar">
      <span class="tiny muted">${esc(t('filters'))}:</span>
      ${['all', 'auto', 'approved', 'manual'].map(s =>
        `<button class="chip ${state.status === s ? 'on' : ''}" data-status="${s}">${esc(s === 'all' ? t('all') : t('st_' + s))}</button>`).join('')}
      <select id="shelfFilter" style="width:auto">
        <option value="all">${esc(t('shelf'))}: ${esc(t('all'))}</option>
        ${shelves.filter(s => !s.virtual).map(s => {
          const bc = bcById[s.bcId];
          return `<option value="${s.id}"${state.shelf === s.id ? ' selected' : ''}>${esc(nm(bc.name))} · ${esc(shelfLabel(s))}</option>`;
        }).join('')}
      </select>
      <button class="chip ${state.lent ? 'on' : ''}" data-lent>${esc(t('lent_only'))}</button>
      <button class="chip ${state.dups ? 'on' : ''}" data-dups>${esc(t('dups_pending'))} (${books.filter(b => b.dupPending).length})</button>
      <button class="chip ${state.wish ? 'on' : ''}" data-wish>☆ ${esc(t('wishlist'))}</button>
      ${state.author ? `<button class="chip on" data-clearauthor>✕ ${esc(state.author)}</button>` : ''}
      ${(state.q || state.status !== 'all' || state.shelf !== 'all' || state.lent || state.author || state.wish || state.dups)
        ? `<button class="linkish" data-clear>${esc(t('clear_filters'))}</button>` : ''}
    </div>

    <div class="countline">${list.length} ${esc(t('n_books'))} · ${authors.size} ${esc(t('n_authors'))}</div>
    <div id="feed"></div>
    <div class="sentinel" id="sentinel"></div>`;

  paint(mount, list);

  // --- events
  const feed = $('#feed', mount);
  $('#q', mount).addEventListener('input', e => { state.q = e.target.value; state.shown = PAGE; const l = filtered(); $('.countline', mount).textContent = `${l.length} ${t('n_books')} · ${authors.size} ${t('n_authors')}`; paint(mount, l); });
  $('#sort', mount).addEventListener('change', e => { state.sort = e.target.value; state.shown = PAGE; paint(mount, filtered()); });
  $('#shelfFilter', mount).addEventListener('change', e => { state.shelf = e.target.value; state.shown = PAGE; render(mount); });
  if (!mount._wired) { mount._wired = true; mount.addEventListener('click', e => {
    const v = e.target.closest('[data-view]'); if (v) { state.view = v.dataset.view; return render(mount); }
    const s = e.target.closest('[data-status]'); if (s) { state.status = s.dataset.status; state.shown = PAGE; return render(mount); }
    if (e.target.closest('[data-lent]')) { state.lent = !state.lent; state.shown = PAGE; return render(mount); }
    if (e.target.closest('[data-wish]')) { state.wish = !state.wish; state.shown = PAGE; return render(mount); }
    if (e.target.closest('[data-dups]')) { state.dups = !state.dups; state.shown = PAGE; return render(mount); }
    if (e.target.closest('[data-clearauthor]')) { state.author = ''; return render(mount); }
    if (e.target.closest('[data-clear]')) { Object.assign(state, { q: '', status: 'all', shelf: 'all', lent: false, author: '', wish: false, dups: false, shown: PAGE }); return render(mount); }
    const o = e.target.closest('[data-open]'); if (o) return openDrawer(o.dataset.open);
    if (e.target.closest('#addBook')) return addBookModal(mount);
  }); }

  // endless scroll
  const sentinel = $('#sentinel', mount);
  const io = new IntersectionObserver(entries => {
    if (!entries[0].isIntersecting) return;
    const l = filtered();
    if (state.shown >= l.length) return;
    state.shown += PAGE;
    paint(mount, l, true);
  }, { rootMargin: '400px' });
  io.observe(sentinel);
  mount._io && mount._io.disconnect();
  mount._io = io;
}

function paint(mount, list, append = false) {
  const feed = $('#feed', mount);
  const slice = list.slice(append ? feed.dataset.n | 0 : 0, state.shown);
  const html = state.view === 'grid'
    ? slice.map(cardHTML).join('')
    : slice.map(rowHTML).join('');
  if (append) feed.querySelector(state.view === 'grid' ? '.bookgrid' : '.booklist').insertAdjacentHTML('beforeend', html);
  else feed.innerHTML = list.length
    ? `<div class="${state.view === 'grid' ? 'bookgrid' : 'booklist'}">${html}</div>`
    : `<div class="empty">${esc(t('no_results'))}</div>`;
  feed.dataset.n = Math.min(state.shown, list.length);
  const s = $('#sentinel', mount);
  if (s) s.textContent = state.shown >= list.length ? (list.length ? t('end_of_list') : '') : t('loading_more');
}

// ---- manual add, with the "is it already here?" check the current UI has ----
function addBookModal(mount) {
  const box = h(`<div class="modal on"><div class="box">
    <h3>${esc(t('add_title'))}</h3>
    <div class="body">
      <label class="fld"><span>${esc(t('f_title'))}</span><input type="text" id="nTitle" class="rtl-safe"></label>
      <label class="fld"><span>${esc(t('f_author'))}</span><input type="text" id="nAuthor" class="rtl-safe" list="authorList"></label>
      <datalist id="authorList">${[...new Set(books.map(b => b.author))].map(a => `<option value="${esc(a)}">`).join('')}</datalist>
      <div class="hint" id="hint"></div>
      <label class="fld"><span>${esc(t('bind_shelf'))}</span>
        <select id="nShelf"><option value="">${esc(t('no_shelf'))}</option>
        ${shelves.map(s => {
          if (s.virtual) return `<option value="${s.id}">☆ ${esc(nm(s.name))}</option>`;
          const bc = bcById[s.bcId], pl = plById[bc.plId];
          return `<option value="${s.id}">${esc(nm(pl.name))} · ${esc(nm(bc.name))} · ${esc(shelfLabel(s))}</option>`; }).join('')}
        </select></label>
      <div id="nDepth"></div>
    </div>
    <div class="foot"><button class="btn" data-x>${esc(t('cancel'))}</button>
      <button class="btn primary" data-ok>${esc(t('save'))}</button></div>
  </div></div>`);
  document.body.append(box);

  const hint = box.querySelector('#hint');
  const check = () => {
    const q = box.querySelector('#nTitle').value.trim();
    if (!q) { hint.innerHTML = ''; return; }
    const exact = books.find(b => normalize(b.title) === normalize(q));
    if (exact) { hint.innerHTML = `<span class="ok">✓ ${esc(t('already_have'))}</span> — <span class="rtl-safe">${esc(exact.author)}</span>`; return; }
    const near = books.filter(b => searchHit(b, q)).slice(0, 3);
    hint.innerHTML = near.length
      ? `<span class="near">${esc(t('near_have'))}</span> <span class="rtl-safe">${near.map(b => esc(b.title)).join(' · ')}</span>`
      : `<span class="muted">${esc(t('not_have'))}</span>`;
  };
  box.querySelector('#nTitle').addEventListener('input', check);
  box.querySelector('#nShelf').addEventListener('change', e => {
    const sh = shelfById[e.target.value];
    box.querySelector('#nDepth').innerHTML = sh && sh.depthCount > 1
      ? `<label class="fld"><span>${esc(t('depth'))}</span><select id="nD">${Array.from({ length: sh.depthCount }, (_, i) => `<option value="${i + 1}">${esc(t('depth_n', i + 1))}</option>`).join('')}</select></label>` : '';
  });
  box.querySelector('[data-x]').onclick = () => box.remove();
  box.querySelector('[data-ok]').onclick = () => {
    const title = box.querySelector('#nTitle').value.trim();
    if (!title) return;
    const shelfId = box.querySelector('#nShelf').value || null;
    books.unshift({
      id: 'b' + (books.length + 1) + 'x', title, author: box.querySelector('#nAuthor').value.trim() || '—',
      status: 'manual', addedAt: '2026-08-07', spine: 'assets/spines/s10.jpg',
      work: { rating: 0, notes: '', readStatus: 'unread' }, unseenReads: 0,
      copies: [{ id: 'nc1', label: '', shelfId, depth: +(box.querySelector('#nD')?.value || 1), tags: [], lastSeen: null, lending: null, provenance: [] }],
    });
    box.remove(); toast(t('save')); render(mount);
  };
}
