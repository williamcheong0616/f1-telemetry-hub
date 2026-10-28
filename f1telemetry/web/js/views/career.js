// Career: Driver Career / My Team / championship seasons, grouped by the game's season ID.
import { api, h, toast, fmtLap, fmtDate, fmtNum, trackName, teamChip, cssVar, state } from '../util.js';
import { LineChart } from '../charts.js';

const SESSION_CODES = { 1: 'FP1', 2: 'FP2', 3: 'FP3', 4: 'FP', 5: 'Q1', 6: 'Q2', 7: 'Q3', 8: 'Q', 9: 'OSQ',
  10: 'SQ1', 11: 'SQ2', 12: 'SQ3', 13: 'SQ', 14: 'OSSQ', 15: 'R', 16: 'R2', 17: 'R3', 18: 'TT' };
const trackCode = id => trackName(id).replace(/[^A-Za-z]/g, '').slice(0, 3).toUpperCase();
const seasonName = s => s.name || s.default_name;
const ord = p => (p ? 'P' + p : '–');

export async function mount(root, arg) {
  if (arg) return mountSeason(root, Number(arg));
  const seasons = await api('/career');
  root.append(h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Career'),
    h('div', { class: 'sub' }, 'Driver Career, My Team and championship seasons. Each race weekend you drive becomes a round.'))));
  if (!seasons.length) {
    const demoBtn = h('button', { class: 'btn primary', onclick: async () => {
      demoBtn.disabled = true;
      try { await api('/demo', { method: 'POST', body: { action: 'start', session: 'weekend', laps: 3, speed: 2 } }); toast('Demo career weekend starting…'); location.hash = '#/live'; }
      catch (e) { toast(e.message); demoBtn.disabled = false; }
    } }, 'Run a demo career weekend');
    root.append(h('div', { class: 'card empty' }, h('h3', {}, 'No career seasons yet'),
      h('p', {}, 'Drive a Driver Career, My Team or championship weekend with UDP telemetry on and the season appears here, ',
        'with standings rebuilt from the races you drive.'),
      demoBtn));
    return;
  }
  const grid = h('div', { class: 'season-grid' });
  for (const s of seasons) {
    const m = s.summary;
    grid.append(h('a', { class: 'card season-card', href: `#/career/${s.id}` },
      h('div', { class: 'row', style: { gap: '8px', flexWrap: 'nowrap' } }, teamChip(s.my_team ? null : s.team_id),
        h('b', { class: 'ellipsis' }, seasonName(s)), h('span', { class: 'badge right' }, s.mode_name || 'Season')),
      h('div', { class: 'small muted', style: { margin: '4px 0 12px' } },
        [s.player_name, s.team_name, `${fmtDate(s.first_at, false)} – ${fmtDate(s.last_at, false)}`].filter(Boolean).join(' · ')),
      h('div', { class: 'kv-grid', style: { gridTemplateColumns: 'repeat(4, minmax(0,1fr))' } },
        kv('Championship', m.championship_position ? `P${m.championship_position}` : '–'),
        kv('Points', fmtNum(m.points)), kv('Wins', fmtNum(m.wins)), kv('Podiums', fmtNum(m.podiums))),
      h('div', { class: 'row small', style: { gap: '4px', marginTop: '12px' } },
        h('span', { class: 'muted' }, `${m.rounds} round${m.rounds === 1 ? '' : 's'}:`),
        ...s.tracks.slice(-12).map(t => h('span', { class: 'chip', title: trackName(t) }, trackCode(t))))));
  }
  root.append(grid);
}

function kv(label, value) {
  return h('div', {}, h('div', { class: 'k' }, label), h('div', { class: 'v' }, value));
}

async function mountSeason(root, link) {
  const s = await api(`/career/${link}`);
  const m = s.summary;
  const cleanups = [];

  // ---------------------------------------------------------------- header
  const nameIn = h('input', { type: 'text', value: s.name || '', placeholder: s.default_name, 'aria-label': 'Season name',
    class: 'title-input' });
  nameIn.addEventListener('change', async () => {
    try { await api(`/career/${link}`, { method: 'PATCH', body: { name: nameIn.value.trim() } }); toast('Season renamed'); }
    catch (e) { toast(e.message); }
  });
  root.append(h('div', { class: 'page-head' }, h('div', { style: { minWidth: 0 } },
    h('div', { class: 'small muted' }, h('a', { href: '#/career' }, 'Career'), ' / ', seasonName(s)),
    nameIn,
    h('div', { class: 'sub row', style: { gap: '10px' } },
      h('span', { class: 'row', style: { gap: '6px' } }, teamChip(s.my_team ? null : s.team_id), s.team_name),
      s.player_name ? h('span', {}, s.player_name) : null,
      h('span', {}, s.mode_name),
      h('span', {}, `${fmtDate(s.first_at, false)} – ${fmtDate(s.last_at, false)}`),
      s.game_year ? h('span', { class: 'muted' }, `F1 ${s.game_year}`) : null))));

  const tiles = h('div', { class: 'tiles', style: { marginBottom: '8px' } });
  const tile = (label, value, sub) => tiles.append(h('div', { class: 'tile' }, h('div', { class: 'label' }, label), h('div', { class: 'value tnum' }, value), sub ? h('div', { class: 'delta' }, sub) : null));
  const gap = m.leader_points - m.points;
  tile('Championship', m.championship_position ? `P${m.championship_position}` : '–', m.championship_position === 1 ? 'leading' : `${gap} pts to the leader`);
  tile('Points', fmtNum(m.points), `${m.races} race${m.races === 1 ? '' : 's'} · ${m.rounds} round${m.rounds === 1 ? '' : 's'}`);
  tile('Wins', fmtNum(m.wins), m.races ? `${fmtNum(m.wins / m.races * 100, 0)}% of races` : null);
  tile('Podiums', fmtNum(m.podiums));
  tile('Poles', fmtNum(m.poles));
  tile('Fastest laps', fmtNum(m.fastest_laps));
  tile('Average finish', m.avg_finish ? 'P' + fmtNum(m.avg_finish, 1) : '–', m.best_finish ? `best P${m.best_finish}` : null);
  tile('Average grid', m.avg_grid ? 'P' + fmtNum(m.avg_grid, 1) : '–', m.dnfs ? `${m.dnfs} DNF` : 'no DNFs');
  root.append(tiles,
    h('p', { class: 'small muted', style: { margin: '0 0 14px' } },
      'Standings are rebuilt from the races this app recorded. Sessions you simulate or skip in the game send no telemetry, so they are not counted here.'));

  if (!s.standings.length) {
    root.append(h('div', { class: 'card empty' }, h('h3', {}, 'No race results yet'), 'Finish a race in this season and the standings appear here.'));
  } else {
    const grid = h('div', { class: 'grid cols-2', style: { marginBottom: '12px' } });
    grid.append(driversCard(s), h('div', { class: 'stack', style: { gap: '12px' } }, teamsCard(s), h2hCard(s)));
    root.append(grid);
    if (s.rounds.length >= 2) root.append(progressionCard(s, cleanups));
    root.append(resultsCard(s));
  }
  root.append(weekendsCard(s));
  return () => cleanups.forEach(fn => fn());
}

function driversCard(s) {
  const leader = s.standings[0]?.points || 0;
  const tb = h('tbody');
  for (const d of s.standings) tb.append(h('tr', { class: d.is_player ? 'me' : '' },
    h('td', { class: 'num' }, d.position),
    h('td', {}, h('span', { class: 'row', style: { gap: '8px', flexWrap: 'nowrap' } }, teamChip(d.my_team ? null : d.team_id), d.is_player ? h('b', {}, d.name) : d.name)),
    h('td', { class: 'muted' }, d.team_name),
    h('td', { class: 'num' }, d.wins || ''), h('td', { class: 'num' }, d.podiums || ''),
    h('td', { class: 'num' }, h('b', {}, d.points)),
    h('td', { class: 'num muted' }, d.position === 1 ? '' : `−${leader - d.points}`)));
  return h('div', { class: 'card' }, h('div', { class: 'card-title' }, "Drivers' championship"),
    h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', {}, h('tr', {},
      ...['Pos', 'Driver', 'Team', 'Wins', 'Podiums', 'Points', 'Gap'].map((t, i) => h('th', { class: [0, 3, 4, 5, 6].includes(i) ? 'num' : '' }, t)))), tb)));
}

function teamsCard(s) {
  const myTeam = s.standings.find(d => d.is_player);
  const tb = h('tbody');
  for (const t of s.teams) tb.append(h('tr', { class: myTeam && t.team_id === myTeam.team_id ? 'me' : '' },
    h('td', { class: 'num' }, t.position),
    h('td', {}, h('span', { class: 'row', style: { gap: '8px', flexWrap: 'nowrap' } }, teamChip(t.my_team ? null : t.team_id), t.team_name)),
    h('td', { class: 'muted small' }, t.drivers.join(', ')),
    h('td', { class: 'num' }, t.wins || ''),
    h('td', { class: 'num' }, h('b', {}, t.points))));
  return h('div', { class: 'card' }, h('div', { class: 'card-title' }, "Constructors' championship"),
    h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', {}, h('tr', {},
      ...['Pos', 'Team', 'Drivers', 'Wins', 'Points'].map((t, i) => h('th', { class: [0, 3, 4].includes(i) ? 'num' : '' }, t)))), tb)));
}

function h2hCard(s) {
  const x = s.head_to_head;
  const card = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Teammate head-to-head', x ? h('span', { class: 'right muted small' }, `vs ${x.name} · ${x.races} race${x.races === 1 ? '' : 's'}`) : null));
  if (!x) { card.append(h('div', { class: 'muted small' }, 'Shown once you have raced alongside a teammate.')); return card; }
  const row = (label, [a, b]) => {
    const total = a + b || 1;
    return h('div', { class: 'h2h-row' },
      h('span', { class: 'tnum h2h-n' }, h('b', {}, a)),
      h('div', { class: 'h2h-bar', title: `${label}: you ${a} – ${b} ${x.name}` },
        h('div', { style: { width: `${a / total * 100}%`, background: cssVar('--accent') } }),
        h('div', { style: { width: `${b / total * 100}%`, background: cssVar('--muted') } })),
      h('span', { class: 'tnum h2h-n' }, b),
      h('span', { class: 'small muted h2h-label' }, label));
  };
  card.append(h('div', { class: 'row small', style: { justifyContent: 'space-between', marginBottom: '6px' } },
    h('span', { class: 'row', style: { gap: '6px' } }, h('i', { class: 'swatch', style: { background: cssVar('--accent') } }), 'You'),
    h('span', { class: 'row', style: { gap: '6px' } }, x.name, h('i', { class: 'swatch', style: { background: cssVar('--muted') } }))),
  row('Qualifying', x.quali), row('Race', x.race), row('Points', x.points));
  return card;
}

function progressionCard(s, cleanups) {
  const card = h('div', { class: 'card', style: { marginBottom: '12px' } }, h('div', { class: 'card-title' }, 'Points progression',
    h('span', { class: 'right row small', style: { gap: '10px' } },
      h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: cssVar('--accent'), height: '3px', width: '14px' } }), 'You'),
      h('span', { class: 'row', style: { gap: '5px' } }, h('i', { class: 'swatch', style: { background: cssVar('--muted'), height: '3px', width: '14px' } }), 'Others · hover a line'))));
  const rounds = s.rounds;
  const ch = new LineChart(card, { height: 300, tooltip: 'nearest', zoom: false, yMin: 0, format: v => fmtNum(v) + ' pts',
    xInt: true, xTicks: rounds.length <= 24 ? rounds.map(r => r.round) : null,
    xFormat: v => rounds[Math.round(v) - 1] ? `R${Math.round(v)} ${trackCode(rounds[Math.round(v) - 1].track_id)}` : '',
    tipX: v => rounds[Math.round(v) - 1] ? `Round ${Math.round(v)} · ${rounds[Math.round(v) - 1].track}` : '' });
  ch.setSeries(s.standings.map(d => ({
    name: d.name, color: d.is_player ? cssVar('--accent') : cssVar('--muted'), width: d.is_player ? 3 : 1.5,
    alpha: d.is_player ? 1 : 0.5, z: d.is_player ? 2 : 1, x: rounds.map(r => r.round), y: d.progression,
    tip: (xv, v) => `<b>${d.name}</b> · ${d.team_name}<br>${fmtNum(v)} pts after round ${Math.round(xv)}`,
  })));
  cleanups.push(() => ch.destroy());
  return card;
}

function resultCell(c) {
  if (!c) return h('td', { class: 'res' });
  const pos = c.race;
  const cls = typeof pos === 'number' ? (pos <= 3 ? `p${pos}` : c.points ? 'pts' : 'nopts') : pos ? 'out' : '';
  const label = [];
  if (pos !== undefined) label.push(typeof pos === 'number' ? `P${pos}` : pos);
  if (c.sprint !== undefined) label.push(`sprint ${typeof c.sprint === 'number' ? 'P' + c.sprint : c.sprint}`);
  if (c.pole) label.push('pole');
  if (c.fl) label.push('fastest lap');
  label.push(`${c.points} pts`);
  return h('td', { class: 'res', title: label.join(' · ') },
    h('span', { class: `res-cell ${cls}${c.pole ? ' pole' : ''}` }, pos ?? '·',
      c.sprint !== undefined ? h('sup', {}, c.sprint) : null,
      c.fl ? h('i', { class: 'fl-dot', 'aria-label': 'fastest lap' }) : null));
}

function resultsCard(s) {
  const head = h('tr', {}, h('th', {}, 'Driver'), ...s.rounds.map(r => h('th', { class: 'res', title: `Round ${r.round} · ${r.track}` }, h('div', { class: 'muted' }, `R${r.round}`), trackCode(r.track_id))), h('th', { class: 'num' }, 'Pts'));
  const tb = h('tbody');
  for (const d of s.standings) tb.append(h('tr', { class: d.is_player ? 'me' : '' },
    h('td', {}, h('span', { class: 'row', style: { gap: '8px', flexWrap: 'nowrap' } }, h('span', { class: 'muted tnum', style: { width: '18px' } }, d.position), teamChip(d.my_team ? null : d.team_id), d.name)),
    ...s.rounds.map(r => resultCell(d.results[r.round])),
    h('td', { class: 'num' }, h('b', {}, d.points))));
  return h('div', { class: 'card', style: { marginBottom: '12px' } }, h('div', { class: 'card-title' }, 'Results by round'),
    h('div', { class: 'table-wrap' }, h('table', { class: 'data res-grid' }, h('thead', {}, head), tb)),
    h('div', { class: 'row small muted', style: { gap: '14px', marginTop: '10px' } },
      h('span', { class: 'row', style: { gap: '6px' } }, h('span', { class: 'res-cell p1' }, '1'), h('span', { class: 'res-cell p2' }, '2'), h('span', { class: 'res-cell p3' }, '3'), 'podium'),
      h('span', { class: 'row', style: { gap: '6px' } }, h('span', { class: 'res-cell pts' }, '7'), 'points'),
      h('span', { class: 'row', style: { gap: '6px' } }, h('span', { class: 'res-cell pole' }, '4'), 'pole'),
      h('span', { class: 'row', style: { gap: '6px' } }, h('span', { class: 'res-cell nopts' }, '5', h('sup', {}, '3')), 'sprint result'),
      h('span', { class: 'row', style: { gap: '6px' } }, h('i', { class: 'fl-dot' }), 'fastest lap')));
}

function weekendsCard(s) {
  const tb = h('tbody');
  for (const r of [...s.rounds].reverse()) {
    const label = x => r.sprint?.session_id === x.id ? 'Sprint' : r.race?.session_id === x.id ? 'Race' : (SESSION_CODES[x.session_type] || 'S');
    const race = r.race;
    let raceTxt = '–';
    if (race) raceTxt = race.status_text || `P${race.position}`;
    const gained = race && !race.status_text && race.grid ? race.grid - race.position : 0;
    tb.append(h('tr', { class: race ? 'click' : '', onclick: race ? () => { location.hash = `#/session/${race.session_id}`; } : null },
      h('td', { class: 'num muted' }, r.round),
      h('td', {}, h('b', {}, r.track)),
      h('td', { class: 'muted' }, fmtDate(r.started_at, false)),
      h('td', {}, h('span', { class: 'row', style: { gap: '4px' } }, ...r.sessions.map(x =>
        h('a', { class: 'chip', href: `#/session/${x.id}`, onclick: e => e.stopPropagation(), title: `${state.meta.session_types[x.session_type] || 'Session'}${x.final_position ? ' · P' + x.final_position : ''}` }, label(x))))),
      h('td', { class: 'num' }, ord(r.quali)),
      h('td', { class: 'num' }, r.sprint ? (r.sprint.status_text || `P${r.sprint.position}`) : '–'),
      h('td', { class: 'num' }, h('b', {}, raceTxt), race && race.grid ? h('span', { class: 'small ' + (gained > 0 ? 'faster' : gained < 0 ? 'slower' : 'muted') }, ` ${gained > 0 ? '+' : gained < 0 ? '−' : '±'}${Math.abs(gained)}`) : null,
        race?.fastest_lap ? h('i', { class: 'fl-dot', title: 'Fastest lap', style: { marginLeft: '6px' } }) : null),
      h('td', { class: 'num' }, r.points ? h('b', {}, r.points) : '0'),
      h('td', { class: 'num' }, fmtLap(race?.best_lap_ms))));
  }
  return h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Your weekends', h('span', { class: 'right muted small' }, 'click a row for the race, a chip for any session')),
    h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', {}, h('tr', {},
      ...['Rd', 'Track', 'Date', 'Sessions', 'Quali', 'Sprint', 'Race', 'Points', 'Race best'].map((t, i) => h('th', { class: [0, 4, 5, 6, 7, 8].includes(i) ? 'num' : '' }, t)))), tb)));
}
