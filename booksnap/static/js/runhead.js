/* ---------------- the header above the results: identity + provenance ------
   Everything needed to tell two runs apart — run number, code sha + dirty
   flag, mode, and the config/catalog snapshot — because "run 3 was better" is
   meaningless without the inputs that produced it. */
import { $, escapeHtml } from './dom.js';
import { api, jsonReq } from './api.js';
import { S } from './state.js';
import { refresh } from './refresh.js';

export function renderRunHead(run, prev) {
  const cv = run.code_version || {};
  $('#runHead').innerHTML = `
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <b>Run #${run.run_no}</b>
      <span class="img-sub">${new Date(run.started_at).toLocaleString()}</span>
      <span class="badge ${run.status === 'completed' ? 'b-AUTO' : 'b-REVIEW'}">${run.status}</span>
      <span class="badge b-none">${escapeHtml(run.mode || 'spines')}</span>
      <span class="mono muted" title="code version">${cv.sha || '?'}${cv.dirty ? '+dirty' : ''}${cv.branch ? ' · ' + cv.branch : ''}</span>
      ${run.duration_s ? `<span class="img-sub">${run.duration_s}s</span>` : ''}
      <span style="flex:1"></span>
      <button class="linkish" id="delRun">delete run</button>
    </div>
    <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
      <input type="text" id="runLabel" placeholder="label this run (e.g. v3: wider token gates)"
             value="${escapeHtml(run.label || '')}" style="flex:1">
      <button id="saveLabel">save</button>
    </div>
    ${prev ? `<div class="img-sub" style="margin-top:6px">compared to run #${prev.run_no}</div>` : ''}
    <details class="prov">
      <summary>run inputs (catalog, config snapshot)</summary>
      <pre>${escapeHtml(JSON.stringify({
        catalog: run.catalog, images: run.image_names,
        per_image: run.images, code_version: cv
      }, null, 1))}</pre>
      <div style="margin-top:6px"><button id="showCfg">show full config snapshot</button></div>
    </details>`;

  $('#delRun').onclick = async () => {
    const b = $('#delRun');           // two-click confirm (see image ✕ note)
    if (b.dataset.armed !== '1') {
      b.dataset.armed = '1';
      b.textContent = `really delete run #${run.run_no}?`;
      b.style.color = '#c0392b';
      setTimeout(() => {
        b.dataset.armed = '';
        b.textContent = 'delete run';
        b.style.color = '';
      }, 3000);
      return;
    }
    await api(`/api/runs/${run.run_id}`, { method: 'DELETE' });
    S.viewRun = null; await refresh();
  };
  $('#saveLabel').onclick = async () => {
    await api(`/api/runs/${run.run_id}`, jsonReq('PATCH', { label: $('#runLabel').value }));
    await refresh();
  };
  $('#showCfg').onclick = async () => {
    const full = await api(`/api/runs/${run.run_id}`);
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(full.config, null, 1);
    $('#showCfg').replaceWith(pre);
  };
}
