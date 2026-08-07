// Tab 2 — the MAP. Sketch-first (owner's call, 2026-08-07): a place is drawn
// as a clean schematic; bookcases are blocks on it; clicking one drills into
// its elevation (shelf rows, each with its photo); clicking a shelf opens the
// durable shelf panel — books at the selected depth + read history (§5.6/§5.7).
// A list view is the fallback for places with no sketch yet.
import { t, nm } from './i18n.js';
import { physicalLibraries, bookcases, shelves, shelfById, bcById, books, reads } from './data.js';
import { h, esc, $, locationLabel, shelfLabel, depthLabel, statusBadge, fmtDate, toast } from './ui.js';
import { openDrawer } from './book.js';

const state = { pl: 'pl1', bc: null, shelf: 'sh2', depth: 1, view: 'map' };

export function selectShelf(id) {
  const s = shelfById[id];
  if (!s || !s.bcId) return;
  state.shelf = id; state.depth = 1; state.bc = s.bcId; state.pl = bcById[s.bcId].plId;
}

const booksOn = (shelfId, depth) =>
  books.filter(b => b.copies.some(c => c.shelfId === shelfId && (depth == null || c.depth === depth)));
const shelvesIn = bcId => shelves.filter(s => s.bcId === bcId);
const caseCount = bcId => shelvesIn(bcId).reduce((n, s) => n + booksOn(s.id, null).length, 0);

export function render(mount) {
  const pl = physicalLibraries.find(p => p.id === state.pl);
  const sh = state.shelf ? shelfById[state.shelf] : null;

  mount.innerHTML = `<div class="shelveslayout">
    <div>
      <div class="chiprow" style="margin-bottom:10px">
        <span class="tiny muted">${esc(t('phys_lib'))}:</span>
        ${physicalLibraries.map(p => `<button class="chip ${state.pl === p.id ? 'on' : ''}" data-pl="${p.id}">${esc(nm(p.name))}</button>`).join('')}
        <button class="chip" data-addplace>＋</button>
        <span class="spacer" style="flex:1"></span>
        <div class="seg">
          <button data-mv="map" class="${state.view === 'map' ? 'on' : ''}">▣ ${esc(t('view_map'))}</button>
          <button data-mv="list" class="${state.view === 'list' ? 'on' : ''}">☰ ${esc(t('view_cards'))}</button>
        </div>
      </div>
      ${state.bc ? elevation(bcById[state.bc])
        : state.view === 'map' && pl.sketch ? placeSketch(pl)
        : placeList(pl)}
    </div>
    <div>${sh ? shelfDetail(sh) : `<div class="empty">${esc(t('click_case'))}</div>`}</div>
  </div>`;

  if (mount._wired) return;
  mount._wired = true;
  mount.addEventListener('click', e => {
    const p = e.target.closest('[data-pl]');
    if (p) { state.pl = p.dataset.pl; state.bc = null; state.shelf = null; return render(mount); }
    const v = e.target.closest('[data-mv]'); if (v) { state.view = v.dataset.mv; return render(mount); }
    const c = e.target.closest('[data-case]'); if (c) { state.bc = c.dataset.case; state.shelf = null; return render(mount); }
    if (e.target.closest('[data-backmap]')) { state.bc = null; state.shelf = null; return render(mount); }
    const s = e.target.closest('[data-shelf]'); if (s) { state.shelf = s.dataset.shelf; state.depth = 1; state.bc = shelfById[s.dataset.shelf].bcId; return render(mount); }
    const d = e.target.closest('[data-depth]'); if (d) { state.depth = +d.dataset.depth; return render(mount); }
    const o = e.target.closest('[data-open]'); if (o) return openDrawer(o.dataset.open);
    if (e.target.closest('[data-adddepth]')) { shelfById[state.shelf].depthCount++; toast(t('add_depth')); return render(mount); }
    const col = e.target.closest('[data-addcolumn]');
    if (col) { bcById[col.dataset.addcolumn].columns++; toast(t('add_column')); return render(mount); }
    const slot = e.target.closest('[data-addshelf]'); if (slot) return toast(t('add_shelf'));
    if (e.target.closest('[data-addcase]')) return toast(t('add_case'));
    if (e.target.closest('[data-addplace]')) return toast(t('phys_lib'));
    if (e.target.closest('[data-draw]')) return toast(t('draw_sketch'));
    if (e.target.closest('[data-editsketch]')) return toast(t('edit_sketch'));
    if (e.target.closest('[data-reread]')) { location.hash = '#/capture'; }
  });
}

// ---------- level 1: the place, as a clean schematic ----------
function placeSketch(pl) {
  const cases = bookcases.filter(b => b.plId === pl.id && b.plan);
  return `<div class="panel">
    <h3><span class="rtl-safe">${esc(nm(pl.name))}</span>
      <span style="display:flex;gap:6px">
        <button class="btn sm ghost" data-editsketch>✎ ${esc(t('edit_sketch'))}</button>
        <button class="btn sm" data-addcase>＋ ${esc(t('add_case'))}</button>
      </span></h3>
    <div class="body">
      <svg class="plan" viewBox="0 0 100 46" role="img">
        ${pl.rooms.map(r => `
          <rect class="room" x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" rx="1.2"/>
          <text class="roomlbl" x="${r.x + r.w / 2}" y="${r.y + r.h - 1.4}">${esc(nm(r.label))}</text>`).join('')}
        ${cases.map(b => {
          const p = b.plan, n = caseCount(b.id), k = shelvesIn(b.id).length;
          return `<g class="case ${state.bc === b.id ? 'on' : ''}" data-case="${b.id}">
            <rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx=".8"/>
            <text class="caselbl" x="${p.x + p.w / 2}" y="${p.y + p.h + 2.8}">${esc(nm(b.name))}</text>
            <text class="casesub" x="${p.x + p.w / 2}" y="${p.y + p.h + 5.2}">${k} ${esc(k === 1 ? t('shelf') : t('n_shelves'))} · ${n} ${esc(t('n_books'))}</text>
          </g>`;
        }).join('')}
        <g class="addcase" data-addcase>
          <rect x="38" y="39" width="24" height="5.5" rx="1"/>
          <text x="50" y="41.8">＋ ${esc(t('add_case'))}</text>
        </g>
      </svg>
      <div class="tiny muted" style="margin-top:8px">${esc(t('click_case'))}</div>
    </div></div>`;
}

// ---------- fallback / no sketch ----------
function placeList(pl) {
  const cases = bookcases.filter(b => b.plId === pl.id);
  return `<div class="panel">
    <h3><span class="rtl-safe">${esc(nm(pl.name))}</span>
      <button class="btn sm" data-addcase>＋ ${esc(t('add_case'))}</button></h3>
    <div class="body">
      ${!pl.sketch ? `<div class="sketchcta">
        <div>${esc(t('no_sketch'))}</div>
        <div style="margin-top:8px;display:flex;gap:7px;justify-content:center;flex-wrap:wrap">
          <button class="btn sm primary" data-draw>✎ ${esc(t('draw_sketch'))}</button>
        </div>
        <div class="tiny muted" style="margin-top:6px">${esc(t('photo_sketch'))}</div>
      </div>` : ''}
      ${cases.map(bc => `
        <div class="casehead rtl-safe">${esc(nm(bc.name))}</div>
        ${shelvesIn(bc.id).map(shelfCard).join('')}`).join('')}
    </div></div>`;
}

// ---------- level 2: the bookcase elevation, drawn as it physically is ----------
// A case is a GRID: `columns` vertical bays across, levels down. The grid is
// pinned to LTR so column 1 is always the leftmost cell — a piece of furniture
// must not mirror when the UI language changes. (Which end is column 1 for a
// Hebrew user is an open question; see UI_PLAN §8.)
function elevation(bc) {
  const list = shelvesIn(bc.id);
  const cols = bc.columns || 1;
  const levels = Math.max(1, ...list.map(s => s.level));
  const at = (c, l) => list.find(s => s.col === c && s.level === l);

  const cells = [];
  for (let l = 1; l <= levels; l++) {
    for (let c = 1; c <= cols; c++) {
      const s = at(c, l);
      cells.push(s ? shelfTile(s) : `<div class="elevslot" data-addshelf="${bc.id}:${c}:${l}">
        <span>${esc(t('add_shelf'))}</span></div>`);
    }
  }

  return `<div class="panel">
    <h3><span style="display:flex;gap:8px;align-items:center">
        <button class="btn sm ghost" data-backmap>← ${esc(t('back_to_place'))}</button>
        <span class="rtl-safe">${esc(nm(bc.name))}</span></span>
      <span class="tiny muted">${cols > 1 ? esc(t('cols_count', cols)) + ' · ' : ''}${list.length} ${esc(list.length === 1 ? t('shelf') : t('n_shelves'))} · ${caseCount(bc.id)} ${esc(t('n_books'))}</span></h3>
    <div class="body">
      ${cols > 1 ? `<div class="colhead" style="grid-template-columns:repeat(${cols},1fr)">
        ${Array.from({ length: cols }, (_, i) => `<span>${esc(t('column_n', i + 1))}</span>`).join('')}
      </div>` : ''}
      <div class="elev" style="grid-template-columns:repeat(${cols},1fr)">${cells.join('')}</div>
      <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="btn sm ghost" data-addcolumn="${bc.id}">${esc(t('add_column'))}</button>
        <span class="tiny muted">${list.length} ${esc(list.length === 1 ? t('shelf') : t('n_shelves'))} — ${esc(t('detect_shelves'))} (segment.py)</span>
      </div>
    </div></div>`;
}

function shelfTile(s) {
  return `<div class="elevshelf ${state.shelf === s.id ? 'on' : ''}" data-shelf="${s.id}"
      style="${s.photo ? `background-image:url('${esc(s.photo)}')` : ''}">
    <div class="ov">
      <span style="font-weight:600">${esc(t('shelf_n', s.level))}</span>
      <span class="tiny">${booksOn(s.id, null).length} ${esc(t('n_books'))}</span>
      ${s.depthCount > 1 ? `<span class="badge b-manual">${esc(t('rows_count', s.depthCount))}</span>` : ''}
      ${s.depthCount > (s.depthRead.length || 0) ? `<span class="badge b-review">!</span>` : ''}
    </div></div>`;
}

function shelfCard(s) {
  return `<div class="shelfcard ${state.shelf === s.id ? 'on' : ''}" data-shelf="${s.id}">
    ${s.photo ? `<img class="ph" src="${esc(s.photo)}" alt="">` : `<div class="ph none">${esc(t('never_read'))}</div>`}
    <div class="info">
      <span class="n">${esc(shelfLabel(s))}</span>
      <span class="tiny muted">${booksOn(s.id, null).length} ${esc(t('n_books'))}</span>
      ${s.depthCount > 1 ? `<span class="badge b-manual">${esc(t('rows_count', s.depthCount))}</span>` : ''}
    </div></div>`;
}

// ---------- level 3: the shelf (durable book list + history) ----------
function shelfDetail(s) {
  const bc = bcById[s.bcId];
  const list = booksOn(s.id, s.depthCount > 1 ? state.depth : null);
  const hist = reads.filter(r => r.shelfId === s.id);
  const staleRows = Array.from({ length: s.depthCount }, (_, i) => i + 1).filter(d => !s.depthRead.includes(d));

  return `<div class="panel">
    <h3><span class="rtl-safe">${esc(nm(bc.name))} · ${esc(shelfLabel(s))}</span>
      <button class="btn sm primary" data-reread>📷 ${esc(t('reread'))}</button></h3>
    <div class="body">
      ${s.photo ? `<img src="${esc(s.photo)}" alt="" style="width:100%;border-radius:9px;display:block;max-height:190px;object-fit:cover">` : ''}
      <div class="chiprow" style="margin-top:10px">
        <span class="tiny muted">${esc(t('last_read'))}: ${esc(s.lastRead ? fmtDate(s.lastRead) : t('never_read'))}</span>
        <span class="tiny muted">·</span>
        <span class="tiny muted">${esc(s.depthCount > 1 ? t('rows_count', s.depthCount) : t('one_row'))}</span>
        ${staleRows.length ? `<span class="badge b-review">${esc(t('stale_rows', staleRows.join(', '), s.lastRead ? fmtDate(s.lastRead) : '—'))}</span>` : ''}
      </div>

      <div class="depthbar">
        ${Array.from({ length: s.depthCount }, (_, i) => i + 1).map(d =>
          `<button data-depth="${d}" class="${state.depth === d ? 'on' : ''}">${esc(s.depthCount > 1 ? depthLabel(d, s.depthCount) : t('one_row'))} · ${booksOn(s.id, d).length}</button>`).join('')}
        <button class="dashed" data-adddepth>${esc(t('add_depth'))}</button>
      </div>

      <h4 class="sublbl">${esc(t('shelf_books'))} (${list.length})</h4>
      <div class="booklist">
        ${list.length ? list.map(b => `
          <div class="brow" data-open="${b.id}">
            <div class="meta"><div class="t rtl-safe">${esc(b.title)}</div>
              <div class="a rtl-safe">${esc(b.author)}</div></div>
            ${b.dupPending ? `<span class="badge b-review">${esc(t('dups_pending'))}</span>` : ''}
            ${b.unseenReads ? `<span class="badge b-warn">${esc(t('unseen_warn', b.unseenReads))}</span>` : ''}
            <div style="flex:none">${statusBadge(b.status)}</div>
          </div>`).join('') : `<div class="empty">${esc(t('never_read'))}</div>`}
      </div>

      <h4 class="sublbl" style="margin-top:18px">${esc(t('read_history'))}</h4>
      ${hist.length ? hist.map(r => `
        <div class="readrow">
          <span class="when">${esc(fmtDate(r.at))}</span>
          <span class="diffbits">
            ${s.depthCount > 1 ? `<span class="m">${esc(depthLabel(r.depth, s.depthCount))}</span>` : ''}
            ${r.added ? `<span class="g">+${r.added} ${esc(t('read_added'))}</span>` : ''}
            ${r.corrected ? `<span class="o">${r.corrected} ${esc(t('read_corrected'))}</span>` : ''}
            ${r.unchanged ? `<span class="m">${r.unchanged} ${esc(t('read_unchanged'))}</span>` : ''}
            ${r.unseen ? `<span class="r">${r.unseen} ${esc(t('read_unseen'))}</span>` : ''}
          </span>
          <span class="tiny muted mono">run ${r.runNo} · ${esc(r.mode)}</span>
        </div>`).join('') : `<div class="empty">${esc(t('never_read'))}</div>`}
    </div></div>`;
}
