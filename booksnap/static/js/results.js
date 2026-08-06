/* ---------------- results: fetch, paint, wire ------------------------------
   The orchestrator. Markup lives in rows.js/runhead.js, the footer's
   search-and-add in lookup.js, the per-row panels in review.js; what is left
   here is the sequence and the event wiring. */
import { $, escapeHtml, cssEsc, keepInPlace } from './dom.js';
import { api, jsonReq } from './api.js';
import { S } from './state.js';
import { clearAuthorPopups, attachAuthorComplete } from './autocomplete.js';
import { rowBuilders, groupByImage } from './rows.js';
import { renderRunHead } from './runhead.js';
import { wireLookupBoxes } from './lookup.js';
import { showEdit, showAlternatives, showWhy } from './review.js';

function renderTabs(run) {
  const tabs = $('#tabs');
  tabs.innerHTML = '';
  if (!run) return;
  const mk = (id, label) => {
    const b = document.createElement('button');
    b.className = 'tab' + (S.tab === id ? ' on' : '');
    b.textContent = label;
    b.onclick = () => { S.tab = id; renderResults(); };
    tabs.appendChild(b);
  };
  const ids = Object.keys(run.images || {});
  mk('all', `All images (${ids.length})`);
  ids.forEach(id => {
    const im = S.images.find(i => i.id === id);
    mk(id, im ? im.name : id);
  });
  if (S.tab !== 'all' && !ids.includes(S.tab)) S.tab = 'all';
}

function deltaEl(cur, prev, key, higherBetter = true) {
  if (!prev) return '';
  const d = cur[key] - (prev.totals[key] ?? 0);
  if (!d) return '';
  const good = higherBetter ? d > 0 : d < 0;
  return `<span class="delta ${good ? 'up' : 'down'}">${d > 0 ? '+' : ''}${d}</span>`;
}

export async function renderResults() {
  const q = new URLSearchParams();
  if (S.viewRun) q.set('run_id', S.viewRun);
  if (S.tab !== 'all') q.set('image_id', S.tab);
  const data = await api('/api/results?' + q);
  const run = data.run;

  if (!run) {
    $('#runHead').innerHTML = '';
    $('#stats').innerHTML = '';
    $('#tabs').innerHTML = '';
    $('#results').innerHTML = '<div class="empty">No runs yet — upload pictures and run the pipeline.</div>';
    return;
  }

  // previous run, for the delta line
  const idx = S.runs.findIndex(r => r.run_id === run.run_id);
  const prev = S.runs.slice(idx + 1).find(r => r.totals.spines);

  renderRunHead(run, prev);
  renderTabs(run);

  // review state for this run + the confirmed library (count + author list
  // for the light autocomplete on author inputs)
  let decisions = {}, libCount = null;
  try { decisions = (await api(`/api/runs/${run.run_id}/decisions`)).decisions || {}; } catch {}
  try {
    const L = await api('/api/library');
    libCount = L.count;
    S.libAuthors = [...new Set(L.books.map(b => b.author).filter(Boolean))].sort();
  } catch {}

  const t = data.totals;
  $('#stats').innerHTML = [
    ['spines', t.spines, null], ['AUTO', t.auto, 'auto'], ['review', t.review, 'review'],
    ['unmatched', t.unmatched, 'unmatched'], ['unique titles', t.unique_titles, null],
    ...(libCount === null ? [] : [['in library 📚', libCount, null]])
  ].map(([l, n, key]) => `
      <div class="stat">
        <div class="n">${n} ${key && S.tab === 'all'
          ? deltaEl(t, prev, key, key !== 'unmatched') : ''}</div>
        <div class="l">${l}</div>
      </div>`).join('');

  const box = $('#results');
  if (!t.spines) {
    box.innerHTML = '<div class="empty">This run produced no spines.</div>';
    return;
  }

  if ($('#uniqueOnly').checked) {
    box.innerHTML = data.unique_titles.map(u => `
      <div class="row"><div>
        <div class="title rtl">${escapeHtml(u.title)}</div>
        <div class="ocr rtl">${escapeHtml(u.author || '')}</div>
      </div></div>`).join('') || '<div class="empty">No titles found.</div>';
    return;
  }

  const onlyMatched = $('#onlyMatched').checked;
  const rows = data.found.filter(f => !onlyMatched || f.title);
  const { rowHtml, manualRows, groupFooter, bulkable } = rowBuilders(run, decisions);
  const groups = groupByImage(rows);

  clearAuthorPopups();              // popups outlive the inputs they anchor to
  box.innerHTML =
    groups.map((g, gi) => g.rows.map(rowHtml).join('') + manualRows(g)
                          + groupFooter(g, gi)).join('')
    || '<div class="empty">Nothing to show with this filter.</div>';
  box.querySelectorAll('input.authorbox').forEach(attachAuthorComplete);

  wireLookupBoxes(box, run);

  // a hand-added book is editable like any other row; showEdit only needs
  // {spine_id, title, author}, and the decision it writes keeps the shelf
  box.querySelectorAll('button.man-ed').forEach(b => {
    b.onclick = () => showEdit(run.run_id,
      { spine_id: b.dataset.sid, title: b.dataset.t, author: b.dataset.a },
      decisions[b.dataset.sid]);
  });
  // removing a hand-added book = reject it (deletes the library entry and
  // overwrites the manual_add decision, so the row disappears)
  box.querySelectorAll('button.man-rm').forEach(b => {
    b.onclick = async () => {
      await api('/api/review', jsonReq('POST', {
        run_id: run.run_id, spine_id: b.dataset.sid, action: 'reject_ignore',
        old: { title: b.dataset.t, author: b.dataset.a } }));
      await renderResults();
    };
  });
  box.querySelectorAll('button.bulk-ok').forEach(b => {
    b.onclick = async () => {
      b.disabled = true;
      // group looked up by the button's own index, not DOM position: a
      // shelf with nothing to approve renders no button, and positional
      // matching then approved the WRONG shelf's rows
      const g = groups[Number(b.dataset.g)];
      for (const f of bulkable(g)) {
        await api('/api/review', jsonReq('POST', {
          run_id: run.run_id, spine_id: f.spine_id, action: 'approve',
          title: f.title, author: f.author || '' }));
      }
      // every approved row loses buttons and shrinks, so the shelf's footer
      // used to jump far up the page — hold it where the eye left it
      await keepInPlace(`[data-footer="${cssEsc(g.name)}"]`, renderResults);
    };
  });

  box.querySelectorAll('button.why').forEach(b => {
    b.onclick = () => showWhy(run.run_id, b.dataset.spine, b);
  });
  box.querySelectorAll('button.rv').forEach(b => {
    const f = rows.find(r => r.spine_id === b.dataset.spine);
    b.onclick = async () => {
      if (b.dataset.a === 'alts') return showAlternatives(run.run_id, f, decisions);
      if (b.dataset.a === 'edit') return showEdit(run.run_id, f, decisions[f.spine_id]);
      const body = { run_id: run.run_id, spine_id: f.spine_id, action: b.dataset.a };
      if (b.dataset.a === 'approve') { body.title = f.title; body.author = f.author || ''; }
      if (b.dataset.a === 'reject_ignore') {
        const d = decisions[f.spine_id];   // undo of replace removes the replacement
        body.old = (d && d.title) ? { title: d.title, author: d.author || '' }
                                  : { title: f.title, author: f.author || '' };
      }
      await api('/api/review', jsonReq('POST', body));
      // the row's controls change height — keep it under the cursor
      await keepInPlace(`.row[data-spine="${cssEsc(f.spine_id)}"]`, renderResults);
    };
  });
}

export function initResults() {
  $('#onlyMatched').onchange = renderResults;
  $('#uniqueOnly').onchange = renderResults;
}
