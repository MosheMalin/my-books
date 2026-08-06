/* ---------------- entry point ----------------------------------------------
   Reads like a table of contents: wire each panel, then ask the server what
   it can actually do, then paint. Loaded as <script type="module">, which is
   deferred by definition, so the DOM is complete before any of this runs. */
import { $ } from './dom.js';
import { api } from './api.js';
import { refresh } from './refresh.js';
import { initImages } from './images.js';
import { initJob, pollJob, updateModeHint } from './job.js';
import { initResults } from './results.js';

/* Disable a processing mode the server cannot run, and say why on hover. */
function disableMode(value, why) {
  const r = document.querySelector(`input[name=mode][value="${value}"]`);
  if (!r) return null;
  r.disabled = true;
  r.closest('.mode-opt').title = why;
  r.closest('.mode-opt').style.opacity = .5;
  return r;
}

async function showHealth() {
  const h = await api('/api/health');
  const cv = h.code_version || {};
  const cat = h.catalog_backend === 'nli'
    ? `catalog: NLI${h.nli_key_set ? '' : ' ⚠ no key'}`
    : (h.catalog_exists ? `catalog: ${h.catalog.split(/[\\/]/).pop()}`
                        : `⚠ catalog not found: ${h.catalog}`);
  $('#health').textContent = cat +
    (h.fallback && h.fallback !== 'none' ? ` · vision: on` : ' · vision: off') +
    (cv.sha ? ` · ${cv.sha}${cv.dirty ? '+dirty' : ''}` : '');
  // fullpage needs Vision. Only disable when health *positively* reports it
  // off — an older/unknown response must not silently lock the option out.
  if (h.fallback === 'none')
    disableMode('fullpage', 'needs BOOKSNAP_FALLBACK=google_vision');
  if (h.lan_url) {
    $('#phoneUrl').textContent = h.lan_url;
    $('#phoneHint').style.display = '';
  }
  // same only-when-positively-off rule for llmpage; if the default (llm)
  // is unavailable, fall back to the free spines mode
  if (h.anthropic_key_set === false) {
    const r = disableMode('llmpage', 'needs ANTHROPIC_API_KEY in .env');
    if (r && r.checked) {
      document.querySelector('input[name=mode][value=spines]').checked = true;
      updateModeHint();
    }
  }
}

initImages();
initJob();
initResults();
$('#viewer').onclick = () => $('#viewer').close();

try { await showHealth(); } catch {}
await refresh();
await pollJob();          // reattach to a run already in progress
