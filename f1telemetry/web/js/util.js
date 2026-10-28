// Shared helpers: API access, formatting, lookups, DOM helpers.

export const state = { meta: null, settings: null };

export async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: {} };
  if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    init.headers['Content-Type'] = 'application/json';
  }
  const r = await fetch('/api' + path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'html') el.innerHTML = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function toast(msg, ms = 2600) {
  const t = h('div', { class: 'toast' }, msg);
  document.body.append(t);
  setTimeout(() => t.remove(), ms);
}

// ------------------------------------------------------------------ formatting
export function fmtLap(ms) {
  if (!ms || ms <= 0) return '–';
  const m = Math.floor(ms / 60000);
  const s = (ms % 60000) / 1000;
  return m > 0 ? `${m}:${s.toFixed(3).padStart(6, '0')}` : s.toFixed(3);
}
export function fmtSector(ms) {
  if (!ms || ms <= 0) return '–';
  return ms >= 60000 ? fmtLap(ms) : (ms / 1000).toFixed(3);
}
export function fmtDelta(ms, digits = 3) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '–';
  const s = ms / 1000;
  return (s > 0 ? '+' : s < 0 ? '−' : '±') + Math.abs(s).toFixed(digits);
}
export function deltaClass(ms) {
  if (ms === null || ms === undefined) return '';
  return ms < 0 ? 'faster' : ms > 0 ? 'slower' : '';
}
export function fmtGap(ms) {
  if (!ms) return '–';
  return '+' + (ms / 1000).toFixed(3);
}
export function fmtDuration(sec) {
  if (!sec) return '0m';
  const hrs = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return hrs ? `${hrs}h ${m}m` : `${m}m`;
}
export function fmtClock(sec) {
  if (sec === null || sec === undefined) return '–';
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}
export function fmtDate(iso, withTime = true) {
  if (!iso) return '–';
  const d = new Date(iso);
  const opts = { day: 'numeric', month: 'short', year: 'numeric' };
  if (withTime) Object.assign(opts, { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleString(undefined, opts);
}
export const fmtNum = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
export function compact(v) {
  if (v === null || v === undefined) return '–';
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(1).replace(/\.0$/, '') + 'K';
  return String(Math.round(v));
}

// units
export const speedUnit = () => (state.settings?.speed_unit === 'mph' ? 'mph' : 'km/h');
export const speedVal = kmh => (kmh === null || kmh === undefined) ? null : (state.settings?.speed_unit === 'mph' ? kmh * 0.621371 : kmh);
export const fmtSpeed = (kmh, d = 0) => kmh === null || kmh === undefined ? '–' : fmtNum(speedVal(kmh), d);
export const tempUnit = () => (state.settings?.temp_unit === 'f' ? '°F' : '°C');
export const tempVal = c => (c === null || c === undefined) ? null : (state.settings?.temp_unit === 'f' ? c * 9 / 5 + 32 : c);
export const fmtTemp = (c, unit = true) => c === null || c === undefined ? '–' : Math.round(tempVal(c)) + (unit ? tempUnit() : '');

// ------------------------------------------------------------------ lookups
export const trackName = id => state.meta?.tracks?.[id] ?? (id === null || id === undefined ? 'Unknown track' : `Track ${id}`);
export const sessionTypeName = id => state.meta?.session_types?.[id] ?? 'Session';
export const teamName = id => state.meta?.teams?.[id] ?? (id === null || id === undefined ? '' : `Team ${id}`);
export const teamColour = id => state.meta?.team_colours?.[id] ?? '#9aa0a6';
export const weatherName = id => state.meta?.weather?.[id] ?? '–';
export const CATEGORY_NAMES = { race: 'Race', qualifying: 'Qualifying', practice: 'Practice', time_trial: 'Time Trial', other: 'Other' };
export const WHEELS = ['RL', 'RR', 'FL', 'FR'];
// Display order: front axle first, like looking down at the car.
export const WHEEL_LAYOUT = [2, 3, 0, 1];

export function tyreLetter(visual) {
  const n = state.meta?.visual_compounds?.[visual] || '';
  if (!n) return '?';
  if (n === 'Super Soft') return 'S';
  return n[0].toUpperCase();
}
export function tyreBadge(visual, size = '') {
  const l = tyreLetter(visual);
  const name = state.meta?.visual_compounds?.[visual] || 'Unknown';
  return h('span', { class: `tyre ${l} ${size}`, title: name }, l);
}
export function teamChip(teamId) {
  return h('span', { class: 'team-dot', style: { background: teamColour(teamId) }, title: teamName(teamId) });
}

// Categorical series colours (validated order; max three laps compared at once).
export function seriesColour(i) {
  const css = getComputedStyle(document.documentElement);
  return css.getPropertyValue(`--s${(i % 8) + 1}`).trim();
}
export const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function tyreTempState(t) {
  if (t === null || t === undefined) return '';
  if (t < 80) return 'state-cold';
  if (t <= 105) return 'state-ok';
  if (t <= 115) return 'state-hot';
  return 'state-crit';
}
export function damageColour(pct) {
  if (!pct) return cssVar('--surface-3');
  if (pct < 20) return cssVar('--warn');
  if (pct < 50) return cssVar('--serious');
  return cssVar('--critical');
}

export function stddev(arr) {
  if (arr.length < 2) return null;
  const m = arr.reduce((a, b) => a + b, 0) / arr.length;
  return Math.sqrt(arr.reduce((a, b) => a + (b - m) ** 2, 0) / (arr.length - 1));
}

export function applyTheme(theme) {
  let t = theme || 'dark';
  if (t === 'system') t = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
}
