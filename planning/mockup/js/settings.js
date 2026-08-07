// Settings — a placeholder inventory of what the vision implies belongs here.
// Nothing is decided; this exists so the shape of the menu can be argued about.
import { t, lang, setLang } from './i18n.js';
import { esc, toast } from './ui.js';

const rows = () => [
  [t('set_lib'), [
    [t('set_members'), 'Viewer / Editor / Admin · invites (VISION §4.2)', 'nav'],
    [t('set_places'), 'Home / Office / Parents\' · bookcases · shelves · depth (§5.7, §7)', 'nav'],
    [t('set_export'), 'CSV / JSON — the honest answer to lock-in (§6)', 'nav'],
  ]],
  [t('set_reading'), [
    [t('mode'), t('mode_llm') + ' — ' + t('mode_llm_d'), 'select'],
    [t('set_keys'), 'Free quota on our key → bring your own (§3, §10)', 'nav'],
    ['Auto-approve AUTO', 'Absorb AUTO claims without asking (library.py does this today)', 'switch-on'],
  ]],
  [t('set_privacy'), [
    [t('set_shared_db'), t('set_shared_d'), 'switch-on'],
    ['Correction corpus', 'Sampled corrections as a rule anchor — separate opt-in (§9.2)', 'switch-off'],
    [t('set_photos'), 'Originals + crops kept, user-purgeable (§3)', 'nav'],
  ]],
  [t('set_audit'), [
    [t('open_audit'), t('set_audit_d'), 'nav'],
  ]],
];

export function render(mount) {
  mount.innerHTML = `<div class="setgrid">
    ${rows().map(([title, items]) => `
      <div class="panel"><h3>${esc(title)}</h3><div class="body">
        ${items.map(([n, d, kind]) => `<div class="setrow">
          <div class="m"><div class="n">${esc(n)}</div><div class="d">${esc(d)}</div></div>
          ${kind === 'nav' ? `<button class="btn sm ghost">›</button>`
            : kind === 'select' ? `<button class="btn sm ghost">⌄</button>`
            : `<button class="sw ${kind === 'switch-on' ? 'on' : ''}"></button>`}
        </div>`).join('')}
      </div></div>`).join('')}

    <div class="panel"><h3>${esc(t('set_lang'))}</h3><div class="body">
      <div class="chiprow">
        <button class="chip ${lang === 'he' ? 'on' : ''}" data-lang="he">עברית (RTL)</button>
        <button class="chip ${lang === 'en' ? 'on' : ''}" data-lang="en">English (LTR)</button>
      </div>
      <div class="tiny muted" style="margin-top:8px">${esc(t('mock_note'))}</div>
    </div></div>
  </div>`;

  if (mount._wired) return;
  mount._wired = true;
  mount.addEventListener('click', e => {
    const l = e.target.closest('[data-lang]');
    if (l) { setLang(l.dataset.lang); location.reload(); return; }
    const s = e.target.closest('.sw'); if (s) return s.classList.toggle('on');
    toast(t('mock_note'));
  });
}
