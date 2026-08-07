// App shell + hash router for the mock.
//   #/library[?author=…]   #/map[/<shelfId>]   #/capture   #/settings
//   #/book/<id>            full-page book, deep-linkable, returns to previous
import { t, lang, setLang, isRtl } from './i18n.js';
import { esc, $, h } from './ui.js';
import * as libraryView from './library.js';
import * as mapView from './map.js';
import * as captureView from './capture.js';
import * as settingsView from './settings.js';
import { openDrawer, closeDrawer, isDrawerOpen, renderBookPage, wireDetail } from './book.js';

const TABS = [
  ['library',  'tab_library',  '📚'],
  ['map',      'tab_shelves',  '🗺'],
  ['capture',  'tab_capture',  '📷'],
  ['settings', 'tab_settings', '⚙'],
];

let lastListHash = '#/library';

function chrome() {
  document.documentElement.lang = lang;
  document.documentElement.dir = isRtl() ? 'rtl' : 'ltr';
  $('#appbar').innerHTML = `
    <div class="brand"><span class="dot"></span>${esc(t('app'))}</div>
    <button class="libpick">🏠<span class="libname"> ${esc(lang === 'he' ? 'משפחת מלין' : 'The Malin family')} ⌄</span></button>
    <div class="nav">
      ${TABS.map(([id, key]) => `<button data-tab="${id}">${esc(t(key))}${id === 'capture' ? `<span class="pip">3</span>` : ''}</button>`).join('')}
    </div>
    <div class="spacer"></div>
    <div class="langtog">
      <button data-lang="he" class="${lang === 'he' ? 'on' : ''}">עב</button>
      <button data-lang="en" class="${lang === 'en' ? 'on' : ''}">EN</button>
    </div>
    <button class="iconbtn" data-tab="settings">⚙</button>`;
  $('#botnav').innerHTML = TABS.map(([id, key, ic]) =>
    `<button data-tab="${id}"><span class="ic">${ic}</span>${esc(t(key))}</button>`).join('');
}

function markTab(name) {
  document.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
}

function route() {
  const hash = location.hash || '#/library';
  const [pathPart, query] = hash.replace(/^#\/?/, '').split('?');
  const [path, arg] = pathPart.split('/');

  if (path === 'book') {
    markTab('');
    ensure('book').innerHTML = renderBookPage(arg, lastListHash);
    window.scrollTo(0, 0);
    return;
  }
  lastListHash = hash;

  if (path === 'map') {
    markTab('map');
    if (arg) mapView.selectShelf(arg);
    mapView.render(ensure('map'));
  } else if (path === 'capture') {
    markTab('capture'); captureView.render(ensure('capture'));
  } else if (path === 'settings') {
    markTab('settings'); settingsView.render(ensure('settings'));
  } else {
    markTab('library');
    libraryView.setAuthorFilter(new URLSearchParams(query || '').get('author'));
    libraryView.render(ensure('library'));
  }
  window.scrollTo(0, 0);
}

/** Views cache their event wiring on the mount node; swap the node when the
    view changes so a stale view's listeners never see another view's DOM. */
function ensure(name) {
  let mount = $('#view');
  if (mount.dataset.page !== name) {
    const fresh = h(`<div id="view" data-page="${name}"></div>`);
    mount.replaceWith(fresh);
    mount = fresh;
  }
  return mount;
}

function go(hash) { location.hash = hash; }

function init() {
  chrome();
  route();

  document.body.addEventListener('click', e => {
    const l = e.target.closest('[data-lang]');
    if (l) { setLang(l.dataset.lang); location.reload(); return; }
    const tb = e.target.closest('[data-tab]');
    if (tb && tb.dataset.tab) return go('#/' + tb.dataset.tab);
    const g = e.target.closest('[data-go]');
    if (g) return go(g.dataset.go);
  });

  $('#scrim').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && isDrawerOpen()) closeDrawer(); });

  wireDetail($('#drawer'), { onNav: go });
  wireDetail($('#viewhost'), { onNav: go });

  window.addEventListener('hashchange', route);
  // an edit in the drawer or on the book page repaints whatever list is behind it
  window.addEventListener('book:changed', () => rerenderCurrent($('#view')));
}

function rerenderCurrent(mount) {
  ({ library: libraryView, map: mapView, capture: captureView, settings: settingsView }[mount.dataset.page])?.render(mount);
}

init();
