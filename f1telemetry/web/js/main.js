import { api, applyTheme, h, state } from './util.js';
import * as live from './views/live.js';
import * as sessions from './views/sessions.js';
import * as session from './views/session.js';
import * as analysis from './views/analysis.js';
import * as workstation from './views/workstation.js';
import * as tracks from './views/tracks.js';
import * as setups from './views/setups.js';
import * as stats from './views/stats.js';
import * as settings from './views/settings.js';
import * as career from './views/career.js';
import * as coach from './views/coach.js';
import * as rig from './views/rig.js';
import * as guide from './views/guide.js';

const routes = {
  live, sessions, session, career, analysis, workstation, coach, tracks, track: tracks, setups, stats, settings, rig, guide,
};
const navFor = { session: 'sessions', track: 'tracks' };
let cleanup = null;
let token = 0;

function parseHash() {
  const raw = location.hash.slice(1) || '/live';
  const [path, qs] = raw.split('?');
  const parts = path.split('/').filter(Boolean);
  return { name: parts[0] || 'live', arg: parts[1], query: Object.fromEntries(new URLSearchParams(qs || '')) };
}

async function route() {
  const my = ++token;
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  const { name, arg, query } = parseHash();
  const view = routes[name] ? name : 'live';
  for (const a of document.querySelectorAll('#nav a')) a.classList.toggle('active', a.dataset.route === (navFor[view] || view));
  const root = document.getElementById('view');
  root.innerHTML = '';
  const container = h('div');
  root.append(container);
  try {
    const fn = await routes[view].mount(container, arg, query, name);
    if (my !== token) { if (fn) fn(); container.remove(); return; }
    cleanup = fn || null;
  } catch (e) {
    console.error(e);
    if (my === token) container.append(h('div', { class: 'card empty' }, h('h3', {}, 'Something went wrong'), String(e.message || e)));
  }
  if (my === token) window.scrollTo(0, 0);
}

async function pollStatus() {
  const pill = document.getElementById('conn');
  try {
    const s = await api('/status');
    state.status = s;
    pill.className = 'conn';
    let txt;
    if (s.udp_error) { pill.classList.add('err'); txt = 'UDP port unavailable'; }
    else if (s.replay?.running) { pill.classList.add('demo'); txt = `Replay · ${s.replay.speed}×${s.replay.paused ? ' · paused' : ''}`; }
    else if (s.demo && s.connected) { pill.classList.add('demo'); txt = `Demo · ${Math.round(s.pps)} pkt/s`; }
    else if (s.connected) { pill.classList.add('on'); txt = `Receiving · ${Math.round(s.pps)} pkt/s`; }
    else txt = `Waiting for game · UDP ${s.udp_port}`;
    if (s.recording?.active) txt += ' · REC';
    pill.querySelector('.txt').textContent = txt;
  } catch {
    pill.className = 'conn err';
    pill.querySelector('.txt').textContent = 'App not running';
  }
}

async function boot() {
  try {
    [state.meta, state.settings] = await Promise.all([api('/meta'), api('/settings')]);
  } catch (e) {
    document.getElementById('view').append(h('div', { class: 'card empty' }, h('h3', {}, 'Cannot reach F1 Telemetry Hub'), 'Make sure the app window is still open.'));
    return;
  }
  applyTheme(state.settings.theme);
  matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => applyTheme(state.settings.theme));
  window.addEventListener('hashchange', route);
  route();
  pollStatus();
  setInterval(pollStatus, 2000);
}

boot();
