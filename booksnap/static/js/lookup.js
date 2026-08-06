/* ---------------- the shelf footer's search/add box ------------------------
   "did I miss it?" — the same box that adds a book first tells you whether
   this run already found it, read it without matching, or the library
   already holds it. Typing is the query; nothing is added until you click. */
import { escapeHtml, cssEsc, keepInPlace } from './dom.js';
import { api, jsonReq } from './api.js';
import { S } from './state.js';
import { renderResults } from './results.js';

export function wireLookupBoxes(box, run) {
  box.querySelectorAll('input.miss-t').forEach(inp => {
    const hint = inp.closest('.row').querySelector('.miss-hint');
    let timer = null, seq = 0;
    const render = (r, strong) => {
      const where = c => c.band === null ? escapeHtml(c.image_name || '')
        : `${escapeHtml(c.image_name || '')} b${c.band}·s${
            String(c.index).padStart(2, '0')}`;
      hint.innerHTML = r.matches.length ? r.matches.map(c => {
        const hit = c.sim >= strong;
        // link only when that row is on screen (another shelf's tab isn't)
        const here = document.querySelector(`.row[data-spine="${c.spine_id}"]`);
        const loc = here ? `<a href="#" class="hint-jump" data-spine="${
          escapeHtml(c.spine_id)}">${where(c)}</a>` : where(c);
        return `<span class="${hit ? 'hint-ok' : 'hint-near'}">${
          hit ? '✓ already listed' : `≈ similar (${c.sim}%)`}</span> ${
          escapeHtml(c.title)}${c.author ? ' — ' + escapeHtml(c.author) : ''}
          <span class="ocr">· ${loc}${c.state ? ' · ' + escapeHtml(c.state) : ''}</span>`;
      }).join('<br>')
        : '<span class="hint-miss">not in this shelf list — add it</span>';
      hint.querySelectorAll('a.hint-jump').forEach(a => {
        a.onclick = ev => {
          ev.preventDefault();
          const row = document.querySelector(
            `.row[data-spine="${a.dataset.spine}"]`);
          if (!row) return;
          row.scrollIntoView({ block: 'center', behavior: 'smooth' });
          row.classList.remove('flash');
          void row.offsetWidth;               // restart the animation
          row.classList.add('flash');
        };
      });
    };
    const search = (delay = 280) => {
      clearTimeout(timer);
      const q = inp.value.trim();
      S.missQueries[inp.dataset.img] = q;
      if (q.length < 2) { hint.innerHTML = ''; return; }
      timer = setTimeout(async () => {
        const mine = ++seq;                    // ignore out-of-order replies
        hint.innerHTML = '<span class="ocr">searching…</span>';
        try {
          const r = await api(`/api/runs/${run.run_id}/lookup?q=${
            encodeURIComponent(q)}`);
          if (mine === seq) render(r, r.strong);
        } catch { if (mine === seq) hint.innerHTML = ''; }
      }, delay);
    };
    inp.oninput = () => search();
    // a query restored after a re-render should show its answer again
    if (inp.value.trim().length >= 2) search(0);
  });

  box.querySelectorAll('button.miss-add').forEach(b => {
    b.onclick = async () => {
      const wrap = b.closest('.row');
      const title = wrap.querySelector('.miss-t').value.trim();
      if (!title) return;
      await api('/api/review', jsonReq('POST', {
        run_id: run.run_id, spine_id: `manual-${Date.now()}`,
        action: 'manual_add', title, image: b.dataset.img,
        author: wrap.querySelector('.miss-a').value.trim() }));
      delete S.missQueries[b.dataset.img];     // question answered by adding
      await keepInPlace(`[data-footer="${cssEsc(b.dataset.img)}"]`, renderResults);
      // straight back to the search/add box: adding one missing book usually
      // means adding the next one too
      const next = document.querySelector(
        `input.miss-t[data-img="${cssEsc(b.dataset.img)}"]`);
      if (next) next.focus();
    };
  });
}
