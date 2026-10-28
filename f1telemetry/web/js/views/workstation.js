// Engineer's workstation: one dense screen per session. Lap traces and time deltas share one cursor with
// two track maps (coloured by gain / loss, speed, inputs or gear, and by car balance), the car's state at
// the cursor, balance by corner speed, the micro-sector timeline, the outing report and lap time evolution.
// On the session being driven it can follow along, moving to each new lap as it is completed.
import {
  api, h, fmtLap, fmtSector, fmtDelta, deltaClass, fmtDate, fmtNum, fmtSpeed, speedUnit, tempVal,
  trackName, sessionTypeName, seriesColour, cssVar, tyreBadge, tyreLetter, tyreTempState, WHEELS, WHEEL_LAYOUT,
} from '../util.js';
import { LineChart, SyncGroup, TrackMap, valueAt, showTip, hideTip, niceTicks } from '../charts.js';
import { CHANNELS, prepare } from './analysis.js';
import { guestLabel } from '../friends.js';

const PREFS = 'f1th.ws';
// trace channels offered, in order, with the workstation's own (compact) heights
const TRACES = { spd: 120, thr: 54, brk: 54, gear: 54, str: 62, rpm: 70, us: 84, slip: 58, ers: 58, glat: 70, glon: 70, ts: 70, bt: 70, fuel: 54, aero: 44, ot: 44 };
const DEFAULT_ON = ['spd', 'thr', 'brk', 'gear', 'str', 'us', 'slip'];
const COLOURINGS = [['gain', 'Gain / loss'], ['speed', 'Speed'], ['inputs', 'Inputs'], ['gear', 'Gear']];
const TYRE_VAR = { S: '--tyre-soft', M: '--tyre-medium', H: '--tyre-hard', I: '--tyre-inter', W: '--tyre-wet' };
const LIVE_POLL_MS = 3000;

function loadPrefs() {
  const d = { on: DEFAULT_ON, colour: 'gain' };
  try { return { ...d, ...JSON.parse(localStorage.getItem(PREFS) || '{}') }; } catch { return d; }
}
function savePrefs(p) { try { localStorage.setItem(PREFS, JSON.stringify(p)); } catch { /* storage blocked */ } }

// ------------------------------------------------------------------ colour helpers
function rgb(c) {
  c = (c || '').trim();
  if (c[0] === '#') {
    let x = c.slice(1);
    if (x.length === 3) x = [...x].map(ch => ch + ch).join('');
    const n = parseInt(x.slice(0, 6), 16);
    return [n >> 16 & 255, n >> 8 & 255, n & 255];
  }
  const m = c.match(/[\d.]+/g);
  return m ? m.slice(0, 3).map(Number) : [128, 128, 128];
}
const mix = (a, b, f) => { const A = rgb(a), B = rgb(b); return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * f)).join(',')})`; };
const q = (f, steps = 10) => Math.round(f * steps) / steps;  // quantised so the map draws runs of one colour
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
// one hue, dim to bright on the dark theme (bright to deep on the light one)
const ramp = f => document.documentElement.dataset.theme === 'light'
  ? `hsl(213 70% ${Math.round(82 - 52 * f)}%)` : `hsl(213 80% ${Math.round(26 + 56 * f)}%)`;

function nearest(xs, x) {
  let lo = 0, hi = xs.length - 1;
  if (hi < 0) return -1;
  if (x <= xs[0]) return 0;
  if (x >= xs[hi]) return hi;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
  return x - xs[lo] < xs[hi] - x ? lo : hi;
}
const has = arr => !!arr && arr.some(v => v !== null && v !== undefined);
const xFormat = v => v >= 1000 ? (v / 1000).toFixed(1) + ' km' : Math.round(v) + ' m';

// micro-sector boundaries, as the app stores them with each lap ("24:length:s2:s3")
function microBounds(key, len, s2, s3) {
  const m = /^(\d+):(\d+):(\d+):(\d+)$/.exec(key || '');
  if (m) [len, s2, s3] = [Number(m[2]), Number(m[3]), Number(m[4])];
  if (!(len > 500)) return null;
  if (!(s2 > 0 && s3 > s2 && s3 < len)) { s2 = len / 3; s3 = 2 * len / 3; }
  const out = [];
  for (const [a, b] of [[0, s2], [s2, s3], [s3, len]]) for (let i = 0; i < 8; i++) out.push(a + (b - a) * i / 8);
  out.push(len);
  return out;
}
function microTimes(L, bnds) {
  const ms = L.lap.micro?.ms;
  if (ms && ms.length === 24 && L.lap.micro.key === L.key) return ms;
  if (!L.p || !bnds) return null;
  const p = L.p, cross = bnds.map((b, i) => i === 0 ? (p.d[0] < 30 ? 0 : null)
    : i === bnds.length - 1 ? L.lap.lap_time_ms / 1000 : valueAt(p.d, p.t, b));
  return cross.slice(1).map((c, i) => c === null || cross[i] === null ? null : Math.round((c - cross[i]) * 1000));
}

// ------------------------------------------------------------------ balance by corner speed (scatter + means)
class BalancePlot {
  constructor(parent, height = 210) {
    this.box = h('div', { class: 'chart', style: { height: height + 'px' } });
    this.canvas = h('canvas');
    this.box.append(this.canvas);
    parent.append(this.box);
    this.series = [];
    this.hot = null;
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.box);
    this.canvas.addEventListener('mousemove', e => this._hover(e));
    this.canvas.addEventListener('mouseleave', () => { this.hot = null; hideTip(); this.draw(); });
  }
  destroy() { this.ro.disconnect(); this.box.remove(); hideTip(); }
  resize() {
    const r = this.box.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    this.w = Math.max(50, r.width); this.hgt = Math.max(50, r.height);
    this.canvas.width = Math.round(this.w * dpr); this.canvas.height = Math.round(this.hgt * dpr);
    this.draw();
  }
  // series: [{ name, color, pts: [[speed, deg]] }]; means per speed bin of width binW
  set(series, binW) {
    this.binW = binW;
    this.series = series.map(s => {
      const bins = new Map();
      for (const [x, y] of s.pts) { const b = Math.floor(x / binW); const o = bins.get(b) || { n: 0, sum: 0 }; o.n++; o.sum += y; bins.set(b, o); }
      const means = [...bins].filter(([, o]) => o.n >= 6).sort((a, b) => a[0] - b[0]).map(([b, o]) => ({ b, x: (b + 0.5) * binW, y: o.sum / o.n, n: o.n }));
      return { ...s, means };
    });
    const xs = this.series.flatMap(s => s.pts.map(p => p[0]));
    const ys = this.series.flatMap(s => s.pts.map(p => Math.abs(p[1]))).sort((a, b) => a - b);
    this.x0 = xs.length ? Math.floor(Math.min(...xs) / binW) * binW : 0;
    this.x1 = xs.length ? Math.ceil(Math.max(...xs) / binW) * binW : 1;
    this.ya = Math.max(1, Math.ceil(ys.length ? ys[Math.floor(ys.length * 0.97)] : 1));
    this.draw();
  }
  X(x) { return 40 + (x - this.x0) / (this.x1 - this.x0 || 1) * (this.w - 50); }
  Y(y) { return 10 + (1 - (y + this.ya) / (2 * this.ya)) * (this.hgt - 32); }
  draw() {
    if (!this.w) return;
    const ctx = this.canvas.getContext('2d'), dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, this.w, this.hgt);
    const muted = cssVar('--muted'), grid = cssVar('--grid'), axis = cssVar('--axis'), ring = cssVar('--surface');
    ctx.font = '11px system-ui, sans-serif'; ctx.lineWidth = 1;
    if (!this.series.some(s => s.pts.length)) {
      ctx.fillStyle = muted; ctx.textAlign = 'center'; ctx.fillText('No cornering samples with balance data', this.w / 2, this.hgt / 2);
      return;
    }
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (const v of niceTicks(-this.ya, this.ya, 4)) {
      const y = Math.round(this.Y(v)) + 0.5;
      ctx.strokeStyle = v === 0 ? axis : grid; ctx.beginPath(); ctx.moveTo(40, y); ctx.lineTo(this.w - 10, y); ctx.stroke();
      ctx.fillStyle = muted; ctx.fillText((v > 0 ? '+' : '') + v + '°', 34, y);
    }
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (const v of niceTicks(this.x0, this.x1, Math.max(2, Math.floor(this.w / 90)))) {
      const x = this.X(v); if (x < 40 || x > this.w - 10) continue;
      ctx.fillText(String(v), x, this.hgt - 18);
    }
    ctx.textAlign = 'left'; ctx.fillStyle = muted;
    ctx.fillText('Understeer', 44, 12);
    ctx.textBaseline = 'bottom'; ctx.fillText('Oversteer', 44, this.hgt - 24);
    ctx.textAlign = 'right'; ctx.fillText(speedUnit(), this.w - 10, this.hgt - 24);
    const clampY = y => clamp(y, -this.ya, this.ya);
    for (const s of [...this.series].reverse()) {  // first series on top
      ctx.fillStyle = s.color; ctx.globalAlpha = 0.22;
      for (const [x, y] of s.pts) { ctx.fillRect(this.X(x) - 1.2, this.Y(clampY(y)) - 1.2, 2.4, 2.4); }
      ctx.globalAlpha = 1;
    }
    for (const s of [...this.series].reverse()) {
      ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.beginPath();
      s.means.forEach((m, i) => { const X = this.X(m.x), Y = this.Y(clampY(m.y)); if (i) ctx.lineTo(X, Y); else ctx.moveTo(X, Y); });
      ctx.stroke();
      for (const m of s.means) {
        ctx.beginPath(); ctx.arc(this.X(m.x), this.Y(clampY(m.y)), this.hot === m.b ? 5.5 : 4, 0, Math.PI * 2);
        ctx.fillStyle = s.color; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = ring; ctx.stroke();
      }
    }
  }
  _hover(e) {
    const r = this.canvas.getBoundingClientRect(), px = e.clientX - r.left;
    const x = this.x0 + (px - 40) / (this.w - 50) * (this.x1 - this.x0);
    const b = Math.floor(x / this.binW);
    const rows = this.series.map(s => ({ s, m: s.means.find(m => m.b === b) })).filter(o => o.m);
    if (!rows.length) { if (this.hot !== null) { this.hot = null; this.draw(); } hideTip(); return; }
    if (this.hot !== b) { this.hot = b; this.draw(); }
    const word = y => Math.abs(y) < 0.1 ? 'neutral' : y > 0 ? 'understeer' : 'oversteer';
    showTip(`<b>${b * this.binW}–${(b + 1) * this.binW} ${speedUnit()}</b><br>` + rows.map(({ s, m }) =>
      `<span style="color:${s.color}">■</span> ${s.name}: ${Math.abs(m.y).toFixed(2)}° ${word(m.y)} <span style="opacity:.7">(${m.n} samples)</span>`).join('<br>'), e.clientX, e.clientY);
  }
}

// ------------------------------------------------------------------ page
export async function mount(root, arg, query) {
  document.body.classList.add('ws-wide');
  const cleanups = [() => document.body.classList.remove('ws-wide'), hideTip];
  const done = () => cleanups.forEach(fn => { try { fn(); } catch (e) { console.error(e); } });
  const prefs = loadPrefs();
  const status = await api('/status').catch(() => ({}));
  const sessions = await api('/sessions?limit=60').catch(() => []);
  const st = {
    sid: Number(query.session) || status.session_id || sessions[0]?.id || null,
    aId: Number(query.lap) || null,
    ref: query.ref ? Number(query.ref) : 'auto',
    follow: !query.lap,
  };
  root.classList.add('ws');
  if (!st.sid) {
    root.append(h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Workstation'))),
      h('div', { class: 'card empty' }, h('h3', {}, 'No sessions yet'), 'Drive a few laps (or run the demo from Settings): this page opens the session as soon as it starts.'));
    const wait = setInterval(async () => {
      const s = await api('/status').catch(() => null);
      if (s?.session_id) { clearInterval(wait); window.dispatchEvent(new HashChangeEvent('hashchange')); }
    }, LIVE_POLL_MS);
    cleanups.push(() => clearInterval(wait));
    return done;
  }

  const cache = new Map();  // lap id -> promise of { lap, cols, p } | null
  const tel = id => {
    if (!cache.has(id)) {
      cache.set(id, api(`/laps/${id}/telemetry`).then(r => (r.cols && r.cols.d?.length > 10 ? { lap: r.lap, cols: r.cols, p: prepare(r) } : null)).catch(() => null));
    }
    return cache.get(id);
  };

  const head = h('div', { class: 'page-head' });
  const toolbar = h('div', { class: 'ws-toolbar' });
  const body = h('div');
  const liveEl = h('div');
  root.append(head, toolbar, liveEl, body);
  let S = null, T = null, G = [], disposers = [], timer = null, lastSig = '', follower = null;
  cleanups.push(() => { disposers.forEach(fn => fn()); clearInterval(timer); follower?.stop(); });

  async function loadSession() {
    S = await api(`/sessions/${st.sid}`);
    const tid = S.session.track_id;
    T = tid === null || tid === undefined ? null : await api(`/tracks/${tid}?category=${S.session.category || ''}`).catch(() => null);
    G = tid === null || tid === undefined ? [] : await api(`/guest-laps?track=${tid}`).catch(() => []);  // friends' laps here
  }
  const telLaps = () => S.laps.filter(l => l.sample_count > 0 && l.lap_time_ms > 0);
  const isLive = () => st.sid === status.session_id;

  async function refresh() {
    try { await loadSession(); } catch (e) { body.replaceChildren(h('div', { class: 'card empty' }, h('h3', {}, 'Session not found'), String(e.message || e))); return; }
    const laps = telLaps();
    lastSig = laps.map(l => l.id).join();
    if (!laps.some(l => l.id === st.aId) || st.follow) st.aId = laps.length ? laps[laps.length - 1].id : null;
    await render();
  }

  // ------------------------------------------------ reference and comparison laps
  function pickRef(laps, A) {
    if (st.ref !== 'auto') return st.ref === A.id ? null : st.ref;
    const valid = laps.filter(l => l.valid && l.id !== A.id).sort((a, b) => a.lap_time_ms - b.lap_time_ms);
    const sessionBest = laps.filter(l => l.valid).sort((a, b) => a.lap_time_ms - b.lap_time_ms)[0];
    if (sessionBest && sessionBest.id === A.id) {  // this is the session's best: compare with the best before it
      const pb = allTimeBest(A);
      if (pb && pb.id !== A.id) return pb.id;
    }
    return valid[0]?.id ?? laps.filter(l => l.id !== A.id).slice(-1)[0]?.id ?? null;
  }
  // the lap being driven is measured against the reference picked above, else this session's best lap,
  // else the all-time best here, else the last lap
  async function liveRef() {
    const laps = telLaps();
    const id = (st.ref !== 'auto' ? st.ref : null)
      ?? laps.filter(l => l.valid).sort((a, b) => a.lap_time_ms - b.lap_time_ms)[0]?.id
      ?? (T?.top_laps || []).filter(l => l.lap_time_ms > 0).sort((a, b) => a.lap_time_ms - b.lap_time_ms)[0]?.id
      ?? laps[laps.length - 1]?.id;
    const r = id ? await tel(id) : null;
    return r && { id, p: r.p, lap: r.lap, label: r.lap.guest ? guestLabel(r.lap) : r.lap.session_id === st.sid ? `L${r.lap.lap_number}` : 'All-time best' };
  }
  const followLap = on => {
    follower?.stop(); follower = null;
    if (on) follower = liveLap(liveEl, { session: () => S?.session, reference: liveRef, track: () => T });
  };

  function allTimeBest(A) {
    return (T?.top_laps || []).filter(l => l.id !== A.id && (l.regs_2026 ?? 0) === (A.regs_2026 ?? 0) && l.lap_time_ms > 0)
      .sort((a, b) => a.lap_time_ms - b.lap_time_ms)[0] || null;
  }

  // ------------------------------------------------ toolbar
  function renderToolbar(laps, A) {
    const sess = sessions.some(s => s.id === st.sid) ? sessions : [S.session, ...sessions];
    const sSel = h('select', { 'aria-label': 'Session', onchange: async () => { st.sid = Number(sSel.value); st.aId = null; st.ref = 'auto'; st.follow = true; await refresh(); } },
      ...sess.map(s => h('option', { value: s.id, selected: s.id === st.sid || null },
        `${trackName(s.track_id)} · ${sessionTypeName(s.session_type)} · ${fmtDate(s.started_at)}${s.id === status.session_id ? ' · live' : ''}`)));
    const aSel = h('select', { 'aria-label': 'Lap', onchange: () => { st.aId = Number(aSel.value); st.follow = false; render(); } },
      ...laps.map(l => h('option', { value: l.id, selected: l.id === A?.id || null }, `L${l.lap_number} · ${fmtLap(l.lap_time_ms)}${l.valid ? '' : ' · invalid'}`)));
    const pb = A ? allTimeBest(A) : null;
    const rSel = h('select', { 'aria-label': 'Reference lap', onchange: () => { st.ref = rSel.value === 'auto' ? 'auto' : Number(rSel.value); render(); } },
      h('option', { value: 'auto', selected: st.ref === 'auto' || null }, 'Auto: best lap'),
      pb && !laps.some(l => l.id === pb.id) ? h('option', { value: pb.id, selected: st.ref === pb.id || null }, `All-time best · ${fmtLap(pb.lap_time_ms)} (${fmtDate(pb.recorded_at, false)})`) : null,
      ...laps.filter(l => l.id !== A?.id).map(l => h('option', { value: l.id, selected: st.ref === l.id || null }, `L${l.lap_number} · ${fmtLap(l.lap_time_ms)}${l.valid ? '' : ' · invalid'}`)),
      ...G.map(l => h('option', { value: l.id, selected: st.ref === l.id || null }, `${guestLabel(l)} · ${fmtLap(l.lap_time_ms)} (friend's lap)`)));
    const lapBtn = isLive() ? h('button', { class: 'btn sm toggle' + (prefs.live !== false ? ' on' : ''), 'aria-pressed': String(prefs.live !== false),
      title: 'Draw the lap you are driving as you go, against the reference', onclick: () => {
        prefs.live = prefs.live === false; savePrefs(prefs); followLap(prefs.live); renderToolbar(laps, A);
      } }, 'Lap in progress') : null;
    const followBtn = isLive() ? h('button', { class: 'btn sm toggle' + (st.follow ? ' on' : ''), 'aria-pressed': String(st.follow), title: 'Move to each new lap as you complete it',
      onclick: () => { st.follow = !st.follow; if (st.follow) refresh(); else renderToolbar(laps, A); } }, st.follow ? '● Following live' : 'Follow live') : null;
    const chBtn = h('button', { class: 'btn sm', 'aria-expanded': 'false', onclick: () => { const open = pop.classList.toggle('hidden') === false; chBtn.setAttribute('aria-expanded', String(open)); } }, 'Channels');
    const pop = h('div', { class: 'ws-pop hidden' }, ...Object.keys(TRACES).map(k => {
      const c = CHANNELS.find(x => x.key === k);
      const box = h('input', { type: 'checkbox', checked: prefs.on.includes(k) || null, onchange: () => {
        prefs.on = box.checked ? [...prefs.on, k] : prefs.on.filter(x => x !== k); savePrefs(prefs); render();
      } });
      return h('label', { class: 'check small' }, box, c.title);
    }));
    toolbar.replaceChildren(...[
      h('label', { class: 'ws-field' }, h('span', {}, 'Session'), sSel),
      h('label', { class: 'ws-field' }, h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: seriesColour(0) } }), 'Lap'), aSel),
      h('label', { class: 'ws-field' }, h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: seriesColour(1) } }), 'Reference'), rSel),
      h('span', { class: 'grow' }), lapBtn, followBtn,
      h('span', { class: 'ws-popwrap' }, chBtn, pop),
      h('button', { class: 'btn sm', onclick: () => group?.setDomain(null) }, 'Reset zoom')].filter(Boolean));
  }

  let group = null, renderNo = 0;
  async function render() {
    const my = ++renderNo;  // a newer choice made while laps were loading wins
    disposers.forEach(fn => fn()); disposers = [];
    const laps = telLaps();
    const ses = S.session;
    head.replaceChildren(h('div', {},
      h('div', { class: 'small muted' }, h('a', { href: `#/session/${ses.id}` }, 'Session'), ' / Workstation'),
      h('h1', {}, `${trackName(ses.track_id)} · ${sessionTypeName(ses.session_type)}`),
      h('div', { class: 'sub' }, `${fmtDate(ses.started_at)} · drag across a trace to zoom, double-click to reset; hover a map to move the cursor.`)));
    const Arow = laps.find(l => l.id === st.aId);
    renderToolbar(laps, Arow);
    if (!Arow) {
      body.replaceChildren(h('div', { class: 'card empty' }, h('h3', {}, isLive() ? 'Waiting for the first lap' : 'No laps with telemetry'),
        isLive() ? 'The workstation fills in as soon as you complete a lap.' : 'Pick another session above.'));
      return;
    }
    history.replaceState(null, '', `#/workstation?session=${st.sid}&lap=${st.aId}${st.ref === 'auto' ? '' : '&ref=' + st.ref}`);
    const refId = pickRef(laps, Arow);
    const prevRow = laps.find(l => l.lap_number === Arow.lap_number - 1);
    const bestRow = laps.filter(l => l.valid).sort((a, b) => a.lap_time_ms - b.lap_time_ms)[0];
    const ids = [Arow.id, refId, prevRow?.id, bestRow?.id].filter((v, i, a) => v && a.indexOf(v) === i);
    const loaded = new Map(await Promise.all(ids.map(async id => [id, await tel(id)])));
    if (my !== renderNo) return;
    const A = loaded.get(Arow.id);
    if (!A) { body.replaceChildren(h('div', { class: 'card empty' }, h('h3', {}, 'No telemetry for this lap'))); return; }
    const mk = (id, i, tag) => {
      const r = loaded.get(id); if (!r) return null;
      const same = r.lap.session_id === st.sid;
      return { ...r, id, color: seriesColour(i), label: r.lap.guest ? guestLabel(r.lap) : same ? `L${r.lap.lap_number}` : 'All-time best', tag };
    };
    const LA = { ...A, id: Arow.id, color: seriesColour(0), label: `L${Arow.lap_number}` };
    // the reference, the lap before and the session's best, each once (one lap can be several of them)
    const tags = new Map();
    for (const [id, tag] of [[refId, 'reference'], [prevRow?.id, 'previous lap'], [bestRow?.id, 'session best']]) {
      if (id && id !== Arow.id) tags.set(id, [...(tags.get(id) || []), tag]);
    }
    const comps = [...tags].map(([id, t], i) => mk(id, i + 1, t.join(', '))).filter(Boolean);
    const R = refId ? comps.find(C => C.id === refId) || null : null;
    const len = T?.track_length || ses.track_length || LA.p.d[LA.p.d.length - 1];
    const s2 = T?.s2_start, s3 = T?.s3_start;
    for (const L of [LA, ...comps]) L.key = LA.lap.micro?.key;
    const bnds = microBounds(LA.lap.micro?.key, len, s2, s3);
    for (const L of [LA, ...comps]) L.micro = microTimes(L, bnds);
    const deltaVs = C => LA.p.d.map((d, k) => { const tr = valueAt(C.p.d, C.p.t, d); return tr === null ? null : LA.p.t[k] - tr; });
    for (const C of comps) C.dA = deltaVs(C);  // + = this lap behind C at that point

    group = new SyncGroup();
    let rafPending = false, cursor = null;
    const cursorFns = [];
    group.on((kind, v) => {
      if (kind !== 'cursor') return;
      cursor = v;
      if (rafPending) return;
      rafPending = true;
      requestAnimationFrame(() => { rafPending = false; for (const fn of cursorFns) fn(cursor); });
    });

    const strip = h('div', { class: 'card ws-strip' });
    const traces = h('div', { class: 'card ws-traces' });
    const maps = h('div', { class: 'ws-col ws-maps' });
    const side = h('div', { class: 'ws-col ws-side' });
    const report = h('div', { class: 'card ws-report' });
    const evo = h('div', { class: 'card ws-evo' });
    body.replaceChildren(strip, h('div', { class: 'ws-grid' }, traces, maps, side, report, evo));

    renderStrip(strip, LA, R, laps, bnds, group);
    renderTraces(traces, LA, R, comps, group, { s2, s3 }, disposers);
    renderMaps(maps, LA, R, T, group, cursorFns, disposers);
    renderSide(side, LA, comps, R, cursorFns, disposers);
    renderReport(report, laps, LA, R, id => { st.aId = id; st.follow = false; render(); }, id => { st.ref = id; render(); });
    renderEvolution(evo, laps, disposers);
    for (const fn of cursorFns) fn(null);
  }

  await refresh();
  followLap(prefs.live !== false);  // it shows itself only while this session is the one being driven
  timer = setInterval(async () => {
    if (!st.follow) return;
    try {
      if (!isLive()) {  // a new session in the game: move to it once its first lap is in
        const now = await api('/status');
        if (now.session_id && now.session_id !== status.session_id) {
          status.session_id = now.session_id; st.sid = now.session_id; st.aId = null; st.ref = 'auto';
          await refresh();
        }
        return;
      }
      const s = await api(`/sessions/${st.sid}`);
      const sig = s.laps.filter(l => l.sample_count > 0 && l.lap_time_ms > 0).map(l => l.id).join();
      if (sig !== lastSig) await refresh();
    } catch { /* app busy; try again next time */ }
  }, LIVE_POLL_MS);
  return done;
}

// ------------------------------------------------------------------ micro-sector timeline
function renderStrip(card, A, R, laps, bnds, group) {
  const bestMicro = Array(24).fill(null);
  for (const l of laps) {
    if (!l.valid || l.micro?.key !== A.lap.micro?.key || !l.micro?.ms) continue;
    l.micro.ms.forEach((v, i) => { if (v && (bestMicro[i] === null || v < bestMicro[i])) bestMicro[i] = v; });
  }
  const a = A.micro, r = R?.micro;
  const sectors = h('div', { class: 'micro ws-micro' });
  const word = { p: 'session best', g: R ? `quicker than ${R.label}` : '', y: R ? `slower than ${R.label}` : '', n: 'no time' };
  for (let s = 0; s < 3; s++) {
    const sec = h('div', { class: 'micro-sec' });
    for (let j = 0; j < 8; j++) {
      const i = s * 8 + j, v = a?.[i], rv = r?.[i];
      const cls = !v ? 'n' : bestMicro[i] !== null && v <= bestMicro[i] && A.lap.valid ? 'p' : rv ? (v <= rv ? 'g' : 'y') : 'n';
      const d = v && rv ? v - rv : null;
      const cell = h('span', { class: `mc mc-${cls}`, role: 'button', tabindex: '0', 'aria-label': `Micro-sector ${s + 1}.${j + 1}` },
        d === null ? '' : Math.abs(d) < 5 ? '.00' : (d > 0 ? '+' : '−') + (Math.abs(d) / 1000).toFixed(2).replace(/^0/, ''));
      const zoom = () => { if (bnds) group.setDomain([Math.max(0, bnds[i] - 60), bnds[i + 1] + 60]); };
      cell.addEventListener('click', zoom);
      cell.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); zoom(); } });
      cell.addEventListener('mousemove', e => showTip(`<b>Micro-sector ${s + 1}.${j + 1}</b>` + (bnds ? ` · ${Math.round(bnds[i])}–${Math.round(bnds[i + 1])} m` : '') +
        `<br>${A.label}: ${v ? (v / 1000).toFixed(3) + ' s' : '–'}` + (R ? `<br>${R.label}: ${rv ? (rv / 1000).toFixed(3) + ' s' : '–'}` : '') +
        (d !== null ? `<br>${fmtDelta(d)} · ${word[cls]}` : cls === 'p' ? '<br>session best' : '') + '<br><span style="opacity:.7">Click to zoom the traces here</span>', e.clientX, e.clientY));
      cell.addEventListener('mouseleave', hideTip);
      sec.append(cell);
    }
    sectors.append(sec);
  }
  const bestOf = k => Math.min(...laps.filter(l => l.valid && l[k] > 0).map(l => l[k]));
  const secCell = (label, k, fmt) => {
    const v = A.lap[k], rv = R?.lap[k], d = v && rv ? v - rv : null;
    const purple = A.lap.valid && v > 0 && v <= bestOf(k);
    return h('div', { class: 'ws-sec' }, h('span', { class: 'muted small' }, label),
      h('b', { class: 'tnum' + (purple ? ' sec-purple' : '') }, fmt(v)),
      h('span', { class: 'small tnum ' + deltaClass(d) }, d === null ? '' : fmtDelta(d)));
  };
  card.replaceChildren(h('div', { class: 'ws-strip-row' },
    h('div', { class: 'ws-strip-main' },
      h('div', { class: 'micro-head small' }, h('span', { class: 'k' }, 'Micro-sectors'),
        h('span', { class: 'lg' }, h('i', { class: 'swatch mc-p' }), 'Session best'),
        R ? h('span', { class: 'lg' }, h('i', { class: 'swatch mc-g' }), `Quicker than ${R.label}`) : null,
        R ? h('span', { class: 'lg' }, h('i', { class: 'swatch mc-y' }), 'Slower') : null),
      sectors),
    h('div', { class: 'ws-secs' }, secCell('S1', 's1_ms', fmtSector), secCell('S2', 's2_ms', fmtSector), secCell('S3', 's3_ms', fmtSector),
      secCell(A.lap.valid ? 'Lap' : 'Lap (invalid)', 'lap_time_ms', fmtLap))));
}

// ------------------------------------------------------------------ traces
function renderTraces(card, A, R, comps, group, { s2, s3 }, disposers) {
  const prefs = loadPrefs();
  const markers = [];
  if (s2) markers.push({ x: s2, label: 'S2' });
  if (s3) markers.push({ x: s3, label: 'S3' });
  const laps = [A, R].filter(Boolean);
  const list = Object.keys(TRACES).filter(k => prefs.on.includes(k) && laps.some(L => has(L.p[k])));
  const charts = [];
  const opts = (c, last, extra = {}) => ({ group, title: c.title, height: TRACES[c.key] ?? c.height, format: c.format, step: c.step, yMin: c.yMin ?? null, yMax: c.yMax ?? null,
    yTicks: c.yTicks, zeroLine: c.zeroLine, symmetric: c.symmetric, showX: last, markers, xFormat, ...extra });
  if (comps.length) {
    const ch = new LineChart(card, opts({ key: 'delta', title: 'Time delta', format: v => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(3) + 's', zeroLine: true, symmetric: true }, !list.length, { height: 120 }));
    ch.setSeries(comps.map(C => ({ name: `vs ${C.label}`, color: C.color, x: A.p.d, y: C.dA, width: 2 })));
    charts.push(ch);
  }
  list.forEach((k, i) => {
    const c = CHANNELS.find(x => x.key === k);
    const ch = new LineChart(card, opts(c, i === list.length - 1));
    ch.setSeries(laps.map(L => ({ name: L.label, color: L.color, x: L.p.d, y: L.p[k], width: L === A ? 2 : 1.5, z: L === A ? 1 : 0 })));  // this lap on top
    charts.push(ch);
  });
  if (!charts.length) card.append(h('div', { class: 'empty' }, 'Turn on a channel with the Channels button.'));
  disposers.push(() => charts.forEach(c => c.destroy()));
}

// ------------------------------------------------------------------ maps
function renderMaps(col, A, R, T, group, cursorFns, disposers) {
  const prefs = loadPrefs();
  const mkMap = (card, height) => {
    const map = new TrackMap(card, { height, interactive: true });
    if (T?.outline) map.setOutline(T.outline, { frame: T.frame });  // plain asphalt: the colours are the lap's
    map.canvas.addEventListener('mousemove', e => {
      if (e.buttons) return;
      const r = map.canvas.getBoundingClientRect(), k = map.pick(e.clientX - r.left, e.clientY - r.top, 0);
      group.setCursor(k >= 0 ? A.p.d[k] : null);
    });
    map.canvas.addEventListener('mouseleave', () => group.setCursor(null));
    disposers.push(() => map.destroy());
    cursorFns.push(v => {
      if (v === null) { map.setMarkers([]); return; }
      map.setMarkers([R, A].filter(Boolean).map(L => ({ x: valueAt(L.p.d, L.p.x, v), z: valueAt(L.p.d, L.p.z, v), color: L.color, r: L === A ? 6 : 5 })));
    });
    return map;
  };
  const legend = (stops, labels) => h('div', { class: 'ws-legend small' },
    h('i', { class: 'ws-grad', style: { background: `linear-gradient(90deg, ${stops.join(',')})` } }),
    h('span', { class: 'row', style: { justifyContent: 'space-between', gap: '8px' } }, ...labels.map(t => h('span', { class: 'muted' }, t))));

  // ---- track map with a choice of colouring
  const seg = h('div', { class: 'segmented' });
  const card = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Track map', h('span', { class: 'right' }, seg)));
  col.append(card);
  const map = mkMap(card, 300);
  const legendBox = h('div');
  card.append(legendBox);
  const neutral = cssVar('--muted');
  const paint = mode => {
    let colors, leg;
    const p = A.p;
    if (mode === 'gain' && R) {
      const good = cssVar('--good-text'), bad = cssVar('--bad-text');
      const dl = R.dA, k20 = [];
      for (let k = 0, j = 0; k < p.d.length; k++) { while (p.d[k] - p.d[j] > 25) j++; k20.push(j); }
      colors = p.d.map((_, k) => {
        const a = dl[k20[k]], b = dl[k];
        if (a === null || b === null) return neutral;
        const f = clamp((a - b) / 0.01, -1, 1);  // + = gaining on the reference over the last 25 m
        return Math.abs(f) < 0.1 ? neutral : f > 0 ? mix(neutral, good, q(f)) : mix(neutral, bad, q(-f));
      });
      leg = legend([bad, neutral, good], [`Losing to ${R.label}`, 'Even', 'Gaining']);
    } else if (mode === 'speed' || (mode === 'gain' && !R)) {
      const v = p.spd.filter(x => x !== null), lo = Math.min(...v), hi = Math.max(...v);
      colors = p.spd.map(x => x === null ? neutral : ramp(q((x - lo) / (hi - lo || 1), 12)));
      leg = legend([ramp(0), ramp(0.5), ramp(1)], [`${fmtNum(lo, 0)} ${speedUnit()}`, `${fmtNum(hi, 0)} ${speedUnit()}`]);
    } else if (mode === 'inputs') {
      const thr = cssVar('--throttle'), brk = cssVar('--brake');
      colors = p.d.map((_, k) => (p.brk[k] > 5 ? brk : p.thr[k] > 90 ? thr : neutral));
      leg = h('div', { class: 'row small ws-legend', style: { gap: '12px' } }, ...[[thr, 'Full throttle'], [neutral, 'Partial / coasting'], [brk, 'Braking']]
        .map(([c, t]) => h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: c, height: '3px', width: '14px' } }), t)));
    } else {
      colors = p.gear.map(g => g === null ? neutral : ramp(clamp((g - 1) / 7, 0, 1)));
      leg = legend([ramp(0), ramp(1)], ['1st', '8th']);
    }
    map.setLines([{ x: p.x, z: p.z, colors, width: 5 }]);
    legendBox.replaceChildren(leg);
  };
  for (const [m, label] of COLOURINGS) {
    if (m === 'gain' && !R) continue;
    seg.append(h('button', { class: prefs.colour === m || (prefs.colour === 'gain' && !R && m === 'speed') ? 'on' : '', onclick: e => {
      for (const b of seg.children) b.classList.toggle('on', b === e.currentTarget);
      const p2 = loadPrefs(); p2.colour = m; savePrefs(p2); paint(m);
    } }, label));
  }
  paint(prefs.colour);

  // ---- balance on track
  const bal = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Balance on track', h('span', { class: 'right small muted' }, A.label)));
  col.append(bal);
  if (!has(A.p.us)) {
    bal.append(h('div', { class: 'muted small ws-note' }, 'No balance data on this lap. Laps recorded with this version on have the understeer angle (from the game\'s Motion Ex data).'));
    return;
  }
  const bmap = mkMap(bal, 260);
  const us = cssVar('--s2'), os = cssVar('--s1');
  const colors = A.p.us.map((v, k) => {
    if (v === null || !(Math.abs(A.p.glat[k] ?? 0) >= 0.6)) return neutral;
    const f = clamp(v / 2, -1, 1);
    return Math.abs(f) < 0.1 ? neutral : f > 0 ? mix(neutral, us, q(f)) : mix(neutral, os, q(-f));
  });
  bmap.setLines([{ x: A.p.x, z: A.p.z, colors, width: 5 }]);
  bal.append(legend([os, neutral, us], ['Oversteer 2°+', 'Neutral', 'Understeer 2°+']));
}

// ------------------------------------------------------------------ side: deltas, car at cursor, balance by speed
function renderSide(col, A, comps, R, cursorFns, disposers) {
  const p = A.p, n = p.d.length;
  // ---- lap time deltas at the cursor
  const dCard = h('div', { class: 'card' });
  col.append(dCard);
  const rows = h('div', { class: 'ws-readout' });
  dCard.append(h('div', { class: 'card-title' }, 'Lap time deltas', h('span', { class: 'right small muted ws-at' })), rows);
  const at = dCard.querySelector('.ws-at');
  const line = (label, value, cls = '', color = null) => h('div', { class: 'ws-rd' },
    h('span', { class: 'row', style: { gap: '6px' } }, color ? h('i', { class: 'swatch', style: { background: color } }) : null, label),
    h('b', { class: 'tnum ' + cls }, value));
  cursorFns.push(v => {
    const k = v === null ? n - 1 : nearest(p.d, v);
    const end = v === null;
    at.textContent = end ? 'end of lap' : `${fmtNum(p.d[k], 0)} m`;
    const tA = end ? A.lap.lap_time_ms / 1000 : p.t[k];
    const out = [line(A.label, end ? fmtLap(A.lap.lap_time_ms) : tA.toFixed(3) + ' s', '', A.color)];
    for (const C of comps) {
      const d = end ? (A.lap.lap_time_ms - C.lap.lap_time_ms) : (C.dA[k] === null ? null : C.dA[k] * 1000);
      out.push(line(`vs ${C.label} (${C.tag})`, fmtDelta(d), deltaClass(d), C.color));
    }
    if (!end && R) {
      const rs = valueAt(R.p.d, R.p.spd, p.d[k]);
      const ds = rs === null || p.spd[k] === null ? null : p.spd[k] - rs;
      out.push(line(`Speed vs ${R.label}`, ds === null ? '–' : `${ds > 0 ? '+' : ds < 0 ? '−' : ''}${fmtNum(Math.abs(ds), 0)} ${speedUnit()}`, ds === null ? '' : ds > 0 ? 'faster' : ds < 0 ? 'slower' : ''));
    }
    rows.replaceChildren(...out);
  });

  // ---- car at the cursor
  const cCard = h('div', { class: 'card' });
  col.append(cCard);
  const carBody = h('div', { class: 'ws-car' });
  cCard.append(h('div', { class: 'card-title' }, 'Car at cursor', h('span', { class: 'right small muted' }, A.label)), carBody);
  const raw = A.cols;
  const wheel = (key, w, i) => raw[key]?.[w]?.[i] ?? null;
  const bar = (label, v, color) => h('div', { class: 'ws-bar' }, h('span', { class: 'muted' }, label),
    h('span', { class: 'ws-bar-track' }, h('i', { style: { width: clamp(v ?? 0, 0, 100) + '%', background: color } })),
    h('b', { class: 'tnum' }, v === null || v === undefined ? '–' : Math.round(v) + '%'));
  cursorFns.push(v => {
    const k = v === null ? n - 1 : nearest(p.d, v), i = p.idx[k];
    const gear = p.gear[k], u = p.us[k], soc = p.ers[k];
    const tyres = WHEEL_LAYOUT.map(w => {
      const ts = wheel('ts', w, i);
      return h('div', { class: 'ws-tyre ' + tyreTempState(ts) },
        h('span', { class: 'muted' }, WHEELS[w]),
        h('b', { class: 'tnum' }, ts === null ? '–' : Math.round(tempVal(ts)) + '°'),
        h('span', { class: 'tnum' }, `in ${wheel('ti', w, i) === null ? '–' : Math.round(tempVal(wheel('ti', w, i))) + '°'}`),
        h('span', { class: 'tnum' }, `${wheel('tp', w, i) === null ? '–' : wheel('tp', w, i).toFixed(1)} psi`),
        h('span', { class: 'tnum muted' }, `brake ${wheel('bt', w, i) === null ? '–' : Math.round(tempVal(wheel('bt', w, i))) + '°'}`),
        h('span', { class: 'tnum muted' }, `wear ${wheel('tw', w, i) === null ? '–' : fmtNum(wheel('tw', w, i), 0) + '%'}`));
    });
    carBody.replaceChildren(
      h('div', { class: 'ws-car-top' },
        h('div', {}, h('b', { class: 'ws-big tnum' }, p.spd[k] === null ? '–' : fmtNum(p.spd[k], 0)), h('span', { class: 'muted small' }, ' ' + speedUnit())),
        h('div', {}, h('span', { class: 'muted small' }, 'Gear '), h('b', { class: 'ws-big tnum' }, gear === null ? '–' : gear <= 0 ? 'N' : String(gear))),
        h('div', { class: 'small tnum' }, p.rpm[k] === null ? '' : fmtNum(p.rpm[k], 0) + ' rpm')),
      bar('Throttle', p.thr[k], cssVar('--throttle')), bar('Brake', p.brk[k], cssVar('--brake')),
      h('div', { class: 'ws-car-mid' },
        h('div', { class: 'ws-tyres' }, ...tyres),
        h('div', { class: 'ws-soc', title: 'Battery (ERS store)' }, h('span', { class: 'muted small' }, 'SOC'),
          h('span', { class: 'ws-soc-track' }, h('i', { style: { height: clamp(soc ?? 0, 0, 100) + '%' } })),
          h('b', { class: 'tnum small' }, soc === null || soc === undefined ? '–' : Math.round(soc) + '%'))),
      h('div', { class: 'small muted ws-car-foot tnum' },
        [p.fuel[k] !== null && p.fuel[k] !== undefined ? `Fuel ${p.fuel[k].toFixed(2)} kg` : null,
          p.glat[k] !== null && p.glat[k] !== undefined ? `Lat ${Math.abs(p.glat[k]).toFixed(1)} g` : null,
          u !== null && u !== undefined ? `${Math.abs(u) < 0.05 ? 'Neutral' : u > 0 ? 'Understeer' : 'Oversteer'} ${Math.abs(u).toFixed(1)}°` : null].filter(Boolean).join(' · ')));
  });

  // ---- balance by corner speed
  const bCard = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Balance by corner speed'));
  col.append(bCard);
  const laps = [A, R].filter(L => L && has(L.p.us));
  if (!laps.length) { bCard.append(h('div', { class: 'muted small ws-note' }, 'Needs a lap with balance data.')); return; }
  const plot = new BalancePlot(bCard, 210);
  disposers.push(() => plot.destroy());
  plot.set(laps.map(L => ({ name: L.label, color: L.color,
    pts: L.p.d.map((_, k) => [L.p.spd[k], L.p.us[k], L.p.glat[k]]).filter(([s, u, g]) => s !== null && u !== null && Math.abs(g ?? 0) >= 1.0).map(([s, u]) => [s, u]) })),
  speedUnit() === 'mph' ? 15 : 25);
  bCard.append(h('div', { class: 'small muted ws-note' }, 'Understeer angle in corners (over 1 g sideways), with the average per speed band. Above zero the front slides more than the rear.'));
}

// ------------------------------------------------------------------ outing report
function renderReport(card, laps, A, R, onPick, onRef) {
  const all = laps;
  const best = Math.min(...all.filter(l => l.valid).map(l => l.lap_time_ms));
  const sb = k => Math.min(...all.filter(l => l.valid && l[k] > 0).map(l => l[k]));
  const sBest = { s1_ms: sb('s1_ms'), s2_ms: sb('s2_ms'), s3_ms: sb('s3_ms') };
  const tb = h('tbody');
  for (const l of [...all].reverse()) {
    const isA = l.id === A.lap.id, isR = R && l.id === R.lap.id;
    const fuel = l.fuel_start !== null && l.fuel_end !== null ? l.fuel_start - l.fuel_end : null;
    tb.append(h('tr', { class: 'click' + (l.valid ? '' : ' invalid') + (isA ? ' ws-a' : '') + (isR ? ' ws-r' : ''), onclick: () => onPick(l.id) },
      h('td', {}, h('span', { class: 'row', style: { gap: '6px', flexWrap: 'nowrap' } },
        h('i', { class: 'swatch', style: { background: isA ? A.color : isR ? R.color : 'transparent' } }), `L${l.lap_number}`)),
      h('td', { class: 'num time' }, h('b', {}, fmtLap(l.lap_time_ms))),
      h('td', { class: 'num small ' + (l.valid && l.lap_time_ms === best ? 'sec-purple' : 'muted') }, l.valid && isFinite(best) ? (l.lap_time_ms === best ? 'best' : fmtDelta(l.lap_time_ms - best)) : ''),
      ...['s1_ms', 's2_ms', 's3_ms'].map(k => h('td', { class: 'num' + (l.valid && l[k] > 0 && l[k] === sBest[k] ? ' sec-purple' : '') }, fmtSector(l[k]))),
      h('td', {}, l.tyre_visual !== null && l.tyre_visual !== undefined ? h('span', { class: 'row', style: { gap: '5px', flexWrap: 'nowrap' } }, tyreBadge(l.tyre_visual), h('span', { class: 'small muted' }, l.tyre_age ?? '')) : ''),
      h('td', { class: 'num' }, l.top_speed ? fmtSpeed(l.top_speed) : '–'),
      h('td', { class: 'num' }, fuel === null ? '–' : fuel.toFixed(2)),
      h('td', {}, isR ? h('span', { class: 'badge info' }, 'ref') : isA ? h('span', { class: 'badge' }, 'lap') :
        h('button', { class: 'btn sm', title: 'Use as reference', onclick: e => { e.stopPropagation(); onRef(l.id); } }, 'Ref'))));
  }
  card.replaceChildren(h('div', { class: 'card-title' }, 'Outing report', h('span', { class: 'right small muted' }, 'Click a lap to load it')),
    h('div', { class: 'table-wrap ws-report-wrap' }, h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, ...['Lap', 'Time', 'Gap', 'S1', 'S2', 'S3', 'Tyre', `Top ${speedUnit()}`, 'Fuel kg', '']
        .map((x, i) => h('th', { class: i && i < 6 || i === 7 || i === 8 ? 'num' : '' }, x)))), tb)));
}

// ------------------------------------------------------------------ lap time evolution
function renderEvolution(card, laps, disposers) {
  card.replaceChildren(h('div', { class: 'card-title' }, 'Lap time evolution', h('span', { class: 'right small muted' }, 'valid laps, by tyre stint')));
  const race = laps[0]?.category === 'race';  // a standing start says nothing about pace
  const valid = laps.filter(l => l.valid && l.lap_time_ms > 0 && (!l.lap_type || l.lap_type === 'flying') && !(race && l.lap_number === 1));
  if (valid.length < 2) { card.append(h('div', { class: 'muted small ws-note' }, 'Shows once there are two or more valid laps.')); return; }
  const best = Math.min(...valid.map(l => l.lap_time_ms));
  const pts = valid.filter(l => l.lap_time_ms <= best * 1.07);
  const stints = [];
  let cur = null, prev = null;
  for (const l of laps) {  // stints from every lap, so pit stops split them even when the in / out laps are left out
    const fresh = !prev || l.tyre_visual !== prev.tyre_visual || (l.tyre_age ?? 0) < (prev.tyre_age ?? 0);
    if (fresh) { cur = { n: stints.length + 1, visual: l.tyre_visual, laps: [] }; stints.push(cur); }
    if (pts.includes(l)) cur.laps.push(l);
    prev = l;
  }
  const series = [];
  for (const s of stints.filter(x => x.laps.length)) {
    const color = cssVar(TYRE_VAR[tyreLetter(s.visual)] || '--s1');
    const xs = s.laps.map(l => l.lap_number), ys = s.laps.map(l => l.lap_time_ms / 1000);
    let slope = null;
    if (xs.length >= 3) {
      const mx = xs.reduce((a, b) => a + b, 0) / xs.length, my = ys.reduce((a, b) => a + b, 0) / ys.length;
      const sxx = xs.reduce((a, x) => a + (x - mx) ** 2, 0);
      slope = sxx ? xs.reduce((a, x, i) => a + (x - mx) * (ys[i] - my), 0) / sxx : null;
      if (slope !== null) series.push({ name: '', color, x: [xs[0], xs[xs.length - 1]], y: [my + slope * (xs[0] - mx), my + slope * (xs[xs.length - 1] - mx)], width: 1.5, dash: [4, 4], legend: false, hoverable: false, dot: false });
    }
    const name = `Stint ${s.n} ${tyreLetter(s.visual)}` + (slope === null ? '' : ` ${slope >= 0 ? '+' : '−'}${Math.abs(slope).toFixed(3)} s/lap`);
    series.push({ name, color, x: xs, y: ys, width: 2, points: true,
      tip: (x, v) => `<b>Lap ${Math.round(x)}</b> · stint ${s.n}<br>${fmtLap(v * 1000)} (${fmtDelta(v * 1000 - best)} to best)` });
  }
  const chart = new LineChart(card, { group: new SyncGroup(), height: 190, tooltip: 'nearest', xInt: true, zoom: false,
    format: v => fmtLap(v * 1000), xFormat: v => 'L' + Math.round(v), tipX: v => 'Lap ' + Math.round(v) });
  chart.setSeries(series);
  card.append(h('div', { class: 'row small ws-legend', style: { gap: '12px' } }, ...series.filter(s => s.legend !== false).map(s =>
    h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: s.color } }), s.name))));
  disposers.push(() => chart.destroy());
}

// ------------------------------------------------------------------ the lap being driven
// Polls the samples recorded since the last call and draws the lap as it is driven: the time delta to the
// reference, speed and pedals against it, and the line so far on a small map coloured by gain and loss.
const LIVE_LAP_MS = 500;
const LIVE_CH = ['spd', 'thr', 'brk'];

function liveLap(el, { session, reference, track }) {
  let key = '', n = 0, timer = null, stopped = false, ui = null, refId = null, L = null;
  const reset = () => { L = { d: [], t: [], x: [], z: [], dt: [], spd: [], thr: [], brk: [] }; };
  reset();
  const deltaAt = (R, d, t) => { const tr = valueAt(R.p.d, R.p.t, d); return tr === null ? null : t - tr; };
  const hide = () => { if (ui) { ui.destroy(); ui = null; } el.replaceChildren(); };

  function append(c, R) {
    let last = L.d.length ? L.d[L.d.length - 1] : -Infinity;
    for (let i = 0; i < c.d.length; i++) {
      const d = c.d[i], t = c.t[i];
      if (d === null || t === null || d < 0 || d <= last) continue;  // before the line, or a sample out of order
      last = d;
      L.d.push(d); L.t.push(t); L.x.push(c.x[i]); L.z.push(c.z[i]);
      L.dt.push(R ? deltaAt(R, d, t) : null);
      for (const k of LIVE_CH) { const ch = CHANNELS.find(x => x.key === k), v = c[k][i]; L[k].push(v === null || v === undefined ? null : ch.map ? ch.map(v) : v); }
    }
  }

  function build(R, len) {
    const T = track();
    const group = new SyncGroup();
    const charts = [];
    const title = h('span'), sub = h('span', { class: 'right small muted' });
    const nums = h('div', { class: 'ws-live-nums' });
    const traces = h('div', { class: 'ws-live-traces' });
    const mapBox = h('div', { class: 'ws-live-map' });
    el.replaceChildren(h('div', { class: 'card ws-live' }, h('div', { class: 'card-title' }, title, sub),
      h('div', { class: 'ws-live-grid' }, traces, h('div', {}, nums, mapBox))));
    const xf = { group, xFormat, showX: false };
    if (R) charts.push(new LineChart(traces, { ...xf, title: `Time delta to ${R.label}`, height: 96, zeroLine: true, symmetric: true,
      format: v => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(3) + 's' }));
    LIVE_CH.forEach((k, i) => {
      const c = CHANNELS.find(x => x.key === k);
      charts.push(new LineChart(traces, { ...xf, title: c.title, height: k === 'spd' ? 110 : 48, format: c.format, yMin: c.yMin ?? null, yMax: c.yMax ?? null,
        yTicks: c.yTicks, showX: i === LIVE_CH.length - 1 }));
    });
    if (len > 0) group.setDomain([0, len]);
    const map = new TrackMap(mapBox, { height: 230 });
    if (T?.outline) map.setOutline(T.outline, { frame: T.frame });
    const colours = { good: cssVar('--good'), bad: cssVar('--critical'), flat: cssVar('--muted') };
    return {
      R,
      destroy() { charts.forEach(c => c.destroy()); map.destroy(); },
      update(r) {
        const live = { name: `L${r.lap}`, color: seriesColour(0), x: L.d, width: 2, z: 1 };
        const ref = R && { name: R.label, color: seriesColour(1), x: R.p.d, width: 1.5, z: 0 };
        let i = 0;
        if (R) charts[i++].setSeries([{ ...live, y: L.dt }]);
        for (const k of LIVE_CH) charts[i++].setSeries([ref && { ...ref, y: R.p[k] }, { ...live, y: L[k] }].filter(Boolean));
        // the line so far: green where this lap is gaining on the reference, red where it is losing
        const cols = new Array(L.d.length).fill(colours.flat);
        if (R) for (let k = 0, j = 0; k < L.d.length; k++) {
          while (L.d[k] - L.d[j] > 40) j++;
          const a = L.dt[j], b = L.dt[k];
          if (a !== null && b !== null && k > j) cols[k] = b - a < -0.004 ? colours.good : b - a > 0.004 ? colours.bad : colours.flat;
        }
        const lines = [];
        if (!T?.outline && R) lines.push({ x: R.p.x, z: R.p.z, color: colours.flat, width: 1.5 });
        lines.push({ x: L.x, z: L.z, colors: cols, width: 4 });
        map.setLines(lines);
        const k = L.d.length - 1;
        map.setMarkers(k >= 0 ? [{ x: L.x[k], z: L.z[k], color: seriesColour(0), r: 6 }] : []);
        // the numbers
        const t = k >= 0 ? L.t[k] : 0, dt = k >= 0 ? L.dt[k] : null;
        title.textContent = `Lap in progress · L${r.lap}`;
        sub.textContent = R ? `against ${R.label} · ${fmtLap(R.lap.lap_time_ms)}` : 'no reference lap yet';
        const num = (label, value, cls = '') => h('div', { class: 'ws-live-num' }, h('span', { class: 'small muted' }, label), h('b', { class: 'tnum ' + cls }, value));
        nums.replaceChildren(
          num('Lap time', fmtLap(Math.round(t * 1000))),
          num('Delta', dt === null ? '–' : fmtDelta(Math.round(dt * 1000)), dt === null ? '' : deltaClass(dt * 1000)),
          num('Predicted', dt === null || !R ? '–' : fmtLap(Math.round(R.lap.lap_time_ms + dt * 1000))),
          num('Distance', k < 0 ? '–' : len > 0 ? `${Math.round(L.d[k] / len * 100)}%` : xFormat(L.d[k])));
      },
    };
  }

  async function tick() {
    timer = null;
    let wait = LIVE_LAP_MS;
    try {
      if (document.hidden) wait = 2000;
      else {
        const r = await api(`/live/lap?key=${encodeURIComponent(key)}&since=${n}`);
        if (stopped) return;
        // this session's lap, or the first lap of a new one at the same circuit (saved when it is complete)
        const ses = session();
        const mine = ses && (r.session_id === ses.id || (r.session_id === null && r.track_id === ses.track_id));
        if (!mine || !r.lap) { hide(); key = ''; n = 0; reset(); wait = 2000; }
        else {
          if (r.start === 0) reset();
          key = r.key; n = r.n;
          const R = await reference();
          if (stopped) return;
          if ((R?.id ?? null) !== refId) {  // a new reference (a quicker lap, or picked above): measure the lap again
            refId = R?.id ?? null;
            L.dt = L.d.map((d, k) => (R ? deltaAt(R, d, L.t[k]) : null));
            if (ui) { ui.destroy(); ui = null; }
          }
          append(r.cols, R);
          if (!L.d.length) hide();
          else {
            if (!ui) ui = build(R, r.track_length || track()?.track_length || 0);
            ui.update(r);
          }
        }
      }
    } catch { wait = 2000; }  // the app is busy or restarting: try again shortly
    if (!stopped) timer = setTimeout(tick, wait);
  }
  tick();
  return { stop() { stopped = true; clearTimeout(timer); hide(); } };
}
