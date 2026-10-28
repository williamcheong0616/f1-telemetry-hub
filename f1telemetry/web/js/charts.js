// Lightweight canvas/SVG charts tuned for telemetry: synced crosshair, drag-to-zoom,
// legend values at the cursor, track maps with zoom/pan, G-force circle, rolling traces.
import { h, cssVar } from './util.js';

const DPR = () => window.devicePixelRatio || 1;

function niceStep(range, count) {
  const raw = range / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const n = raw / mag;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
}
export function niceTicks(min, max, count = 4) {
  if (!(isFinite(min) && isFinite(max)) || min === max) return [min || 0];
  const step = niceStep(max - min, count);
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) out.push(+v.toFixed(10));
  return out;
}
function bisect(arr, x) {
  let lo = 0, hi = arr.length - 1;
  if (hi < 0) return -1;
  if (x <= arr[0]) return 0;
  if (x >= arr[hi]) return hi;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] <= x) lo = mid; else hi = mid;
  }
  return lo;
}
export function valueAt(xs, ys, x, step = false) {
  if (!xs || !xs.length || x < xs[0] || x > xs[xs.length - 1]) return null;
  const i = bisect(xs, x);
  if (step || i >= xs.length - 1) return ys[i];
  const x0 = xs[i], x1 = xs[i + 1], y0 = ys[i], y1 = ys[i + 1];
  if (y0 === null || y1 === null || y0 === undefined || y1 === undefined) return y0 ?? y1 ?? null;
  return x1 === x0 ? y0 : y0 + (y1 - y0) * (x - x0) / (x1 - x0);
}

let tipEl = null;
export function showTip(html, x, y) {
  if (!tipEl) { tipEl = h('div', { class: 'tooltip' }); document.body.append(tipEl); }
  tipEl.innerHTML = html;
  tipEl.style.display = 'block';
  const r = tipEl.getBoundingClientRect();
  let left = x + 14, top = y + 14;
  if (left + r.width > innerWidth - 8) left = x - r.width - 14;
  if (top + r.height > innerHeight - 8) top = y - r.height - 14;
  tipEl.style.left = left + 'px';
  tipEl.style.top = top + 'px';
}
export function hideTip() { if (tipEl) tipEl.style.display = 'none'; }

// ------------------------------------------------------------------ sync group
export class SyncGroup {
  constructor() { this.charts = new Set(); this.domain = null; this.cursor = null; this.listeners = []; }
  add(c) { this.charts.add(c); }
  remove(c) { this.charts.delete(c); }
  fullDomain() {
    let lo = Infinity, hi = -Infinity;
    for (const c of this.charts) { const d = c.dataExtent(); if (d) { lo = Math.min(lo, d[0]); hi = Math.max(hi, d[1]); } }
    return isFinite(lo) ? [lo, hi] : [0, 1];
  }
  setCursor(x) {
    this.cursor = x;
    for (const c of this.charts) c.drawOverlay();
    for (const fn of this.listeners) fn('cursor', x);
  }
  setDomain(d) {
    this.domain = d;
    for (const c of this.charts) c.draw();
    for (const fn of this.listeners) fn('domain', d);
  }
  on(fn) { this.listeners.push(fn); }
}

// ------------------------------------------------------------------ line chart
export class LineChart {
  constructor(parent, opts = {}) {
    this.o = Object.assign({ height: 130, title: '', format: v => v.toFixed(0), xFormat: v => v.toFixed(0), showX: true,
      step: false, yMin: null, yMax: null, tooltip: 'legend', invertY: false, padTop: 8, markers: [], xLabel: '' }, opts);
    this.group = this.o.group || new SyncGroup();
    this.group.add(this);
    this.series = [];
    this.el = h('div', { class: 'chart-block' });
    this.head = h('div', { class: 'chart-head' });
    if (this.o.title || this.o.tooltip === 'legend') this.el.append(this.head);
    this.box = h('div', { class: 'chart', style: { height: this.o.height + 'px' } });
    this.base = h('canvas');
    this.over = h('canvas', { class: 'overlay' });
    this.box.append(this.base, this.over);
    this.el.append(this.box);
    parent.append(this.el);
    this.m = { l: 58, r: 10, t: this.o.padTop, b: this.o.showX ? 20 : 4 };  // l fits labels like "300 km/h"
    this._bind();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.box);
  }
  destroy() { this.ro.disconnect(); this.group.remove(this); this.el.remove(); hideTip(); }
  setSeries(series) { this.series = series.filter(Boolean); this.renderHead(); this.draw(); }
  dataExtent() {
    let lo = Infinity, hi = -Infinity;
    for (const s of this.series) if (s.x && s.x.length) { lo = Math.min(lo, s.x[0]); hi = Math.max(hi, s.x[s.x.length - 1]); }
    return isFinite(lo) ? [lo, hi] : null;
  }
  renderHead() {
    this.head.innerHTML = '';
    if (this.o.title) this.head.append(h('span', { class: 'title' }, this.o.title));
    this.legendEls = [];
    if (this.o.tooltip !== 'legend') return;
    for (const s of this.series) {
      if (s.legend === false) { this.legendEls.push(null); continue; }
      const val = h('b', {}, '');
      const item = h('span', { class: 'lg' }, h('i', { style: { background: s.color } }), s.name ? s.name + ' ' : '', val);
      this.legendEls.push(val);
      this.head.append(item);
    }
  }
  resize() {
    const r = this.box.getBoundingClientRect();
    this.w = Math.max(50, r.width); this.hgt = Math.max(30, r.height);
    for (const c of [this.base, this.over]) { c.width = Math.round(this.w * DPR()); c.height = Math.round(this.hgt * DPR()); }
    this.draw();
  }
  domainX() { return this.group.domain || this.group.fullDomain(); }
  computeY(x0, x1) {
    if (this.o.yMin !== null && this.o.yMax !== null) return [this.o.yMin, this.o.yMax];
    let lo = Infinity, hi = -Infinity;
    for (const s of this.series) {
      if (!s.x) continue;
      const i0 = Math.max(0, bisect(s.x, x0)), i1 = Math.min(s.x.length - 1, bisect(s.x, x1) + 1);
      for (let i = i0; i <= i1; i++) { const v = s.y[i]; if (v === null || v === undefined) continue; if (v < lo) lo = v; if (v > hi) hi = v; }
    }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (this.o.yMin !== null) lo = this.o.yMin;
    if (this.o.yMax !== null) hi = this.o.yMax;
    if (this.o.symmetric) { const a = Math.max(Math.abs(lo), Math.abs(hi)) || 1; lo = -a; hi = a; }
    if (hi === lo) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.06;
    return [this.o.yMin !== null ? lo : lo - pad, this.o.yMax !== null ? hi : hi + pad];
  }
  sx(x) { const [a, b] = this._xd; return this.m.l + (x - a) / (b - a || 1) * (this.w - this.m.l - this.m.r); }
  sy(y) {
    const [a, b] = this._yd; const top = this.m.t, bot = this.hgt - this.m.b;
    const f = (y - a) / (b - a || 1);
    return this.o.invertY ? top + f * (bot - top) : bot - f * (bot - top);
  }
  ix(px) { const [a, b] = this._xd; return a + (px - this.m.l) / (this.w - this.m.l - this.m.r) * (b - a); }
  draw() {
    if (!this.w) return;
    const ctx = this.base.getContext('2d');
    ctx.setTransform(DPR(), 0, 0, DPR(), 0, 0);
    ctx.clearRect(0, 0, this.w, this.hgt);
    const [x0, x1] = this._xd = this.domainX();
    this._yd = this.computeY(x0, x1);
    const grid = cssVar('--grid'), muted = cssVar('--muted'), axis = cssVar('--axis');
    ctx.font = '11px system-ui, sans-serif';
    ctx.lineWidth = 1;
    // y grid + labels
    const yt = this.o.yTicks || niceTicks(this._yd[0], this._yd[1], this.hgt < 100 ? 2 : 3);
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (const v of yt) {
      if (v < Math.min(...this._yd) || v > Math.max(...this._yd)) continue;
      const y = Math.round(this.sy(v)) + 0.5;
      ctx.strokeStyle = grid; ctx.beginPath(); ctx.moveTo(this.m.l, y); ctx.lineTo(this.w - this.m.r, y); ctx.stroke();
      ctx.fillStyle = muted; ctx.fillText(this.o.format(v), this.m.l - 6, y);
    }
    // x labels
    if (this.o.showX) {
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      let xt = this.o.xTicks || niceTicks(x0, x1, Math.max(2, Math.floor(this.w / 110)));
      if (this.o.xInt && !this.o.xTicks) xt = xt.filter(Number.isInteger);  // index axes (laps, sessions)
      ctx.fillStyle = muted;
      for (const v of xt) { const x = this.sx(v); if (x < this.m.l - 1 || x > this.w - this.m.r + 1) continue; ctx.fillText(this.o.xFormat(v), x, this.hgt - this.m.b + 5); }
      ctx.strokeStyle = axis; ctx.beginPath(); ctx.moveTo(this.m.l, this.hgt - this.m.b + 0.5); ctx.lineTo(this.w - this.m.r, this.hgt - this.m.b + 0.5); ctx.stroke();
    }
    if (this.o.zeroLine) {
      const y = Math.round(this.sy(0)) + 0.5;
      ctx.strokeStyle = axis; ctx.beginPath(); ctx.moveTo(this.m.l, y); ctx.lineTo(this.w - this.m.r, y); ctx.stroke();
    }
    // markers (e.g. sector boundaries)
    for (const mk of this.o.markers || []) {
      const x = Math.round(this.sx(mk.x)) + 0.5;
      if (x < this.m.l || x > this.w - this.m.r) continue;
      ctx.strokeStyle = axis; ctx.beginPath(); ctx.moveTo(x, this.m.t); ctx.lineTo(x, this.hgt - this.m.b); ctx.stroke();
      if (mk.label) { ctx.fillStyle = muted; ctx.textAlign = 'left'; ctx.textBaseline = 'top'; ctx.fillText(mk.label, x + 3, this.m.t); }
    }
    // series
    ctx.save();
    ctx.beginPath(); ctx.rect(this.m.l, 0, this.w - this.m.l - this.m.r, this.hgt); ctx.clip();
    const ordered = [...this.series].sort((a, b) => (a.z || 0) - (b.z || 0));
    for (const s of ordered) this._drawSeries(ctx, s, x0, x1);
    ctx.restore();
    this.drawOverlay();
  }
  _drawSeries(ctx, s, x0, x1) {
    if (!s.x || s.x.length < 1) return;
    const xs = s.x, ys = s.y;
    let i0 = Math.max(0, bisect(xs, x0) - 1), i1 = Math.min(xs.length - 1, bisect(xs, x1) + 1);
    ctx.strokeStyle = s.color; ctx.lineWidth = s.width || 2; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    ctx.globalAlpha = s.alpha ?? 1;
    const step = this.o.step || s.step;
    const dense = (i1 - i0) > (this.w * 2.5);
    ctx.beginPath();
    let pen = false, lastPx = null, lastPy = null;
    let bucketPx = null, bMin = 0, bMax = 0, bLast = 0;
    const flush = () => {
      if (bucketPx === null) return;
      if (!pen) { ctx.moveTo(bucketPx, bMin); pen = true; } else ctx.lineTo(bucketPx, bMin);
      ctx.lineTo(bucketPx, bMax); ctx.lineTo(bucketPx, bLast);
    };
    for (let i = i0; i <= i1; i++) {
      const v = ys[i];
      if (v === null || v === undefined) { if (dense) flush(); bucketPx = null; pen = false; continue; }
      const px = this.sx(xs[i]), py = this.sy(v);
      if (dense) {
        const bp = Math.round(px);
        if (bp !== bucketPx) { flush(); bucketPx = bp; bMin = bMax = bLast = py; }
        else { if (py < bMin) bMin = py; if (py > bMax) bMax = py; bLast = py; }
        continue;
      }
      if (!pen) { ctx.moveTo(px, py); pen = true; }
      else if (step) { ctx.lineTo(px, lastPy); ctx.lineTo(px, py); }
      else ctx.lineTo(px, py);
      lastPx = px; lastPy = py;
    }
    if (dense) flush();
    if (s.dash) ctx.setLineDash(s.dash);
    ctx.stroke();
    ctx.setLineDash([]);
    if (s.area) {
      ctx.lineTo(this.sx(xs[i1]), this.sy(Math.max(this._yd[0], 0)));
      ctx.lineTo(this.sx(xs[i0]), this.sy(Math.max(this._yd[0], 0)));
      ctx.closePath(); ctx.globalAlpha = 0.1; ctx.fillStyle = s.color; ctx.fill();
    }
    if (s.points) {
      const ring = cssVar('--surface');
      for (let i = i0; i <= i1; i++) {
        const v = ys[i]; if (v === null || v === undefined) continue;
        const px = this.sx(xs[i]), py = this.sy(v);
        const pc = s.pointColor ? s.pointColor(i) : s.color;
        ctx.globalAlpha = 1; ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI * 2);
        ctx.fillStyle = pc; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = ring; ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }
  drawOverlay() {
    if (!this.w || !this._xd) return;
    const ctx = this.over.getContext('2d');
    ctx.setTransform(DPR(), 0, 0, DPR(), 0, 0);
    ctx.clearRect(0, 0, this.w, this.hgt);
    if (this.drag) {
      const a = Math.min(this.drag.a, this.drag.b), b = Math.max(this.drag.a, this.drag.b);
      ctx.fillStyle = cssVar('--s1'); ctx.globalAlpha = 0.12; ctx.fillRect(a, this.m.t, b - a, this.hgt - this.m.t - this.m.b); ctx.globalAlpha = 1;
    }
    const x = this.group.cursor;
    const vals = this.series.map(s => x === null ? null : valueAt(s.x, s.y, x, this.o.step || s.step));
    if (this.legendEls) this.series.forEach((s, i) => { const el = this.legendEls[i]; if (el) el.textContent = vals[i] === null || vals[i] === undefined ? '' : this.o.format(vals[i]); });
    if (x === null || x === undefined || x < this._xd[0] || x > this._xd[1]) return;
    const px = Math.round(this.sx(x)) + 0.5;
    ctx.strokeStyle = cssVar('--ink-2'); ctx.lineWidth = 1; ctx.globalAlpha = 0.6;
    ctx.beginPath(); ctx.moveTo(px, this.m.t); ctx.lineTo(px, this.hgt - this.m.b); ctx.stroke(); ctx.globalAlpha = 1;
    if (this.o.tooltip === 'legend') {
      const ring = cssVar('--surface');
      this.series.forEach((s, i) => {
        if (vals[i] === null || vals[i] === undefined || s.dot === false) return;
        ctx.beginPath(); ctx.arc(px, this.sy(vals[i]), 4, 0, Math.PI * 2);
        ctx.fillStyle = s.color; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = ring; ctx.stroke();
      });
    }
    if (this.hover) {
      const s = this.hover.series;
      ctx.save(); ctx.beginPath(); ctx.rect(this.m.l, 0, this.w - this.m.l - this.m.r, this.hgt); ctx.clip();
      this._drawSeries(ctx, Object.assign({}, s, { width: 3, alpha: 1, area: false, points: false }), this._xd[0], this._xd[1]);
      ctx.restore();
    }
  }
  _bind() {
    const ev = e => { const r = this.over.getBoundingClientRect(); return { px: e.clientX - r.left, py: e.clientY - r.top }; };
    this.over.addEventListener('mousemove', e => {
      const { px, py } = ev(e);
      if (this.drag) { this.drag.b = px; }
      const x = this.ix(px);
      if (this.o.tooltip === 'nearest') this._nearest(x, py, e);
      this.group.setCursor(x);
    });
    this.over.addEventListener('mouseleave', () => { this.hover = null; hideTip(); this.drag = null; this.group.setCursor(null); });
    this.over.addEventListener('mousedown', e => { if (this.o.zoom === false) return; const { px } = ev(e); this.drag = { a: px, b: px }; });
    this.over.addEventListener('mouseup', e => {
      if (!this.drag) return;
      const a = Math.min(this.drag.a, this.drag.b), b = Math.max(this.drag.a, this.drag.b);
      this.drag = null;
      if (b - a > 6) this.group.setDomain([this.ix(a), this.ix(b)]); else this.drawOverlay();
    });
    this.over.addEventListener('dblclick', () => this.group.setDomain(null));
    this.over.addEventListener('click', e => { if (this.o.onClick) this.o.onClick(this.ix(ev(e).px), this.hover?.series); });
  }
  _nearest(x, py, e) {
    let best = null, bd = 18;
    for (const s of this.series) {
      if (s.hoverable === false) continue;
      const v = valueAt(s.x, s.y, x, this.o.step || s.step);
      if (v === null || v === undefined) continue;
      const d = Math.abs(this.sy(v) - py);
      if (d < bd) { bd = d; best = { series: s, value: v }; }
    }
    this.hover = best;
    if (best) {
      const fx = this.o.tipX ? this.o.tipX(x) : this.o.xFormat(x);
      const body = best.series.tip ? best.series.tip(x, best.value) : `<b>${best.series.name}</b><br>${fx}: ${this.o.format(best.value)}`;
      showTip(body, e.clientX, e.clientY);
    } else hideTip();
  }
}

// ------------------------------------------------------------------ bar chart (SVG)
export function barChart(parent, { data, height = 200, format = v => String(v), labelEvery = 0, colorVar = '--s1', yLabel = '', invert = false }) {
  const wrap = h('div', { class: 'chart', style: { height: height + 'px' } });
  parent.append(wrap);
  const render = () => {
    wrap.innerHTML = '';
    const w = wrap.clientWidth || 300;
    const m = { l: 40, r: 8, t: 10, b: 24 };
    const max = Math.max(1, ...data.map(d => d.value));
    const ticks = niceTicks(0, max, 3);
    const top = ticks[ticks.length - 1] || max;
    const iw = w - m.l - m.r, ih = height - m.t - m.b;
    const band = iw / Math.max(1, data.length);
    const bw = Math.max(2, Math.min(24, band - 2));
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', w); svg.setAttribute('height', height);
    const add = (tag, attrs, text) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text !== undefined) e.textContent = text; svg.append(e); return e; };
    for (const t of ticks) {
      const y = m.t + ih - (t / top) * ih;
      add('line', { x1: m.l, x2: w - m.r, y1: y, y2: y, stroke: cssVar('--grid'), 'stroke-width': 1 });
      add('text', { x: m.l - 6, y: y + 4, 'text-anchor': 'end', 'font-size': 11, fill: cssVar('--muted') }, format(t));
    }
    const every = labelEvery || Math.ceil(data.length / Math.max(1, Math.floor(iw / 48)));
    data.forEach((d, i) => {
      const x = m.l + i * band + (band - bw) / 2;
      const bh = Math.max(d.value > 0 ? 2 : 0, (d.value / top) * ih);
      const y = m.t + ih - bh;
      const r = Math.min(4, bw / 2, bh);
      const path = `M${x},${m.t + ih} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + bw - r},${y} Q${x + bw},${y} ${x + bw},${y + r} L${x + bw},${m.t + ih} Z`;
      const bar = add('path', { d: path, fill: d.color || cssVar(colorVar) });
      const hit = add('rect', { x: m.l + i * band, y: m.t, width: band, height: ih, fill: 'transparent' });
      hit.addEventListener('mousemove', e => { bar.setAttribute('opacity', '0.8'); showTip(d.tip || `<b>${d.label}</b><br>${format(d.value)}`, e.clientX, e.clientY); });
      hit.addEventListener('mouseleave', () => { bar.removeAttribute('opacity'); hideTip(); });
      if (d.onClick) { hit.style.cursor = 'pointer'; hit.addEventListener('click', d.onClick); }
      if (i % every === 0) add('text', { x: m.l + i * band + band / 2, y: height - 6, 'text-anchor': 'middle', 'font-size': 11, fill: cssVar('--muted') }, d.label);
    });
    add('line', { x1: m.l, x2: w - m.r, y1: m.t + ih + 0.5, y2: m.t + ih + 0.5, stroke: cssVar('--axis'), 'stroke-width': 1 });
    wrap.append(svg);
  };
  const ro = new ResizeObserver(render);
  ro.observe(wrap);
  return { destroy: () => { ro.disconnect(); wrap.remove(); } };
}

// Horizontal bars with a label column - for "laps by track" style rankings.
export function hbarList(parent, rows, { format = v => String(v), colorVar = '--s1' } = {}) {
  const max = Math.max(1, ...rows.map(r => r.value));
  const box = h('div', { class: 'stack' });
  for (const r of rows) {
    box.append(h('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(90px, 32%) 1fr auto', gap: '10px', alignItems: 'center', fontSize: '12px' } },
      h('span', { class: 'ink2', style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, r.label),
      h('div', { style: { height: '10px', background: 'transparent' } },
        h('div', { style: { width: Math.max(1, r.value / max * 100) + '%', height: '100%', background: cssVar(colorVar), borderRadius: '0 4px 4px 0' } })),
      h('span', { class: 'tnum' }, format(r.value))));
  }
  parent.append(box);
  return box;
}

// ------------------------------------------------------------------ track map
// Sector colours come from --sec1..3; an outline without sector distances is drawn as plain asphalt.
const SECTOR_VARS = ['--sec1', '--sec2', '--sec3'];
const tracePath = (ctx, t, pts) => { ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(t.X(p[1]), t.Y(p[2])) : ctx.moveTo(t.X(p[1]), t.Y(p[2]))); };
const roundRect = (ctx, x, y, w, hh, r) => { ctx.beginPath(); if (ctx.roundRect) ctx.roundRect(x, y, w, hh, r); else ctx.rect(x, y, w, hh); };

export class TrackMap {
  constructor(parent, { height = 320, interactive = false } = {}) {
    this.box = h('div', { class: 'chart', style: { height: height + 'px' } });
    this.canvas = h('canvas');
    this.box.append(this.canvas);
    parent.append(this.box);
    this.outline = null; this.lines = []; this.cars = []; this.markers = []; this.zones = []; this.labels = []; this.view = null; this.interactive = interactive;
    this.sectors = {}; this.activeSector = null;
    this.follow = null;  // dynamic view: { x, z, span } keeps that point centred with `span` metres across the shorter side
    // Everything is given in game coordinates; a track's frame ({ a, b, c, d, tx, tz }, from lining it up with the
    // bundled circuit outline) turns them into the circuit's own north-up metres. `raw` keeps what was given.
    this.frame = null;
    this.raw = { outline: null, lines: [], cars: [], markers: [], labels: [], follow: null };
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.box);
    if (interactive) this._bind();
  }
  destroy() { this.ro.disconnect(); this.box.remove(); }
  resize() {
    const r = this.box.getBoundingClientRect();
    this.w = Math.max(50, r.width); this.hgt = Math.max(50, r.height);
    this.canvas.width = Math.round(this.w * DPR()); this.canvas.height = Math.round(this.hgt * DPR());
    this.draw();
  }
  // opts: s2 / s3 (sector start distances), partial (open line), marks: false (no sector chips), frame
  setOutline(points, opts = {}) {
    const frame = opts.frame || null, reproject = JSON.stringify(frame) !== JSON.stringify(this.frame);
    this.frame = frame;
    this.raw.outline = points && points.length ? points : null;
    this.outline = this.raw.outline && (frame ? this.raw.outline.map(p => [p[0], ...this._xz(p[1], p[2])]) : this.raw.outline);
    this.sectors = opts; this.bounds = null; this.runs = null;
    if (reproject) {
      const r = this.raw;
      this.lines = r.lines.map(l => this._line(l)); this.cars = r.cars.map(c => this._pt(c));
      this.markers = r.markers.map(m => this._pt(m)); this.labels = r.labels.map(l => this._pt(l)); this.follow = this._pt(r.follow);
    }
    this.draw();
  }
  _xz(x, z) { const f = this.frame; return f && x !== null && x !== undefined ? [f.a * x + f.b * z + f.tx, f.c * x + f.d * z + f.tz] : [x, z]; }
  _pt(o) { if (!o || !this.frame) return o; const [x, z] = this._xz(o.x, o.z); return { ...o, x, z }; }
  _line(l) {
    if (!this.frame) return l;
    const x = new Array(l.x.length), z = new Array(l.x.length);
    for (let i = 0; i < l.x.length; i++) [x[i], z[i]] = this._xz(l.x[i], l.z[i]);
    return { ...l, x, z };
  }
  // sector 2 / 3 start distances (m); live sessions learn them after the outline
  setSectors(s2, s3) {
    if (this.sectors.s2 === s2 && this.sectors.s3 === s3) return;
    this.sectors = { ...this.sectors, s2, s3 }; this.runs = null; this.draw();
  }
  setActiveSector(i) { if (i !== this.activeSector) { this.activeSector = i; this.draw(); } }
  setLines(lines) { this.raw.lines = lines || []; this.lines = this.raw.lines.map(l => this._line(l)); this.bounds = null; this.draw(); }
  setCars(cars, follow = this.raw.follow) {
    this.raw.cars = cars || []; this.raw.follow = follow;
    this.cars = this.raw.cars.map(c => this._pt(c)); this.follow = this._pt(follow); this.draw();
  }
  setFollow(follow) { this.raw.follow = follow; this.follow = this._pt(follow); this.draw(); }
  setMarkers(m) { this.raw.markers = m || []; this.markers = this.raw.markers.map(o => this._pt(o)); this.draw(); }
  // zones: [[fromMetres, toMetres], ...] along the lap, drawn as a dashed line on the asphalt (active aero / DRS)
  setZones(zones) { this.zones = zones || []; this.draw(); }
  setLabels(labels) { this.raw.labels = labels || []; this.labels = this.raw.labels.map(o => this._pt(o)); this.draw(); }  // [{ x, z, text }]
  resetView() { this.view = null; this.draw(); }
  // width / height of the circuit, so a page can size the map to it
  aspect() { const b = this._bounds(); return b ? (b.maxX - b.minX || 1) / (b.maxZ - b.minZ || 1) : null; }
  _bounds() {
    if (this.bounds) return this.bounds;
    let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
    const eat = (x, z) => { if (x === null || z === null || x === undefined) return; if (x < minX) minX = x; if (x > maxX) maxX = x; if (z < minZ) minZ = z; if (z > maxZ) maxZ = z; };
    if (this.outline) for (const p of this.outline) eat(p[1], p[2]);
    for (const l of this.lines) for (let i = 0; i < l.x.length; i += 3) eat(l.x[i], l.z[i]);
    if (!isFinite(minX)) for (const c of this.cars) eat(c.x, c.z);
    if (!isFinite(minX)) return null;
    return this.bounds = { minX, maxX, minZ, maxZ };
  }
  _xf() {
    const b = this._bounds(); if (!b) return null;
    // Seen from above, F1 world space has +X to the right and +Z towards the bottom of the screen;
    // drawing +Z upwards would mirror every circuit.
    if (this.follow) {
      const k = Math.min(this.w, this.hgt) / this.follow.span, { x: fx, z: fz } = this.follow;
      return { k, X: x => this.w / 2 + (x - fx) * k, Y: z => this.hgt / 2 + (z - fz) * k, cx: fx, cz: fz };
    }
    const pad = 28;
    const sc = Math.min((this.w - pad * 2) / (b.maxX - b.minX || 1), (this.hgt - pad * 2) / (b.maxZ - b.minZ || 1));
    const v = this.view || { k: 1, ox: 0, oy: 0 };
    const cx = (b.minX + b.maxX) / 2, cz = (b.minZ + b.maxZ) / 2;
    const k = sc * v.k;
    return { k, X: x => this.w / 2 + (x - cx) * k + v.ox, Y: z => this.hgt / 2 + (z - cz) * k + v.oy, cx, cz };
  }
  _sectorOf(d) { const { s2, s3 } = this.sectors; return !(s2 > 0 && s3 > s2) ? -1 : d < s2 ? 0 : d < s3 ? 1 : 2; }
  // The outline cut into one run per sector (-1 = unknown); neighbouring runs share their boundary point.
  _sectorRuns() {
    if (this.runs) return this.runs;
    const pts = this.sectors.partial ? this.outline : [...this.outline, this.outline[0]];
    const runs = [];
    let cur = null;
    for (const p of pts) {
      const s = this._sectorOf(p[0]);
      if (cur && cur.s !== s) { cur.pts.push(p); runs.push(cur); cur = null; }
      if (!cur) cur = { s, pts: [] };
      cur.pts.push(p);
    }
    if (cur && cur.pts.length > 1) runs.push(cur);
    return this.runs = runs;
  }
  _fade(s) { const a = this.activeSector; return a === null || a === undefined || s === a ? 1 : 0.4; }
  draw() {
    if (!this.w) return;
    const ctx = this.canvas.getContext('2d');
    ctx.setTransform(DPR(), 0, 0, DPR(), 0, 0);
    ctx.clearRect(0, 0, this.w, this.hgt);
    const t = this._xf();
    if (!t) {
      ctx.fillStyle = cssVar('--muted'); ctx.font = '12px system-ui'; ctx.textAlign = 'center';
      ctx.fillText('Track map appears after the first lap', this.w / 2, this.hgt / 2);
      return;
    }
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    if (this.outline) {
      const asphaltWidth = this.follow ? Math.max(6, Math.min(34, 14 * t.k)) : Math.max(6, Math.min(16, 12 * t.k * 3));
      const W = this.lines.length ? Math.max(asphaltWidth, 14 * t.k) : asphaltWidth;
      const edge = Math.max(2, Math.round(W * 0.2));
      const runs = this._sectorRuns(), secCol = SECTOR_VARS.map(cssVar);
      // sector-coloured edges (like kerbs), then the asphalt on top
      ctx.lineCap = 'butt';
      ctx.lineWidth = W + edge * 2;
      for (const r of runs) {
        if (r.s < 0) continue;
        ctx.globalAlpha = this._fade(r.s); ctx.strokeStyle = secCol[r.s];
        tracePath(ctx, t, r.pts); ctx.stroke();
      }
      ctx.globalAlpha = 1; ctx.lineCap = 'round';
      ctx.strokeStyle = cssVar('--surface-3'); ctx.lineWidth = W;
      tracePath(ctx, t, this.outline);
      if (!this.sectors.partial) ctx.closePath();
      ctx.stroke();
      if (!this.lines.length) {  // no laps drawn on the asphalt: tint it by sector as well
        ctx.lineCap = 'butt';
        const act = this.activeSector ?? null;
        for (const r of runs) {
          if (r.s < 0) continue;
          ctx.globalAlpha = act === null ? 0.28 : r.s === act ? 0.45 : 0.12; ctx.strokeStyle = secCol[r.s];
          tracePath(ctx, t, r.pts); ctx.stroke();
        }
        ctx.globalAlpha = 1; ctx.lineCap = 'round';
      }
      if (this.zones.length) {
        ctx.save();
        ctx.strokeStyle = cssVar('--ink'); ctx.globalAlpha = 0.85; ctx.lineCap = 'butt';
        ctx.lineWidth = Math.max(1.5, asphaltWidth / 4); ctx.setLineDash([Math.max(4, W * 0.7), Math.max(3, W * 0.5)]);
        for (const [a, b] of this.zones) {
          ctx.beginPath();
          let pen = false;
          for (const p of this.outline) {
            const inside = a <= b ? p[0] >= a && p[0] <= b : p[0] >= a || p[0] <= b;  // b < a wraps past the line
            if (!inside) { pen = false; continue; }
            if (pen) ctx.lineTo(t.X(p[1]), t.Y(p[2])); else { ctx.moveTo(t.X(p[1]), t.Y(p[2])); pen = true; }
          }
          ctx.stroke();
        }
        ctx.restore();
      }
      this._drawBoundaries(ctx, t, W + edge * 2, secCol);
    }
    for (const l of this.lines) {
      ctx.lineWidth = l.width || 2;
      if (l.colors) {  // one stroke per run of the same colour
        let i = 1;
        while (i < l.x.length) {
          if (l.x[i] === null || l.x[i - 1] === null) { i++; continue; }
          const col = l.colors[i];
          ctx.strokeStyle = col; ctx.beginPath(); ctx.moveTo(t.X(l.x[i - 1]), t.Y(l.z[i - 1]));
          while (i < l.x.length && l.colors[i] === col && l.x[i] !== null) { ctx.lineTo(t.X(l.x[i]), t.Y(l.z[i])); i++; }
          ctx.stroke();
        }
      } else {
        ctx.strokeStyle = l.color; ctx.beginPath();
        let pen = false;
        for (let i = 0; i < l.x.length; i++) {
          if (l.x[i] === null) { pen = false; continue; }
          const X = t.X(l.x[i]), Y = t.Y(l.z[i]);
          if (!pen) { ctx.moveTo(X, Y); pen = true; } else ctx.lineTo(X, Y);
        }
        ctx.stroke();
      }
    }
    const ring = cssVar('--surface');
    if (this.labels.length) {
      ctx.font = '600 11px system-ui'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round';
      for (const l of this.labels) {
        const x = t.X(l.x) + 7, y = t.Y(l.z) - 7;
        ctx.lineWidth = 3; ctx.strokeStyle = ring; ctx.strokeText(l.text, x, y);
        ctx.fillStyle = cssVar('--ink-2'); ctx.fillText(l.text, x, y);
      }
    }
    for (const m of this.markers) {
      if (m.x === null || m.x === undefined) continue;
      const r = m.r || 5;
      ctx.beginPath();
      if (m.shape === 'square') ctx.rect(t.X(m.x) - r, t.Y(m.z) - r, r * 2, r * 2);
      else ctx.arc(t.X(m.x), t.Y(m.z), r, 0, Math.PI * 2);
      ctx.fillStyle = m.color; ctx.fill(); ctx.lineWidth = m.ring ?? 2; ctx.strokeStyle = ring; ctx.stroke();
    }
    const cars = [...this.cars].sort((a, b) => (a.player ? 1 : 0) - (b.player ? 1 : 0));
    for (const c of cars) {
      if (c.x === null || c.x === undefined) continue;
      const x = t.X(c.x), y = t.Y(c.z);
      const r = c.player ? 8 : 6;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = c.color; ctx.fill();
      ctx.lineWidth = c.player ? 3 : 2; ctx.strokeStyle = c.player ? cssVar('--ink') : ring; ctx.stroke();
      if (c.label) {
        ctx.font = c.player ? '700 12px system-ui' : '600 10px system-ui';
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        if (this.follow) { ctx.lineWidth = 3; ctx.strokeStyle = ring; ctx.strokeText(c.label, x + r + 3, y); }
        ctx.fillStyle = cssVar(c.player ? '--ink' : '--ink-2');
        ctx.fillText(c.label, x + r + 3, y);
      }
    }
    if (this.follow && this.outline && !this.sectors.partial) this._drawInset(ctx, t);
  }
  // Start/finish (chequered) and sector lines across the track, each with a chip naming the sector it starts.
  _drawBoundaries(ctx, t, width, secCol) {
    const out = this.outline, n = out.length, known = this._sectorOf(0) >= 0;
    const b = this._bounds(), mx = t.X((b.minX + b.maxX) / 2), my = t.Y((b.minZ + b.maxZ) / 2);
    const half = width / 2;
    [0, this.sectors.s2, this.sectors.s3].forEach((d, s) => {
      if (d === null || d === undefined || (s && !known)) return;
      let bi = -1, bd = Infinity;
      for (let i = 0; i < n; i++) { const dd = Math.abs(out[i][0] - d); if (dd < bd) { bd = dd; bi = i; } }
      if (bi < 0 || bd > 30) return;  // boundary not on this (cropped) outline
      const p = out[bi], a = out[Math.max(0, bi - 2)], c = out[Math.min(n - 1, bi + 2)];
      const x = t.X(p[1]), y = t.Y(p[2]);
      let dx = t.X(c[1]) - t.X(a[1]), dy = t.Y(c[2]) - t.Y(a[2]);
      const len = Math.hypot(dx, dy) || 1; dx /= len; dy /= len;
      const nx = -dy, ny = dx;
      if (s === 0) {  // two rows of squares across the track
        const cells = 4, cw = width / cells, th = Math.max(2.5, width / 5);
        for (let row = 0; row < 2; row++) for (let i = 0; i < cells; i++) {
          const u0 = -half + i * cw, u1 = u0 + cw, v0 = (row - 1) * th, v1 = v0 + th;
          ctx.fillStyle = (i + row) % 2 ? '#111' : '#f4f4f0';
          ctx.beginPath();
          ctx.moveTo(x + nx * u0 + dx * v0, y + ny * u0 + dy * v0); ctx.lineTo(x + nx * u1 + dx * v0, y + ny * u1 + dy * v0);
          ctx.lineTo(x + nx * u1 + dx * v1, y + ny * u1 + dy * v1); ctx.lineTo(x + nx * u0 + dx * v1, y + ny * u0 + dy * v1);
          ctx.fill();
        }
      } else {
        ctx.strokeStyle = cssVar('--ink'); ctx.lineWidth = 2; ctx.lineCap = 'butt';
        ctx.beginPath(); ctx.moveTo(x - nx * half, y - ny * half); ctx.lineTo(x + nx * half, y + ny * half); ctx.stroke();
        ctx.lineCap = 'round';
      }
      if (this.sectors.marks === false) return;  // a cropped outline (one corner) gets the lines only
      const side = (x - mx) * nx + (y - my) * ny >= 0 ? 1 : -1;  // chip on the outside of the circuit
      const lx = x + nx * (half + 14) * side, ly = y + ny * (half + 14) * side;
      const text = known ? 'S' + (s + 1) : 'S/F';
      ctx.font = '700 11px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      const tw = ctx.measureText(text).width;
      roundRect(ctx, lx - tw / 2 - 5, ly - 8, tw + 10, 16, 4);
      ctx.fillStyle = known ? secCol[s] : cssVar('--surface-2'); ctx.fill();
      ctx.fillStyle = known ? '#111' : cssVar('--ink'); ctx.fillText(text, lx, ly + 0.5);
    });
  }
  // Dynamic view: the whole circuit in the corner, with the part the main view shows outlined.
  _drawInset(ctx, t) {
    const b = this._bounds(), bw = b.maxX - b.minX || 1, bh = b.maxZ - b.minZ || 1, pad = 8;
    const k = Math.min((Math.min(220, this.w * 0.32) - pad * 2) / bw, (Math.min(170, this.hgt * 0.36) - pad * 2) / bh);
    if (!(k > 0)) return;
    const iw = bw * k + pad * 2, ih = bh * k + pad * 2, x0 = this.w - iw - 8, y0 = this.hgt - ih - 8;
    const it = { X: x => x0 + pad + (x - b.minX) * k, Y: z => y0 + pad + (z - b.minZ) * k };
    ctx.save();
    roundRect(ctx, x0, y0, iw, ih, 8);
    ctx.globalAlpha = 0.92; ctx.fillStyle = cssVar('--surface'); ctx.fill();
    ctx.globalAlpha = 1; ctx.strokeStyle = cssVar('--border'); ctx.lineWidth = 1; ctx.stroke();
    ctx.clip();
    const secCol = SECTOR_VARS.map(cssVar);
    ctx.lineWidth = 3; ctx.lineJoin = 'round'; ctx.lineCap = 'butt';
    for (const r of this._sectorRuns()) {
      ctx.globalAlpha = r.s < 0 ? 1 : this._fade(r.s); ctx.strokeStyle = r.s < 0 ? cssVar('--ink-2') : secCol[r.s];
      tracePath(ctx, it, r.pts); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    const hw = this.w / 2 / t.k, hh = this.hgt / 2 / t.k;
    ctx.strokeStyle = cssVar('--ink'); ctx.lineWidth = 1.5;
    ctx.strokeRect(it.X(t.cx - hw), it.Y(t.cz - hh), hw * 2 * k, hh * 2 * k);
    for (const c of [...this.cars].sort((a, b2) => (a.player ? 1 : 0) - (b2.player ? 1 : 0))) {
      if (c.x === null || c.x === undefined) continue;
      ctx.beginPath(); ctx.arc(it.X(c.x), it.Y(c.z), c.player ? 4 : 2.5, 0, Math.PI * 2);
      ctx.fillStyle = c.color; ctx.fill();
      if (c.player) { ctx.lineWidth = 1.5; ctx.strokeStyle = cssVar('--ink'); ctx.stroke(); }
    }
    ctx.restore();
  }
  _bind() {
    this.canvas.style.cursor = 'grab';
    this.canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const r = this.canvas.getBoundingClientRect();
      const mx = e.clientX - r.left - this.w / 2, my = e.clientY - r.top - this.hgt / 2;
      const v = this.view || { k: 1, ox: 0, oy: 0 };
      const f = e.deltaY < 0 ? 1.25 : 0.8;
      const k = Math.max(1, Math.min(40, v.k * f));
      const real = k / v.k;
      this.view = { k, ox: mx - (mx - v.ox) * real, oy: my - (my - v.oy) * real };
      this.draw();
    }, { passive: false });
    let drag = null;
    this.canvas.addEventListener('mousedown', e => { drag = { x: e.clientX, y: e.clientY, v: { ...(this.view || { k: 1, ox: 0, oy: 0 }) } }; this.canvas.style.cursor = 'grabbing'; });
    window.addEventListener('mousemove', this._mm = e => {
      if (!drag) return;
      this.view = { k: drag.v.k, ox: drag.v.ox + e.clientX - drag.x, oy: drag.v.oy + e.clientY - drag.y };
      this.draw();
    });
    window.addEventListener('mouseup', this._mu = () => { drag = null; this.canvas.style.cursor = 'grab'; });
    this.canvas.addEventListener('dblclick', () => this.resetView());
    const origDestroy = this.destroy.bind(this);
    this.destroy = () => { window.removeEventListener('mousemove', this._mm); window.removeEventListener('mouseup', this._mu); origDestroy(); };
  }
  // Index of the point of line i nearest to canvas position (px, py), or -1 when none is within r pixels.
  pick(px, py, i = 0, r = 24) {
    const l = this.lines[i], t = this._xf();
    if (!l || !t) return -1;
    let best = -1, bd = r * r;
    for (let k = 0; k < l.x.length; k++) {
      if (l.x[k] === null || l.x[k] === undefined) continue;
      const dx = t.X(l.x[k]) - px, dy = t.Y(l.z[k]) - py, dd = dx * dx + dy * dy;
      if (dd < bd) { bd = dd; best = k; }
    }
    return best;
  }
  // Zoom the view so that the given world point sits at the centre.
  focus(x, z, k = 6) {
    const b = this._bounds(); if (!b) return;
    [x, z] = this._xz(x, z);
    this.view = { k: 1, ox: 0, oy: 0 };
    const t = this._xf();
    this.view = { k, ox: -(x - t.cx) * t.k * k, oy: -(z - t.cz) * t.k * k };
    this.draw();
  }
}

// ------------------------------------------------------------------ G-force circle
export class GForce {
  constructor(parent, size = 180) {
    this.size = size;
    this.canvas = h('canvas', { width: size * DPR(), height: size * DPR(), style: { width: size + 'px', height: size + 'px', display: 'block', margin: '0 auto' } });
    parent.append(this.canvas);
    this.trail = [];
    this.max = 5;
  }
  push(lat, lon) {
    this.trail.push([lat || 0, lon || 0]);
    if (this.trail.length > 30) this.trail.shift();
    this.draw();
  }
  draw() {
    const s = this.size, c = s / 2, ctx = this.canvas.getContext('2d');
    ctx.setTransform(DPR(), 0, 0, DPR(), 0, 0);
    ctx.clearRect(0, 0, s, s);
    const R = c - 14;
    ctx.strokeStyle = cssVar('--grid'); ctx.lineWidth = 1;
    ctx.fillStyle = cssVar('--muted'); ctx.font = '10px system-ui'; ctx.textAlign = 'left';
    for (let g = 1; g <= this.max; g++) {
      ctx.beginPath(); ctx.arc(c, c, R * g / this.max, 0, Math.PI * 2); ctx.stroke();
      if (g % 2 === 1 || g === this.max) ctx.fillText(g + 'g', c + 3, c - R * g / this.max + 11);
    }
    ctx.strokeStyle = cssVar('--axis');
    ctx.beginPath(); ctx.moveTo(c - R, c); ctx.lineTo(c + R, c); ctx.moveTo(c, c - R); ctx.lineTo(c, c + R); ctx.stroke();
    const P = ([lat, lon]) => [c + Math.max(-1, Math.min(1, lat / this.max)) * R, c - Math.max(-1, Math.min(1, lon / this.max)) * R];
    ctx.strokeStyle = cssVar('--s1'); ctx.lineWidth = 2; ctx.globalAlpha = 0.45; ctx.beginPath();
    this.trail.forEach((p, i) => { const [x, y] = P(p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke(); ctx.globalAlpha = 1;
    const last = this.trail[this.trail.length - 1];
    if (last) {
      const [x, y] = P(last);
      ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fillStyle = cssVar('--s1'); ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = cssVar('--surface'); ctx.stroke();
    }
  }
}

// ------------------------------------------------------------------ rolling live trace
export class LiveTrace {
  constructor(parent, { seconds = 15, height = 170 } = {}) {
    this.seconds = seconds;
    this.box = h('div', { class: 'chart', style: { height: height + 'px' } });
    this.canvas = h('canvas');
    this.box.append(this.canvas);
    parent.append(this.box);
    this.pts = [];
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.box);
  }
  destroy() { this.ro.disconnect(); this.box.remove(); }
  resize() {
    const r = this.box.getBoundingClientRect();
    this.w = r.width; this.hgt = r.height;
    this.canvas.width = Math.round(this.w * DPR()); this.canvas.height = Math.round(this.hgt * DPR());
    this.draw();
  }
  push(t, speed, thr, brk, maxSpeed = 360) {
    this.maxSpeed = maxSpeed;
    if (this.pts.length && t < this.pts[this.pts.length - 1][0]) this.pts = [];
    this.pts.push([t, speed, thr, brk]);
    while (this.pts.length && t - this.pts[0][0] > this.seconds) this.pts.shift();
    this.draw();
  }
  draw() {
    if (!this.w) return;
    const ctx = this.canvas.getContext('2d');
    ctx.setTransform(DPR(), 0, 0, DPR(), 0, 0);
    ctx.clearRect(0, 0, this.w, this.hgt);
    const l = 40, r = 8, gap = 10;
    const h1 = (this.hgt - gap) * 0.55, h2 = this.hgt - gap - h1;
    const grid = cssVar('--grid'), muted = cssVar('--muted');
    ctx.font = '10px system-ui'; ctx.fillStyle = muted; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    const now = this.pts.length ? this.pts[this.pts.length - 1][0] : 0;
    const X = t => l + (1 - (now - t) / this.seconds) * (this.w - l - r);
    const maxS = this.maxSpeed || 360;
    const panel = (y0, hh, ticks, fmt) => {
      ctx.strokeStyle = grid; ctx.lineWidth = 1;
      for (const [v, f] of ticks) { const y = Math.round(y0 + hh - f * hh) + 0.5; ctx.beginPath(); ctx.moveTo(l, y); ctx.lineTo(this.w - r, y); ctx.stroke(); ctx.fillText(fmt(v), l - 5, y); }
    };
    panel(0, h1, [[0, 0], [Math.round(maxS / 2), 0.5], [maxS, 1]], v => v);
    panel(h1 + gap, h2, [[0, 0], [100, 1]], v => v + '%');
    const line = (idx, y0, hh, scale, color) => {
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.beginPath();
      this.pts.forEach((p, i) => { const x = X(p[0]), y = y0 + hh - Math.max(0, Math.min(1, p[idx] / scale)) * hh; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
    };
    line(1, 0, h1, maxS, cssVar('--s1'));
    line(2, h1 + gap, h2, 100, cssVar('--throttle'));
    line(3, h1 + gap, h2, 100, cssVar('--brake'));
  }
}

// Minimal SVG outline thumbnail for track cards.
export function trackThumb(outline, color, frame = null) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'track-thumb');
  if (!outline || outline.length < 3) return svg;
  if (frame) outline = outline.map(p => [p[0], frame.a * p[1] + frame.b * p[2] + frame.tx, frame.c * p[1] + frame.d * p[2] + frame.tz]);
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const p of outline) { minX = Math.min(minX, p[1]); maxX = Math.max(maxX, p[1]); minZ = Math.min(minZ, p[2]); maxZ = Math.max(maxZ, p[2]); }
  const pad = (Math.max(maxX - minX, maxZ - minZ)) * 0.06;
  svg.setAttribute('viewBox', `${minX - pad} ${minZ - pad} ${maxX - minX + pad * 2} ${maxZ - minZ + pad * 2}`);  // +Z points down, as on TrackMap
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  const path = document.createElementNS(NS, 'path');
  path.setAttribute('d', outline.map((p, i) => (i ? 'L' : 'M') + p[1].toFixed(1) + ',' + p[2].toFixed(1)).join('') + 'Z');
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', color || cssVar('--ink-2'));
  path.setAttribute('stroke-width', String(Math.max(maxX - minX, maxZ - minZ) / 70));
  path.setAttribute('stroke-linejoin', 'round');
  svg.append(path);
  return svg;
}
