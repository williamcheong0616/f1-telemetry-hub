// Friends' laps: .f1lap files exported from this app on another PC, imported here to compare against.
// The app shows them with negative lap ids; everything about them comes from the file, checked on import.
import { h, toast, fmtLap, fmtDate, trackName } from './util.js';

export const isGuest = id => Number(id) < 0;
export const guestLabel = lap => lap.driver || 'Friend';

async function upload(file) {
  const r = await fetch('/api/guest-laps', { method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' } });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

// a button that picks one or more .f1lap files and imports them; onDone(laps) with the imported laps
export function importButton(onDone, label = "Import a friend's lap") {
  const input = h('input', { type: 'file', accept: '.f1lap,application/octet-stream', multiple: true, class: 'hidden', onchange: async () => {
    const done = [];
    for (const f of input.files) {
      try { done.push(await upload(f)); } catch (e) { toast(`${f.name}: ${e.message}`); }
    }
    input.value = '';
    if (done.length) {
      toast(done.length === 1 ? `Imported ${guestLabel(done[0])}'s ${fmtLap(done[0].lap_time_ms)} at ${trackName(done[0].track_id)}` : `Imported ${done.length} laps`);
      onDone?.(done);
    }
  } });
  return h('span', {}, input, h('button', { class: 'btn sm', title: 'Load a .f1lap file someone exported from their copy of the app', onclick: () => input.click() }, label));
}

// Settings card: every imported lap, to open, use or delete
export function friendsCard() {
  const list = h('div');
  const el = h('div', { class: 'card' }, h('div', { class: 'card-title' }, "Friends' laps", h('span', { class: 'right' }, importButton(() => load()))),
    h('p', { class: 'small ink2', style: { marginTop: 0 } }, 'Send a lap with ', h('b', {}, 'Export lap'), " on a session's lap table. A friend imports the file here and can pick it as the reference on the Telemetry, Workstation and Coach pages."),
    list);
  async function load() {
    let rows = [];
    try { rows = await fetch('/api/guest-laps').then(r => r.json()); } catch { /* app busy */ }
    if (!rows.length) { list.replaceChildren(h('div', { class: 'muted small' }, 'No laps imported yet.')); return; }
    list.replaceChildren(h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Driver'), h('th', {}, 'Circuit'), h('th', { class: 'num' }, 'Lap'), h('th', {}, 'Imported'), h('th', {}, ''))),
      h('tbody', {}, ...rows.map(l => h('tr', {},
        h('td', {}, guestLabel(l)), h('td', {}, trackName(l.track_id)), h('td', { class: 'num tnum' }, fmtLap(l.lap_time_ms)),
        h('td', { class: 'muted' }, fmtDate(l.imported_at)),
        h('td', { class: 'row', style: { gap: '6px', justifyContent: 'flex-end' } },
          h('a', { class: 'btn sm', href: `#/analysis?laps=${l.id}` }, 'Telemetry'),
          h('button', { class: 'btn sm', onclick: async () => {
            if (!confirm(`Delete ${guestLabel(l)}'s lap at ${trackName(l.track_id)}?`)) return;
            await fetch(`/api/guest-laps/${l.id}`, { method: 'DELETE' }); load();
          } }, 'Delete'))))))));
  }
  load();
  return el;
}
