/* ---------------- run history: the left-hand list and the results picker --- */
import { $, escapeHtml } from './dom.js';
import { S } from './state.js';
import { renderResults } from './results.js';

export function runTitle(r) {
  const when = new Date(r.started_at).toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  return `#${r.run_no} · ${when}`;
}

export function renderRuns() {
  $('#runCount').textContent =
    S.runs.length ? `${S.runs.length} run${S.runs.length > 1 ? 's' : ''}` : '';
  const list = $('#runList');
  if (!S.runs.length) { list.innerHTML = '<li class="empty">No runs yet.</li>'; return; }
  const active = S.viewRun || (S.runs.find(r => r.totals.spines) || {}).run_id;
  list.innerHTML = '';
  for (const r of S.runs) {
    const t = r.totals, li = document.createElement('li');
    li.className = 'run-item' + (r.run_id === active ? ' on' : '');
    li.innerHTML = `
      <span class="run-no">#${r.run_no}</span>
      <div class="run-mid">
        <div style="font-size:13px">${escapeHtml(r.label || r.image_names.join(', '))}</div>
        <div class="img-sub">${runTitle(r).split('· ')[1]} ·
          <span class="mono">${r.code_version.sha || '?'}${r.code_version.dirty ? '+' : ''}</span>
          ${r.status !== 'completed' ? ` · <em>${r.status}</em>` : ''}
        </div>
      </div>
      <div style="text-align:right;flex:none">
        <div class="img-sub"><b style="color:var(--auto)">${t.auto}</b>/<b style="color:var(--review)">${t.review}</b>/<span>${t.unmatched}</span></div>
      </div>`;
    li.onclick = () => {
      S.viewRun = r.run_id; S.tab = 'all';
      renderRuns(); renderRunSelect(); renderResults();
    };
    list.appendChild(li);
  }
}

export function renderRunSelect() {
  const sel = $('#runSelect');
  sel.innerHTML = '';
  if (!S.runs.length) { sel.innerHTML = '<option>no runs</option>'; return; }
  for (const r of S.runs) {
    const o = document.createElement('option');
    o.value = r.run_id;
    o.textContent = runTitle(r) + (r.label ? ` · ${r.label}` : '') +
                    ` · ${r.totals.auto}A/${r.totals.review}R`;
    sel.appendChild(o);
  }
  sel.value = S.viewRun || (S.runs.find(r => r.totals.spines) || S.runs[0]).run_id;
  sel.onchange = () => {
    S.viewRun = sel.value; S.tab = 'all';
    renderRuns(); renderResults();
  };
}
