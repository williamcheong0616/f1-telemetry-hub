import { api, h, fmtNum, fmtDuration, fmtDate, trackName, cssVar, CATEGORY_NAMES } from '../util.js';
import { LineChart, barChart, hbarList } from '../charts.js';

export async function mount(root) {
  const [s, tracks] = await Promise.all([api('/stats'), api('/tracks')]);
  const cleanups = [];
  root.append(h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Stats'), h('div', { class: 'sub' }, 'All-time numbers from everything you have driven while the app was recording.'))));
  if (!s.sessions) { root.append(h('div', { class: 'card empty' }, h('h3', {}, 'No data yet'), 'Your stats build up automatically as you drive.')); return; }
  const tiles = h('div', { class: 'tiles', style: { marginBottom: '12px' } });
  const tile = (label, value, sub) => tiles.append(h('div', { class: 'tile' }, h('div', { class: 'label' }, label), h('div', { class: 'value' }, value), sub ? h('div', { class: 'delta' }, sub) : null));
  tile('Distance driven', `${fmtNum(s.distance_m / 1000, 0)} km`, `${fmtNum(s.distance_m / 1000 / 305, 1)} race distances`);
  tile('Time on track', fmtDuration(s.drive_time_s));
  tile('Laps', fmtNum(s.laps), `${fmtNum(s.valid_laps)} valid`);
  tile('Sessions', fmtNum(s.sessions));
  tile('Races', fmtNum(s.races), s.dnfs ? `${s.dnfs} DNF` : null);
  tile('Wins', fmtNum(s.wins), s.races ? `${fmtNum(s.wins / s.races * 100, 0)}% of races` : null);
  tile('Podiums', fmtNum(s.podiums));
  tile('Pole positions', fmtNum(s.poles), 'P1 in qualifying');
  tile('Points', fmtNum(s.points));
  tile('Average finish', s.avg_finish ? 'P' + fmtNum(s.avg_finish, 1) : '–');
  root.append(tiles);

  const grid = h('div', { class: 'grid cols-2' });
  root.append(grid);
  const card = (title, sub) => { const c = h('div', { class: 'card' }, h('div', { class: 'card-title' }, title, sub ? h('span', { class: 'right muted small' }, sub) : null)); grid.append(c); return c; };

  const act = s.activity.slice(-60);
  const c1 = card('Activity', 'laps per day');
  cleanups.push(barChart(c1, { height: 220, data: act.map(a => ({ label: fmtDate(a.day, false).replace(/,? \d{4}$/, ''), value: a.laps || 0,
    tip: `<b>${fmtDate(a.day, false)}</b><br>${a.laps || 0} laps · ${a.sessions} sessions · ${fmtNum((a.distance_m || 0) / 1000, 0)} km` })) }).destroy);

  if (s.finishes.length) {
    const c2 = card('Finishing positions', 'races');
    const maxPos = Math.max(20, ...s.finishes.map(f => f.position));
    const counts = Array.from({ length: maxPos }, (_, i) => s.finishes.find(f => f.position === i + 1)?.count || 0);
    cleanups.push(barChart(c2, { height: 220, data: counts.map((v, i) => ({ label: 'P' + (i + 1), value: v, tip: `<b>P${i + 1}</b><br>${v} race${v === 1 ? '' : 's'}` })), format: v => String(Math.round(v)), labelEvery: 2 }).destroy);
  }
  if (s.race_list.length > 1) {
    const c3 = card('Race results over time', 'finishing position · lower is better');
    const rl = s.race_list;
    const ch = new LineChart(c3, { height: 220, invertY: true, yMin: 1, yMax: Math.max(...rl.map(r => r.final_position), 10), tooltip: 'nearest', zoom: false,
      format: v => 'P' + Math.round(v), xInt: true, xFormat: i => rl[Math.round(i)] ? fmtDate(rl[Math.round(i)].started_at, false) : '', yTicks: [1, 5, 10, 15, 20] });
    ch.setSeries([{ name: 'Finish', color: cssVar('--s1'), x: rl.map((_, i) => i), y: rl.map(r => r.final_position), points: true,
      tip: xv => { const r = rl[Math.round(xv)]; return r ? `<b>P${r.final_position}</b> at ${trackName(r.track_id)}<br>from P${r.grid_position || '?'} · ${r.points || 0} pts<br>${fmtDate(r.started_at)}` : ''; } }]);
    cleanups.push(() => ch.destroy());
  }
  const c4 = card('Laps by track');
  hbarList(c4, tracks.slice().sort((a, b) => b.laps - a.laps).slice(0, 15).map(t => ({ label: t.name, value: t.laps })));
  const c5 = card('Sessions by type');
  hbarList(c5, s.by_category.slice().sort((a, b) => b.sessions - a.sessions).map(c => ({ label: CATEGORY_NAMES[c.category] || c.category, value: c.sessions })), { colorVar: '--s2' });
  return () => cleanups.forEach(fn => fn());
}
