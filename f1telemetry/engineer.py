"""Race engineer: short radio messages worked out from the live data by fixed rules.

No AI model is involved: every message comes from a rule over the telemetry the game sends, so it is
instant, works offline and only quotes numbers the game reported. The dashboard lists the messages and
can speak them with the browser's own voice.

Messages wait for a quiet moment (on a straight, or slow) so the engineer doesn't talk while you brake
or turn in; urgent ones (safety car, flags, penalties, damage) go out at once.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from .constants import INFRINGEMENT_TYPES, PENALTY_TYPES, SESSION_TYPES, TRACKS, VISUAL_COMPOUNDS, WEATHER, name_or

KINDS = ("pace", "sectors", "gaps", "fuel", "tyres", "weather", "alerts", "session", "coach")
WHEEL_NAMES = ("rear left", "rear right", "front left", "front right")  # the order of every wheel array
SPACING_S = 4.0      # between two non-urgent messages
WAIT_S = 8.0         # a non-urgent message goes out after this long even without a quiet moment
STALE_S = 30.0       # ... and is dropped when it still couldn't go out
GAP_EVERY_LAPS = 3   # a plain gaps update when nothing has changed
HOT_C, COLD_C = 108, 72        # tyre surface, smoothed over a few seconds
WEAR_MARKS = (40, 60, 75)      # tyre wear callouts (%)
ERS_MAX_J = 4_000_000.0


def lap_text(ms) -> str:
    m, rem = divmod(int(ms), 60000)
    return f"{m}:{rem / 1000:06.3f}" if m else f"{rem / 1000:.3f}"


def lap_say(ms) -> str:
    """1:28.432 -> "1 28.4", the way an engineer reads a lap time; 1:05.3 -> "1 oh 5.3"."""
    m, tenths = divmod(round(ms / 100), 600)
    s, t = divmod(tenths, 10)
    if not m:
        return f"{s}.{t}"
    return f"{m} {s}.{t}" if s >= 10 else f"{m} oh {s}.{t}"


def delta_say(sec) -> str:
    a = abs(sec)
    if a < 0.05:
        return "less than a tenth"
    if a < 0.15:
        return "a tenth"
    if a < 0.95:
        return f"{round(a * 10)} tenths"
    return "a second" if a < 1.05 else f"{a:.1f} seconds"


def gap_text(sec) -> str:
    return f"{max(sec, 0.1):.1f}"


def gap_say(sec) -> str:
    return f"point {max(1, round(sec * 10))}" if sec < 0.95 else f"{sec:.1f}"


def nice(name) -> str:
    name = (name or "").strip()
    return name.title() if name.isupper() else name


def count_say(n, word) -> str:
    words = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
    return f"{words[n] if n < len(words) else n} {word}{'' if n == 1 else 's'}"


def plural(name) -> str:
    return name + ("es" if name.endswith("h") else "s")


def reason(inf) -> str:
    """A penalty's infringement, the short way an engineer would put it."""
    txt = INFRINGEMENT_TYPES.get(inf, "")
    low = txt.lower()
    if any(w in low for w in ("corner cutting", "ran wide", "running wide", "wall riding")):
        return "track limits"
    if "collision" in low:
        return "causing a collision"
    return low or "an infringement"


def find_corners(cols):
    """The corners of a lap, as the Telemetry page finds them: speed minima with at least 20 km/h of drop
    before and recovery after. Returns [(name, from, to)] in lap distance, named C1, C2, ..."""
    return [(name, lo, hi) for name, _, lo, hi in corner_points(cols)]


def corner_points(cols):
    """Like find_corners, with where the speed is lowest: [(name, apex, from, to)]."""
    ds, ss, last = [], [], -1e9
    for d, v in zip(cols.get("d") or [], cols.get("spd") or []):
        if d is None or d < 0 or d <= last:
            continue
        ds.append(d)
        ss.append(v)
        last = d
    win, found = 15, []
    for i in range(win, len(ss) - win):
        v = ss[i]
        if v is None or any(ss[j] is not None and ss[j] < v for j in range(i - win, i + win + 1)):
            continue
        before = after = v
        j = i
        while j >= 0 and ds[i] - ds[j] < 400:
            before = max(before, ss[j] if ss[j] is not None else before)
            j -= 1
        j = i
        while j < len(ss) and ds[j] - ds[i] < 400:
            after = max(after, ss[j] if ss[j] is not None else after)
            j += 1
        if before - v < 20 or after - v < 20 or (found and ds[i] - found[-1] < 120):
            continue
        found.append(ds[i])
    out = []
    for n, d in enumerate(found):
        lo = max(ds[0], d - 260, (found[n - 1] + d) / 2 if n else -1e9)
        hi = min(ds[-1], d + 200, (d + found[n + 1]) / 2 if n + 1 < len(found) else 1e9)
        out.append((f"C{n + 1}", d, lo, hi))
    return out


class Engineer:
    def __init__(self, rec):
        self.rec = rec
        self.next_id = 1  # never restarts, so the dashboard never mistakes a new message for one it spoke
        self.reset()

    def reset(self):
        self.messages = deque(maxlen=30)
        self.pending = []
        self.last_said: dict[str, float] = {}
        self.last_release = 0.0
        self.corners = None
        self.greeted = False
        self.lap = None
        self.pits = self.pit_status = None
        self.gaps_prev = None
        self.gaps_lap = -99
        self.fuel_band = self.fuel_lap = None
        self.wear_mark = None
        self.dmg = None
        self.faults = None
        self.weather = None
        self.forecast_said = set()
        self.time_left = None
        self.tyre_ema = None
        self.hot_since = [None] * 4
        self.cold_since = None
        self.ers_low_since = None
        self.flag = 0
        self.ot_available = self.drs_allowed = 0
        self.next_check = 0.0
        self.garage = None
        self.debrief_laps = 0
        self.strategy_said = set()

    # ------------------------------------------------------------------ queue
    def say(self, kind, text, speech=None, key=None, urgent=False, cooldown=0.0):
        now = time.time()
        key = key or kind
        if cooldown and now - self.last_said.get(key, -1e9) < cooldown:
            return
        self.last_said[key] = now
        self.pending = [m for m in self.pending if m["key"] != key]  # a newer message on the same subject wins
        self.pending.append({"key": key, "kind": kind, "text": text, "say": speech or text, "urgent": urgent,
                             "queued": now, "lap": self.rec.cur_lap_num})
        if urgent:
            self.release(False)

    def release(self, quiet=True):
        if not self.pending:
            return
        now = time.time()
        keep = []
        for m in sorted(self.pending, key=lambda m: (not m["urgent"], m["queued"])):
            age = now - m["queued"]
            if m["urgent"]:
                self._emit(m, now)
            elif age > STALE_S:
                continue
            elif (quiet or age > WAIT_S) and now - self.last_release >= SPACING_S:
                self._emit(m, now)
            else:
                keep.append(m)
        self.pending = keep

    def _emit(self, m, now):
        self.messages.append({"id": self.next_id, "kind": m["kind"], "text": m["text"], "say": m["say"],
                              "urgent": m["urgent"], "lap": m["lap"]})
        self.next_id += 1
        self.last_release = now

    def snapshot(self):
        return list(self.messages)[-15:]

    def tick(self):
        """Once a second: lets messages out when no car telemetry arrives (in the garage, session over)."""
        if time.time() - self.rec.last_packet_at > 1.0 or not self.rec.telemetry:
            self.release(True)

    # ------------------------------------------------------------------ context
    @property
    def race(self):
        return self.rec._category() == "race"

    def _temp(self, c):
        if self.rec.settings.get("temp_unit") == "f":
            v = round(c * 9 / 5 + 32)
            return f"{v}°F", f"{v} degrees"
        return f"{round(c)}°C", f"{round(c)} degrees"

    def _flying(self, pl):
        return not pl["invalid"] and not self.rec.lap_ctx.get("start_pit") and pl["pit_status"] == 0

    def set_reference(self, cols):
        """The personal-best lap the live delta uses: its corners name where time is lost."""
        self.corners = find_corners(cols) if cols else None

    # ------------------------------------------------------------------ car telemetry (player, every packet)
    def on_car(self, car, lp):
        quiet = car["speed"] < 80 or (car["throttle"] > 0.85 and car["brake"] < 0.05 and abs(car["steer"]) < 0.2)
        self.release(quiet)
        now = time.time()
        if now < self.next_check:
            return
        self.next_check = now + 0.5
        rec = self.rec
        st = rec._player(rec.status) or {}
        on_track = lp["pit_status"] == 0 and lp["driver_status"] in (1, 2, 4) and lp["result_status"] == 2
        self._tyre_temps(car, lp, on_track, now)
        flag = st.get("fia_flag", 0)
        if flag == 3 and self.flag != 3:
            self.say("alerts", "Yellow flag. Careful, no overtaking.", key="yellow", urgent=True, cooldown=20)
        if flag == 2 and self.flag != 2 and self.race:
            self.say("alerts", "Blue flag, let them through.", key="blue", urgent=True, cooldown=30)
        self.flag = flag
        if not self.race:
            return
        t2 = rec._player(rec.telemetry2)
        if t2:
            if t2["ot_available"] and not self.ot_available and on_track:
                self.say("gaps", "Overtake available.", key="ot", urgent=True, cooldown=40)
            self.ot_available = t2["ot_available"]
        elif rec.regs_2026 != 1:
            drs = st.get("drs_allowed", 0)
            if drs and not self.drs_allowed and on_track:
                self.say("gaps", "DRS available.", key="drs", urgent=True, cooldown=45)
            self.drs_allowed = drs
        pct = st.get("ers_store", ERS_MAX_J) / ERS_MAX_J * 100
        if on_track and pct < 8:
            self.ers_low_since = self.ers_low_since or now
            if now - self.ers_low_since >= 5:
                self.say("fuel", f"Battery low, {pct:.0f}%. Harvest before you deploy again.",
                         f"Battery is low, {pct:.0f} percent. Harvest before you deploy again.", key="ers", cooldown=180)
        else:
            self.ers_low_since = None

    def _tyre_temps(self, car, lp, on_track, now):
        ts = car["tyre_surface"]
        self.tyre_ema = [float(v) for v in ts] if self.tyre_ema is None else \
            [e + (v - e) * 0.15 for e, v in zip(self.tyre_ema, ts)]
        if not on_track or car["speed"] < 120:
            self.hot_since, self.cold_since = [None] * 4, None
            return
        hot = []
        for i, e in enumerate(self.tyre_ema):
            if e > HOT_C:
                self.hot_since[i] = self.hot_since[i] or now
                if now - self.hot_since[i] >= 6:
                    hot.append(i)
            else:
                self.hot_since[i] = None
        if hot:
            which = {frozenset((2, 3)): "Both fronts", frozenset((0, 1)): "Both rears"}.get(
                frozenset(hot), WHEEL_NAMES[hot[0]].capitalize() if len(hot) == 1 else "The tyres")
            text, spoken = self._temp(max(self.tyre_ema[i] for i in hot))
            verb = "is" if len(hot) == 1 else "are"
            self.say("tyres", f"{which} overheating, {text}. Look after them in the fast corners.",
                     f"{which} {verb} overheating, {spoken}. Look after the tyres.", key="tyre_hot", cooldown=150)
        cold = all(e < COLD_C for e in self.tyre_ema) and (not self.race or lp["lap"] >= 2)
        if cold:
            self.cold_since = self.cold_since or now
            if now - self.cold_since >= 15:
                text, spoken = self._temp(sum(self.tyre_ema) / 4)
                self.say("tyres", f"Tyres are cold, {text}. Push to build temperature.",
                         f"Tyres are cold, {spoken}. Push to get some heat in.", key="tyre_cold", cooldown=240)
        else:
            self.cold_since = None

    # ------------------------------------------------------------------ lap data (player)
    def on_lap_data(self, pl):
        rec = self.rec
        s = rec.session
        if not self.greeted and s:
            self.greeted = True
            self._greet(s)
        lap = pl["lap"]
        if self.lap is not None and lap > self.lap and self.race:
            self._race_lap_start(pl, s)
        self.lap = lap
        ps = pl["pit_status"]
        if self.race and self.pit_status and ps == 0 and self.pits is not None and pl["pit_stops"] > self.pits:
            st = rec._player(rec.status) or {}
            tyre = VISUAL_COMPOUNDS.get(st.get("visual_compound"))
            on = f" on {plural(tyre)}" if tyre else ""
            self.say("gaps", f"Out of the pits in P{pl['position']}{on}.", key="pit_exit")
        if ps == 0:
            self.pits = pl["pit_stops"]
        self.pit_status = ps
        garage = pl["driver_status"] == 0
        if garage and self.garage is False and not self.race:
            self.debrief("garage")
        self.garage = garage

    def _greet(self, s):
        rec = self.rec
        kind = SESSION_TYPES.get(s.get("session_type"), "Session")
        text = f"Radio check. {kind} at {name_or(TRACKS, s.get('track_id'), 'track ')}."
        if self.race and s.get("total_laps"):
            text += f" {s['total_laps']} laps."
        elif rec.pb_ms:
            text += f" Personal best to beat: {lap_text(rec.pb_ms)}."
            self.say("session", text, text.replace(lap_text(rec.pb_ms), lap_say(rec.pb_ms)), key="greet")
            return
        self.say("session", text, key="greet")

    def _race_lap_start(self, pl, s):
        lap, total = pl["lap"], s.get("total_laps")
        if total and lap == total and pl["result_status"] == 2:
            self.say("session", f"Last lap. P{pl['position']}, bring it home.", key="last_lap")
        ideal, latest = s.get("pit_window_ideal"), s.get("pit_window_latest")
        if ideal and pl["pit_stops"] == 0:
            if lap == ideal:
                self.say("tyres", f"Pit window is open. Ideal lap {ideal}, latest lap {latest}.", key="pit_window")
            elif latest and lap == latest and latest > ideal:
                self.say("tyres", f"Last lap of the pit window, lap {latest}.", key="pit_window")
        self._strategy_call(lap, total, pl["pit_stops"])

    def _strategy_call(self, lap, total, stops):
        """Our own numbers on when to stop (see strategy.py): the plan once a few laps are in, the window
        opening and the lap to box on. Worked out in the background from the saved laps."""
        rec = self.rec
        if not total or total < 8 or lap < 4 or lap >= total:
            return
        sid = rec.session_id

        def work():
            from . import strategy
            try:
                res = strategy.for_recorder(rec)
            except Exception:  # noqa: BLE001  a strategy call is never worth a crash
                return
            if not res.get("available") or not res.get("plans"):
                return
            best, win = res["plans"][0], res.get("window")
            if not best["stops"]:
                return
            route = " to ".join(s["name"].lower() for s in best["stints"])
            nxt = best["stints"][1]["name"].lower()
            with rec.lock:
                if rec.session_id != sid:
                    return
                if f"plan{stops}" not in self.strategy_said:
                    self.strategy_said.add(f"plan{stops}")
                    other = next((p for p in res["plans"] if p["stops"] != best["stops"]), None)
                    n = {1: "One stop", 2: "Two stops"}[best["stops"]]
                    laps = " and ".join(str(p) for p in best["pits"])
                    text = f"Strategy: {n.lower()}, {route}, box around lap{'s' if len(best['pits']) > 1 else ''} {laps}."
                    if other:
                        text += f" {['No stop', 'One stop', 'Two stops'][other['stops']]} is {other['delta_s']:.0f} s slower."
                    self.say("tyres", text, key="strategy")
                elif best["stops"] == 1 and win and lap == win["from"] < win["to"] and f"window{stops}" not in self.strategy_said:
                    self.strategy_said.add(f"window{stops}")
                    self.say("tyres", f"Box window for the {nxt} is open: laps {win['from']} to {win['to']}.", key="strategy")
                if lap == best["pits"][0] and f"box{stops}" not in self.strategy_said:
                    self.strategy_said.add(f"box{stops}")
                    if best["stops"] == 1 and win and win["to"] - lap > 2:  # a wide window: no rush
                        self.say("tyres", f"Best lap to box for the {nxt} is this one. The window runs to lap {win['to']}.", key="box")
                    else:
                        self.say("tyres", f"Box at the end of this lap for the {nxt}.", key="box", urgent=True)

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ micro-sectors
    def on_micro(self, done, pl):
        mt = self.rec.micro
        per = mt.n // 3
        for i in done:
            if (i + 1) % per or i + 1 >= mt.n:
                continue  # only the ends of sectors 1 and 2: the lap message covers sector 3
            k = (i + 1) // per
            self._sector_call(k, mt.cur[(k - 1) * per:k * per], pl)

    def _sector_call(self, k, cells, pl):
        if self.race or not self.rec.micro.ref or not self._flying(pl) or not all(cells) \
                or any(c[2] is None for c in cells):
            return
        delta = sum(c[2] for c in cells) / 1000
        n_p = sum(c[1] == "p" for c in cells)
        n_g = sum(c[1] == "g" for c in cells)
        if abs(delta) < 0.1 and not n_p:
            return
        text = f"Sector {k}: {delta:+.3f} to your PB lap. Micro-sectors: {n_p} record{'' if n_p == 1 else 's'}, " \
               f"{n_g} faster, {len(cells) - n_p - n_g} slower."
        spoken = f"Sector {k}, {delta_say(delta)} {'quicker' if delta < 0 else 'slower'}."
        if n_p:
            spoken += f" {count_say(n_p, 'micro-sector record').capitalize()}."
        self.say("sectors", text, spoken, key=f"sector{k}")

    # ------------------------------------------------------------------ laps
    def lap_done(self, lap_no, lap_ms, valid, lap_type, cols, old_pb_ms, old_pb_ref, old_sb_ms, new_pb, pl, cells):
        rec = self.rec
        if not self.race:
            if valid and lap_type == "flying":
                self._lap_call(lap_ms, cols, old_pb_ms, old_pb_ref, old_sb_ms, cells)
            return
        if new_pb and old_pb_ms:
            self.say("pace", f"Personal best race lap here: {lap_text(lap_ms)}.",
                     f"Personal best race lap. {lap_say(lap_ms)}.", key="lap")
        if pl["result_status"] != 2:
            return
        self._gaps(lap_no, pl)
        self._fuel(lap_no, rec.session.get("total_laps"))

    def _lap_call(self, lap_ms, cols, old_pb_ms, old_pb_ref, old_sb_ms, cells):
        if old_pb_ms is None:
            text = f"{lap_text(lap_ms)}. That's the benchmark."
            spoken = f"{lap_say(lap_ms)}. That's the benchmark."
        elif lap_ms < old_pb_ms:
            d = (lap_ms - old_pb_ms) / 1000
            text = f"New personal best: {lap_text(lap_ms)} ({d:+.3f})."
            spoken = f"New personal best! {lap_say(lap_ms)}, {delta_say(d)} quicker."
        else:
            d = (lap_ms - old_pb_ms) / 1000
            text = f"{lap_text(lap_ms)}, {d:+.3f} to your best."
            spoken = f"{lap_say(lap_ms)}, {delta_say(d)} off your best."
            where = self._where_lost(cols, old_pb_ref) if d < 5 else None
            if where:
                text += f" Most lost at {where[0]} (+{where[1]:.2f})."
                spoken += f" Most of it at corner {where[0][1:]}."
            if old_sb_ms and lap_ms < old_sb_ms:
                text += " Best of the session."
                spoken += " Best of the session."
        n_p = sum(1 for c in cells or [] if c and c[1] == "p")
        if n_p and old_pb_ms is not None:
            text += f" {n_p} micro-sector record{'' if n_p == 1 else 's'}."
            spoken += f" {count_say(n_p, 'micro-sector record').capitalize()}."
            ideal = self.rec.micro.ideal_ms()
            if ideal and ideal < lap_ms:
                text += f" Ideal lap now {lap_text(ideal)}."
                spoken += f" Ideal lap, {lap_say(ideal)}."
        self.say("pace", text, spoken, key="lap")

    def _where_lost(self, cols, ref):
        """(corner, seconds) where this lap lost the most against the personal-best lap."""
        from .recorder import ref_time_at, reference_from
        cur = reference_from(cols)
        if not self.corners or not ref or not cur:
            return None
        worst = None
        for name, lo, hi in self.corners:
            vals = [ref_time_at(cur, hi), ref_time_at(cur, lo), ref_time_at(ref, hi), ref_time_at(ref, lo)]
            if None in vals:
                continue
            loss = (vals[0] - vals[1]) - (vals[2] - vals[3])
            if worst is None or loss > worst[1]:
                worst = (name, loss)
        return worst if worst and worst[1] >= 0.08 else None

    def _gaps(self, lap_no, pl):
        rec = self.rec
        pos = pl["position"]
        by_pos = {c["position"]: (i, c) for i, c in enumerate(rec.lap_data or [])
                  if c["result_status"] == 2 and c["position"] > 0}
        ahead, behind = by_pos.get(pos - 1), by_pos.get(pos + 1)
        ga = pl["delta_front_ms"] / 1000 if ahead and not ahead[1]["pit_status"] else None
        gb = behind[1]["delta_front_ms"] / 1000 if behind and not behind[1]["pit_status"] else None
        ga = ga if ga is not None and 0 < ga < 30 else None
        gb = gb if gb is not None and 0 < gb < 30 else None
        a_name = nice(rec._driver_name(ahead[0])) if ahead else None
        b_name = nice(rec._driver_name(behind[0])) if behind else None
        prev = self.gaps_prev or {}
        texts, says = [], []
        if ga is not None and ga < 1.0:
            texts.append(f"{gap_text(ga)} to {a_name} ahead, within a second.")
            says.append(f"{gap_say(ga)} to {a_name}. You're within a second.")
        elif ga is not None and prev.get("a") == ahead[0] and prev.get("ga") and prev["ga"] - ga >= 0.25:
            texts.append(f"Closing on {a_name}: {gap_text(ga)}, {prev['ga'] - ga:.1f} a lap.")
            says.append(f"Gaining on {a_name}, {delta_say(prev['ga'] - ga)} a lap. Gap {gap_say(ga)}.")
        if gb is not None and gb < 1.0:
            texts.append(f"{b_name} {gap_text(gb)} behind, within a second.")
            says.append(f"{b_name} is {gap_say(gb)} behind. Defend.")
        elif gb is not None and prev.get("b") == behind[0] and prev.get("gb") and prev["gb"] - gb >= 0.25:
            texts.append(f"{b_name} closing: {gap_text(gb)} behind, {prev['gb'] - gb:.1f} a lap.")
            says.append(f"{b_name} is closing, {gap_say(gb)} behind.")
        if not texts and lap_no - self.gaps_lap >= GAP_EVERY_LAPS and (ga is not None or gb is not None):
            parts = [f"gap ahead {gap_text(ga)}" if ga is not None else None, f"behind {gap_text(gb)}" if gb is not None else None]
            texts.append(f"P{pos}, " + ", ".join(p for p in parts if p) + ".")
            say_parts = [f"gap ahead {gap_say(ga)}" if ga is not None else None,
                         f"behind {gap_say(gb)}" if gb is not None else None]
            says.append(f"P{pos}. " + ", ".join(p for p in say_parts if p).capitalize() + ".")
        if texts:
            self.gaps_lap = lap_no
            self.say("gaps", " ".join(texts), " ".join(says), key="gaps")
        self.gaps_prev = {"a": ahead[0] if ahead else None, "ga": ga, "b": behind[0] if behind else None, "gb": gb}

    def _fuel(self, lap_no, total):
        st = self.rec._player(self.rec.status)
        if not st or not total or total - lap_no < 1:
            return
        fl = st["fuel_laps"]
        band = "short" if fl < -0.15 else "plus" if fl > 0.6 else "ok"
        since = lap_no - (self.fuel_lap or 0)
        if not (self.fuel_band is None or (band != self.fuel_band and since >= 2) or (band == "short" and since >= 4)):
            return
        self.fuel_band, self.fuel_lap = band, lap_no
        if band == "plus":
            self.say("fuel", f"Fuel {fl:+.1f} laps. You can push.", f"Fuel is plus {fl:.1f} laps. You can push.", key="fuel")
        elif band == "ok":
            self.say("fuel", f"Fuel on target ({fl:+.1f} laps).", "Fuel is on target.", key="fuel")
        else:
            self.say("fuel", f"Fuel {fl:+.1f} laps. Lift and coast.",
                     f"We're {abs(fl):.1f} laps short on fuel. Lift and coast into the big stops.", key="fuel")

    # ------------------------------------------------------------------ events
    def on_event(self, ev):
        rec = self.rec
        me = rec.player_idx
        c = ev["code"]
        if c == "PENA" and ev.get("vehicle") == me:
            self._penalty(ev)
        elif c == "SCAR":
            kind, what = ev["sc_type"], ev["sc_event"]
            msg = {(1, 0): "Safety car, safety car. Stay positive on the delta.",
                   (2, 0): "Virtual safety car. Keep above the delta.",
                   (1, 1): "Safety car in this lap. Get ready for the restart.",
                   (2, 1): "VSC ending. Get ready.",
                   (3, 0): "Formation lap. Warm up the tyres and brakes."}.get((kind, what))
            if what == 3:
                msg = "Green flag. Race is back on."
            if msg:
                self.say("alerts", msg, key="sc", urgent=True)
        elif c == "SEND":
            self.debrief("end")
        elif c == "RDFL":
            self.say("alerts", "Red flag, red flag. Slow down and come back to the pits.", key="red", urgent=True)
        elif c == "OVTK" and self.race:
            if ev["vehicle"] == me:
                self.say("gaps", f"Good move on {nice(rec._driver_name(ev['other_vehicle']))}.", key="ovtk")
            elif ev["other_vehicle"] == me:
                self.say("gaps", f"{nice(rec._driver_name(ev['vehicle']))} got past.", key="ovtk")
        elif c == "FTLP" and ev.get("vehicle") == me and self.race:
            ms = round(ev["lap_time"] * 1000)
            self.say("pace", f"Fastest lap of the race: {lap_text(ms)}.", f"Fastest lap of the race! {lap_say(ms)}.", key="lap")
        elif c in ("DRSE", "DRSD", "OVEN", "OVDI") and self.race and not (c[:3] == "DRS" and rec.regs_2026 == 1):
            text = {"DRSE": "DRS is enabled.", "DRSD": "DRS is disabled.",
                    "OVEN": "Overtake Mode is enabled.", "OVDI": "Overtake Mode is disabled."}[c]
            self.say("gaps", text, key=c, cooldown=30)

    def _penalty(self, ev):
        kind, why = ev["penalty_type"], reason(ev["infringement"])
        if kind == 4:
            secs = ev["time"] if ev["time"] not in (0, 255) else None
            text = f"{secs}-second time penalty, {why}." if secs else f"Time penalty, {why}."
            self.say("alerts", text, text.replace("-second", " second"), key="pena", urgent=True)
        elif kind in (0, 1):
            text = f"{'Drive-through' if kind == 0 else 'Stop-go'} penalty, {why}."
            self.say("alerts", text, key="pena", urgent=True)
        elif kind == 5:
            self.say("alerts", f"Warning: {why}.", f"That's a warning, {why}.", key="warn", cooldown=5)
        elif 10 <= kind <= 15:
            if not self.race:
                which = "This lap and the next" if kind in (11, 13) else "This lap"
                verb = "are" if kind in (11, 13) else "is"
                self.say("alerts", f"{which} {verb} invalidated: {why}.", f"{which} {verb} invalid, {why}.", key="invalid", cooldown=5)
        elif kind == 3:
            self.say("alerts", "Reminder: you still have a penalty to serve.", key="pena_reminder", cooldown=30)
        elif kind == 17:
            self.say("alerts", f"Black flag warning, {why}.", key="pena", urgent=True)
        elif kind in (2, 6, 9):
            self.say("alerts", f"{PENALTY_TYPES[kind]}: {why}.", key="pena", urgent=True)

    # ------------------------------------------------------------------ session (weather, time left)
    def on_session(self, s):
        w = s.get("weather")
        if self.weather is not None and w is not None and w != self.weather:
            wet, was_wet = w >= 3, self.weather >= 3
            if wet and not was_wet:
                self.say("weather", f"It's raining: {WEATHER.get(w, 'rain').lower()}.", "Rain's started.", key="weather")
            elif was_wet and not wet:
                self.say("weather", "Rain has stopped. The track will start drying.", key="weather")
            elif wet and w > self.weather:
                self.say("weather", "Rain is getting heavier.", key="weather")
            elif wet:
                self.say("weather", "Rain is easing.", key="weather")
            if wet != was_wet:
                self.forecast_said = set()
        self.weather = w
        if w is not None:
            self._forecast(s, w >= 3)
        tl = s.get("time_left")
        if self.rec._category() in ("practice", "qualifying") and tl is not None and self.time_left is not None:
            for mark in (300, 120):
                if tl <= mark < self.time_left and (s.get("duration") or 0) > mark + 60 and tl > 0:
                    self.say("session", f"{mark // 60} minutes left in the session.", key="time_left")
        self.time_left = tl

    def _forecast(self, s, wet_now):
        fc = sorted((f for f in s.get("forecast") or [] if f["session_type"] == s.get("session_type")
                     and 0 < f["offset"] <= 15), key=lambda f: f["offset"])
        for f in fc:
            if (f["weather"] >= 3) == wet_now:
                continue
            key = (not wet_now, f["offset"] <= 5)
            if key in self.forecast_said:
                return
            self.forecast_said.add(key)
            if wet_now:
                self.say("weather", f"Rain should stop in about {f['offset']} minutes.", key="forecast")
            else:
                self.say("weather", f"Rain expected in {f['offset']} minutes ({f['rain']}% chance).",
                         f"Rain expected in {f['offset']} minutes, {f['rain']} percent chance.", key="forecast")
            return

    # ------------------------------------------------------------------ damage and tyre wear
    def on_damage(self, d):
        race = self.race
        levels = {"front wing": max(d["fl_wing"], d["fr_wing"]), "rear wing": d["rear_wing"], "floor": d["floor"],
                  "diffuser": d["diffuser"], "sidepod": d["sidepod"]}
        faults = {"drs": d["drs_fault"], "ers": d["ers_fault"], "engine": d["engine_blown"] or d["engine_seized"],
                  "tyre": max(d["tyre_damage"])}
        wear = max(d["tyre_wear"])
        if self.dmg is None:  # what the car already had when we joined: nothing to report
            self.dmg, self.faults = levels, faults
            self.wear_mark = max((m for m in WEAR_MARKS if wear >= m), default=0)
            return
        for part, v in levels.items():
            last = self.dmg[part]
            if v < last:
                self.dmg[part] = v  # repaired, or a flashback
            elif v >= max(10, last + 10):
                self.dmg[part] = v
                side = ""
                if part == "front wing" and d["fl_wing"] != d["fr_wing"]:
                    side = " left" if d["fl_wing"] > d["fr_wing"] else " right"
                text = f"{part.capitalize()}{side} damage, {v}%."
                if race and part == "front wing" and v >= 40:
                    text += " Box for a new front wing."
                self.say("alerts", text, text.replace("%", " percent"), key=f"dmg_{part}", urgent=v >= 40)
        f0 = self.faults
        if faults["drs"] and not f0["drs"]:
            self.say("alerts", "DRS failure.", key="drs_fault", urgent=True)
        if faults["ers"] and not f0["ers"]:
            self.say("alerts", "ERS fault. We've lost the battery.", key="ers_fault", urgent=True)
        if faults["engine"] and not f0["engine"]:
            self.say("alerts", "Engine failure.", key="engine", urgent=True)
        if faults["tyre"] >= 40 > f0["tyre"]:
            i = d["tyre_damage"].index(faults["tyre"])
            text = f"Tyre damage, {WHEEL_NAMES[i]} {faults['tyre']}%." + (" Box if you can." if race else "")
            self.say("alerts", text, text.replace("%", " percent"), key="tyre_damage", urgent=True)
        self.faults = faults
        if self.rec._category() == "time_trial":
            return
        if wear < self.wear_mark - 20:
            self.wear_mark = 0  # a new set of tyres
        for m in WEAR_MARKS:
            if wear >= m > self.wear_mark:
                self.wear_mark = m
                wheel = WHEEL_NAMES[d["tyre_wear"].index(max(d["tyre_wear"]))]
                end = " They're nearly done." if m == WEAR_MARKS[-1] else ""
                self.say("tyres", f"Tyre wear {wear:.0f}%, {wheel} worst.{end}",
                         f"Tyre wear is {wear:.0f} percent, {wheel} the worst.{end}", key="wear")

    # ------------------------------------------------------------------ results
    def debrief(self, why):
        """The three corners worth most on a typical lap, back in the garage or when the session ends.
        Worked out from the saved laps in the background; said only when there are new laps since last time."""
        rec = self.rec
        sid, n = rec.session_id, len(rec.saved_laps)
        if not sid or n < 3 or n <= self.debrief_laps:
            return
        self.debrief_laps = n
        mph = rec.settings.get("speed_unit") == "mph"

        def work():
            from . import coach
            try:
                res = coach.analyse_session(rec.store, sid, mph=mph)
            except Exception:  # noqa: BLE001  a debrief is never worth a crash
                return
            fixes = (res or {}).get("fixes") or []
            if len(res.get("laps_used") or []) < 3 or not fixes:
                return
            with rec.lock:
                if rec.session_id != sid:
                    return
                intro = "Back in the garage." if why == "garage" else "Debrief."
                names = ", ".join(f"corner {f['n']} ({f['loss_s']:.2f} s)" for f in fixes)
                spoken = ", ".join(f"corner {f['n']}" for f in fixes)
                self.say("coach", f"{intro} Where the time is on a typical lap: {names}.",
                         f"{intro} Where the time is: {spoken}.", key="debrief")
                for i, f in enumerate(fixes):
                    self.say("coach", f["text"], f["say"], key=f"debrief{i}")

        threading.Thread(target=work, daemon=True).start()

    def on_final(self, pos, points):
        cat = self.rec._category()
        if not pos:
            return
        if cat == "race":
            pts = f" {points} point{'' if points == 1 else 's'}." if points else ""
            self.say("session", f"Chequered flag. P{pos}.{pts}", key="final")
        elif cat == "qualifying":
            self.say("session", f"That's qualifying done. P{pos}.", key="final")
        self.debrief("end")
