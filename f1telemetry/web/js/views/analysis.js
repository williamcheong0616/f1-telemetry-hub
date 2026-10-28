// Lap telemetry analysis: overlay up to 3 laps against distance, racing line map, corners.
import {
  api, h, toast, fmtLap, fmtSector, fmtDelta, deltaClass, fmtDate, fmtNum, speedVal, speedUnit, tempVal, tempUnit,
  trackName, sessionTypeName, seriesColour, cssVar, compact, tyreBadge, CATEGORY_NAMES,
} from '../util.js';
import { LineChart, SyncGroup, TrackMap, valueAt } from '../charts.js';
import { importButton, guestLabel } from '../friends.js';

const MAX_LAPS = 3;
const avg4 = arr => (i) => { let s = 0, n = 0; for (const a of arr) { const v = a[i]; if (v !== null && v !== undefined) { s += v; n++; } } return n ? s / n : null; };
const max4 = arr => (i) => { let m = null; for (const a of arr) { const v = a[i]; if (v !== null && v !== undefined && (m === null || v > m)) m = v; } return m; };

// Understeer angle, smoothed over about 0.15 s; nothing below 60 km/h, where slip angles say little.
const balanceOf = c => {
  if (!c.us) return () => null;
  const n = c.us.length, out = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (!(c.spd[i] >= 60) || c.us[i] === null) continue;
    let s = 0, k = 0;
    for (let j = Math.max(0, i - 2); j <= Math.min(n - 1, i + 2); j++) if (c.us[j] !== null && c.spd[j] >= 60) { s += c.us[j]; k++; }
    out[i] = s / k;
  }
  return i => out[i];
};
// + rear wheelspin, - lock-up (whichever is bigger), as a slip percentage
const slipOf = c => (!c.lk ? () => null : i => {
  const l = c.lk[i], w = c.ws[i];
  if (l === null && w === null) return null;
  return (w || 0) >= (l || 0) ? (w || 0) * 100 : -(l || 0) * 100;
});

export const CHANNELS = [
  { key: 'delta', title: 'Delta', on: true, height: 110, format: v => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(3) + 's', zeroLine: true, symmetric: true, needs2: true },
  { key: 'line', title: 'Line vs reference', on: true, height: 90, format: v => (v > 0.05 ? 'L ' : v < -0.05 ? 'R ' : '') + Math.abs(v).toFixed(1) + ' m', zeroLine: true, symmetric: true, needs2: true },
  { key: 'spd', title: 'Speed', on: true, height: 150, map: v => speedVal(v), format: v => Math.round(v) + ' ' + speedUnit() },
  { key: 'thr', title: 'Throttle', on: true, height: 80, yMin: 0, yMax: 100, format: v => Math.round(v) + '%', yTicks: [0, 50, 100] },
  { key: 'brk', title: 'Brake', on: true, height: 80, yMin: 0, yMax: 100, format: v => Math.round(v) + '%', yTicks: [0, 50, 100] },
  { key: 'gear', title: 'Gear', on: true, height: 80, yMin: 0, yMax: 8, step: true, format: v => v <= 0 ? 'N' : String(Math.round(v)), yTicks: [2, 4, 6, 8] },
  { key: 'str', title: 'Steering', on: true, height: 80, yMin: -1, yMax: 1, format: v => (v > 0 ? 'R ' : v < 0 ? 'L ' : '') + Math.abs(Math.round(v * 100)) + '%', zeroLine: true, yTicks: [-1, 0, 1] },
  { key: 'rpm', title: 'RPM', on: true, height: 90, format: v => compact(v) },
  { key: 'ers', title: 'ERS store', on: false, height: 80, yMin: 0, yMax: 100, format: v => Math.round(v) + '%' },
  { key: 'glat', title: 'Lateral G', on: false, height: 90, format: v => v.toFixed(2) + 'g', zeroLine: true, symmetric: true },
  { key: 'glon', title: 'Longitudinal G', on: false, height: 90, format: v => v.toFixed(2) + 'g', zeroLine: true, symmetric: true },
  { key: 'ts', title: 'Tyre surface (avg)', on: false, height: 90, derive: c => avg4(c.ts), map: v => tempVal(v), format: v => Math.round(v) + tempUnit() },
  { key: 'bt', title: 'Brake temp (max)', on: false, height: 90, derive: c => max4(c.bt), map: v => tempVal(v), format: v => Math.round(v) + tempUnit() },
  { key: 'sp', title: 'Suspension (avg)', on: false, height: 90, derive: c => avg4(c.sp), format: v => v.toFixed(1) + ' mm' },
  { key: 'fuel', title: 'Fuel', on: false, height: 80, format: v => v.toFixed(2) + ' kg' },
  // from Motion Ex; laps recorded before these channels existed have none
  { key: 'us', title: 'Understeer angle', on: false, height: 90, derive: balanceOf, zeroLine: true, symmetric: true, optional: true,
    format: v => (v > 0.05 ? 'US ' : v < -0.05 ? 'OS ' : '') + Math.abs(v).toFixed(1) + '°' },
  { key: 'slip', title: 'Wheelspin / lock-up', on: false, height: 70, derive: slipOf, zeroLine: true, optional: true,
    format: v => (v > 0.5 ? 'spin ' : v < -0.5 ? 'lock ' : '') + Math.abs(Math.round(v)) + '%' },
  // format 2026 only; offered when one of the laps has the data
  { key: 'aero', title: 'Active aero', on: false, height: 60, yMin: 0, yMax: 1, step: true, format: v => v >= 0.5 ? 'Straight' : 'Corner', yTicks: [0, 1], optional: true },
  { key: 'ot', title: 'Overtake Mode', on: false, height: 60, yMin: 0, yMax: 1, step: true, format: v => v >= 0.5 ? 'Active' : 'Off', yTicks: [0, 1], optional: true },
];

export function prepare(rec) {
  // Keep strictly increasing, non-negative distance so lookups by distance are well defined.
  const c = rec.cols;
  const idx = [];
  let last = -Infinity;
  for (let i = 0; i < c.d.length; i++) {
    const d = c.d[i];
    if (d === null || d < 0 || d <= last) continue;
    idx.push(i); last = d;
  }
  const pick = arr => idx.map(i => arr[i]);
  const out = { d: pick(c.d), t: pick(c.t), x: pick(c.x), z: pick(c.z), idx };
  for (const ch of CHANNELS) {
    if (ch.needs2) continue;  // computed against the reference lap in mount()
    let src;
    if (ch.derive) { const f = ch.derive(c); src = idx.map(i => f(i)); }
    else src = c[ch.key] ? pick(c[ch.key]) : [];
    out[ch.key] = ch.map ? src.map(v => (v === null || v === undefined) ? null : ch.map(v)) : src;
  }
  return out;
}

function findCorners(ref) {
  // Speed minima with at least 20 km/h of drop before and recovery after.
  const s = ref.spd, d = ref.d, out = [];
  const win = 15;
  for (let i = win; i < s.length - win; i++) {
    const v = s[i]; if (v === null) continue;
    let isMin = true;
    for (let j = i - win; j <= i + win; j++) if (s[j] !== null && s[j] < v) { isMin = false; break; }
    if (!isMin) continue;
    let before = v, after = v;
    for (let j = i; j >= 0 && d[i] - d[j] < 400; j--) before = Math.max(before, s[j] ?? before);
    for (let j = i; j < s.length && d[j] - d[i] < 400; j++) after = Math.max(after, s[j] ?? after);
    if (before - v < speedVal(20) || after - v < speedVal(20)) continue;
    if (out.length && d[i] - out[out.length - 1].d < 120) continue;
    out.push({ d: d[i], i, speed: v });
  }
  return out;
}

export async function mount(root, arg, query) {
  let ids = (query.laps || '').split(',').map(Number).filter(Boolean).slice(0, MAX_LAPS);
  if (!ids.length) return renderPicker(root, null, picked => { location.hash = `#/analysis?laps=${picked}`; });

  const recs = [];
  for (const id of ids) {
    try { recs.push(await api(`/laps/${id}/telemetry`)); } catch (e) { toast(`Lap ${id}: ${e.message}`); }
  }
  const usable = recs.filter(r => r.cols && r.cols.d?.length > 10);
  if (!usable.length) {
    root.append(h('div', { class: 'card empty' }, h('h3', {}, 'No telemetry for these laps'), 'Pick other laps from a ', h('a', { href: '#/sessions' }, 'session'), '.'));
    return;
  }
  const trackId = usable[0].lap.track_id;
  const track = await api(`/tracks/${trackId}`).catch(() => null);
  hand = handedness(track?.frame);
  const laps = usable.map((r, i) => ({ ...r, i, color: seriesColour(i), p: prepare(r) }));
  // Short, unambiguous labels: "L5", or "L3 Q" / "L3 R" when lap numbers collide.
  const SHORT = { race: 'R', qualifying: 'Q', practice: 'P', time_trial: 'TT', other: '' };
  for (const L of laps) {
    if (L.lap.guest) { L.label = guestLabel(L.lap); continue; }
    const n = L.lap.lap_number;
    const clash = laps.filter(o => o.lap.lap_number === n).length > 1;
    L.label = `L${n}` + (clash ? ` ${SHORT[L.lap.category] || ''}` : '');
  }
  for (const L of laps) if (laps.filter(o => o.label === L.label).length > 1) L.label += ` (${L.i + 1})`;
  const ref = laps[0];
  for (const L of laps) {
    L.p.delta = L === ref ? L.p.d.map(() => 0) : L.p.d.map((d, k) => { const tr = valueAt(ref.p.d, ref.p.t, d); return tr === null ? null : L.p.t[k] - tr; });
    // sideways distance from the reference line at the same lap distance (+ = left of it)
    L.p.line = L === ref ? L.p.d.map(() => 0) : L.p.d.map((d, k) => {
      const v = lateralOffset(ref.p, d, [L.p.x[k], L.p.z[k]]);
      return v === null || Math.abs(v) > 40 ? null : v;
    });
  }
  const cleanups = [];
  const group = new SyncGroup();
  const visible = Object.fromEntries(CHANNELS.map(c => [c.key, c.on && (!c.needs2 || laps.length > 1)]));

  // ---------------------------------------------------------------- header
  const setHash = list => { location.hash = `#/analysis?laps=${list.join(',')}`; };
  const chips = h('div', { class: 'lap-chips' });
  laps.forEach((L, i) => {
    const l = L.lap;
    chips.append(h('span', { class: 'lap-chip' }, h('span', { class: 'swatch', style: { background: L.color } }),
      h('b', { class: 'tnum' }, fmtLap(l.lap_time_ms)),
      h('span', { class: 'ink2' }, l.guest ? `${guestLabel(l)} · friend's lap${l.started_at ? ' · ' + fmtDate(l.started_at, false) : ''}`
        : `Lap ${l.lap_number} · ${sessionTypeName(l.session_type)} · ${fmtDate(l.started_at, false)}`),
      l.tyre_visual !== null ? tyreBadge(l.tyre_visual) : null,
      l.valid ? null : h('span', { class: 'badge bad' }, 'invalid'),
      i === 0 ? h('span', { class: 'badge info' }, 'reference') : h('button', { title: 'Make reference', onclick: () => setHash([l.id, ...ids.filter(x => x !== l.id)]) }, '⇤'),
      h('button', { title: 'Remove', onclick: () => setHash(ids.filter(x => x !== l.id)) }, '×')));
  });
  const addBtn = h('button', { class: 'btn', disabled: laps.length >= MAX_LAPS || null, onclick: () => {
    pickerBox.classList.toggle('hidden');
    if (!pickerBox.dataset.loaded) { pickerBox.dataset.loaded = '1'; renderPicker(pickerBox, { trackId, sessionId: ref.lap.session_id, exclude: ids }, id => setHash([...ids, id])); }
  } }, '+ Add lap');
  const pickerBox = h('div', { class: 'hidden', style: { marginBottom: '12px' } });
  root.append(h('div', { class: 'page-head' },
    h('div', {}, h('div', { class: 'small muted' }, h('a', { href: ref.lap.guest ? '#/sessions' : `#/session/${ref.lap.session_id}` }, ref.lap.guest ? 'Sessions' : 'Session'), ' / Telemetry'),
      h('h1', {}, `${trackName(trackId)} telemetry`),
      h('div', { class: 'sub' }, 'Drag across a chart to zoom, double-click to reset. Scroll the map to zoom, drag to pan.')),
    h('div', { class: 'row' }, addBtn, ...laps.filter(L => !L.lap.guest).map(L => h('a', { class: 'btn sm', href: `/api/export/lap/${L.lap.id}.csv` }, `CSV lap ${L.lap.lap_number}`)))),
  h('div', { class: 'row', style: { marginBottom: '12px' } }, chips), pickerBox);

  // channel toggles
  const toggles = h('div', { class: 'row small', style: { gap: '6px', marginBottom: '10px' } }, h('span', { class: 'muted' }, 'Channels:'));
  for (const c of CHANNELS) {
    if (c.needs2 && laps.length < 2) continue;
    if (c.optional && !laps.some(L => L.p[c.key].some(v => v !== null && v !== undefined))) continue;
    const b = h('button', { class: 'btn sm toggle' + (visible[c.key] ? ' on' : ''), 'aria-pressed': String(visible[c.key]), onclick: () => {
      visible[c.key] = !visible[c.key]; b.classList.toggle('on', visible[c.key]); b.setAttribute('aria-pressed', String(visible[c.key])); drawCharts();
    } }, c.title);
    toggles.append(b);
  }
  toggles.append(h('span', { class: 'grow' }), h('button', { class: 'btn sm', onclick: () => group.setDomain(null) }, 'Reset zoom'));

  const chartsCol = h('div', { class: 'card' });
  const side = h('div', { class: 'live-col' });
  root.append(toggles, h('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(300px, 420px)', gap: '12px', alignItems: 'start' }, class: 'analysis-grid' }, chartsCol, side));

  const markers = [];
  if (track?.s2_start) markers.push({ x: track.s2_start, label: 'S2' });
  if (track?.s3_start) markers.push({ x: track.s3_start, label: 'S3' });
  let charts = [];
  function drawCharts() {
    for (const c of charts) c.destroy();
    charts = [];
    chartsCol.innerHTML = '';
    const list = CHANNELS.filter(c => visible[c.key]);
    list.forEach((c, i) => {
      const ch = new LineChart(chartsCol, { group, title: c.title, height: c.height, format: c.format, step: c.step, yMin: c.yMin ?? null, yMax: c.yMax ?? null,
        yTicks: c.yTicks, zeroLine: c.zeroLine, symmetric: c.symmetric, showX: i === list.length - 1, markers, xFormat: v => v >= 1000 ? (v / 1000).toFixed(1) + ' km' : Math.round(v) + ' m' });
      ch.setSeries(laps.map(L => ({ name: L.label, color: L.color, x: L.p.d, y: L.p[c.key], width: laps.length > 1 ? 1.75 : 2, legend: true,
        dot: !(c.needs2 && L === ref) })).filter(s => !(c.needs2 && s.color === ref.color)));
      charts.push(ch);
    });
    if (!list.length) chartsCol.append(h('div', { class: 'empty' }, 'Turn on a channel above.'));
  }
  drawCharts();
  cleanups.push(() => charts.forEach(c => c.destroy()));

  // ---------------------------------------------------------------- map
  let follow = false;
  let colouring = 'lap';
  const followBtn = h('button', { class: 'btn sm toggle', onclick: () => { follow = !follow; followBtn.classList.toggle('on', follow); if (!follow) map.resetView(); } }, 'Follow cursor');
  const colourSeg = h('div', { class: 'segmented' },
    h('button', { class: 'on', onclick: e => setColouring('lap', e) }, 'By lap'),
    laps.length > 1 ? h('button', { onclick: e => setColouring('fastest', e), title: 'Each 50 m stretch coloured by the lap that was quickest through it' }, 'Fastest') : null,
    h('button', { onclick: e => setColouring('inputs', e) }, 'Ref inputs'));
  const mapCard = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Racing line', h('span', { class: 'right row', style: { gap: '6px' } }, colourSeg, followBtn)));
  side.append(mapCard);
  const map = new TrackMap(mapCard, { height: 380, interactive: true });
  cleanups.push(() => map.destroy());
  const legendRow = h('div', { class: 'row small', style: { marginTop: '8px', gap: '12px' } });
  mapCard.append(legendRow);
  if (track?.outline) map.setOutline(track.outline, { s2: track.s2_start, s3: track.s3_start, frame: track.frame });
  function setColouring(mode, e) {
    colouring = mode;
    for (const b of colourSeg.children) b.classList.toggle('on', b === e.currentTarget);
    drawLines();
  }
  function drawLines() {
    legendRow.innerHTML = '';
    if (colouring === 'lap') {
      map.setLines(laps.map(L => ({ x: L.p.x, z: L.p.z, color: L.color, width: 2 })).reverse());
      for (const L of laps) legendRow.append(h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: L.color, height: '3px', width: '14px' } }), L.label));
    } else if (colouring === 'fastest') {
      const { colors, share } = fastestBySegment(laps, ref, 50);
      map.setLines([{ x: ref.p.x, z: ref.p.z, colors, width: 4 }]);
      for (const L of laps) legendRow.append(h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: L.color, height: '3px', width: '14px' } }),
        `${L.label} fastest on ${fmtNum(share.get(L) * 100, 0)}%`));
    } else {
      const thr = cssVar('--throttle'), brk = cssVar('--brake'), coast = cssVar('--muted');
      const colors = ref.p.d.map((_, k) => (ref.p.brk[k] > 5 ? brk : ref.p.thr[k] > 90 ? thr : coast));
      map.setLines([{ x: ref.p.x, z: ref.p.z, colors, width: 3 }]);
      for (const [c, t] of [[thr, 'Full throttle'], [coast, 'Partial / coasting'], [brk, 'Braking']]) legendRow.append(h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: c, height: '3px', width: '14px' } }), t));
    }
  }
  drawLines();
  group.on((kind, v) => {
    if (kind !== 'cursor') return;
    if (v === null) { map.setMarkers([]); return; }
    const ms = laps.map(L => ({ x: valueAt(L.p.d, L.p.x, v), z: valueAt(L.p.d, L.p.z, v), color: L.color, r: 6 }));
    map.setMarkers(ms);
    if (follow && ms[0].x !== null) map.focus(ms[0].x, ms[0].z, 8);
  });

  // ---------------------------------------------------------------- sectors & summary
  const secCard = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Lap comparison'));
  side.append(secCard);
  const tb = h('tbody');
  const rowsDef = [
    ['Lap time', L => L.lap.lap_time_ms, fmtLap, true],
    ['Sector 1', L => L.lap.s1_ms, fmtSector, true],
    ['Sector 2', L => L.lap.s2_ms, fmtSector, true],
    ['Sector 3', L => L.lap.s3_ms, fmtSector, true],
    ['Top speed', L => Math.max(...L.p.spd.filter(v => v !== null)), v => fmtNum(v, 0) + ' ' + speedUnit(), false],
    ['Full throttle', L => pctWhere(L.p, k => L.p.thr[k] >= 98), v => fmtNum(v, 1) + '%', false],
    ['Braking', L => pctWhere(L.p, k => L.p.brk[k] > 5), v => fmtNum(v, 1) + '%', false],
    ['Coasting', L => pctWhere(L.p, k => L.p.brk[k] <= 5 && L.p.thr[k] < 10), v => fmtNum(v, 1) + '%', false],
    ['Gear shifts', L => L.p.gear.reduce((n, g, k) => n + (k && g !== L.p.gear[k - 1] ? 1 : 0), 0), v => String(v), false],
  ];
  for (const [label, fn, fmt, isTime] of rowsDef) {
    const base = fn(ref);
    tb.append(h('tr', {}, h('td', { class: 'muted' }, label), ...laps.map(L => {
      const v = fn(L);
      const diff = L === ref || !isTime || !v || !base ? null : v - base;
      return h('td', { class: 'num' }, fmt(v), diff !== null ? h('div', { class: 'small ' + deltaClass(diff) }, fmtDelta(diff)) : null);
    })));
  }
  secCard.append(h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
    h('thead', {}, h('tr', {}, h('th', {}, ''), ...laps.map(L => h('th', { class: 'num' }, h('span', { class: 'row', style: { gap: '5px', justifyContent: 'flex-end' } }, h('i', { class: 'swatch', style: { background: L.color } }), L.label))))), tb)));

  // ---------------------------------------------------------------- corners: racing line through every corner
  const corners = analyseCorners(laps, ref);
  map.setLabels(corners.map(c => ({ x: c.apexPos?.[0], z: c.apexPos?.[1], text: c.name })).filter(l => l.x !== undefined));
  const zoomTo = c => {
    group.setDomain([Math.max(0, c.lo - 40), c.hi + 40]);
    if (c.apexPos) map.focus(c.apexPos[0], c.apexPos[1], 7);
    chartsCol.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const cornerSection = h('div', { class: 'card', style: { marginTop: '12px' } });
  root.append(cornerSection);
  const miniMaps = [];
  cleanups.push(() => miniMaps.forEach(m => m.map.destroy()));
  if (!corners.length) {
    cornerSection.append(h('div', { class: 'card-title' }, 'Corners'), h('div', { class: 'muted small' }, 'Not enough speed variation to detect corners.'));
  } else {
    let order = 'track', scale = laps.length > 1 ? 4 : 1;
    const seg = (opts, get, set) => {
      const el = h('div', { class: 'segmented' }, ...opts.map(([v, label]) => h('button', { class: get() === v ? 'on' : '', onclick: e => {
        set(v); for (const b of el.children) b.classList.toggle('on', b === e.currentTarget);
      } }, label)));
      return el;
    };
    const grid = h('div', { class: 'corner-grid' });
    const cards = corners.map(c => cornerCard(c, laps, ref, track, zoomTo, miniMaps));
    const render = () => {
      const list = order === 'track' ? cards : [...cards].sort((a, b) => b.c.spread - a.c.spread);
      grid.replaceChildren(...list.map(x => x.el));
      for (const m of miniMaps) m.draw(scale);
    };
    cornerSection.append(
      h('div', { class: 'card-title' }, `Racing line · ${corners.length} corners`,
        h('span', { class: 'right row', style: { gap: '6px' } },
          laps.length > 1 ? seg([['track', 'Track order'], ['diff', 'Biggest difference']], () => order, v => { order = v; render(); }) : null,
          laps.length > 1 ? seg([[4, 'Differences ×4'], [1, 'True scale']], () => scale, v => { scale = v; render(); }) : null)),
      h('div', { class: 'small muted', style: { marginBottom: '10px' } },
        laps.length > 1
          ? `Each lap's line through the corner against the reference (${ref.label}), compared at the same distance around the lap. Sideways differences are drawn 4× larger unless you pick True scale; the numbers are always real metres. ■ braking point · ● apex (minimum speed). Click a corner to zoom the charts and map to it.`
          : 'Your line through each corner. ■ braking point · ● apex (minimum speed). Add a lap to compare lines. Click a corner to zoom the charts and map to it.'),
      grid);
    render();
    group.on((kind, v) => {
      if (kind !== 'cursor') return;
      for (const m of miniMaps) m.cursor(v);
    });
  }

  const mq = matchMedia('(max-width: 1100px)');
  const applyLayout = () => { const g = root.querySelector('.analysis-grid'); if (g) g.style.gridTemplateColumns = mq.matches ? 'minmax(0,1fr)' : 'minmax(0, 1fr) minmax(300px, 420px)'; };
  mq.addEventListener('change', applyLayout); applyLayout();
  cleanups.push(() => mq.removeEventListener('change', applyLayout));
  return () => cleanups.forEach(fn => fn());
}

// ------------------------------------------------------------------ racing line geometry
const posAt = (p, d) => {
  const x = valueAt(p.d, p.x, d), z = valueAt(p.d, p.z, d);
  return x === null || z === null ? null : [x, z];
};

function headingAt(p, d) {
  const a = posAt(p, d - 4), b = posAt(p, d + 4);
  if (!a || !b) return null;
  const hx = b[0] - a[0], hz = b[1] - a[1], n = Math.hypot(hx, hz);
  return n > 0.5 ? [hx / n, hz / n] : null;
}

// +1 when game coordinates drawn with +Z down are the right way round; -1 when lining the track up with its
// real outline showed them mirrored, which flips left and right below.
let hand = 1;
const handedness = f => (f && f.a * f.d - f.b * f.c < 0 ? -1 : 1);

// Signed sideways distance (m) of point q from the reference line at lap distance d; + = left of it,
// as seen from the car. Seen from above +X is right and +Z is down (see TrackMap).
function lateralOffset(p, d, q) {
  const o = posAt(p, d), hd = headingAt(p, d);
  if (!o || !hd || !q || q[0] === null || q[1] === null) return null;
  return hand * (hd[1] * (q[0] - o[0]) - hd[0] * (q[1] - o[1]));
}

function fastestBySegment(laps, ref, seg) {
  const end = Math.min(...laps.map(L => L.p.d[L.p.d.length - 1]));
  const winners = [];
  const won = new Map(laps.map(L => [L, 0]));
  for (let s = 0; s * seg < end; s++) {
    const a = s * seg, b = Math.min(end, a + seg);
    let best = null, bestDt = Infinity;
    for (const L of laps) {
      const ta = valueAt(L.p.d, L.p.t, Math.max(a, L.p.d[0])), tb = valueAt(L.p.d, L.p.t, b);
      if (ta === null || tb === null) continue;
      if (tb - ta < bestDt) { bestDt = tb - ta; best = L; }
    }
    winners.push(best);
    if (best) won.set(best, won.get(best) + 1);
  }
  const total = winners.filter(Boolean).length || 1;
  const muted = cssVar('--muted');
  return {
    colors: ref.p.d.map(d => winners[Math.floor(d / seg)]?.color ?? muted),
    share: new Map([...won].map(([L, n]) => [L, n / total])),
  };
}

// Braking point, apex, line and exit of every lap through every corner of the reference lap.
function analyseCorners(laps, ref) {
  const found = findCorners(ref.p);
  return found.map((c, n) => {
    const prev = found[n - 1], next = found[n + 1];
    const lo = Math.max(ref.p.d[0], c.d - 260, prev ? (prev.d + c.d) / 2 : -Infinity);
    const hi = Math.min(ref.p.d[ref.p.d.length - 1], c.d + 200, next ? (c.d + next.d) / 2 : Infinity);
    const hIn = headingAt(ref.p, c.d - 40), hOut = headingAt(ref.p, c.d + 40);
    const turn = hIn && hOut ? hand * (hIn[1] * hOut[0] - hIn[0] * hOut[1]) : 0;  // > 0: turning left
    const per = new Map(laps.map(L => [L, cornerStats(L, ref, c.d, lo, hi)]));
    const r = per.get(ref);
    for (const L of laps) {
      const s = per.get(L);
      if (L === ref) continue;
      if (r.apexD !== null) {
        const off = lateralOffset(ref.p, r.apexD, posAt(L.p, r.apexD));
        s.apexOffset = off === null ? null : Math.abs(off) < 0.25 || !turn ? 0 : (Math.sign(off) === Math.sign(turn) ? -1 : 1) * Math.abs(off);  // + wider, - tighter
      }
      const a = valueAt(L.p.d, L.p.delta, lo), b = valueAt(L.p.d, L.p.delta, hi);
      s.dt = a === null || b === null ? null : (b - a) * 1000;
    }
    const spread = Math.max(0, ...laps.filter(L => L !== ref).map(L => Math.abs(per.get(L).dt ?? 0)));
    return { name: `C${n + 1}`, d: c.d, lo, hi, dir: turn > 0.05 ? 'Left' : turn < -0.05 ? 'Right' : '', per, spread,
             apexPos: r.apexD !== null ? posAt(ref.p, r.apexD) : posAt(ref.p, c.d) };
  });
}

function cornerStats(L, ref, d, lo, hi) {
  const p = L.p;
  let apexD = null, minSpd = null;
  for (let k = 0; k < p.d.length; k++) {
    if (p.d[k] < d - 90) continue;
    if (p.d[k] > d + 90) break;
    if (p.spd[k] !== null && (minSpd === null || p.spd[k] < minSpd)) { minSpd = p.spd[k]; apexD = p.d[k]; }
  }
  let brakeD = null, throttleD = null;
  for (let k = 1; k < p.d.length && apexD !== null; k++) {
    if (p.d[k] < lo) continue;
    if (p.d[k] > apexD) break;
    if (p.brk[k] > 10 && !(p.brk[k - 1] > 10)) { brakeD = p.d[k]; break; }
  }
  for (let k = 0; k < p.d.length && apexD !== null; k++) {
    if (p.d[k] <= apexD) continue;
    if (p.d[k] > hi + 150) break;
    if (p.thr[k] >= 90) { throttleD = p.d[k]; break; }
  }
  const t0 = valueAt(p.d, p.t, lo), t1 = valueAt(p.d, p.t, hi);
  return { apexD, minSpd, brakeD, throttleD, exitSpd: valueAt(p.d, p.spd, hi),
           time: t0 === null || t1 === null ? null : t1 - t0, apexOffset: L === ref ? 0 : null, dt: null };
}

function cornerCard(c, laps, ref, track, zoomTo, miniMaps) {
  const r = c.per.get(ref);
  const mapBox = h('div');
  const head = h('div', { class: 'corner-head' }, h('b', {}, c.name),
    h('span', { class: 'muted small' }, [c.dir, `${fmtNum(c.d, 0)} m`].filter(Boolean).join(' · ')),
    h('span', { class: 'grow' }),
    ...laps.filter(L => L !== ref && c.per.get(L).dt !== null).map(L => {
      const dt = c.per.get(L).dt;
      return h('span', { class: 'row small', style: { gap: '4px' } }, h('i', { class: 'swatch', style: { background: L.color, height: '3px', width: '10px' } }),
        h('span', { class: 'tnum ' + deltaClass(dt) }, fmtDelta(dt)));
    }));
  const metres = (v, more, less) => v === null ? '–' : Math.abs(v) < 1 ? 'same' : `${fmtNum(Math.abs(v), 0)} m ${v > 0 ? more : less}`;
  const speedCell = (v, rv) => v === null ? '–' : [fmtNum(v, 0), rv !== null && Math.round(v - rv) !== 0
    ? h('span', { class: 'small ' + (v > rv ? 'faster' : 'slower') }, ` ${v > rv ? '+' : '−'}${fmtNum(Math.abs(v - rv), 0)}`) : null];
  const rows = [
    ['Time', L => L === ref ? (r.time !== null ? r.time.toFixed(2) + ' s' : '–')
      : c.per.get(L).dt === null ? '–' : h('span', { class: deltaClass(c.per.get(L).dt) }, fmtDelta(c.per.get(L).dt))],
    ['Braking', L => { const s = c.per.get(L); return L === ref ? (s.brakeD !== null ? `${fmtNum(s.brakeD, 0)} m` : 'no braking')
      : s.brakeD === null || r.brakeD === null ? (s.brakeD === null ? 'no braking' : `${fmtNum(s.brakeD, 0)} m`) : metres(s.brakeD - r.brakeD, 'later', 'earlier'); }],
    [`Min ${speedUnit()}`, L => speedCell(c.per.get(L).minSpd, L === ref ? null : r.minSpd)],
    ['Line at apex', L => { const o = c.per.get(L).apexOffset; return L === ref ? 'reference' : o === null ? '–' : Math.abs(o) < 0.25 ? 'same' : `${fmtNum(Math.abs(o), 1)} m ${o > 0 ? 'wider' : 'tighter'}`; }],
    ['Full throttle', L => { const s = c.per.get(L); return L === ref || r.throttleD === null ? (s.throttleD !== null ? `${fmtNum(s.throttleD, 0)} m` : '–')
      : s.throttleD === null ? '–' : metres(s.throttleD - r.throttleD, 'later', 'earlier'); }],
    [`Exit ${speedUnit()}`, L => speedCell(c.per.get(L).exitSpd, L === ref ? null : r.exitSpd)],
  ].filter(([label]) => laps.length > 1 || label !== 'Line at apex');
  const table = h('table', { class: 'data corner-table' },
    laps.length > 1 ? h('thead', {}, h('tr', {}, h('th', {}, ''), ...laps.map(L => h('th', { class: 'num' },
      h('span', { class: 'row', style: { gap: '4px', justifyContent: 'flex-end', flexWrap: 'nowrap' } }, h('i', { class: 'swatch', style: { background: L.color, height: '3px', width: '10px' } }), L.label))))) : null,
    h('tbody', {}, ...rows.map(([label, fn]) => h('tr', {}, h('td', { class: 'muted' }, label), ...laps.map(L => h('td', { class: 'num' }, fn(L)))))));
  const el = h('div', { class: 'corner-card', role: 'button', tabindex: '0', title: `Zoom the charts and map to ${c.name}`,
    onclick: () => zoomTo(c), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); zoomTo(c); } } },
    head, mapBox, h('div', { class: 'table-wrap' }, table));

  // mini map: the corner only, every lap's line, optionally with the sideways differences exaggerated
  const map = new TrackMap(mapBox, { height: 200 });
  const apex = r.apexD ?? c.d;
  let vlo = Math.max(c.lo, Math.min(r.brakeD ?? apex - 80, apex - 80) - 25);
  let vhi = Math.min(c.hi, Math.max(apex + 80, (r.throttleD ?? apex) + 30));
  if (vhi - vlo < 160) { vlo = apex - 80; vhi = apex + 80; }
  if (track?.outline) {
    const crop = track.outline.filter(p => p[0] >= vlo - 10 && p[0] <= vhi + 10);
    if (crop.length > 2) map.setOutline(crop, { partial: true, marks: false, s2: track.s2_start, s3: track.s3_start, frame: track.frame });
  }
  const lineOf = (L, scale) => {
    const xs = [], zs = [];
    for (let k = 0; k < L.p.d.length; k++) {
      const d = L.p.d[k];
      if (d < vlo) continue;
      if (d > vhi) break;
      let x = L.p.x[k], z = L.p.z[k];
      if (scale !== 1 && L !== ref && x !== null) {
        const o = posAt(ref.p, d);
        if (o) { x = o[0] + (x - o[0]) * scale; z = o[1] + (z - o[1]) * scale; }
      }
      xs.push(x); zs.push(z);
    }
    return { xs, zs };
  };
  let scaleNow = 1, statics = [];
  const at = (L, d, scale) => {
    const q = posAt(L.p, d);
    if (!q || scale === 1 || L === ref) return q;
    const o = posAt(ref.p, d);
    return o ? [o[0] + (q[0] - o[0]) * scale, o[1] + (q[1] - o[1]) * scale] : q;
  };
  const mini = {
    map,
    draw(scale) {
      scaleNow = scale;
      map.setLines(laps.map(L => { const { xs, zs } = lineOf(L, scale); return { x: xs, z: zs, color: L.color, width: L === ref && laps.length > 1 ? 3 : 2 }; }));  // reference underneath
      statics = [];
      for (const L of laps) {
        const s = c.per.get(L);
        const b = s.brakeD !== null ? at(L, s.brakeD, scale) : null, a = s.apexD !== null ? at(L, s.apexD, scale) : null;
        if (b) statics.push({ x: b[0], z: b[1], color: L.color, r: 3.5, shape: 'square', ring: 1.5 });
        if (a) statics.push({ x: a[0], z: a[1], color: L.color, r: 4, ring: 1.5 });
      }
      map.setMarkers(statics);
    },
    cursor(v) {
      if (v === null || v < vlo || v > vhi) { if (map.markers !== statics) map.setMarkers(statics); return; }
      const live = laps.map(L => { const q = at(L, v, scaleNow); return q ? { x: q[0], z: q[1], color: L.color, r: 5 } : null; }).filter(Boolean);
      map.setMarkers([...statics, ...live]);
    },
  };
  miniMaps.push(mini);
  return { c, el };
}

function pctWhere(p, pred) {
  let tot = 0, hit = 0;
  for (let k = 1; k < p.d.length; k++) { const dd = p.d[k] - p.d[k - 1]; tot += dd; if (pred(k)) hit += dd; }
  return tot ? hit / tot * 100 : 0;
}

// ------------------------------------------------------------------ lap picker
async function renderPicker(root, opts, onPick) {
  const box = h('div', { class: 'card' });
  root.append(box);
  if (!opts) {
    root.prepend(h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Telemetry'),
      h('div', { class: 'sub' }, 'Pick a lap to analyse - speed, throttle, brake, gear, steering, RPM, racing line and corner-by-corner deltas.'))));
  }
  const tracks = await api('/tracks');
  if (!tracks.length) { box.append(h('div', { class: 'empty' }, h('h3', {}, 'No laps recorded yet'), 'Drive a few laps (or run the demo from Settings) and come back.')); return; }
  const sel = h('select', {}, ...tracks.map(t => h('option', { value: t.track_id }, `${t.name} (${t.laps} laps)`)));
  const catSel = h('select', {}, h('option', { value: '' }, 'All session types'), ...Object.entries(CATEGORY_NAMES).map(([k, v]) => h('option', { value: k }, v)));
  const list = h('div');
  box.append(h('div', { class: 'row', style: { marginBottom: '10px' } }, h('b', {}, opts ? 'Add a lap' : 'Fastest laps'), h('span', { class: 'grow' }),
    importButton(() => load()), sel, catSel), list);
  if (opts?.trackId !== undefined) { sel.value = String(opts.trackId); sel.disabled = true; }
  const load = async () => {
    const t = await api(`/tracks/${sel.value}` + (catSel.value ? `?category=${catSel.value}` : ''));
    let laps = t.top_laps.filter(l => !(opts?.exclude || []).includes(l.id));
    if (opts?.sessionId) {
      const s = await api(`/sessions/${opts.sessionId}`);
      const own = s.laps.filter(l => l.lap_time_ms > 0 && l.sample_count && !(opts.exclude || []).includes(l.id) && !laps.some(x => x.id === l.id))
        .map(l => ({ ...l, session_type: s.session.session_type }));
      laps = [...own.map(l => ({ ...l, _thisSession: true })), ...laps];
    }
    const friends = (await api(`/guest-laps?track=${sel.value}`).catch(() => [])).filter(l => !(opts?.exclude || []).includes(l.id));
    laps = [...laps.filter(l => l._thisSession), ...friends, ...laps.filter(l => !l._thisSession)];
    list.innerHTML = '';
    if (!laps.length) { list.append(h('div', { class: 'empty' }, 'No other valid laps for this track yet.')); return; }
    const best = Math.min(...t.top_laps.map(l => l.lap_time_ms));
    const tb = h('tbody');
    for (const l of laps.slice(0, 60)) {
      tb.append(h('tr', { class: 'click', onclick: () => onPick(l.id) },
        h('td', { class: 'num tnum' }, h('b', {}, fmtLap(l.lap_time_ms))),
        h('td', { class: 'num muted' }, best ? fmtDelta(l.lap_time_ms - best) : ''),
        h('td', {}, l.guest ? [guestLabel(l), h('span', { class: 'badge', style: { marginLeft: '6px' } }, 'friend')] : sessionTypeName(l.session_type),
          l._thisSession ? h('span', { class: 'badge info', style: { marginLeft: '6px' } }, 'this session') : null),
        h('td', { class: 'num' }, l.guest ? '–' : 'Lap ' + l.lap_number),
        h('td', {}, l.tyre_visual !== null && l.tyre_visual !== undefined ? tyreBadge(l.tyre_visual) : ''),
        h('td', { class: 'muted' }, fmtDate(l.guest ? l.imported_at : l.recorded_at)),
        h('td', {}, l.valid ? '' : h('span', { class: 'badge bad' }, 'invalid'), l.telemetry_complete === 0 ? h('span', { class: 'badge' }, 'partial') : ''),
        h('td', {}, h('button', { class: 'btn sm' }, opts ? 'Add' : 'Analyse'))));
    }
    list.append(h('div', { class: 'table-wrap', style: { maxHeight: '420px', overflowY: 'auto' } }, h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, ...['Time', 'Gap', 'Session', 'Lap', 'Tyre', 'Date', '', ''].map((x, i) => h('th', { class: i < 2 || i === 3 ? 'num' : '' }, x)))), tb)));
  };
  sel.addEventListener('change', load);
  catSel.addEventListener('change', load);
  await load();
}
