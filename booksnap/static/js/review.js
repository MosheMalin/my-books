/* ---------------- the three per-row panels: fix / alternatives / why -------
   Each toggles the row's own .why-box open, so they are mutually exclusive by
   construction. All of them re-render the results on success, which is why
   this module imports renderResults back from results.js — a cycle, but a
   safe one: both sides are hoisted function declarations, and neither is
   called while the modules are still evaluating. */
import { escapeHtml } from './dom.js';
import { api, jsonReq } from './api.js';
import { attachAuthorComplete } from './autocomplete.js';
import { renderResults } from './results.js';

/* ---------------- "fix details" — the match is right, the text is off ------ */
export function showEdit(runId, f, d) {
  const box = document.getElementById('alts-' + f.spine_id);
  if (box.style.display !== 'none') { box.style.display = 'none'; return; }
  // edit what the row currently SHOWS: after an approve/replace the library
  // holds the decision's text, not the run's original claim, so prefilling
  // (and retracting) the claim would resurrect a title already corrected
  const held = d && ['approve', 'replace', 'manual_add'].includes(d.action) && d.title;
  const curT = held ? d.title : f.title;
  const curA = held ? (d.author || '') : (f.author || '');
  // a rejected row holds nothing in the library — nothing to retract
  const old = (d && d.action === 'reject_ignore') ? {}
                                                  : { title: curT, author: curA };
  box.style.display = '';
  box.innerHTML = `
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
      <input type="text" class="rtl" id="edT-${f.spine_id}" value="${escapeHtml(curT)}"
             style="flex:2;min-width:150px" placeholder="title">
      <input type="text" class="rtl authorbox" id="edA-${f.spine_id}" value="${escapeHtml(curA)}"
             style="flex:1;min-width:120px" placeholder="author">
      <button id="edS-${f.spine_id}">save to library</button>
      <button class="linkish" id="edX-${f.spine_id}">✕ cancel</button>
    </div>`;
  attachAuthorComplete(box.querySelector('.authorbox'));
  document.getElementById('edX-' + f.spine_id).onclick = () => { box.style.display = 'none'; };
  document.getElementById('edS-' + f.spine_id).onclick = async () => {
    const title = document.getElementById('edT-' + f.spine_id).value.trim();
    if (!title) return;
    await api('/api/review', jsonReq('POST', {
      run_id: runId, spine_id: f.spine_id, action: 'replace',
      title, author: document.getElementById('edA-' + f.spine_id).value.trim(),
      old }));
    await renderResults();
  };
}

/* ---------------- "find better" alternatives ---------------- */
export async function showAlternatives(runId, f, decisions) {
  const box = document.getElementById('alts-' + f.spine_id);
  if (box.style.display !== 'none') { box.style.display = 'none'; return; }
  box.style.display = '';
  box.innerHTML = '<div class="ocr">looking for alternatives…</div>';
  const d = decisions[f.spine_id];
  // exclude by title+author PAIR — excluding by title alone hid a same-title
  // different-author alternative (שהות by Salvatore vs the Stiefvater claim)
  const exclude = JSON.stringify([
    { title: f.title, author: f.author || '' },
    // the book currently on this row (after a correction) is not an
    // "alternative" to itself
    ...(d && d.title ? [{ title: d.title, author: d.author || '' }] : []),
    ...(d && d.rejected_title ? [{ title: d.rejected_title, author: d.rejected_author || '' }] : [])
  ]);
  const r = await api(`/api/runs/${runId}/alternatives/${encodeURIComponent(f.spine_id)}?exclude=${encodeURIComponent(exclude)}`);
  if (!r.candidates.length) {
    box.innerHTML = '<div class="ocr">no other plausible candidate — you can add the right book manually below. <button class="linkish" onclick="this.closest(\'.why-box\').style.display=\'none\'">✕ close</button></div>';
    return;
  }
  box.innerHTML = r.candidates.map((c, i) => `
    <div style="display:flex;gap:8px;align-items:center;padding:3px 0">
      <button class="alt-use" data-i="${i}">use this</button>
      <span class="rtl">${escapeHtml(c.title)} — ${escapeHtml(c.author || '')}</span>
      <span class="muted mono">${c.score}</span>
    </div>`).join('') + `
    <div style="padding:3px 0">
      <button class="linkish" onclick="this.closest('.why-box').style.display='none'">✕ none of these — close</button>
    </div>`;
  box.querySelectorAll('button.alt-use').forEach(b => {
    b.onclick = async () => {
      const c = r.candidates[+b.dataset.i];
      await api('/api/review', jsonReq('POST', {
        run_id: runId, spine_id: f.spine_id, action: 'replace',
        title: c.title, author: c.author || '',
        old: { title: f.title, author: f.author || '' } }));
      await renderResults();
    };
  });
}

/* ---------------- why did this match? ---------------- */
export async function showWhy(runId, spineId, btn) {
  const box = document.getElementById('why-' + spineId);
  if (box.style.display !== 'none') { box.style.display = 'none'; btn.textContent = 'why?'; return; }
  box.style.display = '';
  btn.textContent = 'hide';
  box.innerHTML = '<div class="ocr">explaining…</div>';
  let d;
  try { d = await api(`/api/runs/${runId}/explain/${encodeURIComponent(spineId)}`); }
  catch (e) { box.innerHTML = `<div class="err">${escapeHtml(e.message)}</div>`; return; }

  const rows = d.candidates.map(c => `
    <tr class="${c.rejected ? 'rej' : 'pass'}">
      <td class="rtl">${escapeHtml(c.title)}</td>
      <td>${c.rejected ? '—' : c.score.toFixed(1)}</td>
      <td class="rtl">${c.title_hits.map(escapeHtml).join(', ') || '<span class="muted">none</span>'}</td>
      <td>${c.title_sim}</td>
      <td class="rtl">${c.author_hits.map(escapeHtml).join(', ') || ''}</td>
      <td>${c.rejected ? `<span class="muted">${escapeHtml(c.rejected)}</span>` : '<b>accepted</b>'}</td>
    </tr>`).join('');

  box.innerHTML = `
    <div class="ocr" style="margin-bottom:6px">
      query tokens: <span class="rtl mono">${d.query_tokens.map(escapeHtml).join(' · ')}</span>
    </div>
    <table class="why-t">
      <thead><tr><th>candidate</th><th>score</th><th>title hits</th>
                 <th>title&nbsp;sim</th><th>author hits</th><th>verdict</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="6" class="muted">no candidate had any title evidence</td></tr>'}</tbody>
    </table>
    <div class="ocr" style="margin-top:6px">
      Recomputed with <b>${escapeHtml(d.explained_with)}</b>
      (${escapeHtml(d.code_version.sha || '?')}${d.code_version.dirty ? '+dirty' : ''}) —
      may differ from what this run stored.
    </div>`;
}
