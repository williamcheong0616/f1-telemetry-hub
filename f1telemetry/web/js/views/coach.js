// Corner coach: where a typical lap of a session loses time against the best one, why, and how consistent
// every corner is. The analysis comes from the app (/api/coach); the engineer reads the same fixes out.
import { api, h, fmtLap, fmtDelta, deltaClass, fmtDate, fmtNum, trackName, sessionTypeName, speedUnit } from '../util.js';
import { guestLabel } from '../friends.js';

export async function mount(root, arg, query) {
  const sessions = (await api('/sessions?limit=120')).filter(s => s.laps_completed >= 2);
  const sid = Number(arg) || sessions[0]?.id;
  root.append(h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Coach'),
    h('div', { class: 'sub' }, 'Where a typical lap loses time against your best one, corner by corner, and how consistent you are.'))));
  if (!sid) {
    root.append(h('div', { class: 'card empty' }, h('h3', {}, 'Nothing to coach yet'), 'Drive at least two complete laps in a session and come back.'));
    return;
  }
  const S = await api(`/sessions/${sid}`);
  const ses = S.session;
  const T = ses.track_id !== null ? await api(`/tracks/${ses.track_id}?category=${ses.category || ''}`).catch(() => null) : null;
  const pb = (T?.top_laps || []).filter(l => l.session_id !== sid && l.telemetry_complete).sort((a, b) => a.lap_time_ms - b.lap_time_ms)[0];
  const best = S.laps.filter(l => l.valid && l.lap_time_ms > 0).sort((a, b) => a.lap_time_ms - b.lap_time_ms)[0];
  const refId = query.ref ? Number(query.ref) : null;
  const friends = ses.track_id !== null ? await api(`/guest-laps?track=${ses.track_id}`).catch(() => []) : [];

  const sSel = h('select', { 'aria-label': 'Session', onchange: () => { location.hash = `#/coach/${sSel.value}`; } },
    ...(sessions.some(s => s.id === sid) ? sessions : [ses, ...sessions]).map(s => h('option', { value: s.id, selected: s.id === sid || null },
      `${trackName(s.track_id)} · ${sessionTypeName(s.session_type)} · ${fmtDate(s.started_at)} · ${s.laps_completed} laps`)));
  const rSel = h('select', { 'aria-label': 'Compare with', onchange: () => { location.hash = `#/coach/${sid}${rSel.value ? '?ref=' + rSel.value : ''}`; } },
    h('option', { value: '' }, `Best lap of this session${best ? ' · ' + fmtLap(best.lap_time_ms) : ''}`),
    pb && (!best || pb.lap_time_ms < best.lap_time_ms) ? h('option', { value: pb.id, selected: refId === pb.id || null }, `All-time best · ${fmtLap(pb.lap_time_ms)} (${fmtDate(pb.recorded_at, false)})`) : null,
    ...friends.map(l => h('option', { value: l.id, selected: refId === l.id || null }, `${guestLabel(l)} · ${fmtLap(l.lap_time_ms)} (friend's lap)`)));
  root.querySelector('.page-head').append(h('div', { class: 'row' }, sSel, rSel));

  const body = h('div', { class: 'stack' }, h('div', { class: 'card empty' }, 'Working through the laps…'));
  root.append(body);
  const res = await api(`/coach/${sid}${refId ? '?ref=' + refId : ''}`);
  body.replaceChildren(...render(res));
}

function render(res) {
  if (!res.corners.length) {
    return [h('div', { class: 'card empty' }, h('h3', {}, 'Not enough to go on'), res.note || 'This session needs at least two complete laps with telemetry.')];
  }
  const laps = res.laps;
  const ref = res.ref;
  const others = laps.filter(l => l.valid && l.id !== ref.id).sort((a, b) => a.lap_time_ms - b.lap_time_ms);
  const typical = others[Math.floor((others.length - 1) / 2)] || null;  // the median lap, for the Telemetry link
  const refLabel = ref.guest ? `${ref.driver}'s lap` : ref.same_session ? `your best lap (L${ref.lap_number})` : 'your all-time best';

  // ---------------------------------------------------------------- headline numbers
  const tiles = h('div', { class: 'tiles' });
  const tile = (label, value, sub, cls = '') => tiles.append(h('div', { class: 'tile' }, h('div', { class: 'label' }, label),
    h('div', { class: 'value tnum ' + cls }, value), sub ? h('div', { class: 'delta small muted' }, sub) : null));
  tile(ref.guest ? ref.driver : ref.same_session ? 'Best lap' : 'All-time best', fmtLap(ref.lap_time_ms), ref.guest ? "friend's lap, the reference" : ref.same_session ? `lap ${ref.lap_number}` : 'the reference');
  if (res.typical_ms) tile('Typical lap', fmtLap(res.typical_ms), h('span', { class: deltaClass(res.typical_ms - ref.lap_time_ms) }, `${fmtDelta(res.typical_ms - ref.lap_time_ms)} · median of ${laps.filter(l => l.valid).length} laps`));
  if (res.ideal_ms && res.ideal_ms < ref.lap_time_ms) tile('Best of every corner', fmtLap(res.ideal_ms), h('span', { class: 'faster' }, `${fmtDelta(res.ideal_ms - ref.lap_time_ms)} if you put them together`));
  if (res.lap_spread_ms !== null) tile('Consistency', `±${(res.lap_spread_ms / 1000).toFixed(2)} s`, 'lap time spread (standard deviation)');

  // ---------------------------------------------------------------- the fixes
  const fixCard = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'What to work on',
    h('span', { class: 'right small muted' }, `a typical lap against ${refLabel}`)));
  if (!res.fixes.length) fixCard.append(h('p', { class: 'muted', style: { margin: 0 } }, 'No corner costs you more than a twentieth on a typical lap. That is a consistent session.'));
  res.fixes.forEach((f, i) => {
    const c = res.corners.find(x => x.name === f.name);
    const link = typical ? `#/analysis?laps=${ref.id},${typical.id}` : `#/analysis?laps=${ref.id}`;
    fixCard.append(h('div', { class: 'coach-fix' },
      h('div', { class: 'coach-rank' }, String(i + 1)),
      h('div', { class: 'grow' },
        h('div', { class: 'row', style: { gap: '8px' } }, h('b', {}, `Corner ${f.n}`), h('span', { class: 'slower tnum' }, `−${f.loss_s.toFixed(2)} s`),
          h('span', { class: 'muted small' }, `${fmtNum(c.d, 0)} m into the lap`)),
        h('div', { class: 'ink2' }, f.detail),
        h('a', { class: 'small', href: link }, `Compare ${typical ? `L${typical.lap_number} with ${ref.same_session ? 'L' + ref.lap_number : 'the all-time best'}` : 'the lap'} on the Telemetry page (${c.name}) →`))));
  });

  // ---------------------------------------------------------------- every corner
  const unit = res.unit === 'mph' ? 'mph' : speedUnit();
  const m = (v, more, less) => v === null || v === undefined ? '–' : Math.abs(v) < 2 ? 'same' : `${fmtNum(Math.abs(v), 0)} m ${v > 0 ? more : less}`;
  const v = (x) => x === null || x === undefined ? '–' : Math.abs(x) < 1 ? 'same' : h('span', { class: x > 0 ? 'faster' : 'slower' }, `${x > 0 ? '+' : '−'}${fmtNum(Math.abs(x), 0)}`);
  const spread = (x, u, d = 0) => x === null || x === undefined ? '–' : `±${fmtNum(x, d)}${u}`;
  const maxLoss = Math.max(0.05, ...res.corners.map(c => Math.abs(c.loss_s || 0)));
  const tbody = h('tbody', {}, ...res.corners.map(c => h('tr', {},
    h('td', {}, h('b', {}, c.name)),
    h('td', { class: 'num' }, c.loss_s === null ? '–' : h('span', { class: 'coach-loss' },
      h('i', { class: c.loss_s > 0 ? 'neg' : 'pos', style: { width: `${Math.max(2, Math.round(Math.min(1, Math.abs(c.loss_s) / maxLoss) * 60))}px` } }),
      h('span', { class: 'tnum ' + deltaClass(c.loss_s * 1000) }, fmtDelta(c.loss_s * 1000, 2)))),
    h('td', { class: 'num' }, m(c.brake_m, 'later', 'earlier')),
    h('td', { class: 'num' }, v(c.min_v)),
    h('td', { class: 'num' }, c.line_m === null ? '–' : Math.abs(c.line_m) < 0.5 ? 'same' : `${fmtNum(Math.abs(c.line_m), 1)} m ${c.line_m > 0 ? 'wider' : 'tighter'}`),
    h('td', { class: 'num' }, m(c.throttle_m, 'later', 'earlier')),
    h('td', { class: 'num' }, v(c.exit_v)),
    h('td', { class: 'num' }, spread(c.spread.time_s, ' s', 2)),
    h('td', { class: 'num' }, spread(c.spread.brake_m, ' m')),
    h('td', { class: 'num' }, spread(c.spread.min_v, '')),
    h('td', { class: 'num' }, c.best ? h('span', { class: 'faster', title: `Lap ${c.best.lap_number} was your quickest through ${c.name}` }, `L${c.best.lap_number} −${c.best.gain_s.toFixed(2)}`) : '–'))));
  const cornerCard = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Every corner',
    h('span', { class: 'right small muted' }, `median of the other laps against ${refLabel}`)),
    h('div', { class: 'table-wrap' }, h('table', { class: 'data coach-table' },
      h('thead', {},
        h('tr', {}, h('th', {}, ''), h('th', { class: 'num' }, 'Time'), h('th', { class: 'num' }, 'Braking'), h('th', { class: 'num' }, `Min ${unit}`),
          h('th', { class: 'num' }, 'Line at apex'), h('th', { class: 'num' }, 'Full throttle'), h('th', { class: 'num' }, `Exit ${unit}`),
          h('th', { class: 'num', title: 'How much the time through the corner varies from lap to lap' }, 'Time ±'),
          h('th', { class: 'num', title: 'How much the braking point varies from lap to lap' }, 'Brake ±'),
          h('th', { class: 'num', title: `How much the minimum speed varies from lap to lap (${unit})` }, 'Min ±'),
          h('th', { class: 'num', title: 'The lap that was quickest through this corner, if it was not the reference' }, 'Best here'))),
      tbody)),
    h('p', { class: 'small muted', style: { margin: '10px 0 0' } },
      'Corner numbers are the app\'s own (C1 is the first corner it finds after the line), the same as on the Telemetry page. ',
      'Braking and full throttle are in metres against the reference; the ± columns are standard deviations over the laps.'));

  // ---------------------------------------------------------------- corner by lap
  const shown = laps.slice(-16);
  const heat = (dt) => {
    if (dt === null || dt === undefined) return {};
    const f = Math.min(1, Math.abs(dt) / 0.25);
    return { background: `color-mix(in srgb, var(${dt > 0 ? '--critical' : '--good'}) ${Math.round(8 + f * 50)}%, transparent)` };
  };
  const grid = h('table', { class: 'data coach-heat' },
    h('thead', {}, h('tr', {}, h('th', {}, ''), ...shown.map(l => h('th', { class: 'num' + (l.id === ref.id ? ' ref' : '') }, `L${l.lap_number}`)))),
    h('tbody', {}, ...res.corners.map(c => h('tr', {}, h('td', {}, h('b', {}, c.name)), ...shown.map(l => {
      const pl = c.per_lap[l.id];
      const dt = pl && pl.time !== null && c.ref.time !== null ? pl.time - c.ref.time : null;
      return h('td', { class: 'num tnum', style: l.id === ref.id ? {} : heat(dt), title: dt === null ? '' : `L${l.lap_number} through ${c.name}: ${fmtDelta(dt * 1000)} against the reference` },
        l.id === ref.id ? 'ref' : dt === null ? '–' : Math.abs(dt) < 0.005 ? '0.00' : (dt > 0 ? '+' : '−') + Math.abs(dt).toFixed(2));
    })))));
  const lapCard = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Every corner, every lap',
    h('span', { class: 'right small muted' }, 'seconds against the reference: red slower, green quicker')),
    h('div', { class: 'table-wrap' }, grid),
    res.least_consistent.length ? h('p', { class: 'small ink2', style: { margin: '10px 0 0' } },
      `Least consistent: ${res.least_consistent.map(n => 'corner ' + n.slice(1)).join(', ')}. A corner that is quick on some laps and slow on others is often where the easiest time is.`) : null);
  return [tiles, fixCard, cornerCard, lapCard];
}
