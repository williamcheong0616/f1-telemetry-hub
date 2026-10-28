// Race engineer radio: lists the engineer's messages and speaks them with the browser's own voice.
// The messages come from fixed rules in the app (engineer.py); nothing leaves this PC. Voice, tones and
// which kinds of message to hear are remembered per device, so a phone beside the screen can talk
// while the PC stays quiet.
import { h } from './util.js';

export const RADIO_KINDS = [
  ['pace', 'Lap times'], ['sectors', 'Sector and micro-sector calls'], ['gaps', 'Gaps and positions'],
  ['fuel', 'Fuel and battery'], ['tyres', 'Tyres, pit window and strategy'], ['weather', 'Weather'],
  ['alerts', 'Flags, penalties and damage'], ['session', 'Session (radio check, laps left, result)'],
  ['coach', 'Debrief (where the time is, after a session)'],
];
const KIND_LABEL = { pace: 'Pace', sectors: 'Sectors', gaps: 'Gaps', fuel: 'Fuel', tyres: 'Tyres', weather: 'Weather', alerts: 'Alert', session: 'Session', coach: 'Debrief' };
const RATES = [[0.9, 'Slow'], [1.05, 'Normal'], [1.2, 'Quick'], [1.35, 'Very quick']];
// micro-sector tones: two high beeps for a record, one beep when faster than the PB lap, a low one when slower
const TONES = { p: [[1320, 0.07], [0, 0.05], [1320, 0.07]], g: [[880, 0.09]], y: [[440, 0.12]] };

const KEY = 'f1th.radio';
function loadPrefs() {
  const d = { voice: false, beep: true, tones: false, rate: 1.05, voiceURI: '', off: [] };
  try { return { ...d, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch { return d; }
}
function savePrefs(p) { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* storage blocked */ } }

export class Radio {
  constructor() {
    this.prefs = loadPrefs();
    this.synth = 'speechSynthesis' in window ? window.speechSynthesis : null;
    this.spoken = null;   // highest message id already handled
    this.microSeq = null;
    this.listKey = '';
    this.audio = null;
    this.el = this._build();
    this._unlock = () => { this.audio?.resume?.(); this._hint(); };
    document.addEventListener('pointerdown', this._unlock);
    document.addEventListener('keydown', this._unlock);
    if (this.synth) this.synth.addEventListener?.('voiceschanged', () => this._fillVoices());
  }

  destroy() {
    document.removeEventListener('pointerdown', this._unlock);
    document.removeEventListener('keydown', this._unlock);
    this.synth?.cancel();
  }

  enabled(kind) { return !this.prefs.off.includes(kind); }

  _set(k, v) { this.prefs[k] = v; savePrefs(this.prefs); }

  _build() {
    const p = this.prefs;
    this.voiceBtn = h('button', { class: 'btn sm', 'aria-pressed': String(p.voice), onclick: () => this._toggleVoice() });
    this.setBtn = h('button', { class: 'btn sm', 'aria-expanded': 'false', title: 'Choose what the engineer tells you', onclick: () => {
      const open = this.panel.classList.toggle('hidden') === false;
      this.setBtn.setAttribute('aria-expanded', String(open));
    } }, 'Messages');
    this.voiceSel = h('select', { 'aria-label': 'Voice', onchange: () => this._set('voiceURI', this.voiceSel.value) });
    const rate = h('select', { 'aria-label': 'Speaking speed', onchange: () => this._set('rate', Number(rate.value)) },
      ...RATES.map(([v, l]) => h('option', { value: v, selected: v === p.rate || null }, l)));
    const check = (label, on, set) => {
      const box = h('input', { type: 'checkbox', checked: on || null, onchange: () => set(box.checked) });
      return h('label', { class: 'check small' }, box, label);
    };
    this.panel = h('div', { class: 'radio-panel hidden' },
      h('div', { class: 'radio-kinds' }, ...RADIO_KINDS.map(([k, label]) => check(label, this.enabled(k), on => {
        this._set('off', on ? this.prefs.off.filter(x => x !== k) : [...this.prefs.off, k]);
        this.listKey = '';
      }))),
      h('div', { class: 'stack', style: { marginTop: '10px' } },
        check('Radio click before each message', p.beep, on => this._set('beep', on)),
        check('A tone for every micro-sector (two high beeps: your record, one beep: faster than your PB lap, low beep: slower)', p.tones, on => this._set('tones', on))),
      this.synth ? h('div', { class: 'row small', style: { marginTop: '10px' } }, this.voiceSel, rate,
        h('button', { class: 'btn sm', onclick: () => { this._ensureAudio(); this.speak({ say: 'Radio check. Loud and clear.' }, true); } }, 'Test voice'))
        : h('p', { class: 'small muted' }, 'This browser has no speech voices: messages are shown as text only.'));
    this.hintEl = h('div', { class: 'small muted hidden radio-hint' }, 'Click anywhere on this page to let the engineer speak (browsers keep pages quiet until you do).');
    this.list = h('div', { class: 'radio-list', 'aria-live': 'polite' });
    const card = h('div', { class: 'card radio-card' },
      h('h3', {}, 'Race engineer', h('span', { class: 'right row', style: { gap: '6px' } }, this.synth ? this.voiceBtn : null, this.setBtn)),
      this.panel, this.hintEl, this.list);
    this._voiceLabel();
    this._fillVoices();
    this._renderList([]);
    return card;
  }

  _voiceLabel() {
    this.voiceBtn.textContent = this.prefs.voice ? 'Voice on' : 'Voice off';
    this.voiceBtn.setAttribute('aria-pressed', String(this.prefs.voice));
    this.voiceBtn.classList.toggle('primary', this.prefs.voice);
    this._hint();
  }

  _hint() {
    const blocked = this.prefs.voice && navigator.userActivation && !navigator.userActivation.hasBeenActive;
    this.hintEl.classList.toggle('hidden', !blocked);
  }

  _toggleVoice() {
    this._set('voice', !this.prefs.voice);
    this._voiceLabel();
    if (this.prefs.voice) { this._ensureAudio(); this.speak({ say: 'Radio check. Loud and clear.' }, true); }
    else this.synth?.cancel();
  }

  _fillVoices() {
    if (!this.synth) return;
    const voices = this.synth.getVoices();
    const en = voices.filter(v => /^en/i.test(v.lang));
    const list = en.length ? en : voices;
    this.voiceSel.innerHTML = '';
    this.voiceSel.append(h('option', { value: '' }, 'Default voice'),
      ...list.map(v => h('option', { value: v.voiceURI, selected: v.voiceURI === this.prefs.voiceURI || null }, `${v.name} (${v.lang})`)));
  }

  _voice() {
    const voices = this.synth.getVoices();
    return voices.find(v => v.voiceURI === this.prefs.voiceURI)
      || voices.find(v => /^en-GB/i.test(v.lang)) || voices.find(v => /^en/i.test(v.lang)) || null;
  }

  _ensureAudio() {
    if (!this.audio && (window.AudioContext || window.webkitAudioContext)) {
      try { this.audio = new (window.AudioContext || window.webkitAudioContext)(); } catch { this.audio = null; }
    }
    this.audio?.resume?.();
  }

  // [[frequency, seconds]], frequency 0 = silence
  _beep(steps, gain = 0.08) {
    const ctx = this.audio;
    if (!ctx || ctx.state !== 'running') return 0;
    let t = ctx.currentTime + 0.01;
    for (const [f, d] of steps) {
      if (f) {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'sine'; o.frequency.value = f;
        g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(gain, t + 0.008); g.gain.setValueAtTime(gain, t + d - 0.015); g.gain.linearRampToValueAtTime(0, t + d);
        o.connect(g).connect(ctx.destination); o.start(t); o.stop(t + d + 0.02);
      }
      t += d;
    }
    return (t - ctx.currentTime) * 1000;
  }

  speak(m, force = false) {
    if (!this.synth || (!this.prefs.voice && !force)) return;
    const u = new SpeechSynthesisUtterance(m.say || m.text);
    const v = this._voice();
    if (v) { u.voice = v; u.lang = v.lang; } else u.lang = 'en-GB';
    u.rate = this.prefs.rate;
    if (m.urgent) this.synth.cancel();  // a safety car or a penalty doesn't wait behind a lap time
    const idle = !this.synth.speaking && !this.synth.pending;
    const wait = idle && this.prefs.beep ? this._beep([[1150, 0.05], [0, 0.03], [1500, 0.06]], 0.05) : 0;
    if (wait) setTimeout(() => this.synth.speak(u), wait + 40); else this.synth.speak(u);
  }

  update(snap) {
    const msgs = snap.radio || [];
    const source = snap.replay?.running ? 'replay:' + snap.replay.name : 'live';
    if (source !== this.source) { this.source = source; this.spoken = null; this.microSeq = null; }  // a replay counts its messages from 1
    const maxId = msgs.reduce((a, m) => Math.max(a, m.id), 0);
    if (this.spoken === null || (msgs.length && maxId < this.spoken)) this.spoken = maxId;  // nothing said before the page opened (or the app restarted)
    for (const m of msgs) {
      if (m.id <= this.spoken) continue;
      this.spoken = m.id;
      if (this.enabled(m.kind)) this.speak(m);
    }
    const shown = msgs.filter(m => this.enabled(m.kind));
    const key = shown.map(m => m.id).join() + '|' + this.prefs.off.join();
    if (key !== this.listKey) { this.listKey = key; this._renderList(shown); }
    const mc = snap.player?.micro;
    if (mc) {
      if (this.microSeq === null || mc.seq < this.microSeq) this.microSeq = mc.seq;
      else if (mc.seq > this.microSeq) {
        this.microSeq = mc.seq;
        const tone = TONES[mc.last_done?.[1]];
        if (tone && this.prefs.tones && this.prefs.voice) this._beep(tone);
      }
    }
  }

  _renderList(msgs) {
    this.list.innerHTML = '';
    if (!msgs.length) {
      this.list.append(h('div', { class: 'muted small' }, 'Lap times, gaps, fuel, tyres, weather and alerts will be called here.'));
      return;
    }
    for (const m of [...msgs].reverse().slice(0, 12)) {
      this.list.append(h('div', { class: 'radio-msg' + (m.urgent ? ' urgent' : '') },
        h('span', { class: 'lap' }, m.lap ? 'L' + m.lap : ''),
        h('span', { class: 'badge' + (m.urgent ? ' bad' : '') }, KIND_LABEL[m.kind] || m.kind),
        h('span', { class: 'txt' }, m.text)));
    }
  }
}
