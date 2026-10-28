// Live dashboard: streams /api/live/stream (Server-Sent Events, ~15 Hz).
import {
  api, h, state, fmtLap, fmtSector, fmtDelta, deltaClass, fmtClock, fmtSpeed, speedUnit, fmtTemp, fmtNum,
  tyreBadge, teamChip, WHEELS, WHEEL_LAYOUT, tyreTempState, damageColour, cssVar, speedVal, toast,
} from '../util.js';
import { GForce, LiveTrace, TrackMap } from '../charts.js';
import { ttBadges, ttRows, ttTable } from '../tt.js';
import { Radio } from '../radio.js';
import { LiveBar } from '../replaybar.js';
import { StrategyCard } from '../strategycard.js';

const DAMAGE_PARTS = [['fl_wing', 'Front wing L'], ['fr_wing', 'Front wing R'], ['rear_wing', 'Rear wing'], ['floor', 'Floor'],
  ['diffuser', 'Diffuser'], ['sidepod', 'Sidepods'], ['gearbox', 'Gearbox'], ['engine', 'Engine']];
const PU_PARTS = [['wear_ice', 'ICE'], ['wear_mguh', 'MGU-H'], ['wear_mguk', 'MGU-K'], ['wear_es', 'ES'], ['wear_ce', 'CE'], ['wear_tc', 'TC']];

export async function mount(page) {
  const bar = new LiveBar();  // Record button, and the replay controls while a recording plays
  const root = h('div');
  page.append(bar.el, root);
  let ui = null;
  let frame = 0;
  let outlineVersion = -1;
  let lastOutlineFetch = 0;
  let lastSnap = null;
  let waitingKey = null;
  const radio = new Radio();  // outlives the dashboard, so nothing is read out twice when a new session starts
  const es = new EventSource('/api/live/stream');
  es.onmessage = e => {
    let snap;
    try { snap = JSON.parse(e.data); } catch { return; }
    lastSnap = snap;
    bar.update(snap);
    radio.update(snap);
    frame++;
    if (!snap.session || !snap.player) {
      if (ui) { ui.destroy(); ui = null; }
      const st = state.status || {};
      const key = `${!!snap.status?.connected}|${!!snap.replay?.running}|${snap.replay?.error || ""}|${st.udp_error || ''}|${st.udp_port}|${(st.local_ips || []).join()}`;
      if (key !== waitingKey) { waitingKey = key; renderWaiting(root, snap); }
      return;
    }
    waitingKey = null;
    if (!ui) { root.innerHTML = ''; ui = buildDashboard(root, radio); outlineVersion = -1; }
    update(ui, snap, frame);
    const now = Date.now();
    if (snap.outline_version !== outlineVersion || (!snap.has_outline && now - lastOutlineFetch > 4000)) {
      outlineVersion = snap.outline_version;
      lastOutlineFetch = now;
      api('/live/track').then(t => {
        if (!ui) return;
        ui.map.setOutline(t.outline, { s2: snap.session.s2_start, s3: snap.session.s3_start, partial: t.partial, frame: t.frame });
        ui.$.mapApprox.classList.toggle('hidden', !t.approx);
        fitMap(ui);
      }).catch(() => {});
    }
  };
  return () => { es.close(); radio.destroy(); if (ui) ui.destroy(); };
}

// ------------------------------------------------------------------ waiting screen
function renderWaiting(root, snap) {
  const st = state.status || {};
  const ips = st.local_ips || [];
  root.innerHTML = '';
  if (snap?.replay?.running) {
    const r = snap.replay;
    root.append(h('div', { class: 'waiting' }, h('div', { class: 'card' }, h('div', { class: 'pulse' }),
      h('h2', { style: { margin: '0 0 6px' } }, r.error ? 'The replay could not start' : 'Starting the replay…'),
      h('p', { class: 'muted', style: { margin: 0 } }, r.error || 'The dashboard appears as soon as the recording reaches the session.'))));
    return;
  }
  const demoBtn = h('button', { class: 'btn primary', onclick: async () => {
    demoBtn.disabled = true;
    try { await api('/demo', { method: 'POST', body: { action: 'start', session: 'race', laps: 5, speed: 1 } }); toast('Demo race starting…'); }
    catch (e) { toast(e.message); demoBtn.disabled = false; }
  } }, 'Start a demo race');
  root.append(h('div', { class: 'waiting' }, h('div', { class: 'card' },
    h('div', { class: 'pulse' }),
    h('h2', { style: { margin: '0 0 6px' } }, snap?.status?.connected ? 'Waiting for a session…' : 'Waiting for telemetry'),
    h('p', { class: 'muted', style: { margin: '0 0 14px' } },
      snap?.status?.connected ? 'Data is arriving - head out on track and the dashboard will appear.'
        : `Listening on UDP port ${st.udp_port ?? 20777}. In F1 25 open Settings › Telemetry Settings and set:`),
    st.udp_error ? h('p', { class: 'badge bad', style: { whiteSpace: 'normal', textTransform: 'none' } }, st.udp_error) : null,
    h('ol', {},
      h('li', {}, 'UDP Telemetry: ', h('b', {}, 'On'), ' · UDP Broadcast Mode: ', h('b', {}, 'Off')),
      st.platform === 'darwin'  // the game can't run on a Mac: it sends to the Mac from a console or a PC
        ? h('li', {}, 'UDP IP Address: ', h('b', {}, ips.join(' / ') || "this Mac's IP address"), h('span', { class: 'muted' },
          `${ips.length ? ' (this Mac)' : ' (System Settings › Network)'}, set on the console or PC the game runs on`))
        : h('li', {}, 'UDP IP Address: ', h('b', {}, '127.0.0.1'), ips.length ? h('span', { class: 'muted' }, ` (or ${ips.join(' / ')} if the game runs on a console / another PC)`) : null),
      h('li', {}, 'UDP Port: ', h('b', {}, String(st.udp_port ?? 20777)), ' · UDP Send Rate: ', h('b', {}, '30–60 Hz')),
      h('li', {}, 'UDP Format: ', h('b', {}, '2026'), h('span', { class: 'muted' }, ' (2026 Season Pack; 2025 or 2024 also work)'),
        ' · Your Telemetry: ', h('b', {}, 'Public'))),
    h('div', { class: 'row', style: { justifyContent: 'center', marginTop: '16px' } }, demoBtn,
      h('a', { class: 'btn', href: '#/sessions' }, 'Browse history')))));
}

// ------------------------------------------------------------------ dashboard
function buildDashboard(root, radio) {
  const $ = {};
  const ref = (id, el) => { $[id] = el; return el; };
  const kv = (label, id) => h('div', {}, h('div', { class: 'k' }, label), ref(id, h('div', { class: 'v' })));

  const sessionBar = h('div', { class: 'card session-bar' },
    ref('track', h('div', { class: 'track' })),
    ref('stype', h('span', { class: 'badge info' })),
    h('div', { class: 'kv' }, ref('lapsK', h('span', { class: 'k' }, 'Lap')), ref('laps', h('span', { class: 'v' }))),
    h('div', { class: 'kv' }, h('span', { class: 'k' }, 'Weather'), ref('weather', h('span', { class: 'v' }))),
    h('div', { class: 'kv' }, h('span', { class: 'k' }, 'Track / Air'), ref('temps', h('span', { class: 'v' }))),
    ref('scWrap', h('div', { class: 'kv' }, h('span', { class: 'k' }, 'Status'), ref('sc', h('span', { class: 'v' })))),
    ref('pitWrap', h('div', { class: 'kv' }, h('span', { class: 'k' }, 'Pit window'), ref('pitwin', h('span', { class: 'v' })))),
    h('div', { class: 'grow' }),
    ref('forecast', h('div', { class: 'forecast' })),
    ref('stale', h('span', { class: 'badge warn hidden' }, 'No data - paused?')));

  // left column
  const pedal = (label, id, color) => h('div', { class: 'pedal' },
    h('div', { class: 'bar' }, ref(id, h('div', { style: { background: color, height: '0%' } }))), label, ref(id + 'V', h('b', {}, '0')));
  const carCard = h('div', { class: 'card' }, h('h3', {}, 'Car', ref('pl', h('span', { class: 'right muted' }))),
    h('div', { class: 'dash-main' }, ref('gear', h('div', { class: 'gear' }, 'N')),
      h('div', {}, ref('speed', h('div', { class: 'speed' })), ref('rpm', h('div', { class: 'small muted tnum' })),
        h('div', { class: 'revbar' }, ref('rev', h('div', { style: { width: '0%' } }))))),
    h('div', { class: 'pedals' }, pedal('Throttle', 'thr', cssVar('--throttle')), pedal('Brake', 'brk', cssVar('--brake')), pedal('Clutch', 'clu', cssVar('--muted'))),
    h('div', { class: 'small muted', style: { marginTop: '10px' } }, 'Steering'),
    h('div', { class: 'steer' }, ref('steer', h('div', { style: { left: '50%' } }))),
    h('div', { class: 'kv-grid', style: { marginTop: '14px' } },
      h('div', {}, ref('drsK', h('div', { class: 'k' }, 'DRS')), ref('drs', h('div', { class: 'v' }))),
      ref('otWrap', h('div', { class: 'hidden' }, h('div', { class: 'k' }, 'Overtake Mode'), ref('ot', h('div', { class: 'v' })))),
      h('div', {}, h('div', { class: 'k' }, 'ERS'), h('div', { class: 'v' }, ref('ers', h('span'))), h('div', { class: 'meter' }, ref('ersBar', h('div', { style: { width: '0%' } })))),
      h('div', {}, h('div', { class: 'k' }, 'Fuel'), ref('fuel', h('div', { class: 'v' }))),
      kv('Fuel mix', 'fmix'), kv('Brake bias', 'bbias'), kv('Engine temp', 'etemp'),
      kv('TC / ABS', 'tcabs'), h('div', {}, ref('ersLapK', h('div', { class: 'k' }, 'Deployed / harvested')), ref('ersLap', h('div', { class: 'v' })))));
  const gCard = h('div', { class: 'card' }, h('h3', {}, 'G-force'));
  const gforce = new GForce(gCard, 180);
  gCard.append(h('div', { class: 'kv-grid', style: { gridTemplateColumns: 'repeat(3,1fr)', marginTop: '8px', textAlign: 'center' } },
    kv('Lateral', 'glat'), kv('Longitudinal', 'glon'), kv('Vertical', 'gvert')));

  // centre column
  const lapCard = h('div', { class: 'card' },
    h('h3', {}, 'Lap', ref('lapState', h('span', { class: 'right' }))),
    h('div', { class: 'row', style: { alignItems: 'flex-end', gap: '24px' } },
      h('div', {}, h('div', { class: 'small muted' }, 'Position'), ref('pos', h('div', { class: 'laptime' }, '–'))),
      h('div', { class: 'grow' }, h('div', { class: 'small muted' }, 'Current lap'), ref('laptime', h('div', { class: 'laptime tnum' }, '–'))),
      h('div', { class: 'deltas' },
        h('div', {}, h('div', { class: 'small muted' }, 'Δ personal best'), ref('dpb', h('div', { class: 'delta-big' }, '–'))),
        h('div', {}, h('div', { class: 'small muted' }, 'Δ session best'), ref('dsb', h('div', { class: 'delta-big' }, '–'))))),
    h('div', { class: 'sectors' }, ...[0, 1, 2].map(i => ref('sec' + i, h('div', { class: 'sector' }, h('div', { class: 'k' }, 'Sector ' + (i + 1)), h('div', { class: 'v' }, '–'))))),
    ref('microWrap', h('div', { class: 'micro-wrap hidden' },
      h('div', { class: 'micro-head small' }, h('span', { class: 'k' }, 'Micro-sectors'),
        h('span', { class: 'lg' }, h('i', { class: 'swatch mc-p' }), 'Your record'),
        h('span', { class: 'lg' }, h('i', { class: 'swatch mc-g' }), 'Faster than PB lap'),
        h('span', { class: 'lg' }, h('i', { class: 'swatch mc-y' }), 'Slower'),
        h('span', { class: 'grow' }), ref('microIdeal', h('span', { class: 'muted tnum' }))),
      ref('micro', h('div', { class: 'micro' })),
      ref('microInfo', h('div', { class: 'small muted tnum', style: { marginTop: '4px' } })))),
    h('div', { class: 'kv-grid', style: { gridTemplateColumns: 'repeat(4, minmax(0,1fr))', marginTop: '12px' } },
      kv('Last lap', 'last'), kv('Session best', 'best'), kv('Personal best', 'pb'), kv('Gap ahead / leader', 'gaps')));
  const traceCard = h('div', { class: 'card' }, h('h3', {}, 'Inputs · last 15 s',
    h('span', { class: 'right row small', style: { gap: '12px' } },
      h('span', { class: 'lg' }, h('i', { class: 'swatch', style: { background: cssVar('--s1'), height: '3px' } }), ' Speed'),
      h('span', {}, h('i', { class: 'swatch', style: { background: cssVar('--throttle'), height: '3px' } }), ' Throttle'),
      h('span', {}, h('i', { class: 'swatch', style: { background: cssVar('--brake'), height: '3px' } }), ' Brake'))));
  const trace = new LiveTrace(traceCard, { seconds: 15, height: 170 });
  // Static shows the whole circuit, Dynamic follows your car; either can fill the whole window.
  const mapState = loadMapState();
  const modeBtn = (mode, label, title) => h('button', { 'data-mode': mode, title, onclick: () => setMapMode(mode) }, label);
  const mapCard = ref('mapCard', h('div', { class: 'card map-card' },
    h('h3', {}, 'Track', h('span', { class: 'grow' }),
      ref('mapMode', h('div', { class: 'segmented' }, modeBtn('static', 'Static', 'Show the whole circuit'), modeBtn('dynamic', 'Dynamic', 'Follow your car'))),
      ref('mapZoom', h('span', { class: 'zoom' },
        h('button', { class: 'btn sm', title: 'Zoom out', 'aria-label': 'Zoom out', onclick: () => zoomMap(1) }, '−'),
        h('button', { class: 'btn sm', title: 'Zoom in', 'aria-label': 'Zoom in', onclick: () => zoomMap(-1) }, '+'))),
      ref('mapFull', h('button', { class: 'btn sm', title: 'Fill the whole window (Esc to leave)', onclick: () => setMapFull(!mapCard.classList.contains('map-full')) }, 'Full window')))));
  const map = new TrackMap(mapCard, { height: 340 });
  mapCard.append(h('div', { class: 'map-legend' },
    ...[1, 2, 3].map(i => h('span', { class: 'lg' }, h('i', { class: 'swatch', style: { background: `var(--sec${i})` } }), `Sector ${i}`)),
    ref('zoneLg', h('span', { class: 'lg hidden' }, h('i', { class: 'zone-swatch' }), ref('zoneLgT', h('span')))),
    h('span', { class: 'grow' }),
    ref('mapApprox', h('span', { class: 'muted hidden', title: 'Cars are placed by lap distance until a few corners have lined the map up with the game' }, 'Approximate positions')),
    ref('mapInfo', h('span', { class: 'muted tnum' }))));
  const towerCard = ref('towerCard', h('div', { class: 'card' }, h('h3', {}, 'Timing', ref('towerInfo', h('span', { class: 'right muted' }))),
    h('div', { class: 'table-wrap' }, ref('tower', h('table', { class: 'data tower' })))));
  const ttCard = ref('ttCard', h('div', { class: 'card hidden' }, h('h3', {}, 'Time trial', ref('ttInfo', h('span', { class: 'right row', style: { gap: '6px' } }))),
    ref('tt', h('div', { class: 'table-wrap' }))));

  // right column
  const tyreCard = h('div', { class: 'card' }, h('h3', {}, 'Tyres', ref('tyreHead', h('span', { class: 'right row', style: { gap: '8px' } }))),
    ref('tyres', h('div', { class: 'tyres' })), ref('tyreSets', h('div', { class: 'row small', style: { marginTop: '10px', gap: '6px' } })));
  const dmgCard = h('div', { class: 'card' }, h('h3', {}, 'Damage & power unit', ref('faults', h('span', { class: 'right row', style: { gap: '6px' } }))),
    ref('dmg', h('div', { class: 'stack small' })), ref('pu', h('div', { class: 'kv-grid', style: { gridTemplateColumns: 'repeat(3,1fr)', marginTop: '12px' } })));
  const evCard = h('div', { class: 'card' }, h('h3', {}, 'Race control'), ref('events', h('div', { class: 'events' })));
  $.strategy = new StrategyCard();

  root.append(sessionBar, h('div', { class: 'live-grid' },
    h('div', { class: 'live-col' }, carCard, gCard),
    h('div', { class: 'live-col' }, lapCard, mapCard, ttCard, traceCard, towerCard),
    h('div', { class: 'live-col live-right' }, radio.el, tyreCard, $.strategy.el, dmgCard, evCard)));

  // tyre boxes (front axle on top)
  $.tyreBoxes = WHEEL_LAYOUT.map(w => {
    const box = h('div', { class: 'tyre-box' },
      h('div', { class: 'pos' }, h('span', {}, WHEELS[w]), h('span', { class: 'wear' })),
      h('div', { class: 'temp' }), h('div', { class: 'rows' }));
    $.tyres.append(box);
    return { w, box };
  });
  $.dmgRows = DAMAGE_PARTS.map(([k, label]) => {
    const fill = h('div', { style: { width: '0%' } });
    const val = h('span', { class: 'tnum', style: { width: '36px', textAlign: 'right' } });
    $.dmg.append(h('div', { class: 'dmg-row' }, h('span', { style: { width: '92px' } }, label), h('div', { class: 'bar' }, fill), val));
    return { k, fill, val };
  });

  function setMapMode(mode) {
    mapState.mode = mode; saveMapState(mapState);
    for (const b of $.mapMode.children) b.classList.toggle('on', b.dataset.mode === mode);
    $.mapZoom.classList.toggle('hidden', mode !== 'dynamic');
    if (mode !== 'dynamic') map.setFollow(null);
  }
  function zoomMap(dir) {
    const i = MAP_SPANS.indexOf(mapState.span);
    mapState.span = MAP_SPANS[Math.max(0, Math.min(MAP_SPANS.length - 1, (i < 0 ? 2 : i) + dir))];
    saveMapState(mapState);
    if (map.follow) map.setFollow({ ...map.follow, span: mapState.span });
  }
  function setMapFull(on) {
    mapCard.classList.toggle('map-full', on);
    $.mapFull.textContent = on ? 'Exit full window' : 'Full window';
    if (!on) fitMap(ui);
  }
  const onKey = e => { if (e.key === 'Escape' && mapCard.classList.contains('map-full')) setMapFull(false); };
  const onResize = () => fitMap(ui);
  const onWheel = e => { if (mapState.mode !== 'dynamic') return; e.preventDefault(); zoomMap(e.deltaY > 0 ? 1 : -1); };
  document.addEventListener('keydown', onKey);
  window.addEventListener('resize', onResize);
  map.canvas.addEventListener('wheel', onWheel, { passive: false });
  setMapMode(mapState.mode);
  const ui = { $, map, trace, gforce, mapState, destroy: () => {
    document.removeEventListener('keydown', onKey); window.removeEventListener('resize', onResize);
    map.destroy(); trace.destroy();
  } };
  requestAnimationFrame(() => fitMap(ui));
  return ui;
}

const MAP_SPANS = [200, 300, 450, 700, 1000, 1500];  // dynamic map: metres across its shorter side
function loadMapState() {
  try {
    const v = JSON.parse(localStorage.getItem('f1th.liveMap') || '{}');
    return { mode: v.mode === 'dynamic' ? 'dynamic' : 'static', span: MAP_SPANS.includes(v.span) ? v.span : 450 };
  } catch { return { mode: 'static', span: 450 }; }
}
function saveMapState(st) { try { localStorage.setItem('f1th.liveMap', JSON.stringify(st)); } catch { /* storage blocked */ } }

// Size the map so the whole card fits in the window: down to the bottom edge from where the card starts
// (or the window height under the top bar when it starts too far down), never taller than the circuit needs.
function fitMap(ui) {
  const card = ui.$.mapCard, box = ui.map.box;
  if (!card.isConnected || card.classList.contains('map-full')) return;
  const chrome = card.offsetHeight - box.offsetHeight;  // header, legend, padding
  const topbar = document.querySelector('.topbar')?.offsetHeight || 0;
  const top = card.getBoundingClientRect().top + window.scrollY;
  let avail = window.innerHeight - top - chrome - 16;
  if (avail < 320) avail = window.innerHeight - topbar - chrome - 28;
  const a = ui.map.outline ? ui.map.aspect() : null;
  const need = a ? box.clientWidth / a + 56 : avail;  // 56: the map's own padding above and below the circuit
  const hgt = Math.round(Math.max(220, Math.min(avail, need)));
  if (Math.abs(box.offsetHeight - hgt) > 2) box.style.height = hgt + 'px';
}

// "VERSTAPPEN" / "Max Verstappen" -> "VER"
const shortName = n => { const w = String(n || '').trim().split(/\s+/).pop().replace(/[^\p{L}\p{N}]/gu, ''); return (w || String(n || '')).slice(0, 3).toUpperCase(); };

const set = (el, txt) => { if (el && el.textContent !== txt) el.textContent = txt; };

function update(ui, snap, frame) {
  const { $ } = ui;
  const s = snap.session, p = snap.player;
  $.strategy.update(snap);
  // session bar
  set($.track, s.track);
  set($.stype, s.type_name);
  if (s.category === 'race' && s.total_laps) { set($.lapsK, 'Lap'); set($.laps, `${p.lap} / ${s.total_laps}`); }
  else { set($.lapsK, 'Time left'); set($.laps, fmtClock(s.time_left)); }
  set($.weather, s.weather_name);
  set($.temps, `${fmtTemp(s.track_temp)} / ${fmtTemp(s.air_temp)}`);
  set($.sc, (s.sc ? s.sc_name : 'Green') + (s.aero_partial ? ' · partial aero' : ''));
  $.sc.className = 'v ' + (s.sc ? 'slower' : '');
  $.pitWrap.classList.toggle('hidden', !(s.category === 'race' && s.pit_ideal));
  set($.pitwin, s.pit_ideal ? `L${s.pit_ideal}–${s.pit_latest} (rejoin P${s.pit_rejoin})` : '–');
  $.stale.classList.toggle('hidden', !!snap.status.connected || !!snap.replay?.running);
  if (frame % 15 === 1) {
    $.forecast.innerHTML = '';
    for (const f of (s.forecast || []).slice(0, 5)) {
      $.forecast.append(h('div', { class: 'f', title: `Track ${f.track_temp}°C, air ${f.air_temp}°C` },
        h('b', {}, f.offset ? `+${f.offset}m` : 'Now'), `${state.meta.weather[f.weather] || '–'} · ${f.rain}%`));
    }
  }

  // car
  set($.gear, p.gear === 0 ? 'N' : p.gear < 0 ? 'R' : String(p.gear));
  $.speed.innerHTML = `${fmtSpeed(p.speed)}<small>${speedUnit()}</small>`;
  set($.rpm, `${fmtNum(p.rpm)} rpm${p.suggested_gear ? ' · suggested ' + p.suggested_gear : ''}`);
  const revPct = Math.min(100, (p.rpm / (p.max_rpm || 13000)) * 100);
  $.rev.style.width = revPct + '%';
  $.rev.style.background = revPct > 95 ? cssVar('--critical') : revPct > 85 ? cssVar('--warn') : cssVar('--good');
  const pedal = (id, v) => { $[id].style.height = Math.round(v) + '%'; set($[id + 'V'], Math.round(v) + '%'); };
  pedal('thr', p.throttle * 100); pedal('brk', p.brake * 100); pedal('clu', p.clutch);
  $.steer.style.left = (50 + (p.steer || 0) * 50) + '%';
  if (p.regs_2026) {
    // 2026 cars: active aero replaces DRS, Overtake Mode is the new push-to-pass
    set($.drsK, 'Active aero');
    set($.drs, p.aero_mode ? 'Straight mode' : p.aero_available ? 'Available' : p.aero_distance ? `in ${p.aero_distance} m` : 'Corner mode');
    $.drs.className = 'v ' + (p.aero_mode ? 'faster' : '');
    set($.ot, p.ot_active ? 'ACTIVE' : p.ot_available ? 'Available' : p.ot_distance ? `in ${p.ot_distance} m` : '–');
    $.ot.className = 'v ' + (p.ot_active ? 'faster' : '');
  } else {
    set($.drsK, 'DRS');
    set($.drs, p.drs ? 'OPEN' : p.drs_allowed ? 'Available' : p.drs_distance ? `in ${p.drs_distance} m` : 'Off');
    $.drs.className = 'v ' + (p.drs ? 'faster' : '');
  }
  $.otWrap.classList.toggle('hidden', !p.regs_2026);
  set($.ers, `${fmtNum(p.ers_pct, 0)}% · ${p.ers_mode}`);
  $.ersBar.style.width = Math.min(100, p.ers_pct || 0) + '%';
  set($.fuel, p.fuel === null ? '–' : `${fmtNum(p.fuel, 1)} kg · ${p.fuel_laps >= 0 ? '+' : ''}${fmtNum(p.fuel_laps, 2)} laps`);
  set($.fmix, p.fuel_mix);
  set($.bbias, p.brake_bias ? p.brake_bias + '%' : '–');
  set($.etemp, fmtTemp(p.engine_temp));
  set($.tcabs, `${['Off', 'Med', 'Full'][p.tc] ?? '–'} / ${p.abs ? 'On' : 'Off'}`);
  if (p.ers_harvest_limit_mj) {  // format 2026 sends the per-lap harvest limit
    set($.ersLapK, `Deployed / harvested (max ${fmtNum(p.ers_harvest_limit_mj, 1)} MJ)`);
    set($.ersLap, `${fmtNum(p.ers_deployed_mj, 2)} / ${fmtNum(p.ers_harvested_mj, 2)} MJ`);
  } else {
    set($.ersLapK, 'Deployed / harvested');
    set($.ersLap, `${fmtNum(p.ers_deployed_pct, 0)}% / ${fmtNum(p.ers_harvested_pct, 0)}%`);
  }
  ui.gforce.push(p.g_lat, p.g_lon);
  set($.glat, fmtNum(p.g_lat, 2) + 'g'); set($.glon, fmtNum(p.g_lon, 2) + 'g'); set($.gvert, fmtNum(p.g_vert, 2) + 'g');
  set($.pl, `${p.name}${p.team ? ' · ' + p.team : ''}`);

  // lap
  set($.pos, p.position ? 'P' + p.position : '–');
  set($.laptime, fmtLap(p.lap_time_ms));
  $.laptime.classList.toggle('invalid', !!p.invalid);
  $.lapState.innerHTML = '';
  $.lapState.append(...[
    p.wrong_way ? h('span', { class: 'badge bad' }, 'Wrong way') : null,
    p.invalid ? h('span', { class: 'badge bad' }, 'Lap invalid') : null,
    p.pit_status ? h('span', { class: 'badge warn' }, p.pit_status === 1 ? 'Pitting' : 'In pit lane') : null,
    p.penalties ? h('span', { class: 'badge bad' }, `+${p.penalties}s penalty`) : null,
    p.warnings ? h('span', { class: 'badge' }, `${p.warnings} warnings`) : null,
    h('span', { class: 'muted small' }, p.driver_status),
  ].filter(Boolean));
  set($.dpb, fmtDelta(p.delta_pb_ms, 2)); $.dpb.className = 'delta-big ' + deltaClass(p.delta_pb_ms);
  set($.dsb, fmtDelta(p.delta_session_ms, 2)); $.dsb.className = 'delta-big ' + deltaClass(p.delta_session_ms);
  const cur = [p.s1_ms, p.s2_ms, null];
  for (let i = 0; i < 3; i++) {
    const box = $['sec' + i];
    let val = null, cls = 'sector';
    if (i < p.sector) val = cur[i];
    if (val) cls += ' ' + sectorClass(val, i, p);
    if (i === p.sector) {
      cls += ' active';
      const done = (p.sector > 0 ? p.s1_ms : 0) + (p.sector > 1 ? p.s2_ms : 0);
      set(box.lastChild, fmtSector(p.lap_time_ms - done));
      box.lastChild.className = 'v muted';
    } else {
      set(box.lastChild, val ? fmtSector(val) : (p.last_sectors?.[i] ? fmtSector(p.last_sectors[i]) : '–'));
      box.lastChild.className = val ? 'v' : 'v muted';
    }
    box.className = cls;
  }
  renderMicro(ui, p.micro);
  set($.last, fmtLap(p.last_lap_ms));
  set($.best, fmtLap(p.best_lap_ms));
  set($.pb, fmtLap(p.pb_ms));
  set($.gaps, s.category === 'race' ? `${p.position > 1 ? '+' + (p.delta_front_ms / 1000).toFixed(1) : '–'} / ${p.position > 1 ? '+' + (p.delta_leader_ms / 1000).toFixed(1) : '–'}` : '–');

  ui.trace.push(performance.now() / 1000, speedVal(p.speed), p.throttle * 100, p.brake * 100, speedVal(360));

  // tyres
  if (frame % 3 === 0) {
    $.tyreHead.innerHTML = '';
    $.tyreHead.append(tyreBadge(p.tyre_visual), h('span', { class: 'ink2' }, `${p.tyre_name}${p.tyre_compound ? ' (' + p.tyre_compound + ')' : ''} · ${p.tyre_age ?? 0} laps`));
    for (const { w, box } of $.tyreBoxes) {
      const surf = p.tyre_surface?.[w], inner = p.tyre_inner?.[w];
      box.className = 'tyre-box ' + tyreTempState(surf);
      set(box.querySelector('.wear'), p.wear ? `${fmtNum(p.wear[w], 1)}% wear` : '');
      set(box.querySelector('.temp'), fmtTemp(surf));
      box.querySelector('.rows').innerHTML =
        `<span>Inner</span><span>${fmtTemp(inner)}</span><span>Pressure</span><span>${fmtNum(p.tyre_pressure?.[w], 1)} psi</span>` +
        `<span>Brake</span><span>${fmtTemp(p.brake_temp?.[w])}</span>` +
        (p.blisters?.[w] ? `<span>Blisters</span><span>${p.blisters[w]}%</span>` : '') +
        (p.tyre_damage?.[w] ? `<span>Damage</span><span>${p.tyre_damage[w]}%</span>` : '');
    }
    $.tyreSets.innerHTML = '';
    if (p.tyre_sets?.length) {
      $.tyreSets.append(h('span', { class: 'muted' }, 'Available sets:'));
      for (const t of p.tyre_sets.slice(0, 10)) $.tyreSets.append(h('span', { class: 'chip', title: `${t.name} ${t.compound} · ${t.life_span} laps left` }, tyreBadge(t.visual), `${t.wear}%`, t.fitted ? ' (fitted)' : ''));
    }
    // damage
    const d = p.damage || {};
    for (const r of $.dmgRows) {
      const v = d[r.k] || 0;
      r.fill.style.width = v + '%'; r.fill.style.background = damageColour(v);
      set(r.val, v + '%');
    }
    $.pu.innerHTML = '';
    for (const [k, label] of PU_PARTS) $.pu.append(h('div', {}, h('div', { class: 'k' }, label + ' wear'), h('div', { class: 'v' }, (d[k] ?? 0) + '%')));
    $.faults.innerHTML = '';
    if (d.drs_fault) $.faults.append(h('span', { class: 'badge bad' }, 'DRS fault'));
    if (d.ers_fault) $.faults.append(h('span', { class: 'badge bad' }, 'ERS fault'));
    if (d.engine_blown) $.faults.append(h('span', { class: 'badge bad' }, 'Engine blown'));
  }

  // map
  const zones = (s.aero_zones?.length ? s.aero_zones : s.drs_zones || []).map(([a, b]) => [a * s.track_length, b * s.track_length]);
  const zoneKey = JSON.stringify(zones);
  if (zoneKey !== ui.zoneKey) {
    ui.zoneKey = zoneKey; ui.map.setZones(zones);
    $.zoneLg.classList.toggle('hidden', !zones.length);
    set($.zoneLgT, s.aero_zones?.length ? 'Active aero zone' : 'DRS zone');
  }
  ui.map.setSectors(s.s2_start, s.s3_start);
  ui.map.setActiveSector(p.sector ?? null);
  const dyn = ui.mapState.mode === 'dynamic';
  const me = snap.cars.find(c => c.player);
  ui.map.setCars(snap.cars.map(c => ({ x: c.x, z: c.z, color: c.color, player: c.player,
    label: c.player ? `P${c.pos}` : dyn ? `${c.pos} ${shortName(c.name)}` : String(c.pos) })),
  dyn && me && me.x !== null && me.x !== undefined ? { x: me.x, z: me.z, span: ui.mapState.span } : null);
  set($.mapInfo, `${snap.cars.length} cars · ${fmtNum(p.lap_distance, 0)} m`);
  if (frame % 15 === 0) fitMap(ui);

  // tower + events (lower refresh rate)
  if (frame % 4 === 0) {
    renderTower(ui, snap);
    renderTimeTrial(ui, snap);
  }
  if (frame % 8 === 0) {
    $.events.innerHTML = '';
    const evs = [...snap.events].reverse();
    if (!evs.length) $.events.append(h('div', { class: 'muted' }, 'No events yet'));
    for (const e of evs) $.events.append(h('div', { class: 'ev' }, h('span', { class: 'lap' }, e.lap ? 'L' + e.lap : ''), h('span', {}, e.text)));
  }
}

// Micro-sectors: each sector in equal stretches. Purple = your record there, green = at least as quick as
// your personal-best lap, yellow = slower; stretches not reached yet this lap show the last lap faded.
const MICRO_WORDS = { p: 'your record', g: 'faster than your PB lap', y: 'slower than your PB lap', n: 'first time timed here' };
function renderMicro(ui, mc) {
  const { $ } = ui;
  $.microWrap.classList.toggle('hidden', !mc);
  if (!mc) return;
  const key = JSON.stringify([mc.cur, mc.at, mc.last?.map(c => c?.[1]), mc.ideal_ms]);
  if (key === ui.microKey) return;
  ui.microKey = key;
  const n = mc.cur.length, per = mc.per;
  if (!ui.microCells || ui.microCells.length !== n) {
    $.micro.innerHTML = '';
    ui.microCells = [];
    for (let s = 0; s < 3; s++) {
      const grp = h('div', { class: 'micro-sec' });
      for (let i = s * per; i < (s + 1) * per; i++) { const c = h('i', { class: 'mc' }); grp.append(c); ui.microCells.push(c); }
      $.micro.append(grp);
    }
  }
  const counts = { p: 0, g: 0, y: 0 };
  ui.microCells.forEach((el, i) => {
    const c = mc.cur[i], prev = mc.last?.[i];
    const label = `${Math.floor(i / per) + 1}.${i % per + 1}`;
    let cls = 'mc', title;
    if (c) {
      cls += ' mc-' + c[1];
      if (counts[c[1]] !== undefined) counts[c[1]]++;
      title = `Micro-sector ${label}: ${fmtSector(c[0])} s${c[2] !== null ? ` (${fmtDelta(c[2], 3)} vs PB lap)` : ''}, ${MICRO_WORDS[c[1]]}`;
    } else if (prev) {
      cls += ' mc-' + prev[1] + ' faded';
      title = `Micro-sector ${label}: last lap ${fmtSector(prev[0])} s, ${MICRO_WORDS[prev[1]]}`;
    } else title = `Micro-sector ${label}: not timed yet`;
    if (i === mc.at) cls += ' now';
    el.className = cls;
    el.title = title;
  });
  set($.microIdeal, mc.ideal_ms ? `Ideal lap ${fmtLap(mc.ideal_ms)}` : '');
  $.microIdeal.title = 'Your best time in every micro-sector, added up';
  const done = counts.p + counts.g + counts.y;
  set($.microInfo, !mc.has_best ? 'Your first valid lap here sets the micro-sector records.'
    : done ? `This lap: ${counts.p} record${counts.p === 1 ? '' : 's'} · ${counts.g} faster · ${counts.y} slower` : 'This lap: –');
}

function sectorClass(v, i, p) {
  const ob = p.overall_best_sectors?.[i];
  const pb = p.best_sectors?.[i];
  if (ob && v <= ob) return 'purple';
  if (!pb || v <= pb) return 'green';
  return 'yellow';
}

function renderTimeTrial(ui, snap) {
  const tt = snap.time_trial;
  const { $ } = ui;
  $.ttCard.classList.toggle('hidden', !tt);
  $.towerCard.classList.toggle('hidden', !!tt && snap.cars.length <= 1);
  if (!tt) return;
  const p = snap.player;
  const current = { label: 'This lap', running: true, lap_ms: p.lap_time_ms, invalid: p.invalid,
    s1_ms: p.sector > 0 ? p.s1_ms : null, s2_ms: p.sector > 1 ? p.s2_ms : null };
  $.tt.replaceChildren(ttTable(ttRows(tt, current)));
  $.ttInfo.replaceChildren(...ttBadges(tt));
}

function renderTower(ui, snap) {
  const s = snap.session;
  const race = s.category === 'race';
  const cars = snap.cars;
  const bestOverall = Math.min(...cars.map(c => c.best_ms || Infinity));
  const t = ui.$.tower;
  t.innerHTML = '';
  t.append(h('thead', {}, h('tr', {}, h('th', { class: 'num' }, 'Pos'), h('th', {}, 'Driver'), h('th', { class: 'num' }, race ? 'Gap' : 'Gap'),
    h('th', { class: 'num' }, race ? 'Int' : ''), h('th', { class: 'num' }, 'Last'), h('th', { class: 'num' }, 'Best'), h('th', {}, 'Tyre'),
    h('th', { class: 'num' }, 'Pits'), h('th', {}, ''))));
  const tb = h('tbody');
  for (const c of cars) {
    let gap = '–', intv = '';
    if (race) {
      gap = c.pos === 1 ? 'Leader' : c.gap_leader_ms ? '+' + (c.gap_leader_ms / 1000).toFixed(1) : '–';
      intv = c.pos === 1 ? '' : c.gap_front_ms ? '+' + (c.gap_front_ms / 1000).toFixed(1) : '–';
    } else if (c.best_ms && isFinite(bestOverall)) {
      gap = c.best_ms === bestOverall ? fmtLap(c.best_ms) : '+' + ((c.best_ms - bestOverall) / 1000).toFixed(3);
    }
    const flags = [];
    if (c.pit) flags.push(h('span', { class: 'badge warn' }, 'PIT'));
    if (c.penalties) flags.push(h('span', { class: 'badge bad' }, `+${c.penalties}s`));
    if (c.status && c.status !== 'Active') flags.push(h('span', { class: 'badge' }, c.status));
    tb.append(h('tr', { class: c.player ? 'me' : '' },
      h('td', { class: 'pos num' }, c.pos),
      h('td', {}, h('span', { class: 'row', style: { gap: '8px', flexWrap: 'nowrap' } }, teamChip(c.team_id), c.name)),
      h('td', { class: 'num' }, gap), h('td', { class: 'num muted' }, intv),
      h('td', { class: 'num' + (c.invalid ? ' muted' : '') }, fmtLap(c.last_ms)),
      h('td', { class: 'num' + (c.best_ms && c.best_ms === bestOverall ? ' sec-purple' : '') }, fmtLap(c.best_ms)),
      h('td', {}, c.tyre ? h('span', { class: 'row', style: { gap: '4px', flexWrap: 'nowrap' } }, tyreBadge(c.tyre), h('span', { class: 'muted small' }, c.tyre_age ?? '')) : '–'),
      h('td', { class: 'num' }, c.pits || ''),
      h('td', {}, ...flags)));
  }
  t.append(tb);
  ui.$.towerInfo.textContent = `${cars.length} cars`;
}
