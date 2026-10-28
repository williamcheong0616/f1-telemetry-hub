import { api, h, state, fmtLap, fmtDate, trackName, sessionTypeName, teamChip, teamName, weatherName, fmtDuration, CATEGORY_NAMES } from '../util.js';

export async function mount(root, arg, query) {
  const [tracks] = await Promise.all([api('/tracks')]);
  const filter = { track: query.track ?? '', category: query.category ?? '', mode: query.mode ?? '' };
  const modeSel = h('select', { 'aria-label': 'Game mode', onchange: () => { filter.mode = modeSel.value; load(); } },
    ...[['', 'All modes'], ['career', 'Career'], ['championship', 'Championship'], ['time_trial', 'Time Trial'], ['grand_prix', 'Grand Prix'], ['online', 'Online'], ['other', 'Other']]
      .map(([v, label]) => h('option', { value: v }, label)));
  modeSel.value = filter.mode;
  const trackSel = h('select', { onchange: () => { filter.track = trackSel.value; load(); } },
    h('option', { value: '' }, 'All tracks'), ...tracks.map(t => h('option', { value: t.track_id }, t.name)));
  trackSel.value = filter.track;
  const seg = h('div', { class: 'segmented' });
  for (const [k, label] of [['', 'All'], ['race', 'Race'], ['qualifying', 'Qualifying'], ['practice', 'Practice'], ['time_trial', 'Time Trial']]) {
    seg.append(h('button', { class: filter.category === k ? 'on' : '', onclick: e => {
      filter.category = k;
      for (const b of seg.children) b.classList.toggle('on', b === e.currentTarget);
      load();
    } }, label));
  }
  const body = h('div');
  root.append(
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Sessions'), h('div', { class: 'sub' }, 'Every session is recorded automatically while the app is running.')),
      h('div', { class: 'row' }, trackSel, modeSel, seg)),
    body);

  async function load() {
    const qs = new URLSearchParams();
    if (filter.track !== '') qs.set('track', filter.track);
    if (filter.category) qs.set('category', filter.category);
    if (filter.mode) qs.set('mode', filter.mode);
    const rows = await api('/sessions?' + qs);
    body.innerHTML = '';
    if (!rows.length) {
      body.append(h('div', { class: 'card empty' }, h('h3', {}, 'No sessions yet'),
        'Drive a lap with UDP telemetry enabled and it will show up here. You can also run a demo session from ', h('a', { href: '#/settings' }, 'Settings'), '.'));
      return;
    }
    const tb = h('tbody');
    for (const s of rows) {
      let result = '–';
      if (s.final_position) result = `P${s.final_position}` + (s.grid_position ? ` (from P${s.grid_position})` : '');
      tb.append(h('tr', { class: 'click', onclick: () => { location.hash = `#/session/${s.id}`; } },
        h('td', {}, fmtDate(s.started_at)),
        h('td', {}, h('b', {}, trackName(s.track_id))),
        h('td', {}, sessionTypeName(s.session_type), h('div', { class: 'muted small' },
          [state.meta.game_modes[s.game_mode], s.network_game ? 'online' : ''].filter(Boolean).join(' · '))),
        h('td', {}, s.team_id !== null ? h('span', { class: 'row', style: { gap: '6px', flexWrap: 'nowrap' } }, teamChip(s.team_id), teamName(s.team_id)) : '–'),
        h('td', { class: 'num' }, s.laps_completed ?? 0),
        h('td', { class: 'num' }, fmtLap(s.best_lap_ms)),
        h('td', {}, result),
        h('td', { class: 'muted' }, weatherName(s.weather)),
        h('td', { class: 'num muted' }, fmtDuration(s.drive_time_s))));
    }
    body.append(h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, ...['Date', 'Track', 'Session', 'Team', 'Laps', 'Best lap', 'Result', 'Weather', 'Drive time'].map((t, i) =>
        h('th', { class: [4, 5, 8].includes(i) ? 'num' : '' }, t)))), tb))));
  }
  await load();
}
export { CATEGORY_NAMES };
