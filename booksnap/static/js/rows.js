/* ---------------- results rows: markup only, no wiring ---------------------
   A factory rather than loose functions: every builder here needs the same
   two things (the run being viewed and this run's review decisions), and
   threading them through eight signatures obscured what the markup actually
   says. Callers get back pure string builders; results.js does the wiring. */
import { escapeHtml } from './dom.js';
import { S } from './state.js';

export function rowBuilders(run, decisions) {
  const cropUrl = f => `/api/runs/${run.run_id}/crops/${encodeURIComponent(f.spine_id)}`;

  // review controls per claim: ✓ approve · ✗ wrong (ignore) · ⟳ find better.
  // AUTO claims are already in the library ("auto"); ✗ removes them.
  const reviewCell = f => {
    if (!f.title) return '';
    const d = decisions[f.spine_id];
    const sp = escapeHtml(f.spine_id);
    if (d && (d.action === 'approve' || d.action === 'replace' || d.action === 'manual_add')) {
      // (the corrected title is the row's headline — see `effective` below;
      // this cell only carries the state badge and the actions)
      // a confirmed row stays editable: a typo noticed after approving used
      // to need undo-then-fix (owner feedback)
      return `<span class="badge b-AUTO" title="confirmed in library">✓ library</span>
        <button class="linkish rv" data-a="edit" data-spine="${sp}">✎ fix details</button>
        <button class="linkish rv" data-a="reject_ignore" data-spine="${sp}">undo</button>`;
    }
    if (d && d.action === 'reject_ignore') {
      return `<span class="badge b-WRONG">✗ marked wrong</span>
        <button class="linkish rv" data-a="alts" data-spine="${sp}">find better</button>
        <button class="linkish rv" data-a="edit" data-spine="${sp}">✎ fix details</button>
        <button class="linkish rv" data-a="clear" data-spine="${sp}"
                title="mis-click? return to undecided (does not re-add to library)">undo</button>`;
    }
    // no "auto ✓" chip here: the tier badge right above already says AUTO,
    // and a second green chip next to ✓/✗ read as a third state (owner
    // feedback). AUTO rows are library-absorbed silently; ✗ removes.
    return `
      <button class="linkish rv" data-a="approve" data-spine="${sp}">✓ approve</button>
      <button class="linkish rv" data-a="reject_ignore" data-spine="${sp}">✗ wrong</button>
      <button class="linkish rv" data-a="alts" data-spine="${sp}">⟳ find better</button>
      <button class="linkish rv" data-a="edit" data-spine="${sp}">✎ fix details</button>`;
  };

  // a claim the owner marked wrong must READ as wrong: the tier badge keeps
  // its text (you still see it WAS an AUTO) but turns red, and no green
  // appears anywhere on the row — a rejected row wearing a green badge
  // looked like a confirmed book (owner feedback, run 18)
  const isRejected = f => (decisions[f.spine_id] || {}).action === 'reject_ignore';
  // "replace" is the only decision that CHANGES the book (via ✎ fix details
  // or ⟳ find better) — flag it beside the tier so an edited row is
  // distinguishable from an untouched one at a glance
  const isEdited = f => (decisions[f.spine_id] || {}).action === 'replace';
  // What this row IS, now: once a decision approves or rewrites a claim, the
  // library holds the decision's text, so that is the row's headline. The
  // run's original claim stays visible underneath as "was …" — it is the
  // immutable record, but it is history, not the answer (owner feedback: a
  // row fixed to "יער דנקטון חלק א'" still read "יער דנקטון").
  const effective = f => {
    const d = decisions[f.spine_id];
    if (d && ['approve', 'replace', 'manual_add'].includes(d.action) && d.title) {
      return { title: d.title, author: d.author || '',
               changed: d.title !== f.title || (d.author || '') !== (f.author || '') };
    }
    return { title: f.title, author: f.author || '', changed: false };
  };
  const tierBadge = f => `<div style="display:flex;gap:4px;align-items:center">${
    isRejected(f)
      ? `<span class="badge b-WRONG" title="marked wrong">${f.tier || 'none'}</span>`
      : `<span class="badge b-${f.tier || 'none'}">${f.tier || 'none'}</span>`}${
    isEdited(f) ? '<span class="badge b-EDIT" title="title/author changed by hand">✎ edited</span>' : ''
    }</div>`;

  const rowHtml = f => `
    <div class="row${isRejected(f) ? ' rejected' : ''}" data-spine="${escapeHtml(f.spine_id)}">
      <img src="${cropUrl(f)}" alt="" loading="lazy"
           onerror="this.style.visibility='hidden'"
           onclick="showViewer('${cropUrl(f)}')" style="cursor:zoom-in">
      <div style="flex:1;min-width:0">
        ${f.title
          ? `<div class="title rtl">${escapeHtml(effective(f).title)}</div>
             <div class="ocr rtl">${escapeHtml(effective(f).author)}</div>
             ${effective(f).changed
                ? `<div class="ocr rtl" title="what this run matched before you corrected it">was: ${
                    escapeHtml(f.title)}${f.author ? ` — ${escapeHtml(f.author)}` : ''}</div>`
                : ''}`
          : '<div class="muted">— no match —</div>'}
        <div class="ocr rtl" title="raw OCR">${escapeHtml(f.ocr_text || '')}</div>
        <div class="ocr mono" title="${escapeHtml(f.spine_id)}">b${f.band}·s${
          String(f.index).padStart(2, '0')}${
          f.rotation ? ` · ${f.rotation}` : ''}${
          f.ms ? ` · ${(f.ms / 1000).toFixed(1)}s` : ''}${
          f.ocr_score ? ` · score ${f.ocr_score}` : ''}${
          S.tab === 'all' ? ` · ${escapeHtml(f.image_name)}` : ''}</div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex:none;max-width:170px">
        ${tierBadge(f)}
        <button class="linkish why" data-spine="${escapeHtml(f.spine_id)}">why?</button>
        ${reviewCell(f)}
      </div>
    </div>
    <div class="why-box" id="why-${escapeHtml(f.spine_id)}" style="display:none"></div>
    <div class="why-box" id="alts-${escapeHtml(f.spine_id)}" style="display:none"></div>`;

  // bulk-approve eligibility: AUTO rows the owner has NOT decided on — a
  // claim marked wrong must never ride along with an approve-all, and the
  // button's count is exactly the set the click will approve
  const bulkable = g => g.rows.filter(
    f => f.tier === 'AUTO' && f.title && !decisions[f.spine_id]);

  // books added by hand for this shelf render as their own rows, so the
  // addition is visible in place instead of only in the library count
  // (a 'replace' keeps the shelf: editing a hand-added book must not orphan it)
  const manualRows = g => Object.entries(decisions)
    .filter(([, d]) => ['manual_add', 'replace'].includes(d.action)
                       && d.image === g.name)
    .map(([sid, d]) => `
    <div class="row" data-spine="${escapeHtml(sid)}">
      <div style="flex:1;min-width:0">
        <div class="title rtl">${escapeHtml(d.title)}</div>
        <div class="ocr rtl">${escapeHtml(d.author || '')}</div>
        <div class="ocr">added by hand — no spine crop</div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex:none;max-width:170px">
        <div style="display:flex;gap:4px;align-items:center">
          <span class="badge b-MANUAL" title="added manually to this shelf">+ manual</span>
          ${d.action === 'replace'
            ? '<span class="badge b-EDIT" title="title/author changed by hand">✎ edited</span>' : ''}
        </div>
        <span class="badge b-AUTO" title="confirmed in library">✓ library</span>
        <button class="linkish man-ed" data-sid="${escapeHtml(sid)}"
                data-t="${escapeHtml(d.title)}" data-a="${escapeHtml(d.author || '')}">✎ fix details</button>
        <button class="linkish man-rm" data-sid="${escapeHtml(sid)}"
                data-t="${escapeHtml(d.title)}" data-a="${escapeHtml(d.author || '')}">✕ remove</button>
      </div>
    </div>
    <div class="why-box" id="alts-${escapeHtml(sid)}" style="display:none"></div>`).join('');

  const groupFooter = (g, gi) => {
    const autos = bulkable(g);
    return `
    <div class="row" data-footer="${escapeHtml(g.name)}" style="align-items:center;gap:8px">
      <div style="flex:1;display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <span class="img-sub" style="flex-basis:100%">${escapeHtml(g.name)}</span>
        <input type="text" class="rtl miss-t" placeholder="search this run, or add — title"
               data-img="${escapeHtml(g.name)}" value="${escapeHtml(S.missQueries[g.name] || '')}"
               style="flex:2;min-width:130px">
        <input type="text" class="rtl miss-a authorbox" placeholder="author (optional)" style="flex:1;min-width:100px">
        <button class="miss-add" data-img="${escapeHtml(g.name)}">+ add to library</button>
        ${autos.length ? `<button class="bulk-ok" data-g="${gi}">✓ approve all auto (${autos.length})</button>` : ''}
        <div class="miss-hint" style="flex-basis:100%"></div>
      </div>
    </div>`;
  };

  return { rowHtml, manualRows, groupFooter, bulkable };
}

/* rows come ordered per image — group them so each shelf gets its own
   footer: add-a-missing-book + bulk-approve for that shelf's AUTO rows */
export function groupByImage(rows) {
  const groups = [];
  for (const f of rows) {
    const g = groups[groups.length - 1];
    if (!g || g.name !== f.image_name) groups.push({ name: f.image_name, rows: [f] });
    else g.rows.push(f);
  }
  return groups;
}
