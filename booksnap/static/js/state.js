/* Shared mutable UI state.
   One exported object rather than a set of exported `let`s: ES module bindings
   are read-only for importers, so a plain `export let images` could be read
   everywhere but reassigned only inside this file. Fields on an object can be
   written from wherever the change actually happens. */
export const S = {
  images: [],
  runs: [],
  selected: new Set(),
  viewRun: null,        // run_id being viewed, null = latest
  tab: 'all',
  polling: null,
  // per-shelf "is it already here?" queries, kept across re-renders so an
  // approve/reject elsewhere doesn't wipe what you were checking
  missQueries: {},
  libAuthors: [],       // confirmed-library authors, for author autocomplete
};

/* the footnote under the Run button must describe the SELECTED mode — the
   "~10s per spine" text only applies to the Tesseract spines path */
export const MODE_HINTS = {
  spines: '~10s per spine. Stopping keeps every spine already read.',
  fullpage: 'One Vision call per photo, then each found title is checked ' +
            'against the catalog. Stopping keeps finished images.',
  llmpage: 'Claude reads each photo in parts (~1 min), then each found ' +
           'title is checked against the catalog. Stopping keeps finished images.',
};
