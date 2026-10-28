import {
  api, h, toast, fmtLap, fmtSector, fmtDelta, fmtDate, fmtDuration, fmtNum, fmtSpeed, speedUnit, trackName, sessionTypeName,
  teamName, teamChip, weatherName, tyreBadge, stddev, cssVar, WHEELS, state, fmtTemp,
} from '../util.js';
import { LineChart, SyncGroup, barChart, showTip, hideTip } from '../charts.js';
import { renderSetup } from './setups.js';
import { ttBadges, ttRows, ttTable } from '../tt.js';
import { startReplay } from '../replaybar.js';

export async function mount(root, id) {
  const data = await api(`/sessions/${id}`);
  const s = data.session, laps = data.laps;
  const cleanups = [];
  const timed = laps.filter(l => l.lap_time_ms > 0);
  const valid = timed.filter(l => l.valid);
  const best = valid.length ? Math.min(...valid.map(l => l.lap_time_ms)) : null;
  const bestSec = [1, 2, 3].map(i => Math.min(...valid.map(l => l['s' + i + '_ms']).filter(v => v > 0)));
  const theoretical = bestSec.every(isFinite) ? bestSec.reduce((a, b) => a + b, 0) : null;
  const flying = valid.filter(l => l.lap_type === 'flying');
  const avg = flying.length ? flying.reduce((a, l) => a + l.lap_time_ms, 0) / flying.length : null;
  // consistency: std dev of flying laps within 107% of the best (ignores SC / traffic laps)
  const clean = flying.filter(l => best && l.lap_time_ms <= best * 1.07).map(l => l.lap_time_ms);
  const sigma = stddev(clean);
  const results = s.results || [];
  const me = results.find(r => r.is_player);
  const selected = new Set();
  const inSeason = s.season_link && ['career', 'championship'].includes(s.mode_group);

  // ---------------------------------------------------------------- header
  const compareBtn = h('button', { class: 'btn primary', disabled: true, onclick: () => { location.hash = `#/analysis?laps=${[...selected].join(',')}`; } }, 'Compare telemetry');
  const delBtn = h('button', { class: 'btn danger', onclick: async () => {
    if (!confirm('Delete this session and all its laps and telemetry? This cannot be undone.')) return;
    try { await api(`/sessions/${id}`, { method: 'DELETE' }); toast('Session deleted'); location.hash = '#/sessions'; }
    catch (e) { toast(e.message); }
  } }, 'Delete');
  root.append(h('div', { class: 'page-head' },
    h('div', {},
      h('div', { class: 'small muted' }, ...(inSeason
        ? [h('a', { href: '#/career' }, 'Career'), ' / ', h('a', { href: `#/career/${s.season_link}` }, s.season_name || s.mode_name || 'Season')]
        : [h('a', { href: '#/sessions' }, 'Sessions'), ' / ', h('a', { href: `#/track/${s.track_id}` }, trackName(s.track_id))])),
      h('h1', {}, `${trackName(s.track_id)} · ${sessionTypeName(s.session_type)}`),
      h('div', { class: 'sub row', style: { gap: '10px' } },
        fmtDate(s.started_at),
        s.team_id !== null ? h('span', { class: 'row', style: { gap: '6px' } }, teamChip(s.team_id), teamName(s.team_id)) : null,
        h('span', {}, `${weatherName(s.weather)} · track ${fmtTemp(s.track_temp)} · air ${fmtTemp(s.air_temp)}`),
        s.mode_name ? h('span', {}, s.mode_name) : null,
        s.formula === 13 ? h('span', {}, 'F1 26 cars') : null,
        s.ai_difficulty && s.category !== 'time_trial' ? h('span', {}, `AI ${s.ai_difficulty}`) : null,
        s.network_game ? h('span', { class: 'badge info' }, 'Online') : null,
        s.game_year ? h('span', { class: 'muted' }, `F1 ${s.game_year}`) : null)),
    h('div', { class: 'row' }, compareBtn,
      h('a', { class: 'btn', href: `#/workstation?session=${id}`, title: 'Every lap of this session on one screen' }, 'Workstation'),
      h('a', { class: 'btn', href: `#/coach/${id}`, title: 'Where a typical lap loses time, corner by corner' }, 'Coach'),
      s.recording ? h('button', { class: 'btn', title: 'Play the recording of this session on the Live page', onclick: () => startReplay(s.recording) }, '▶ Replay') : null,
      h('a', { class: 'btn', href: `/api/export/session/${id}.csv` }, 'Export CSV'), delBtn)));

  const tiles = h('div', { class: 'tiles', style: { marginBottom: '14px' } });
  const tile = (label, value, delta) => tiles.append(h('div', { class: 'tile' }, h('div', { class: 'label' }, label), h('div', { class: 'value tnum' }, value), delta ? h('div', { class: 'delta' }, delta) : null));
  if (s.final_position) {
    const gained = s.grid_position ? s.grid_position - s.final_position : 0;
    tile(s.category === 'race' ? 'Result' : 'Classified', `P${s.final_position}`,
      s.grid_position ? h('span', { class: gained > 0 ? 'faster' : gained < 0 ? 'slower' : '' }, `from P${s.grid_position} (${gained > 0 ? '+' : gained < 0 ? '−' : '±'}${Math.abs(gained)})`) : null);
  }
  if (s.points) tile('Points', String(s.points));
  if (s.start_reaction) tile('Start reaction', `${s.start_reaction.toFixed(3)} s`, 'lights out to launch');
  tile('Best lap', fmtLap(best), best ? `lap ${valid.find(l => l.lap_time_ms === best).lap_number}` : 'no valid lap');
  tile('Theoretical best', fmtLap(theoretical), theoretical && best ? `${fmtDelta(theoretical - best)} vs best` : 'sum of best sectors');
  tile('Average lap', fmtLap(avg), `${flying.length} clean laps`);
  tile('Consistency (σ)', sigma ? (sigma / 1000).toFixed(3) + 's' : '–', 'std dev, laps within 107%');
  tile('Laps', String(timed.length), `${valid.length} valid`);
  tile('Distance', `${fmtNum((s.distance_m || 0) / 1000, 1)} km`, fmtDuration(s.drive_time_s));
  root.append(tiles);
  if (s.time_trial && (s.time_trial.personal_best?.lap_ms || s.time_trial.rival?.lap_ms)) {
    const tt = Object.fromEntries(Object.entries(s.time_trial).map(([k, v]) => [k, v && v.lap_ms ? v : null]));
    root.append(h('div', { class: 'card', style: { marginBottom: '14px' } },
      h('div', { class: 'card-title' }, 'Time trial · game data', h('span', { class: 'right row', style: { gap: '6px' } }, ...ttBadges(tt))),
      h('div', { class: 'table-wrap' }, ttTable(ttRows(tt)))));
  }

  // ---------------------------------------------------------------- tabs
  const tabsDef = [['laps', 'Laps'], ['charts', 'Charts']];
  if (results.length || Object.keys(s.positions?.laps || {}).length > 1) tabsDef.push(['race', 'Race analysis']);
  if (Object.keys(s.history || {}).length > 1) tabsDef.push(['field', 'All drivers']);
  tabsDef.push(['events', `Events (${data.events.length})`], ['setup', 'Setup'], ['notes', 'Notes']);
  const tabBar = h('div', { class: 'tabs' });
  const pane = h('div');
  root.append(tabBar, pane);
  const show = key => {
    for (const fn of cleanups.splice(0)) fn();
    for (const b of tabBar.children) b.classList.toggle('on', b.dataset.k === key);
    pane.innerHTML = '';
    ({ laps: renderLaps, charts: renderCharts, race: renderRace, field: renderField, events: renderEvents, setup: renderSetups, notes: renderNotes })[key]();
  };
  for (const [k, label] of tabsDef) tabBar.append(h('button', { 'data-k': k, onclick: () => show(k) }, label));

  function renderLaps() {
    if (!timed.length) { pane.append(h('div', { class: 'card empty' }, 'No completed laps in this session.')); return; }
    const regs26 = laps.some(l => l.regs_2026);  // 2026 cars: Overtake Mode uses instead of DRS
    const tb = h('tbody');
    for (const l of laps) {
      const cb = h('input', { type: 'checkbox', checked: selected.has(l.id) || null, disabled: !l.sample_count || null });
      const row = h('tr', { class: (l.valid ? '' : 'invalid ') + (selected.has(l.id) ? 'sel' : '') });
      cb.addEventListener('change', () => {
        if (cb.checked) {
          if (selected.size >= 3) { cb.checked = false; toast('Compare up to 3 laps at a time'); return; }
          selected.add(l.id);
        } else selected.delete(l.id);
        row.classList.toggle('sel', cb.checked);
        compareBtn.disabled = !selected.size;
        compareBtn.textContent = selected.size ? `Compare telemetry (${selected.size})` : 'Compare telemetry';
      });
      const secCell = i => {
        const v = l['s' + i + '_ms'];
        return h('td', { class: 'num' + (l.valid && v > 0 && v === bestSec[i - 1] ? ' sec-purple' : '') }, fmtSector(v));
      };
      const wearAvg = arr => arr ? arr.reduce((a, b) => a + b, 0) / 4 : null;
      const wearDelta = l.wear_end && l.wear_start ? wearAvg(l.wear_end) - wearAvg(l.wear_start) : null;
      const fuelUsed = l.fuel_start !== null && l.fuel_end !== null ? l.fuel_start - l.fuel_end : null;
      row.append(
        h('td', {}, cb),
        h('td', { class: 'num' }, l.lap_number),
        h('td', { class: 'num time' + (l.valid && l.lap_time_ms === best ? ' sec-purple' : '') }, fmtLap(l.lap_time_ms)),
        h('td', { class: 'num ' + (best && l.valid ? (l.lap_time_ms === best ? '' : 'muted') : 'muted') }, best && l.lap_time_ms ? fmtDelta(l.lap_time_ms - best) : '–'),
        secCell(1), secCell(2), secCell(3),
        h('td', {}, l.tyre_visual !== null ? h('span', { class: 'row', style: { gap: '5px', flexWrap: 'nowrap' } }, tyreBadge(l.tyre_visual), h('span', { class: 'muted small' }, l.tyre_age ?? '')) : '–'),
        h('td', { class: 'num' }, wearDelta !== null ? `+${fmtNum(wearDelta, 2)}%` : '–'),
        h('td', { class: 'num' }, fuelUsed !== null ? `${fmtNum(fuelUsed, 2)} kg` : '–'),
        h('td', { class: 'num' }, l.ers_deployed !== null ? `${fmtNum(l.ers_deployed / 1e6, 2)} MJ` : '–'),
        h('td', { class: 'num' }, fmtSpeed(l.top_speed)),
        h('td', { class: 'num' }, (regs26 ? l.overtake_activations : l.drs_activations) ?? '–'),
        h('td', { class: 'num' }, l.position ? 'P' + l.position : '–'),
        h('td', {}, l.valid ? '' : h('span', { class: 'badge bad' }, 'Invalid'), ' ', l.lap_type !== 'flying' ? h('span', { class: 'badge' }, l.lap_type) : null),
        h('td', { class: 'nowrap' }, l.sample_count ? [h('a', { class: 'btn sm', href: `#/analysis?laps=${l.id}` }, 'Telemetry'), ' ',
          h('a', { class: 'btn sm', href: `/api/laps/${l.id}/export`, title: 'Save this lap as a .f1lap file to send to a friend' }, 'Export lap')]
          : h('span', { class: 'muted small' }, 'no data')));
      tb.append(row);
    }
    pane.append(h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Lap times', h('span', { class: 'right muted small' }, 'Tick up to 3 laps to overlay their telemetry')),
      h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
        h('thead', {}, h('tr', {}, ...['', 'Lap', 'Time', 'Δ best', 'S1', 'S2', 'S3', 'Tyre', 'Wear', 'Fuel used', 'ERS used', `Top ${speedUnit()}`, regs26 ? 'Overtake' : 'DRS', 'Pos', '', ''].map((t, i) =>
          h('th', { class: [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13].includes(i) ? 'num' : '' }, t)))), tb))));
  }

  function renderCharts() {
    if (timed.length < 2) { pane.append(h('div', { class: 'card empty' }, 'Charts need at least two completed laps.')); return; }
    const grid = h('div', { class: 'grid cols-2' });
    pane.append(grid);
    const card = (title, sub) => { const c = h('div', { class: 'card' }, h('div', { class: 'card-title' }, title, sub ? h('span', { class: 'right muted small' }, sub) : null)); grid.append(c); return c; };
    const x = timed.map(l => l.lap_number);
    const lapFmt = v => 'Lap ' + Math.round(v);
    const xTicks = x.length <= 20 ? x : null;

    const c1 = card('Lap time', 'invalid laps in grey');
    const ys = timed.map(l => l.lap_time_ms / 1000);
    const median = [...ys].sort((a, b) => a - b)[Math.floor(ys.length / 2)];
    const lt = new LineChart(c1, { height: 220, tooltip: 'nearest', format: v => fmtLap(v * 1000), xFormat: v => String(Math.round(v)), xInt: true, xTicks, tipX: lapFmt, zoom: false,
      yMax: Math.min(Math.max(...ys), median * 1.15) });
    const muted = cssVar('--muted');
    lt.setSeries([{ name: 'Lap time', color: cssVar('--s1'), x, y: ys, points: true, pointColor: i => timed[i].valid ? cssVar('--s1') : muted,
      tip: (xv, v) => { const l = timed.find(t => t.lap_number === Math.round(xv)); return l ? `<b>Lap ${l.lap_number}</b><br>${fmtLap(l.lap_time_ms)}${l.valid ? '' : ' (invalid)'}` : ''; } }]);
    cleanups.push(() => lt.destroy());

    const wl = timed.filter(l => l.wear_end);
    if (wl.length) {
      const c2 = card('Tyre wear', 'end of lap, %');
      const g = new LineChart(c2, { height: 220, format: v => v.toFixed(1) + '%', xFormat: v => String(Math.round(v)), xInt: true, xTicks, zoom: false, yMin: 0 });
      // RL, RR, FL, FR -> show fronts first
      g.setSeries([2, 3, 0, 1].map((w, i) => ({ name: WHEELS[w], color: cssVar(`--s${i + 1}`), x: wl.map(l => l.lap_number), y: wl.map(l => l.wear_end[w]), points: wl.length < 25 })));
      cleanups.push(() => g.destroy());
    }
    const fl = timed.filter(l => l.fuel_start !== null && l.fuel_end !== null);
    if (fl.length) {
      const c3 = card('Fuel used per lap', 'kg');
      cleanups.push(barChart(c3, { height: 220, data: fl.map(l => ({ label: String(l.lap_number), value: Math.max(0, l.fuel_start - l.fuel_end), tip: `<b>Lap ${l.lap_number}</b><br>${fmtNum(l.fuel_start - l.fuel_end, 2)} kg used<br>${fmtNum(l.fuel_end, 2)} kg left` })), format: v => v.toFixed(1) }).destroy);
    }
    const el = timed.filter(l => l.ers_deployed !== null);
    if (el.length) {
      const c4 = card('ERS deployed per lap', 'MJ (4 MJ max per lap)');
      cleanups.push(barChart(c4, { height: 220, colorVar: '--s2', data: el.map(l => ({ label: String(l.lap_number), value: l.ers_deployed / 1e6, tip: `<b>Lap ${l.lap_number}</b><br>${fmtNum(l.ers_deployed / 1e6, 2)} MJ deployed<br>${fmtNum((l.ers_harvested || 0) / 1e6, 2)} MJ harvested` })), format: v => v.toFixed(1) }).destroy);
    }
    const c5 = card('Top speed', speedUnit());
    const ts = new LineChart(c5, { height: 200, format: v => v.toFixed(0), xFormat: v => String(Math.round(v)), xInt: true, xTicks, zoom: false, tooltip: 'nearest', tipX: lapFmt });
    ts.setSeries([{ name: 'Top speed', color: cssVar('--s1'), x, y: timed.map(l => state.settings.speed_unit === 'mph' ? l.top_speed * 0.621371 : l.top_speed), points: true }]);
    cleanups.push(() => ts.destroy());
  }

  function playerIdx() {
    if (me) return me.idx;
    const d = (s.drivers || []).find(d => d.name === s.player_name);
    return d ? d.idx : 0;
  }
  function driverName(idx) {
    const d = (s.drivers || []).find(d => d.idx === Number(idx));
    return d ? d.name : `Car ${Number(idx) + 1}`;
  }
  function driverTeam(idx) {
    const d = (s.drivers || []).find(d => d.idx === Number(idx));
    return d ? d.team_id : null;
  }

  function renderRace() {
    const pidx = playerIdx();
    if (results.length) {
      const leader = results[0];
      const tb = h('tbody');
      for (const r of results) {
        const gained = r.grid ? r.grid - r.position : 0;
        const gap = r.position === 1 ? fmtRaceTime(r.total_time) : (r.laps < leader.laps ? `+${leader.laps - r.laps} lap${leader.laps - r.laps > 1 ? 's' : ''}` : '+' + (r.total_time - leader.total_time).toFixed(3));
        tb.append(h('tr', { class: r.is_player ? 'me' : '' },
          h('td', { class: 'num' }, h('b', {}, r.position)),
          h('td', {}, h('span', { class: 'row', style: { gap: '8px', flexWrap: 'nowrap' } }, teamChip(r.team_id), r.name)),
          h('td', { class: 'muted' }, teamName(r.team_id)),
          h('td', { class: 'num' }, r.grid || '–'),
          h('td', { class: 'num ' + (gained > 0 ? 'faster' : gained < 0 ? 'slower' : 'muted') }, gained > 0 ? `+${gained}` : gained < 0 ? `−${-gained}` : '±0'),
          h('td', { class: 'num' }, r.laps),
          h('td', { class: 'num' }, s.category === 'race' ? gap : fmtLap(r.best_lap_ms)),
          h('td', { class: 'num' }, fmtLap(r.best_lap_ms)),
          h('td', { class: 'num' }, r.pit_stops),
          h('td', {}, h('span', { class: 'row', style: { gap: '3px', flexWrap: 'nowrap' } }, ...(r.stints || []).map(st => tyreBadge(st.visual)))),
          h('td', { class: 'num' }, r.penalty_time ? `+${r.penalty_time}s` : ''),
          h('td', { class: 'num' }, r.points || ''),
          h('td', { class: 'muted' }, state.meta.result_status[r.result_status] || '')));
      }
      pane.append(h('div', { class: 'card', style: { marginBottom: '12px' } }, h('div', { class: 'card-title' }, 'Final classification'),
        h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', {}, h('tr', {},
          ...['Pos', 'Driver', 'Team', 'Grid', '+/−', 'Laps', s.category === 'race' ? 'Time / gap' : 'Best', 'Best lap', 'Pits', 'Tyres', 'Pen', 'Pts', 'Status'].map((t, i) => h('th', { class: [0, 3, 4, 5, 6, 7, 8, 10, 11].includes(i) ? 'num' : '' }, t)))), tb))));
    }
    const pos = s.positions?.laps || {};
    const grid = s.positions?.grid || {};
    if (Object.keys(pos).length > 1) {
      const c = h('div', { class: 'card', style: { marginBottom: '12px' } }, h('div', { class: 'card-title' }, 'Positions by lap',
        h('span', { class: 'right row small', style: { gap: '10px' } }, h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: cssVar('--accent'), height: '3px', width: '14px' } }), 'You'),
          h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: cssVar('--muted'), height: '3px', width: '14px' } }), 'Others · hover a line'))));
      pane.append(c);
      const n = Math.max(...Object.values(pos).map(a => a.length));
      const ch = new LineChart(c, { height: 340, invertY: true, yMin: 1, yMax: Math.max(...Object.values(pos).flat().filter(Boolean), 2), tooltip: 'nearest', zoom: false,
        format: v => 'P' + Math.round(v), xFormat: v => v === 0 ? 'Grid' : String(Math.round(v)), xInt: true, tipX: v => Math.round(v) === 0 ? 'Grid' : 'Lap ' + Math.round(v),
        yTicks: [1, 5, 10, 15, 20].filter(v => v <= 22), xTicks: n <= 25 ? Array.from({ length: n + 1 }, (_, i) => i) : null });
      const series = Object.entries(pos).map(([idx, arr]) => {
        const isMe = Number(idx) === pidx;
        const ys = [grid[idx] ?? null, ...arr];
        return { name: driverName(idx), color: isMe ? cssVar('--accent') : cssVar('--muted'), width: isMe ? 3 : 1.5, alpha: isMe ? 1 : 0.55, z: isMe ? 2 : 1,
          x: ys.map((_, i) => i), y: ys, step: false,
          tip: (xv, v) => `<b>${driverName(idx)}</b> · ${teamName(driverTeam(idx))}<br>${Math.round(xv) === 0 ? 'Grid' : 'Lap ' + Math.round(xv)}: P${Math.round(v)}` };
      });
      ch.setSeries(series);
      cleanups.push(() => ch.destroy());
    }
    // tyre strategy
    const hist = s.history || {};
    const order = results.length ? results.map(r => String(r.idx)) : Object.keys(hist);
    if (Object.keys(hist).length) {
      const doneLaps = hx => hx.laps.filter(l => l[0] > 0).length;
      const totalLaps = Math.max(...Object.values(hist).map(doneLaps), 1);
      const card = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Tyre strategy', h('span', { class: 'right muted small' }, 'stint bars, letter = compound')));
      const wrap = h('div', { class: 'stack small' });
      for (const idx of order) {
        const hx = hist[idx]; if (!hx) continue;
        const row = h('div', { style: { display: 'grid', gridTemplateColumns: '140px 1fr', gap: '10px', alignItems: 'center' } },
          h('span', { class: 'row', style: { gap: '6px', flexWrap: 'nowrap', overflow: 'hidden' } }, teamChip(driverTeam(idx)), h('span', { class: Number(idx) === pidx ? '' : 'ink2', style: { fontWeight: Number(idx) === pidx ? 700 : 400 } }, driverName(idx))));
        const bar = h('div', { style: { display: 'flex', gap: '2px', height: '18px' } });
        let start = 0;
        for (const st of hx.stints) {
          const end = Math.min(st.end_lap === 255 ? doneLaps(hx) : st.end_lap, doneLaps(hx));
          const len = Math.max(0, end - start);
          const letter = (state.meta.visual_compounds[st.visual] || '?')[0];
          const col = { S: '--tyre-soft', M: '--tyre-medium', H: '--tyre-hard', I: '--tyre-inter', W: '--tyre-wet' }[letter] || '--muted';
          const seg = h('div', { style: { flex: `0 0 ${len / totalLaps * 100}%`, background: cssVar(col), borderRadius: '4px', display: 'flex', alignItems: 'center', paddingLeft: '6px', fontWeight: 700, fontSize: '11px', color: letter === 'S' || letter === 'I' || letter === 'W' ? '#fff' : '#111', minWidth: '0', overflow: 'hidden' } }, len >= 2 ? `${letter} ${len}` : '');
          seg.addEventListener('mousemove', e => showTip(`<b>${driverName(idx)}</b><br>${state.meta.visual_compounds[st.visual] || '?'} · laps ${start + 1}–${end} (${len})`, e.clientX, e.clientY));
          seg.addEventListener('mouseleave', hideTip);
          bar.append(seg);
          start = end;
        }
        row.append(bar);
        wrap.append(row);
      }
      card.append(wrap);
      pane.append(card);
    }
    if (!pane.children.length) pane.append(h('div', { class: 'card empty' }, 'No race data recorded.'));
  }

  function renderField() {
    const hist = s.history || {};
    const pidx = playerIdx();
    const card = h('div', { class: 'card', style: { marginBottom: '12px' } }, h('div', { class: 'card-title' }, 'Lap times - all drivers', h('span', { class: 'right muted small' }, 'hover a line for the driver')));
    pane.append(card);
    // only laps with all three sectors: drops out-laps that started mid-lap and the lap still in progress
    const complete = l => l[0] > 0 && l[1] > 0 && l[2] > 0 && l[3] > 0;
    const validBest = Math.min(...Object.values(hist).flatMap(x => x.laps.filter(l => complete(l) && (l[4] & 1)).map(l => l[0])));
    const plotted = l => complete(l) && !(l[0] < validBest * 0.97);  // faster than any valid lap = didn't cover the full lap
    const all = Object.values(hist).flatMap(x => x.laps.filter(plotted).map(l => l[0])).sort((a, b) => a - b);
    const med = all[Math.floor(all.length / 2)] || 90000;
    const n = Math.max(0, ...Object.values(hist).map(x => x.laps.length));
    const ch = new LineChart(card, { height: 320, tooltip: 'nearest', zoom: false, format: v => fmtLap(v), xFormat: v => String(Math.round(v)), xInt: true, tipX: v => 'Lap ' + Math.round(v),
      xTicks: n <= 25 ? Array.from({ length: n }, (_, i) => i + 1) : null,
      yMin: all.length ? all[0] * 0.995 : null, yMax: all.length ? Math.min(all[all.length - 1], med * 1.12) * 1.005 : null });
    ch.setSeries(Object.entries(hist).map(([idx, hx]) => {
      const isMe = Number(idx) === pidx;
      const pts = hx.laps.map((l, i) => [i + 1, plotted(l) ? l[0] : 0]).filter(p => p[1] > 0);
      return { name: driverName(idx), color: isMe ? cssVar('--accent') : cssVar('--muted'), width: isMe ? 3 : 1.5, alpha: isMe ? 1 : 0.5, z: isMe ? 2 : 1,
        x: pts.map(p => p[0]), y: pts.map(p => p[1]), tip: (xv, v) => `<b>${driverName(idx)}</b><br>Lap ${Math.round(xv)}: ${fmtLap(v)}` };
    }));
    cleanups.push(() => ch.destroy());
    // per-driver summary
    const rows = Object.entries(hist).map(([idx, hx]) => {
      const t = hx.laps.filter(complete).map(l => l[0]);
      const v = hx.laps.filter(l => complete(l) && (l[4] & 1)).map(l => l[0]);
      const bestL = v.length ? Math.min(...v) : null;
      const cleanL = v.filter(x => bestL && x <= bestL * 1.07);
      const sec = [1, 2, 3].map(i => { const xs = hx.laps.filter(l => l[i] > 0 && (l[4] & (1 << i))).map(l => l[i]); return xs.length ? Math.min(...xs) : null; });
      return { idx, name: driverName(idx), team: driverTeam(idx), laps: t.length, best: bestL, avg: cleanL.length ? cleanL.reduce((a, b) => a + b, 0) / cleanL.length : null, sigma: stddev(cleanL), sec };
    }).sort((a, b) => (a.best || 1e12) - (b.best || 1e12));
    const fastest = rows[0]?.best;
    const secBest = [0, 1, 2].map(i => Math.min(...rows.map(r => r.sec[i] || Infinity)));
    const tb = h('tbody');
    for (const r of rows) tb.append(h('tr', { class: Number(r.idx) === pidx ? 'me' : '' },
      h('td', {}, h('span', { class: 'row', style: { gap: '8px', flexWrap: 'nowrap' } }, teamChip(r.team), r.name)),
      h('td', { class: 'num' + (r.best && r.best === fastest ? ' sec-purple' : '') }, fmtLap(r.best)),
      h('td', { class: 'num muted' }, r.best && fastest ? fmtDelta(r.best - fastest) : '–'),
      ...r.sec.map((v, i) => h('td', { class: 'num' + (v && v === secBest[i] ? ' sec-purple' : '') }, fmtSector(v))),
      h('td', { class: 'num' }, fmtLap(r.avg)), h('td', { class: 'num' }, r.sigma ? (r.sigma / 1000).toFixed(3) : '–'), h('td', { class: 'num' }, r.laps)));
    pane.append(h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Pace summary'),
      h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', {}, h('tr', {},
        ...['Driver', 'Best', 'Gap', 'Best S1', 'Best S2', 'Best S3', 'Avg (107%)', 'σ', 'Laps'].map((t, i) => h('th', { class: i ? 'num' : '' }, t)))), tb))));
  }

  function renderEvents() {
    if (!data.events.length) { pane.append(h('div', { class: 'card empty' }, 'No events recorded.')); return; }
    const tb = h('tbody');
    for (const e of data.events) tb.append(h('tr', {}, h('td', { class: 'num muted' }, e.lap ? 'L' + e.lap : ''), h('td', { class: 'num muted' }, e.session_time !== null ? fmtRaceTime(e.session_time) : ''), h('td', {}, h('span', { class: 'badge' }, e.code)), h('td', {}, e.text)));
    pane.append(h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', {}, h('tr', {}, h('th', { class: 'num' }, 'Lap'), h('th', { class: 'num' }, 'Session time'), h('th', {}, 'Code'), h('th', {}, 'Event'))), tb))));
  }

  function renderSetups() {
    if (!data.setups.length) { pane.append(h('div', { class: 'card empty' }, 'No setup captured (the game sends setups for your own car only).')); return; }
    for (const st of data.setups) {
      const lapsWith = laps.filter(l => l.setup_id === st.id).map(l => l.lap_number);
      pane.append(h('div', { class: 'card', style: { marginBottom: '12px' } }, h('div', { class: 'card-title' }, st.name || `Setup #${st.id}`,
        h('span', { class: 'right muted small' }, `used on lap${lapsWith.length > 1 ? 's' : ''} ${lapsWith.join(', ')} · `, h('a', { href: `#/setups?id=${st.id}` }, 'open in library'))), renderSetup(st.data)));
    }
  }

  function renderNotes() {
    const ta = h('textarea', { rows: 8, placeholder: 'Notes about this session - setup feelings, strategy, what to try next…' }, s.notes || '');
    ta.addEventListener('change', async () => { await api(`/sessions/${id}`, { method: 'PATCH', body: { notes: ta.value } }); s.notes = ta.value; toast('Notes saved'); });
    pane.append(h('div', { class: 'card' }, ta, h('div', { class: 'small muted', style: { marginTop: '6px' } }, 'Saved automatically when you click away.')));
  }

  show('laps');
  return () => { for (const fn of cleanups) fn(); };
}

function fmtRaceTime(sec) {
  if (!sec) return '–';
  const hrs = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = (sec % 60).toFixed(3).padStart(6, '0');
  return hrs ? `${hrs}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}
