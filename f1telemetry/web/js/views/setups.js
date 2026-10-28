import { api, h, toast, fmtLap, fmtDate, fmtDelta, deltaClass, fmtTemp, trackName, teamName, teamChip } from '../util.js';

const GROUPS = [
  ['Aerodynamics', [['front_wing', 'Front wing'], ['rear_wing', 'Rear wing']]],
  ['Transmission', [['diff_on_throttle', 'Differential on throttle', '%'], ['diff_off_throttle', 'Differential off throttle', '%'], ['engine_braking', 'Engine braking', '%']]],
  ['Suspension geometry', [['front_camber', 'Front camber', '°', 2], ['rear_camber', 'Rear camber', '°', 2], ['front_toe', 'Front toe', '°', 2], ['rear_toe', 'Rear toe', '°', 2]]],
  ['Suspension', [['front_suspension', 'Front suspension'], ['rear_suspension', 'Rear suspension'], ['front_arb', 'Front anti-roll bar'], ['rear_arb', 'Rear anti-roll bar'],
    ['front_ride_height', 'Front ride height'], ['rear_ride_height', 'Rear ride height']]],
  ['Brakes', [['brake_pressure', 'Brake pressure', '%'], ['brake_bias', 'Front brake bias', '%']]],
  ['Tyre pressures', [['fl_pressure', 'Front left', ' psi', 1], ['fr_pressure', 'Front right', ' psi', 1], ['rl_pressure', 'Rear left', ' psi', 1], ['rr_pressure', 'Rear right', ' psi', 1]]],
  ['Weight', [['ballast', 'Ballast'], ['fuel_load', 'Fuel load', ' kg', 1]]],
];

const fmtVal = (v, unit = '', d = 0) => v === null || v === undefined ? '–' : (typeof v === 'number' ? v.toFixed(d) : v) + unit;

export function renderSetup(data, other) {
  const grid = h('div', { class: 'setup-grid' });
  for (const [title, rows] of GROUPS) {
    const g = h('div', { class: 'setup-group' }, h('h4', {}, title));
    for (const [k, label, unit, d] of rows) {
      const a = data?.[k], b = other?.[k];
      const differs = other && fmtVal(a, '', d) !== fmtVal(b, '', d);
      g.append(h('div', { class: 'r' + (differs ? ' diff' : '') }, h('span', { class: 'ink2' }, label),
        h('b', {}, fmtVal(a, unit, d), differs ? h('span', { class: 'muted' }, ` → ${fmtVal(b, unit, d)}`) : null)));
    }
    grid.append(g);
  }
  return grid;
}

export function setupText(st) {
  const lines = [`${st.name || 'Setup #' + st.id} - ${trackName(st.track_id)}`];
  for (const [title, rows] of GROUPS) {
    lines.push('', title.toUpperCase());
    for (const [k, label, unit, d] of rows) lines.push(`${label}: ${fmtVal(st.data[k], unit, d)}`);
  }
  return lines.join('\n');
}

export async function mount(root, arg, query) {
  const all = await api('/setups');
  const tracks = [...new Map(all.map(s => [s.track_id, s.track_name])).entries()];
  let trackFilter = '';
  let current = query.id ? Number(query.id) : null;
  let compare = null;
  const trackSel = h('select', { onchange: () => { trackFilter = trackSel.value; renderList(); } },
    h('option', { value: '' }, 'All tracks'), ...tracks.map(([id, name]) => h('option', { value: id }, name)));
  root.append(h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Setups'),
    h('div', { class: 'sub' }, 'Every car setup you drive with is captured automatically and linked to the laps it produced.')), trackSel));
  if (!all.length) { root.append(h('div', { class: 'card empty' }, h('h3', {}, 'No setups captured yet'), 'Setups are saved when you complete a lap.')); return; }
  const layout = h('div', { class: 'grid', style: { gridTemplateColumns: 'minmax(260px, 360px) minmax(0, 1fr)' } });
  const listEl = h('div', { class: 'card', style: { padding: '6px' } });
  const detailEl = h('div');
  layout.append(listEl, detailEl);
  root.append(layout);
  const mq = matchMedia('(max-width: 860px)');
  const lay = () => { layout.style.gridTemplateColumns = mq.matches ? 'minmax(0,1fr)' : 'minmax(260px, 360px) minmax(0, 1fr)'; };
  mq.addEventListener('change', lay); lay();

  function renderList() {
    listEl.innerHTML = '';
    const rows = all.filter(s => trackFilter === '' || String(s.track_id) === trackFilter);
    for (const s of rows) {
      listEl.append(h('div', { class: 'row click', style: { padding: '10px', borderRadius: '8px', cursor: 'pointer', background: s.id === current ? 'var(--surface-2)' : '', flexWrap: 'nowrap' },
        onclick: () => { current = s.id; compare = null; renderList(); renderDetail(); } },
        h('div', { class: 'grow', style: { minWidth: 0 } },
          h('div', { style: { fontWeight: 600 } }, s.favorite ? '★ ' : '', s.name || `Setup #${s.id}`),
          h('div', { class: 'small muted' }, `${s.track_name} · ${fmtDate(s.created_at, false)}`)),
        h('div', { class: 'small tnum', style: { textAlign: 'right' } }, h('div', {}, fmtLap(s.best_lap_ms)), h('div', { class: 'muted' }, `${s.laps} laps`))));
    }
  }
  function renderDetail() {
    detailEl.innerHTML = '';
    const st = all.find(s => s.id === current) || all[0];
    if (!st) return;
    current = st.id;
    const other = compare ? all.find(s => s.id === compare) : null;
    const name = h('input', { type: 'text', value: st.name || '', placeholder: `Setup #${st.id}`, style: { fontSize: '16px', fontWeight: 600, minWidth: '220px' } });
    name.addEventListener('change', async () => { await api(`/setups/${st.id}`, { method: 'PATCH', body: { name: name.value } }); st.name = name.value; renderList(); toast('Renamed'); });
    const fav = h('button', { class: 'btn', onclick: async () => { st.favorite = st.favorite ? 0 : 1; await api(`/setups/${st.id}`, { method: 'PATCH', body: { favorite: st.favorite } }); renderList(); renderDetail(); } }, st.favorite ? '★ Favourite' : '☆ Favourite');
    const cmpSel = h('select', { onchange: () => { compare = cmpSel.value ? Number(cmpSel.value) : null; renderDetail(); } },
      h('option', { value: '' }, 'Compare with…'), ...all.filter(s => s.id !== st.id).map(s => h('option', { value: s.id }, `${s.name || 'Setup #' + s.id} · ${s.track_name}`)));
    cmpSel.value = compare ? String(compare) : '';
    const copy = h('button', { class: 'btn', onclick: async () => { try { await navigator.clipboard.writeText(setupText(st)); toast('Setup copied to clipboard'); } catch { toast('Clipboard not available'); } } }, 'Copy as text');
    const del = h('button', { class: 'btn danger', onclick: async () => {
      if (!confirm('Delete this setup? Laps keep their times but lose the link to it.')) return;
      await api(`/setups/${st.id}`, { method: 'DELETE' });
      all.splice(all.indexOf(st), 1); current = null; renderList(); renderDetail();
    } }, 'Delete');
    const notes = h('textarea', { rows: 3, placeholder: 'Notes - balance, tyre behaviour, conditions…' }, st.notes || '');
    notes.addEventListener('change', async () => { await api(`/setups/${st.id}`, { method: 'PATCH', body: { notes: notes.value } }); st.notes = notes.value; toast('Notes saved'); });
    detailEl.append(h('div', { class: 'card' },
      h('div', { class: 'row', style: { marginBottom: '6px' } }, name, h('span', { class: 'grow' }), fav, copy, del),
      h('div', { class: 'row small muted', style: { marginBottom: '14px', gap: '10px' } },
        h('span', {}, trackName(st.track_id)), st.team_id !== null ? h('span', { class: 'row', style: { gap: '5px' } }, teamChip(st.team_id), teamName(st.team_id)) : null,
        h('span', {}, `captured ${fmtDate(st.created_at)}`), h('span', {}, `${st.laps} laps · best ${fmtLap(st.best_lap_ms)}`),
        st.session_id ? h('a', { href: `#/session/${st.session_id}` }, 'first session') : null),
      h('div', { class: 'row', style: { marginBottom: '12px' } }, cmpSel, other ? h('span', { class: 'small muted' }, 'Highlighted rows differ: this setup → compared setup') : null),
      renderSetup(st.data, other?.data),
      h('div', { style: { marginTop: '14px' } }, notes)));
    const adv = h('div', { class: 'card', style: { marginTop: '12px' } }, h('div', { class: 'card-title' }, 'Setup advisor'), h('div', { class: 'muted small' }, 'Reading the laps…'));
    detailEl.append(adv);
    const my = st.id;
    api(`/setups/${st.id}/advice`).then(a => { if (current === my) adv.replaceChildren(...advisorView(a, id => { current = id; compare = null; renderList(); renderDetail(); })); })
      .catch(e => adv.replaceChildren(h('div', { class: 'card-title' }, 'Setup advisor'), h('div', { class: 'muted' }, e.message)));
  }
  renderList();
  renderDetail();
  return () => mq.removeEventListener('change', lay);
}

// ------------------------------------------------------------------ advisor
const BAL_ROWS = [['bands', 'slow', 'Slow corners', 'under 120 km/h'], ['bands', 'medium', 'Medium corners', '120–200 km/h'], ['bands', 'fast', 'Fast corners', 'over 200 km/h'],
  ['phases', 'entry', 'Corner entry', 'on the brakes'], ['phases', 'mid', 'Mid-corner', 'coasting'], ['phases', 'exit', 'Corner exit', 'on the power']];
const balWord = u => u >= 0.25 ? 'understeer' : u <= -0.25 ? 'oversteer' : 'neutral';

function advisorView(a, openSetup) {
  const title = h('div', { class: 'card-title' }, 'Setup advisor',
    h('span', { class: 'right small muted' }, a.laps ? `${a.laps} laps · best ${fmtLap(a.best_ms)} · typical ${fmtLap(a.typical_ms)}` : 'no laps yet'));
  if (!a.laps) return [title, h('p', { class: 'muted', style: { margin: 0 } }, 'Drive a few laps with this setup and the advisor reads its balance from them.')];
  const pr = a.profile;
  const MAX = 3;  // degrees at the end of each bar
  const rows = BAL_ROWS.map(([grp, k, label, sub]) => {
    const u = pr[grp][k].us;
    const w = u === null ? 0 : Math.min(50, Math.abs(u) / MAX * 50);
    return h('div', { class: 'bal-row' },
      h('div', { class: 'bal-label' }, h('div', {}, label), h('div', { class: 'small muted' }, sub)),
      h('div', { class: 'bal-track', title: u === null ? 'Not enough cornering here yet' : `${u > 0 ? '+' : ''}${u.toFixed(2)}° understeer angle` },
        h('i', { class: 'bal-mid' }),
        u === null ? null : h('i', { class: 'bal-bar ' + (u >= 0 ? 'us' : 'os'), style: u >= 0 ? { left: '50%', width: w + '%' } : { right: '50%', width: w + '%' } })),
      h('div', { class: 'bal-val small tnum' }, u === null ? 'not enough data' : `${u > 0 ? '+' : u < 0 ? '−' : ''}${Math.abs(u).toFixed(1)}° ${balWord(u)}`));
  });
  const extra = [
    pr.spin_pct !== null ? `Wheelspin on ${pr.spin_pct.toFixed(0)}% of the way out of slow corners` : null,
    pr.lock_pct !== null ? `lock-ups on ${pr.lock_pct.toFixed(0)}% of the braking` : null,
    pr.ts_f !== null && pr.ts_r !== null ? `tyre surface ${fmtTemp(pr.ts_f)} front, ${fmtTemp(pr.ts_r)} rear` : null,
  ].filter(Boolean).join(' · ');
  const balance = h('div', {}, h('div', { class: 'bal-axis small muted' }, h('span', {}, '← oversteer (the rear slides)'), h('span', {}, 'understeer (the front pushes) →')),
    ...rows, extra ? h('div', { class: 'small muted', style: { marginTop: '8px' } }, extra) : null);
  const tips = h('div', { class: 'stack', style: { marginTop: '14px' } }, h('b', {}, 'What to try'),
    ...a.suggestions.map(s => h('div', { class: 'adv-tip' }, h('span', { class: 'badge info' }, s.area),
      h('div', {}, h('div', { class: 'ink2' }, s.text), s.changes.length ? h('div', { class: 'row', style: { gap: '6px', marginTop: '4px' } }, ...s.changes.map(c => h('span', { class: 'chip' }, c))) : null))),
    h('div', { class: 'small muted' }, 'One change at a time, then a few laps: the advisor compares the new setup with this one.'));
  const out = [title, balance, tips];
  const p = a.previous;
  if (p) {
    const prevName = p.name || `Setup #${p.id}`;
    out.push(h('div', { class: 'stack', style: { marginTop: '16px' } },
      h('b', {}, 'What changed from ', h('a', { href: '#', onclick: e => { e.preventDefault(); openSetup(p.id); } }, prevName), ', and what it did'),
      p.changes.length ? h('div', { class: 'row', style: { gap: '6px' } }, ...p.changes.map(c => h('span', { class: 'chip' }, `${c.label} ${c.from} → ${c.to}`)))
        : h('div', { class: 'muted small' }, 'Only the fuel load differs.'),
      p.effects.length ? h('ul', { class: 'adv-effects' }, ...p.effects.map(e => h('li', {}, e.text)))
        : h('div', { class: 'muted small' }, 'No clear change in balance, wheelspin, lock-ups or tyre temperatures.'),
      h('div', { class: 'row small', style: { gap: '14px' } },
        p.best_delta_ms !== null ? h('span', {}, 'Best lap ', h('b', { class: 'tnum ' + deltaClass(p.best_delta_ms) }, fmtDelta(p.best_delta_ms))) : null,
        p.typical_delta_ms !== null ? h('span', {}, 'Typical lap ', h('b', { class: 'tnum ' + deltaClass(p.typical_delta_ms) }, fmtDelta(p.typical_delta_ms))) : null,
        h('span', { class: 'muted' }, `${p.laps} laps with ${prevName}`)),
      p.caveats.length ? h('div', { class: 'small', style: { color: 'var(--warn)' } }, `Not a like-for-like comparison: ${p.caveats.join(', ')}.`) : null));
  }
  return out;
}
