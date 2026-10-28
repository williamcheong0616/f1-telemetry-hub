// Race strategy on the Live page: the pit window and the best plans with no, one and two stops from the lap
// being driven, worked out by the app from how the tyres are wearing and the lap times falling off.
import { api, h, tyreBadge } from './util.js';

const LOSS_KEY = 'f1th.pitLoss';
const REFRESH_MS = 15000;

function loadLoss() { try { return Number(localStorage.getItem(LOSS_KEY)) || null; } catch { return null; } }
function saveLoss(v) { try { if (v) localStorage.setItem(LOSS_KEY, String(v)); else localStorage.removeItem(LOSS_KEY); } catch { /* storage blocked */ } }

const SOURCE = { 'this race': 'measured in this race', game: "from the game's tyre data", default: 'typical value' };

export class StrategyCard {
  constructor() {
    this.info = h('span', { class: 'right small muted' });
    this.body = h('div', { class: 'stack small' }, h('div', { class: 'muted' }, 'Working out the stops…'));
    this.el = h('div', { class: 'card hidden' }, h('h3', {}, 'Strategy', this.info), this.body);
    this.key = null; this.at = 0; this.busy = false;
  }

  update(snap) {
    const s = snap.session, p = snap.player;
    const race = !!(s && s.category === 'race' && s.total_laps > 1 && p);
    this.el.classList.toggle('hidden', !race);
    if (!race) { this.key = null; return; }
    const key = `${s.uid}:${p.lap}:${p.tyre_visual}:${p.pits}`;
    if (this.busy || (key === this.key && Date.now() - this.at < REFRESH_MS)) return;
    this.key = key; this.fetch();
  }

  fetch() {
    this.at = Date.now(); this.busy = true;
    const loss = loadLoss();
    api(`/live/strategy${loss ? '?pit_loss=' + loss : ''}`).then(r => this.render(r)).catch(() => {}).finally(() => { this.busy = false; });
  }

  render(r) {
    this.info.textContent = r.total_laps ? `lap ${r.lap} of ${r.total_laps}` : '';
    if (!r.available) { this.body.replaceChildren(h('div', { class: 'muted' }, r.reason || 'No strategy yet.')); return; }
    const route = stints => h('span', { class: 'strat-route' }, ...stints.flatMap((s, i) => [
      i ? h('span', { class: 'muted' }, '›') : null,
      h('span', { class: 'strat-stint', title: `${s.name}: laps ${s.from}–${s.to}` }, tyreBadge(s.visual), h('span', { class: 'tnum muted' }, s.laps))]).filter(Boolean));
    const best = r.plans[0], w = r.window;
    const head = h('div', { class: 'strat-best' },
      h('div', { class: 'strat-big' }, best.stops ? `Box lap ${best.pits.join(' and ')}` : 'No stop needed'),
      h('div', {}, best.text),
      w && best.stops === 1 ? h('div', { class: 'muted' }, `Window for the ${w.name.toLowerCase()}: laps ${w.from}–${w.to} (within 1 s of the best lap to box)`) : null);
    const plans = h('div', { class: 'strat-plans' }, ...r.plans.map((p, i) => h('div', { class: 'strat-plan' + (i ? '' : ' best') },
      h('span', {}, ['No stop', '1 stop', '2 stops'][p.stops]), route(p.stints),
      h('span', { class: 'tnum muted' }, p.pits.length ? 'lap ' + p.pits.join(', ') : '–'),
      h('b', { class: 'tnum' + (i ? '' : ' faster') }, i ? `+${p.delta_s.toFixed(1)} s` : 'best'))));
    const c = r.current;
    const now = h('div', {}, h('b', {}, `${c.name} · ${c.age} laps`),
      c.wear !== null && c.wear !== undefined ? ` · ${Math.round(c.wear)}% worn` : '',
      c.wear_rate ? ` (${c.wear_rate.toFixed(1)}%/lap)` : '',
      ` · dropping off ${c.deg.toFixed(2)} s a lap`,
      c.life_lap ? h('span', { style: { color: 'var(--warn)' } }, ` · done around lap ${c.life_lap}`) : '');
    const model = h('table', { class: 'data strat-model' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Tyre'), h('th', { class: 'num', title: 'Seconds lost per lap for every lap of tyre age' }, 'Drop-off'),
        h('th', { class: 'num', title: 'New-tyre pace against your fitted compound' }, 'Pace'), h('th', { class: 'num' }, 'Life'), h('th', { class: 'num' }, 'Sets'))),
      h('tbody', {}, ...r.compounds.map(m => h('tr', {},
        h('td', {}, tyreBadge(m.visual)),
        h('td', { class: 'num tnum', title: SOURCE[m.source] }, `${m.deg.toFixed(3)} s`),
        h('td', { class: 'num tnum', title: SOURCE[m.pace_source] }, m.visual === c.visual ? '–' : `${m.pace > 0 ? '+' : m.pace < 0 ? '−' : ''}${Math.abs(m.pace).toFixed(2)} s`),
        h('td', { class: 'num tnum' }, `${m.life} laps`),
        h('td', { class: 'num tnum' + (m.sets ? '' : ' muted') }, m.sets)))));
    const lossIn = h('input', { type: 'number', min: 5, max: 60, step: 0.5, value: r.pit_loss_s, class: 'strat-loss', 'aria-label': 'Pit stop time loss in seconds',
      onchange: () => { const v = Number(lossIn.value); saveLoss(v >= 5 && v <= 60 ? v : null); this.fetch(); } });
    const gw = r.game_window || {};
    const foot = h('div', { class: 'muted' },
      h('label', { class: 'row', style: { gap: '6px' } }, 'Pit stop costs', lossIn, 's',
        r.pit_loss_source === 'given' && r.measured_pit_loss_s ? h('span', {}, `(measured here: ${r.measured_pit_loss_s} s)`) : null,
        r.pit_loss_source === 'given' ? h('button', { class: 'btn sm', onclick: () => { saveLoss(null); this.fetch(); } }, 'Reset') : null,
        r.pit_loss_source === 'this race' ? h('span', {}, '(measured from your stop)') : null),
      gw.ideal ? h('div', {}, `The game's own pit window: lap ${gw.ideal}${gw.latest && gw.latest !== gw.ideal ? '–' + gw.latest : ''}.`) : null,
      r.dry_rule && r.used.length < 2 ? h('div', {}, 'Every plan uses a second dry compound, as the rules ask.') : null,
      h('div', {}, 'Safety cars and weather change everything: this is the plan for a clean race.'));
    this.body.replaceChildren(head, plans, now, model, foot);
  }
}
