import { api, h, fmtLap, fmtDelta, fmtDate, fmtNum, trackName, sessionTypeName, tyreBadge, cssVar, CATEGORY_NAMES, weatherName } from '../util.js';
import { ttBadges, ttRows, ttTable } from '../tt.js';
import { LineChart, TrackMap, trackThumb } from '../charts.js';

export async function mount(root, arg, query, name) {
  if (name === 'track' && arg !== undefined) return detail(root, Number(arg));
  const tracks = await api('/tracks');
  root.append(h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Tracks & personal bests'),
    h('div', { class: 'sub' }, 'Your fastest valid lap on every circuit, with the theoretical best from your best sectors.'))));
  if (!tracks.length) { root.append(h('div', { class: 'card empty' }, h('h3', {}, 'No tracks yet'), 'Complete a lap and the circuit appears here.')); return; }
  const grid = h('div', { class: 'grid auto-fill' });
  for (const t of tracks) {
    grid.append(h('a', { class: 'card list-card', href: `#/track/${t.track_id}` },
      trackThumb(t.outline, cssVar('--ink-2'), t.frame),
      h('div', { class: 'row', style: { marginTop: '8px', justifyContent: 'space-between' } }, h('b', {}, t.name), h('span', { class: 'muted small' }, fmtDate(t.last_driven, false))),
      h('div', { class: 'row', style: { marginTop: '6px', gap: '18px' } },
        h('div', {}, h('div', { class: 'small muted' }, 'Personal best'), h('div', { class: 'tnum', style: { fontSize: '20px', fontWeight: 650 } }, fmtLap(t.best_lap_ms))),
        h('div', {}, h('div', { class: 'small muted' }, 'Theoretical'), h('div', { class: 'tnum ink2' }, fmtLap(t.theoretical_ms)))),
      h('div', { class: 'small muted', style: { marginTop: '6px' } }, `${t.laps} laps · ${t.sessions} sessions · ${fmtNum((t.distance_m || 0) / 1000, 0)} km`)));
  }
  root.append(grid);
}

async function detail(root, id) {
  const t = await api(`/tracks/${id}`);
  const cleanups = [];
  root.append(h('div', { class: 'page-head' }, h('div', {},
    h('div', { class: 'small muted' }, h('a', { href: '#/tracks' }, 'Tracks'), ' / ', t.name), h('h1', {}, t.name),
    h('div', { class: 'sub' }, `${t.length ? fmtNum(t.length / 1000, 3) + ' km · ' : ''}${t.sessions.length} sessions`))));
  const tiles = h('div', { class: 'tiles', style: { marginBottom: '12px' } });
  const order = ['time_trial', 'qualifying', 'race', 'practice', 'other'];
  const cats = [...t.best_by_category].sort((a, b) => order.indexOf(a.category) - order.indexOf(b.category));
  if (!cats.length) tiles.append(h('div', { class: 'tile' }, h('div', { class: 'label' }, 'Personal best'), h('div', { class: 'value' }, '–'), h('div', { class: 'delta' }, 'no valid laps yet')));
  for (const c of cats) {
    tiles.append(h('div', { class: 'tile' }, h('div', { class: 'label' }, `${CATEGORY_NAMES[c.category] || c.category} best`), h('div', { class: 'value tnum' }, fmtLap(c.best_lap_ms)),
      h('div', { class: 'delta' }, c.theoretical_ms ? `theoretical ${fmtLap(c.theoretical_ms)} (${fmtDelta(c.theoretical_ms - c.best_lap_ms)})` : `${c.laps} valid laps`)));
  }
  root.append(tiles);

  const grid = h('div', { class: 'grid', style: { gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)' } });
  root.append(grid);
  const left = h('div', { class: 'live-col' }), right = h('div', { class: 'live-col' });
  grid.append(left, right);
  const mq = matchMedia('(max-width: 1000px)');
  const lay = () => { grid.style.gridTemplateColumns = mq.matches ? 'minmax(0,1fr)' : 'minmax(0, 1.4fr) minmax(0, 1fr)'; };
  mq.addEventListener('change', lay); lay();
  cleanups.push(() => mq.removeEventListener('change', lay));

  // progression
  const prog = t.sessions.filter(s => s.best_lap_ms).sort((a, b) => a.started_at.localeCompare(b.started_at));
  if (prog.length > 1) {
    const c = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Progression', h('span', { class: 'right muted small' }, 'best valid lap per session')));
    left.append(c);
    const ch = new LineChart(c, { height: 220, tooltip: 'nearest', zoom: false, format: v => fmtLap(v), xFormat: i => prog[Math.round(i)] ? fmtDate(prog[Math.round(i)].started_at, false) : '',
      tipX: i => '', xInt: true, xTicks: prog.length <= 8 ? prog.map((_, i) => i) : null });
    ch.setSeries([{ name: 'Best lap', color: cssVar('--s1'), x: prog.map((_, i) => i), y: prog.map(s => s.best_lap_ms), points: true,
      tip: (xv) => { const s = prog[Math.round(xv)]; return s ? `<b>${fmtLap(s.best_lap_ms)}</b><br>${sessionTypeName(s.session_type)} · ${fmtDate(s.started_at)}` : ''; } }]);
    cleanups.push(() => ch.destroy());
  }
  // leaderboard
  const lb = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Personal leaderboard', h('span', { class: 'right muted small' }, 'top 50 valid laps · click to analyse')));
  left.append(lb);
  if (!t.top_laps.length) lb.append(h('div', { class: 'empty' }, 'No valid laps yet.'));
  else {
    const best = t.top_laps[0].lap_time_ms;
    const tb = h('tbody');
    t.top_laps.forEach((l, i) => tb.append(h('tr', { class: 'click', onclick: () => { location.hash = `#/analysis?laps=${l.id}`; } },
      h('td', { class: 'num muted' }, i + 1), h('td', { class: 'num' }, h('b', {}, fmtLap(l.lap_time_ms))), h('td', { class: 'num muted' }, i ? fmtDelta(l.lap_time_ms - best) : ''),
      h('td', { class: 'num' }, fmtLap(l.s1_ms).replace(/^0:/, '')), h('td', { class: 'num' }, fmtLap(l.s2_ms).replace(/^0:/, '')), h('td', { class: 'num' }, fmtLap(l.s3_ms).replace(/^0:/, '')),
      h('td', {}, sessionTypeName(l.session_type)), h('td', {}, l.tyre_visual !== null ? tyreBadge(l.tyre_visual) : ''),
      h('td', { class: 'muted' }, weatherName(l.weather)), h('td', { class: 'muted' }, fmtDate(l.recorded_at, false)),
      h('td', {}, h('a', { class: 'btn sm', href: `#/session/${l.session_id}`, onclick: e => e.stopPropagation() }, 'Session')))));
    lb.append(h('div', { class: 'table-wrap', style: { maxHeight: '520px', overflowY: 'auto' } }, h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, ...['#', 'Time', 'Gap', 'S1', 'S2', 'S3', 'Session', 'Tyre', 'Weather', 'Date', ''].map((x, i) => h('th', { class: i < 6 ? 'num' : '' }, x)))), tb)));
  }

  // the game's own Time Trial records (includes laps from before the app was installed)
  const ttd = t.time_trial?.time_trial;
  if (ttd && (ttd.personal_best?.lap_ms || ttd.rival?.lap_ms)) {
    const tt = Object.fromEntries(Object.entries(ttd).map(([k, v]) => [k, v && v.lap_ms ? v : null]));
    right.append(h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Time trial · game data',
      h('span', { class: 'right row', style: { gap: '6px' } }, ...ttBadges(tt))),
      h('div', { class: 'table-wrap' }, ttTable(ttRows(tt))),
      h('div', { class: 'small muted', style: { marginTop: '8px' } },
        'Personal best and rival as the game reported them in your latest Time Trial here (',
        h('a', { href: `#/session/${t.time_trial.session_id}` }, fmtDate(t.time_trial.started_at, false)),
        '). The personal best can include laps set before this app was installed.')));
  }
  // map
  if (t.outline) {
    const mc = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Circuit'));
    right.append(mc);
    const m = new TrackMap(mc, { height: 300, interactive: true });
    m.setOutline(t.outline, { s2: t.s2_start, s3: t.s3_start, frame: t.frame });
    cleanups.push(() => m.destroy());
  }
  // sessions
  const sc = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Sessions here'));
  right.append(sc);
  const tb = h('tbody');
  for (const s of t.sessions.slice(0, 40)) tb.append(h('tr', { class: 'click', onclick: () => { location.hash = `#/session/${s.id}`; } },
    h('td', {}, fmtDate(s.started_at, false)), h('td', {}, sessionTypeName(s.session_type)), h('td', { class: 'num' }, s.laps_completed),
    h('td', { class: 'num' }, fmtLap(s.best_lap_ms)), h('td', { class: 'num' }, s.final_position ? 'P' + s.final_position : '')));
  sc.append(h('div', { class: 'table-wrap', style: { maxHeight: '360px', overflowY: 'auto' } }, h('table', { class: 'data' },
    h('thead', {}, h('tr', {}, ...['Date', 'Session', 'Laps', 'Best', 'Result'].map((x, i) => h('th', { class: i >= 2 ? 'num' : '' }, x)))), tb)));
  // setups
  if (t.setups.length) {
    const st = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Setups used here'));
    right.append(st);
    for (const s of t.setups.slice(0, 12)) st.append(h('a', { class: 'row', href: `#/setups?id=${s.id}`, style: { justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--grid)', textDecoration: 'none' } },
      h('span', {}, s.favorite ? '★ ' : '', s.name || `Setup #${s.id}`), h('span', { class: 'muted small tnum' }, `${s.laps} laps · best ${fmtLap(s.best_lap_ms)}`)));
  }
  return () => cleanups.forEach(fn => fn());
}
