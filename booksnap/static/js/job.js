/* ---------------- run + stop + progress polling ---------------- */
import { $ } from './dom.js';
import { api, jsonReq } from './api.js';
import { S, MODE_HINTS } from './state.js';
import { refresh } from './refresh.js';
import { renderImages } from './images.js';

export function updateModeHint() {
  const m = document.querySelector('input[name=mode]:checked');
  $('#modeHint').textContent = MODE_HINTS[m ? m.value : 'spines'];
}

export function startPolling() {
  if (!S.polling) { S.polling = setInterval(pollJob, 1200); pollJob(); }
}

export async function pollJob() {
  let job;
  try { job = await api('/api/job'); } catch { return; }
  const running = job.state === 'running';
  $('#runBtn').style.display = running ? 'none' : '';
  $('#stopBtn').style.display = running ? '' : 'none';
  $('#stopBtn').disabled = !!job.stopping;
  $('#stopBtn').textContent = job.stopping ? 'Stopping after this spine…' : 'Stop';
  $('#progress').style.display = running ? '' : 'none';

  if (running) {
    const done = job.done || 0, tot = job.spines || 0;
    // One continuous bar. LLM/page runs have two long phases per image —
    // reading the photo (tiles), then verifying each found book against the
    // catalog — weighted 50/50 within the image; the bar then advances
    // across images, never restarting from zero.
    let frac = tot ? done / tot : 0, msg = tot ? `spine ${done}/${tot}` : 'segmenting…';
    if (job.phase === 'reading') {
      frac = 0.5 * (tot ? done / tot : 0);
      msg = `reading the photo (part ${done}/${tot})`;
    } else if (job.phase === 'matching') {
      frac = 0.5 + 0.5 * (tot ? done / tot : 0);
      msg = `checking ${tot} found titles against the catalog (${done}/${tot})`;
    } else if (job.phase === 'ocr') {
      msg = `reading block ${done}/${tot}`;
    }
    const nImg = job.image_total || 1, iImg = Math.max(1, job.image_no || 1);
    const overall = ((iImg - 1) + frac) / nImg;
    $('#progText').textContent =
      `Image ${iImg}/${nImg} — ${job.name || ''} · ${msg}`;
    $('#progBar').style.width = `${Math.round(overall * 100)}%`;
    S.images = (await api('/api/images')).images;
    renderImages();
  } else {
    clearInterval(S.polling); S.polling = null;
    await refresh();
  }
}

export function initJob() {
  $('#runBtn').onclick = async () => {
    if (!S.selected.size) return alert('Select at least one picture.');
    try {
      const mode = document.querySelector('input[name=mode]:checked').value;
      const r = await api('/api/run', jsonReq('POST', { image_ids: [...S.selected], mode }));
      S.viewRun = r.run_id;
      startPolling();
    } catch (e) { alert('Could not start: ' + e.message); }
  };

  $('#stopBtn').onclick = async () => {
    $('#stopBtn').disabled = true;
    try { await api('/api/stop', { method: 'POST' }); } catch (e) { alert(e.message); }
  };

  document.querySelectorAll('input[name=mode]')
    .forEach(r => r.addEventListener('change', updateModeHint));
  updateModeHint();
}
