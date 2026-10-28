// Rig display: a stripped-down screen for a phone or tablet on the wheel or the monitor stand. A big live
// delta with its bar, the micro-sectors, the lap time, gear and speed - nothing else. Tap the delta to switch
// between your personal best and the session's best; the corner buttons go full screen and keep it awake.
import { api, h, fmtLap, fmtSpeed, speedUnit } from '../util.js';

const PREFS = 'f1th.rig';
const SCALE_S = 1.0;  // the bar is full at this many seconds up or down

function loadPrefs() { try { return { vs: 'pb', ...JSON.parse(localStorage.getItem(PREFS) || '{}') }; } catch { return { vs: 'pb' }; } }
function savePrefs(p) { try { localStorage.setItem(PREFS, JSON.stringify(p)); } catch { /* storage blocked */ } }

export async function mount(root) {
  document.body.classList.add('rig');
  const prefs = loadPrefs();
  const el = {};
  const ref = (k, e) => (el[k] = e);
  const btn = (label, title, onclick) => h('button', { class: 'rig-btn', title, 'aria-label': title, onclick }, label);

  let lock = null;
  const wantAwake = () => prefs.awake !== false;
  async function keepAwake() {
    if (!wantAwake() || !('wakeLock' in navigator) || document.hidden) return;
    try { lock = await navigator.wakeLock.request('screen'); lock.addEventListener('release', () => { lock = null; }); } catch { lock = null; }
    showAwake();
  }
  const onVis = () => { if (!document.hidden && !lock) keepAwake(); };
  document.addEventListener('visibilitychange', onVis);
  const awakeBtn = btn('', 'Keep the screen on', async () => {
    prefs.awake = !wantAwake(); savePrefs(prefs);
    if (prefs.awake) await keepAwake(); else { await lock?.release().catch(() => {}); lock = null; }
    showAwake();
  });
  function showAwake() {
    const ok = 'wakeLock' in navigator;
    awakeBtn.textContent = !ok ? 'Screen: phone settings' : wantAwake() && lock ? 'Screen stays on' : 'Screen may sleep';
    awakeBtn.title = ok ? 'Keep the screen on while this page is open' : 'This browser only keeps the screen on over https or on this PC: set the phone\'s screen timeout instead';
    awakeBtn.classList.toggle('on', !!lock);
  }

  root.append(h('div', { class: 'rig-wrap' },
    h('div', { class: 'rig-ctl' },
      h('a', { class: 'rig-btn', href: '#/live', title: 'Back to the full dashboard' }, '← Dashboard'),
      h('span', { class: 'grow' }),
      ref('info', h('span', { class: 'rig-info' })),
      awakeBtn,
      btn('Full screen', 'Fill the screen', () => { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen?.().catch(() => {}); })),
    h('div', { class: 'rig-delta', role: 'button', tabindex: '0', title: 'Tap to switch between personal best and session best',
      onclick: () => { prefs.vs = prefs.vs === 'pb' ? 'sb' : 'pb'; savePrefs(prefs); }, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { prefs.vs = prefs.vs === 'pb' ? 'sb' : 'pb'; savePrefs(prefs); } } },
      ref('vs', h('div', { class: 'rig-vs' })),
      ref('delta', h('div', { class: 'rig-dnum tnum' }, '–')),
      h('div', { class: 'rig-bar' }, h('i', { class: 'rig-mid' }), ref('bar', h('i', { class: 'rig-fill' })))),
    ref('micro', h('div', { class: 'rig-micro' })),
    h('div', { class: 'rig-main' },
      h('div', { class: 'rig-cell' }, h('span', {}, 'Lap'), ref('lap', h('b', { class: 'tnum' }, '–'))),
      h('div', { class: 'rig-cell rig-gear' }, h('span', {}, 'Gear'), ref('gear', h('b', {}, 'N'))),
      h('div', { class: 'rig-cell' }, h('span', {}, speedUnit()), ref('speed', h('b', { class: 'tnum' }, '–')))),
    h('div', { class: 'rig-foot' },
      h('div', {}, h('span', {}, 'Last'), ref('last', h('b', { class: 'tnum' }, '–'))),
      h('div', {}, ref('bestK', h('span', {}, 'Best')), ref('best', h('b', { class: 'tnum' }, '–'))),
      h('div', {}, ref('posK', h('span', {}, 'Lap')), ref('pos', h('b', { class: 'tnum' }, '–'))))));
  showAwake();
  keepAwake();

  // how to open this page on a phone
  Promise.all([api('/status').catch(() => ({})), api('/settings').catch(() => ({}))]).then(([s, set]) => {
    const ip = (s.local_ips || [])[0];
    el.info.textContent = ip && set.lan_access ? `On a phone: http://${ip}:${s.http_port}/#/rig` : ip ? 'Turn on LAN access in Settings to open this on a phone' : '';
  });

  let cells = [], lastKey = '';
  function micro(mc) {
    if (!mc) { el.micro.replaceChildren(); cells = []; return; }
    if (cells.length !== mc.cur.length) {
      el.micro.replaceChildren(); cells = [];
      for (let s = 0; s < 3; s++) {
        const g = h('div', { class: 'micro-sec' });
        for (let i = 0; i < mc.per; i++) { const c = h('i', { class: 'mc' }); g.append(c); cells.push(c); }
        el.micro.append(g);
      }
    }
    const key = JSON.stringify([mc.cur, mc.at, mc.last?.map(c => c?.[1])]);
    if (key === lastKey) return;
    lastKey = key;
    cells.forEach((c, i) => {
      const cur = mc.cur[i], prev = mc.last?.[i];
      c.className = 'mc' + (cur ? ' mc-' + cur[1] : prev ? ' mc-' + prev[1] + ' faded' : '') + (i === mc.at ? ' now' : '');
    });
  }

  const set = (e, v) => { if (e.textContent !== v) e.textContent = v; };
  const es = new EventSource('/api/live/stream');
  es.onmessage = e => {
    let snap;
    try { snap = JSON.parse(e.data); } catch { return; }
    const p = snap.player, s = snap.session;
    if (!p || !s) { set(el.delta, '–'); set(el.vs, snap.status?.connected ? 'Waiting for your car' : 'Waiting for the game'); el.bar.style.width = '0'; micro(null); return; }
    const pb = prefs.vs === 'pb';
    const d = pb ? p.delta_pb_ms : p.delta_session_ms;
    set(el.vs, pb ? 'vs your personal best' : 'vs the session best');
    if (d === null || d === undefined) {
      set(el.delta, '–'); el.delta.className = 'rig-dnum tnum'; el.bar.style.width = '0';
    } else {
      set(el.delta, (d > 0 ? '+' : d < 0 ? '−' : '') + (Math.abs(d) / 1000).toFixed(3));
      el.delta.className = 'rig-dnum tnum ' + (d < 0 ? 'gain' : d > 0 ? 'loss' : '');
      const w = Math.min(50, Math.abs(d) / 1000 / SCALE_S * 50);
      el.bar.className = 'rig-fill ' + (d < 0 ? 'gain' : 'loss');
      Object.assign(el.bar.style, d < 0 ? { left: '', right: '50%', width: w + '%' } : { right: '', left: '50%', width: w + '%' });
    }
    micro(p.micro);
    set(el.lap, p.lap_time_ms ? fmtLap(p.lap_time_ms) : '–');
    el.lap.classList.toggle('loss', !!p.invalid);
    set(el.gear, p.gear === 0 ? 'N' : p.gear === -1 ? 'R' : String(p.gear ?? '–'));
    set(el.speed, fmtSpeed(p.speed));
    set(el.last, p.last_lap_ms ? fmtLap(p.last_lap_ms) : '–');
    set(el.bestK, pb ? 'Personal best' : 'Session best');
    set(el.best, (pb ? p.pb_ms : p.best_lap_ms) ? fmtLap(pb ? p.pb_ms : p.best_lap_ms) : '–');
    const race = s.category === 'race';
    set(el.posK, race ? 'Position' : 'Lap');
    set(el.pos, race ? `P${p.position}${s.total_laps ? ` · ${p.lap}/${s.total_laps}` : ''}` : String(p.lap ?? '–'));
  };
  return () => {
    es.close();
    document.removeEventListener('visibilitychange', onVis);
    lock?.release().catch(() => {});
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    document.body.classList.remove('rig');
  };
}
