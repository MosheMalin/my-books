// Tab 3 — capture & read. Practically today's view, re-centred on SHELVES
// instead of runs: every photo is assigned to a shelf + depth before reading.
// Review is INLINE here (momentum while the crops are on screen); the shelf
// stays the durable home for the books and the history (VISION §5.5/§5.6).
import { t, nm } from './i18n.js';
import { captures, shelves, shelfById, bcById, plById, reviewRows } from './data.js';
import { h, esc, $, $$, shelfLabel, depthLabel, toast } from './ui.js';

const state = { sel: new Set(['cap1', 'cap2']), mode: 'llmpage', running: false, prog: 0, done: true };
const decisions = {};   // rowId -> approved | rejected | copy decision

export function render(mount) {
  mount.innerHTML = `<div class="capturelayout">
    <div>
      <div class="panel" style="margin-bottom:14px">
        <h3><span>${esc(t('tab_capture'))}</span><span class="muted tiny">${captures.length}</span></h3>
        <div class="body">
          <div id="drop"><strong>${esc(t('drop_here'))}</strong><br><span class="tiny">${esc(t('or_click'))}</span></div>
          <div class="tiny muted" style="margin-top:7px">📱 ${esc(t('phone_hint', '192.168.1.24:8756'))}</div>

          <div class="chiprow" style="margin:12px 0 6px">
            <button class="linkish" data-all>${esc(t('select_all'))}</button>
            <button class="linkish" data-none>${esc(t('select_none'))}</button>
            <button class="linkish" data-new>${esc(t('select_new'))}</button>
          </div>
          <div id="caps">${captures.map(capRow).join('')}</div>

          <div style="margin-top:14px">
            <div class="tiny muted" style="margin-bottom:5px">${esc(t('mode'))}</div>
            <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:10px">
              ${[['spines', 'mode_spines', 'mode_spines_d'], ['fullpage', 'mode_full', 'mode_full_d'], ['llmpage', 'mode_llm', 'mode_llm_d']]
                .map(([v, n, d]) => `<label class="modeopt"><input type="radio" name="mode" value="${v}"${state.mode === v ? ' checked' : ''}>
                  <span><b>${esc(t(n))}</b>${esc(t(d))}</span></label>`).join('')}
            </div>
            <div style="display:flex;gap:8px">
              <button class="btn primary" id="runBtn" style="flex:1">${esc(t('run'))} (${state.sel.size})</button>
              ${state.running ? `<button class="btn danger" id="stopBtn" style="flex:1">${esc(t('stop'))}</button>` : ''}
            </div>
            <div id="progWrap" style="display:${state.running ? 'block' : 'none'};margin-top:10px">
              <div class="tiny muted" id="progText"></div>
              <div class="bar"><div id="progBar" style="width:${state.prog}%"></div></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div>${state.done ? reviewPanel() : `<div class="empty">${esc(t('review_now'))}</div>`}</div>
  </div>`;

  if (mount._wired) return;
  mount._wired = true;
  mount.addEventListener('change', e => {
    if (e.target.name === 'mode') { state.mode = e.target.value; return; }
    if (e.target.dataset.capShelf) { const c = captures.find(x => x.id === e.target.dataset.capShelf); c.shelfId = e.target.value || null; c.state = c.shelfId ? 'ready' : 'unassigned'; return render(mount); }
    if (e.target.dataset.capDepth) { captures.find(x => x.id === e.target.dataset.capDepth).depth = +e.target.value; }
  });
  mount.addEventListener('click', e => {
    const row = e.target.closest('[data-cap]');
    if (row && !e.target.closest('select')) {
      const id = row.dataset.cap;
      state.sel.has(id) ? state.sel.delete(id) : state.sel.add(id);
      return render(mount);
    }
    if (e.target.closest('[data-all]')) { captures.forEach(c => state.sel.add(c.id)); return render(mount); }
    if (e.target.closest('[data-none]')) { state.sel.clear(); return render(mount); }
    if (e.target.closest('[data-new]')) { state.sel = new Set(captures.filter(c => c.state !== 'done').map(c => c.id)); return render(mount); }
    if (e.target.closest('#runBtn')) return fakeRun(mount);
    if (e.target.closest('#stopBtn')) { state.running = false; state.done = true; return render(mount); }
    if (e.target.closest('#drop')) return toast(t('drop_here'));

    const a = e.target.closest('[data-approve]'); if (a) { decisions[a.dataset.approve] = 'approved'; return render(mount); }
    const r = e.target.closest('[data-reject]');  if (r) { decisions[r.dataset.reject] = 'rejected'; return render(mount); }
    const d = e.target.closest('[data-dup]');     if (d) { decisions[d.dataset.row] = d.dataset.dup; return render(mount); }
    const p = e.target.closest('[data-pick]');    if (p) { const row = reviewRows.find(x => x.id === p.dataset.row); row.title = p.dataset.pick; decisions[row.id] = 'approved'; return render(mount); }
    if (e.target.closest('[data-approveall]')) { reviewRows.filter(x => x.tier === 'AUTO').forEach(x => decisions[x.id] = 'approved'); return render(mount); }
    if (e.target.closest('[data-why]')) return toast('explain()');
  });
}

function capRow(c) {
  const sel = state.sel.has(c.id);
  const sh = c.shelfId ? shelfById[c.shelfId] : null;
  return `<div class="caprow ${sel ? 'sel' : ''}" data-cap="${c.id}">
    <input type="checkbox" ${sel ? 'checked' : ''} style="width:16px;height:16px;flex:none;accent-color:var(--accent)">
    <img src="${esc(c.thumb)}" alt="">
    <div class="m">
      <div class="fn">${esc(c.file)}</div>
      <div style="display:flex;gap:5px;margin-top:4px;flex-wrap:wrap">
        <select data-cap-shelf="${c.id}">
          <option value="">${esc(t('unassigned'))}</option>
          ${shelves.filter(s => !s.virtual).map(s => { const bc = bcById[s.bcId];
            return `<option value="${s.id}"${c.shelfId === s.id ? ' selected' : ''}>${esc(nm(bc.name))} · ${esc(shelfLabel(s))}</option>`; }).join('')}
        </select>
        ${sh && sh.depthCount > 1 ? `<select data-cap-depth="${c.id}">
          ${Array.from({ length: sh.depthCount }, (_, i) => i + 1).map(d =>
            `<option value="${d}"${c.depth === d ? ' selected' : ''}>${esc(depthLabel(d, sh.depthCount))}</option>`).join('')}
        </select>` : ''}
      </div>
    </div>
    ${c.state === 'done' ? `<span class="badge b-approved">✓</span>` : ''}
  </div>`;
}

function reviewPanel() {
  const added = reviewRows.filter(r => r.diff === 'added').length;
  const unchanged = reviewRows.filter(r => r.diff === 'unchanged').length;
  const unmatched = reviewRows.filter(r => r.diff === 'unmatched').length;
  const shelfName = shelfLabel(shelfById.sh2);

  return `<div class="panel">
    <h3><span>${esc(t('review_now'))}</span>
      <button class="btn sm" data-approveall>${esc(t('approve_all'))}</button></h3>
    <div class="body">
      <div class="chiprow" style="margin-bottom:8px">
        <span class="badge b-approved rtl-safe">${esc(nm(bcById.bc1.name))} · ${esc(shelfName)} · ${esc(depthLabel(2, 2))}</span>
        <span class="diffbits">
          <span class="g">+${added} ${esc(t('read_added'))}</span>
          <span class="m">${unchanged} ${esc(t('read_unchanged'))}</span>
          <span class="r">${unmatched} ${esc(t('unmatched'))}</span></span>
        <button class="chip" data-go="#/map/sh2">${esc(t('goto_shelf'))} →</button>
      </div>
      <div class="tiny muted" style="margin-bottom:10px">${esc(t('review_hint'))}</div>
      ${reviewRows.map(reviewRow).join('')}
    </div></div>`;
}

function reviewRow(r) {
  const dec = decisions[r.id];
  const tierCls = r.tier === 'AUTO' ? 'b-auto' : r.tier === 'REVIEW' ? 'b-review' : 'b-none';
  const diffBadge = r.diff === 'added' ? `<span class="badge b-auto">${esc(t('diff_added'))}</span>`
    : r.diff === 'unchanged' ? `<span class="badge b-manual">${esc(t('diff_unchanged'))}</span>`
    : r.diff === 'duplicate' ? `<span class="badge b-review">${esc(t('diff_duplicate'))}</span>` : '';

  return `<div class="rrow ${dec === 'rejected' ? 'rejected' : ''}">
    <div class="top">
      <img class="spine" src="${esc(r.spine)}" alt="">
      <div class="m">
        <div class="t rtl-safe">${esc(r.title || t('unmatched'))}</div>
        <div class="tiny muted rtl-safe">${esc(r.author || '')} ${r.ocr ? `· «${esc(r.ocr)}»` : ''}</div>
        <div class="chiprow" style="margin-top:5px">
          <span class="badge ${tierCls}">${esc(r.tier === 'none' ? '—' : r.tier)}${r.score ? ' ' + r.score : ''}</span>
          ${diffBadge}
          ${dec === 'approved' ? `<span class="badge b-approved">✓</span>` : ''}
          <button class="linkish" data-why>${esc(t('why'))}</button>
        </div>
      </div>
      <div class="acts">
        ${r.title && dec !== 'approved' ? `<button class="btn sm primary" data-approve="${r.id}">✓</button>` : ''}
        ${r.title ? `<button class="btn sm" data-reject="${r.id}">✕</button>` : ''}
      </div>
    </div>
    ${r.diff === 'duplicate' && !dec ? `<div class="dupbox">
      <div class="rtl-safe" style="margin-bottom:7px">${esc(t('dup_q', r.dupOf.label[document.documentElement.lang] || r.dupOf.label.he))}</div>
      <div class="chiprow">
        <button class="chip" data-row="${r.id}" data-dup="same">${esc(t('dup_same'))}</button>
        <button class="chip" data-row="${r.id}" data-dup="another">${esc(t('dup_another'))}</button>
        <button class="chip" data-row="${r.id}" data-dup="wrong">${esc(t('dup_wrong'))}</button>
      </div>
      <div class="tiny muted" style="margin-top:6px">${esc(t('dup_same'))} ← default</div>
    </div>` : ''}
    ${r.alts && dec !== 'approved' ? `<div class="altbox">
      <div class="tiny muted" style="margin-bottom:5px">${esc(t('alternatives'))}</div>
      <table>${r.alts.map(([tt, aa, sc]) => `<tr>
        <td class="rtl-safe">${esc(tt)}</td><td class="rtl-safe muted">${esc(aa)}</td>
        <td class="mono">${sc}</td>
        <td style="text-align:end"><button class="btn sm" data-row="${r.id}" data-pick="${esc(tt)}">${esc(t('approve'))}</button></td>
      </tr>`).join('')}</table></div>` : ''}
  </div>`;
}

function fakeRun(mount) {
  state.running = true; state.done = false; state.prog = 0;
  render(mount);
  const total = state.sel.size || 1;
  let i = 0;
  const tick = setInterval(() => {
    i++;
    state.prog = Math.min(100, (i / (total * 4)) * 100);
    const pt = $('#progText', mount), pb = $('#progBar', mount);
    if (pt) pt.textContent = t('reading_now', Math.ceil(i / 4), total);
    if (pb) pb.style.width = state.prog + '%';
    if (state.prog >= 100 || !state.running) {
      clearInterval(tick); state.running = false; state.done = true; render(mount);
    }
  }, 260);
}
