import { api, h, toast, state, applyTheme, fmtNum, fmtDate, fmtLap, trackName, sessionTypeName } from '../util.js';
import { clock, fmtSize, startReplay } from '../replaybar.js';
import { friendsCard } from '../friends.js';

const PACKET_NAMES = ['Motion', 'Session', 'Lap Data', 'Event', 'Participants', 'Car Setups', 'Car Telemetry', 'Car Status',
  'Final Classification', 'Lobby Info', 'Car Damage', 'Session History', 'Tyre Sets', 'Motion Ex', 'Time Trial', 'Lap Positions'];

export async function mount(root) {
  const [settings, status, demo] = await Promise.all([api('/settings'), api('/status'), api('/demo')]);
  root.append(h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Settings'), h('div', { class: 'sub' }, `F1 Telemetry Hub v${status.version}`))));
  const grid = h('div', { class: 'grid cols-2' });
  root.append(grid);

  // ---------------------------------------------------------------- connection
  const diag = h('div');
  const conn = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Game connection'), diag);
  const renderDiag = s => {
    diag.innerHTML = '';
    diag.append(...[
      h('div', { class: 'row', style: { marginBottom: '10px' } },
        s.udp_error ? h('span', { class: 'badge bad' }, 'Not listening') : s.connected ? h('span', { class: 'badge good' }, 'Receiving data') : h('span', { class: 'badge' }, 'Waiting for data'),
        h('span', { class: 'muted small' }, s.udp_error || `UDP ${s.udp_host}:${s.udp_port} · ${fmtNum(s.pps, 0)} packets/s · ${fmtNum(s.packets)} total`)),
      s.game ? h('div', { class: 'small muted', style: { marginBottom: '8px' } }, `Game: F1 ${s.game.year} · packet format ${s.game.format} · version ${s.game.version}`) : null,
      Object.keys(s.size_warnings || {}).length ? h('div', { class: 'badge warn', style: { whiteSpace: 'normal', textTransform: 'none', marginBottom: '8px' } },
        `Unexpected packet sizes for: ${Object.keys(s.size_warnings).map(k => PACKET_NAMES[k] || k).join(', ')}. Make sure UDP Format is 2025, or 2026 with the 2026 Season Pack.`) : null,
      h('ol', { class: 'small ink2', style: { paddingLeft: '18px', margin: '0 0 10px' } },
        h('li', {}, 'In the game: Settings › Telemetry Settings'),
        h('li', {}, 'UDP Telemetry ', h('b', {}, 'On'), ', UDP Broadcast Mode ', h('b', {}, 'Off')),
        s.platform === 'darwin'  // the game can't run on a Mac: it sends to the Mac from a console or a PC
          ? h('li', {}, 'UDP IP Address ', h('b', {}, (s.local_ips || []).join(' / ') || "this Mac's IP address"),
            `${(s.local_ips || []).length ? ' (this Mac)' : ' (System Settings › Network)'}, set on the console or PC the game runs on (also enable "Allow LAN" below for viewing on a tablet)`)
          : h('li', {}, 'UDP IP Address ', h('b', {}, '127.0.0.1'), (s.local_ips || []).length ? ` - or ${s.local_ips.join(' / ')} when the game runs on a console or another PC (also enable "Allow LAN" below for viewing on a tablet)` : ''),
        h('li', {}, 'UDP Port ', h('b', {}, String(s.udp_port)), ', Send Rate ', h('b', {}, '30–60 Hz'), ', UDP Format ', h('b', {}, '2025'), ', Your Telemetry ', h('b', {}, 'Public'))),
      h('details', {}, h('summary', { class: 'small muted', style: { cursor: 'pointer' } }, 'Packets received by type'),
        h('table', { class: 'data', style: { marginTop: '6px' } }, h('tbody', {}, ...PACKET_NAMES.map((n, i) => h('tr', {}, h('td', { class: 'muted' }, `${i} · ${n}`), h('td', { class: 'num' }, fmtNum(s.packet_counts?.[i] || 0)))))))].filter(Boolean));
  };
  renderDiag(status);
  const timer = setInterval(async () => { try { renderDiag(await api('/status')); } catch { /* app closing */ } }, 2000);
  grid.append(conn);

  // ---------------------------------------------------------------- demo
  const demoCard = h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Demo mode'));
  const kind = h('select', {}, h('option', { value: 'race' }, 'Race'), h('option', { value: 'quali' }, 'Qualifying'), h('option', { value: 'tt' }, 'Time trial'),
    h('option', { value: 'weekend' }, 'Career weekend (quali + race)'));
  const fmt = h('select', { 'aria-label': 'Cars and UDP format' }, h('option', { value: 2025 }, '2025 cars (format 2025)'),
    h('option', { value: 2026 }, '2026 cars (format 2026)'));
  const laps = h('input', { type: 'number', value: 5, min: 1, max: 60, style: { width: '80px' } });
  const speed = h('select', {}, ...[1, 2, 5, 10].map(v => h('option', { value: v }, `${v}× speed`)));
  const stateEl = h('span', { class: 'small muted' });
  const startBtn = h('button', { class: 'btn primary', onclick: async () => {
    await api('/demo', { method: 'POST', body: { action: 'start', session: kind.value, laps: Number(laps.value), speed: Number(speed.value), format: Number(fmt.value) } });
    toast('Demo started - open the Live tab'); refreshDemo();
  } }, 'Start demo');
  const stopBtn = h('button', { class: 'btn', onclick: async () => { await api('/demo', { method: 'POST', body: { action: 'stop' } }); refreshDemo(); } }, 'Stop');
  const delBtn = h('button', { class: 'btn danger', onclick: async () => {
    if (!confirm('Delete all sessions recorded on the Demo Circuit?')) return;
    const r = await api('/demo/data', { method: 'DELETE' }); toast(`Deleted ${r.deleted_sessions} demo sessions`);
  } }, 'Delete demo data');
  const refreshDemo = async () => { const d = await api('/demo'); stateEl.textContent = d.running ? `Running: ${d.session}, ${d.laps} laps at ${d.speed}×, format ${d.format}` : 'Not running'; stopBtn.disabled = !d.running; };
  stateEl.textContent = demo.running ? `Running: ${demo.session}` : 'Not running';
  stopBtn.disabled = !demo.running;
  demoCard.append(h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Generates realistic F1 25 telemetry on a fictional "Demo Circuit" so you can try every screen without the game. Demo sessions are stored like real ones; delete them any time.'),
    h('div', { class: 'row' }, kind, fmt, h('label', { class: 'row small' }, 'Laps', laps), speed, startBtn, stopBtn),
    h('div', { class: 'row', style: { marginTop: '10px' } }, stateEl, h('span', { class: 'grow' }), delBtn));
  grid.append(demoCard);

  // ---------------------------------------------------------------- preferences
  const f = {};
  const field = (label, el, hint) => h('label', { class: 'field' }, h('span', {}, label), el, hint ? h('span', { style: { fontWeight: 400 } }, hint) : null);
  f.udp_port = h('input', { type: 'number', value: settings.udp_port, min: 1, max: 65535 });
  f.forward = h('input', { type: 'text', value: (settings.forward || []).join(', '), placeholder: 'e.g. 127.0.0.1:20778' });
  f.telemetry_hz = h('select', {}, ...[10, 20, 30, 60].map(v => h('option', { value: v }, `${v} samples/s`)));
  f.telemetry_hz.value = String(settings.telemetry_hz);
  f.speed_unit = h('select', {}, h('option', { value: 'kmh' }, 'km/h'), h('option', { value: 'mph' }, 'mph'));
  f.speed_unit.value = settings.speed_unit;
  f.temp_unit = h('select', {}, h('option', { value: 'c' }, '°C'), h('option', { value: 'f' }, '°F'));
  f.temp_unit.value = settings.temp_unit;
  f.theme = h('select', {}, h('option', { value: 'dark' }, 'Dark'), h('option', { value: 'light' }, 'Light'), h('option', { value: 'system' }, 'Follow system'));
  f.theme.value = settings.theme || 'dark';
  f.http_port = h('input', { type: 'number', value: settings.http_port, min: 1024, max: 65535 });
  f.lan_access = h('input', { type: 'checkbox', checked: settings.lan_access || null });
  f.open_browser = h('input', { type: 'checkbox', checked: settings.open_browser || null });
  const save = h('button', { class: 'btn primary', onclick: async () => {
    const body = {
      udp_port: Number(f.udp_port.value), forward: f.forward.value, telemetry_hz: Number(f.telemetry_hz.value),
      speed_unit: f.speed_unit.value, temp_unit: f.temp_unit.value, theme: f.theme.value, http_port: Number(f.http_port.value),
      lan_access: f.lan_access.checked, open_browser: f.open_browser.checked,
    };
    try {
      const r = await api('/settings', { method: 'POST', body });
      state.settings = r.settings;
      applyTheme(r.settings.theme);
      toast(r.restart_required ? 'Saved - restart the app for the dashboard port / LAN change' : 'Settings saved');
      if (r.listener?.udp_error) toast(r.listener.udp_error, 5000);
    } catch (e) { toast(e.message, 4000); }
  } }, 'Save settings');
  grid.append(h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Preferences'),
    h('div', { class: 'grid cols-2' },
      field('UDP port', f.udp_port, 'must match the game'),
      field('Recording rate', f.telemetry_hz, 'telemetry samples stored per second'),
      field('Speed unit', f.speed_unit), field('Temperature unit', f.temp_unit),
      field('Theme', f.theme),
      field('Forward UDP to', f.forward, 'comma-separated host:port, for other tools'),
      field('Dashboard port', f.http_port, 'needs restart'),
      h('div', { class: 'stack', style: { paddingTop: '18px' } },
        h('label', { class: 'check small' }, f.lan_access, 'Allow LAN access (view on phone / tablet) - needs restart'),
        h('label', { class: 'check small' }, f.open_browser, 'Open the dashboard when the app starts'))),
    h('div', { class: 'row', style: { marginTop: '14px' } }, save)));

  // ---------------------------------------------------------------- recordings
  const recs = recordingsCard(settings);
  grid.append(recs.el, friendsCard());

  // ---------------------------------------------------------------- data
  grid.append(h('div', { class: 'card' }, h('div', { class: 'card-title' }, 'Data'),
    h('p', { class: 'small ink2', style: { marginTop: 0 } }, 'Everything is stored locally in a SQLite database. Nothing is uploaded anywhere.'),
    h('div', { class: 'small' }, h('span', { class: 'muted' }, 'Folder: '), h('code', { class: 'inline' }, status.data_dir)),
    h('div', { class: 'small', style: { marginTop: '6px' } }, h('span', { class: 'muted' }, 'Database size: '), `${fmtNum(status.db_size / 1048576, 1)} MB`),
    h('div', { class: 'row', style: { marginTop: '12px' } }, h('button', { class: 'btn', onclick: () => api('/open-folder', { method: 'POST' }) }, 'Open data folder')),
    h('p', { class: 'small muted' }, 'Back up by copying the folder while the app is closed.')));
  return () => { clearInterval(timer); recs.destroy(); };
}

// Raw game data saved to files, one per session, to replay on the Live page or send to someone.
function recordingsCard(settings) {
  const auto = h('input', { type: 'checkbox', checked: settings.auto_record || null, onchange: async () => {
    try {
      const r = await api('/settings', { method: 'POST', body: { auto_record: auto.checked } });
      state.settings = r.settings;
      toast(auto.checked ? 'Every session will be recorded' : 'Automatic recording off');
      refresh();
    } catch (e) { toast(e.message); auto.checked = !auto.checked; }
  } });
  const caps = [2, 5, 10, 20, 50, 100];
  if (!caps.includes(settings.recordings_max_gb)) caps.push(settings.recordings_max_gb), caps.sort((a, b) => a - b);
  const cap = h('select', { 'aria-label': 'Most disk space for recordings', onchange: async () => {
    try { const r = await api('/settings', { method: 'POST', body: { recordings_max_gb: Number(cap.value) } }); state.settings = r.settings; refresh(); }
    catch (e) { toast(e.message); }
  } }, ...caps.map(v => h('option', { value: v }, `${v} GB`)));
  cap.value = String(settings.recordings_max_gb);
  const summary = h('span', { class: 'small muted tnum' });
  const list = h('div', { class: 'table-wrap' });
  let key = null;

  const del = async it => {
    if (!confirm(`Delete the recording ${it.name}? The session stays in your history.`)) return;
    try { await api(`/recordings/${it.name}`, { method: 'DELETE' }); toast('Recording deleted'); refresh(); }
    catch (e) { toast(e.message); }
  };
  const render = info => {
    const k = JSON.stringify([info.items, info.replay?.name, info.max_gb]);
    const used = info.total_bytes, max = info.max_gb * 1e9;
    summary.textContent = `${info.items.length} recording${info.items.length === 1 ? '' : 's'} · ${fmtSize(used)} of ${info.max_gb} GB`
      + (used > max * 0.9 ? ' · the oldest are deleted to make room' : '');
    if (k === key) return;
    key = k;
    if (!info.items.length) {
      list.replaceChildren(h('p', { class: 'small muted', style: { margin: '6px 0 0' } },
        'No recordings yet. Press ● Record on the Live page, or record every session automatically.'));
      return;
    }
    list.replaceChildren(h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Recorded'), h('th', {}, 'Session'), h('th', { class: 'num' }, 'Length'), h('th', { class: 'num' }, 'Size'), h('th', {}))),
      h('tbody', {}, ...info.items.map(it => {
        const s = it.session;
        const playing = info.replay?.running && info.replay.name === it.name;
        const label = s ? h('a', { href: `#/session/${s.id}` }, `${trackName(s.track_id)} · ${sessionTypeName(s.session_type)}`)
          : h('span', { class: 'muted', title: 'Nothing was saved to the history from this file, e.g. only menus or a session shorter than a lap' }, 'No session in history');
        return h('tr', {},
          h('td', { class: 'nowrap' }, fmtDate(it.started_at)),
          h('td', {}, label, s?.best_lap_ms ? h('span', { class: 'muted small' }, ` · best ${fmtLap(s.best_lap_ms)}`) : null,
            it.game_year ? h('span', { class: 'muted small' }, ` · F1 ${it.game_year}`) : null),
          h('td', { class: 'num' }, clock(it.duration_s)),
          h('td', { class: 'num' }, fmtSize(it.size)),
          h('td', { class: 'num nowrap' }, it.recording ? h('span', { class: 'badge bad' }, 'Recording…')
            : h('span', { class: 'row', style: { gap: '6px', justifyContent: 'flex-end', flexWrap: 'nowrap' } },
              playing ? h('a', { class: 'btn sm', href: '#/live' }, 'Replaying') : h('button', { class: 'btn sm primary', onclick: () => startReplay(it.name) }, '▶ Replay'),
              h('a', { class: 'btn sm', href: `/api/recordings/${it.name}`, download: it.name }, 'Download'),
              h('button', { class: 'btn sm danger', onclick: () => del(it) }, 'Delete'))));
      }))));
  };
  const refresh = async () => { try { render(await api('/recordings')); } catch { /* app closing */ } };
  refresh();
  const timer = setInterval(refresh, 4000);
  const el = h('div', { class: 'card', style: { gridColumn: '1 / -1' } }, h('div', { class: 'card-title' }, 'Recordings'),
    h('p', { class: 'small ink2', style: { marginTop: 0 } }, 'A recording keeps everything the game sends, one file per session. ',
      'Replay it on the Live page - race engineer and micro-sectors included - to look at a session again, or send the file to someone to look at your data. ',
      'Replays never change your history.'),
    h('div', { class: 'row' },
      h('label', { class: 'check small' }, auto, 'Record every session automatically'),
      h('label', { class: 'row small' }, 'Keep up to', cap),
      h('span', { class: 'grow' }), summary,
      h('button', { class: 'btn sm', onclick: () => api('/open-folder', { method: 'POST', body: { folder: 'recordings' } }) }, 'Open recordings folder')),
    list);
  return { el, destroy: () => clearInterval(timer) };
}
