/* ---------------- pictures: upload, list, selection ---------------- */
import { $, escapeHtml, showViewer } from './dom.js';
import { api } from './api.js';
import { S } from './state.js';
import { refresh } from './refresh.js';

async function upload(fileList) {
  const drop = $('#drop'), fileInput = $('#file');
  if (!fileList || !fileList.length) return;
  const fd = new FormData();
  for (const f of fileList) fd.append('files', f);
  drop.innerHTML = `<strong>Uploading ${fileList.length} file(s)…</strong>`;
  try {
    const res = await api('/api/images', { method: 'POST', body: fd });
    res.added.forEach(a => S.selected.add(a.id));
    if (res.rejected.length)
      alert('Skipped:\n' + res.rejected.map(r => `${r.name} — ${r.reason}`).join('\n'));
  } catch (e) { alert('Upload failed: ' + e.message); }
  drop.innerHTML = '<strong>Drop shelf photos here</strong><br>or click to choose files';
  drop.appendChild(fileInput);
  await refresh();
}

export function statusBadge(im) {
  if (im.status === 'running') return '<span class="badge b-REVIEW">running</span>';
  if (im.status === 'error')   return '<span class="badge b-none">error</span>';
  const s = im.summary;
  if (s && (im.status === 'done' || im.status === 'stopped'))
    return `${im.status === 'stopped' ? '<span class="badge b-REVIEW">stopped</span> ' : ''}
            <span class="badge b-AUTO">${s.auto} auto</span>
            <span class="badge b-REVIEW">${s.review} review</span>
            <span class="badge b-none">${s.unmatched} none</span>`;
  return '<span class="badge b-none">not processed</span>';
}

export function renderImages() {
  $('#imgCount').textContent = S.images.length ? `${S.images.length} loaded` : '';
  const list = $('#imgList');
  if (!S.images.length) { list.innerHTML = '<li class="empty">No pictures yet.</li>'; return; }
  list.innerHTML = '';
  for (const im of S.images) {
    const li = document.createElement('li');
    li.className = 'img-item' + (S.selected.has(im.id) ? ' sel' : '');
    li.innerHTML = `
      <input type="checkbox" ${S.selected.has(im.id) ? 'checked' : ''}>
      <img src="/api/images/${im.id}/thumb" alt="">
      <div class="img-meta">
        <div class="img-name" title="${escapeHtml(im.name)}">${escapeHtml(im.name)}</div>
        <div class="img-sub">${statusBadge(im)}</div>
        ${im.error ? `<div class="err">${escapeHtml(im.error)}</div>` : ''}
      </div>
      <button class="linkish" title="remove">✕</button>`;
    const cb = li.querySelector('input'), thumb = li.querySelector('img'),
          del = li.querySelector('button');
    cb.onchange = () => { cb.checked ? S.selected.add(im.id) : S.selected.delete(im.id); renderImages(); };
    thumb.onclick = e => { e.stopPropagation(); showViewer(`/api/images/${im.id}/full`); };
    del.onclick = async e => {
      e.stopPropagation();
      // no confirm() popup — it is silently suppressed in embedded browsers,
      // which made the ✕ appear dead. Two-click inline confirm instead.
      if (del.dataset.armed !== '1') {
        del.dataset.armed = '1';
        del.textContent = 'sure?';
        del.style.color = '#c0392b';
        setTimeout(() => {
          del.dataset.armed = '';
          del.textContent = '✕';
          del.style.color = '';
        }, 3000);
        return;
      }
      try { await api(`/api/images/${im.id}`, { method: 'DELETE' }); await refresh(); }
      catch (err) {
        del.textContent = 'error';
        del.title = err.message;
      }
    };
    li.onclick = e => { if (e.target !== cb) cb.click(); };
    list.appendChild(li);
  }
}

export function initImages() {
  const drop = $('#drop'), fileInput = $('#file');
  drop.onclick = () => fileInput.click();
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); upload(e.dataTransfer.files); };
  fileInput.onchange = () => { upload(fileInput.files); fileInput.value = ''; };

  $('#selAll').onclick  = () => { S.images.forEach(i => S.selected.add(i.id)); renderImages(); };
  $('#selNone').onclick = () => { S.selected.clear(); renderImages(); };
  $('#selNew').onclick  = () => {
    S.selected = new Set(S.images.filter(i => i.status !== 'done').map(i => i.id));
    renderImages();
  };
}
