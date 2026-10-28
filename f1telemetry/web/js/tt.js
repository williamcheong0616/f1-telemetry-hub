// Time Trial table: your laps vs. the game's personal best and the rival (Time Trial packet).
import { h, fmtLap, fmtSector, fmtDelta, deltaClass, state } from './util.js';

export function assistText(d) {
  const m = state.meta || {};
  return [`TC ${m.tt_traction?.[d.tc] ?? d.tc}`, `ABS ${d.abs ? 'on' : 'off'}`, m.tt_gearbox?.[d.gearbox]].filter(Boolean).join(' · ');
}

// Rows for the table, compared against the rival when there is one, else the personal best.
// `current` is an optional in-progress lap ({ label, lap_ms, s1_ms, s2_ms, running: true }).
export function ttRows(tt, current) {
  const rows = current ? [current] : [];
  if (tt.session_best) rows.push({ ...tt.session_best, label: 'Session best', assists: tt.session_best });
  const pb = tt.personal_best ? { ...tt.personal_best, label: 'Personal best', assists: tt.personal_best } : null;
  if (pb) rows.push(pb);
  if (tt.rival) {
    const rival = { ...tt.rival, label: tt.rival.name ? `Rival · ${tt.rival.name}` : 'Rival', assists: tt.rival };
    rows.push(rival);
    return { rows, ref: rival, refLabel: 'rival' };
  }
  return { rows, ref: pb, refLabel: 'PB' };
}

export function ttTable({ rows, ref, refLabel }) {
  const tb = h('tbody');
  for (const r of rows) {
    const isRef = r === ref;
    const sector = (v, rv) => h('td', { class: 'num' }, v ? fmtSector(v) : '–',
      !isRef && v && rv ? h('div', { class: 'small ' + deltaClass(v - rv) }, fmtDelta(v - rv)) : null);
    const lapDelta = !isRef && !r.running && r.lap_ms && ref?.lap_ms ? r.lap_ms - ref.lap_ms : null;
    tb.append(h('tr', {},
      h('td', {}, h('div', { class: 'row', style: { gap: '6px', flexWrap: 'nowrap' } }, r.label,
        r.valid === 0 || r.invalid ? h('span', { class: 'badge bad' }, 'invalid') : null),
      r.assists ? h('div', { class: 'tt-assists' }, assistText(r.assists)) : null),
      h('td', { class: 'num' + (r.running ? ' muted' : '') }, r.running ? (r.lap_ms ? fmtLap(r.lap_ms) : '–') : h('b', {}, fmtLap(r.lap_ms))),
      sector(r.s1_ms, ref?.s1_ms), sector(r.s2_ms, ref?.s2_ms), sector(r.s3_ms, ref?.s3_ms),
      h('td', { class: 'num ' + (lapDelta === null ? 'muted' : deltaClass(lapDelta)) }, isRef ? 'ref' : lapDelta === null ? '–' : fmtDelta(lapDelta))));
  }
  return h('table', { class: 'data tt-table' }, h('thead', {}, h('tr', {}, h('th', {}, ''),
    ...['Lap', 'S1', 'S2', 'S3', `Δ ${refLabel}`].map(t => h('th', { class: 'num' }, t)))), tb);
}

export function ttBadges(tt) {
  const d = tt.session_best || tt.personal_best;
  if (!d) return [];
  return [h('span', { class: 'badge' }, d.equal_performance ? 'Equal performance' : 'Real car performance'),
    d.custom_setup ? h('span', { class: 'badge' }, 'Custom setup') : null].filter(Boolean);
}
