/* The one "reload everything and repaint" entry point.
   Lives in its own module because almost every action module needs to call it
   after a mutation, and the render modules in turn need each other — keeping
   it separate from main.js stops the entry point being part of that cycle. */
import { api } from './api.js';
import { S } from './state.js';
import { renderImages } from './images.js';
import { renderRuns, renderRunSelect } from './runs.js';
import { renderResults } from './results.js';

export async function refresh() {
  const [images, runs] = await Promise.all([
    api('/api/images').then(d => d.images),
    api('/api/runs').then(d => d.runs),
  ]);
  S.images = images;
  S.runs = runs;
  const known = new Set(S.images.map(i => i.id));
  S.selected = new Set([...S.selected].filter(id => known.has(id)));
  if (S.viewRun && !S.runs.some(r => r.run_id === S.viewRun)) S.viewRun = null;
  renderImages(); renderRuns(); renderRunSelect(); await renderResults();
}
