// The bar above the Live page: the Record button, and the controls of a replay while one is running.
import { api, h, toast, trackName, sessionTypeName, fmtDate } from './util.js';

const SPEEDS = [0.5, 1, 2, 4, 8, 16];

export const clock = s => {
  s = Math.max(0, Math.round(s || 0));
  const hh = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), ss = String(s % 60).padStart(2, '0');
  return hh ? `${hh}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
};
export const fmtSize = b => (b === null || b === undefined ? '–' : b >= 1e9 ? (b / 1e9).toFixed(2) + ' GB' : (b / 1e6).toFixed(b >= 1e8 ? 0 : 1) + ' MB');

export async function startReplay(name, speed = 1) {
  try {
    await api('/replay', { method: 'POST', body: { action: 'start', name, speed } });
    location.hash = '#/live';
  } catch (e) { toast(e.message); }
}

export class LiveBar {
  constructor() {
    this.r = null; this.c = null; this.dragging = false;
    this.playBtn = h('button', { class: 'btn sm', onclick: () => this._cmd(this.r?.paused ? 'resume' : 'pause') });
    this.speedSeg = h('div', { class: 'segmented', role: 'group', 'aria-label': 'Replay speed' },
      ...SPEEDS.map(v => h('button', { 'data-v': v, onclick: () => this._cmd('speed', v) }, `${v}×`)));
    this.range = h('input', { type: 'range', min: 0, max: 1, step: 1, value: 0, class: 'replay-range', 'aria-label': 'Replay position' });
    this.range.addEventListener('pointerdown', () => { this.dragging = true; });
    this.range.addEventListener('change', () => { this.dragging = false; this._cmd('seek', Number(this.range.value)); });
    this.time = h('span', { class: 'small tnum replay-time' });
    this.label = h('span', { class: 'small muted replay-label' });
    this.rp = h('div', { class: 'replay-ctl hidden' }, h('span', { class: 'badge info' }, 'Replay'), this.playBtn, this.speedSeg,
      this.range, this.time, this.label, h('button', { class: 'btn sm', onclick: () => this._cmd('stop') }, 'Stop replay'));
    this.recInfo = h('span', { class: 'small tnum rec-info' });
    this.recBtn = h('button', { class: 'btn sm rec-btn', onclick: () => this._toggleRec() }, '● Record');
    this.el = h('div', { class: 'live-bar' }, this.rp, h('span', { class: 'grow' }), this.recInfo, this.recBtn,
      h('a', { class: 'btn sm', href: '#/rig', title: 'A stripped-down screen for a phone on the rig: delta, micro-sectors, lap time, gear' }, 'Rig display'));
  }

  async _cmd(action, value) {
    try { this.update({ replay: await api('/replay', { method: 'POST', body: { action, value } }), recording: this.c }); }
    catch (e) { toast(e.message); }
  }

  async _toggleRec() {
    const on = !this.c?.manual;
    try {
      const c = await api('/recordings', { method: 'POST', body: { action: on ? 'start' : 'stop' } });
      this.update({ replay: this.r, recording: c });
      toast(on ? 'Recording: everything the game sends is saved, to replay later' : 'Recording stopped');
    } catch (e) { toast(e.message); }
  }

  update(snap) {
    const r = snap.replay, c = snap.recording;
    this.r = r; this.c = c;
    const on = !!r?.running;
    this.rp.classList.toggle('hidden', !on);
    if (on) {
      this.playBtn.textContent = r.paused ? '▶ Play' : '❚❚ Pause';
      for (const b of this.speedSeg.children) b.classList.toggle('on', Number(b.dataset.v) === r.speed);
      const dur = r.duration_s || 0;
      this.range.max = String(Math.max(1, Math.round(dur)));
      if (!this.dragging) this.range.value = String(Math.round(r.pos_s));
      this.time.textContent = r.error ? '' : r.loading ? 'Loading…' : r.seeking ? `Skipping… ${clock(r.pos_s)}`
        : `${clock(r.pos_s)} / ${clock(dur)}${r.done ? ' · finished' : r.paused ? ' · paused' : ''}`;
      const s = r.session;
      this.label.textContent = r.error ? `Replay failed: ${r.error}`
        : [s ? `${trackName(s.track_id)} · ${sessionTypeName(s.session_type)}` : '', r.started_at ? fmtDate(r.started_at) : ''].filter(Boolean).join(' · ');
    }
    if (c) {
      this.recBtn.classList.toggle('on', !!(c.manual || c.active));
      this.recBtn.textContent = c.manual ? '■ Stop recording' : c.auto ? '● Auto-record on' : '● Record';
      this.recBtn.disabled = c.auto && !c.manual;
      this.recBtn.title = c.auto ? 'Every session is recorded: change it in Settings › Recordings' : 'Save everything the game sends, to replay it later';
      this.recInfo.textContent = c.active ? `REC ${clock(c.seconds)} · ${fmtSize(c.bytes)}` : c.armed ? 'Recording starts with the next data' : '';
      this.recInfo.classList.toggle('rec-live', !!c.active);
    }
  }
}
