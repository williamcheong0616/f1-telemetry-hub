"""Turns the raw UDP packet stream into live dashboard state and recorded history.

One Recorder instance follows one game session at a time (keyed by the header's
session UID). The player's car is sampled into a per-lap buffer; when the lap
counter rolls over, the buffer is written to SQLite together with a lap summary
(times, sectors, tyres, fuel, ERS, damage, setup).
"""
from __future__ import annotations

import bisect
import struct
import threading
import time
from collections import deque

from . import circuits, micro, packets
from .constants import (
    ACTUAL_COMPOUNDS, COLLISION_SEVERITY, DRIVER_STATUS, ERS_MODES, EVENT_NAMES, FORMULA, FUEL_MIX, GAME_MODES,
    INFRINGEMENT_TYPES, PARTIAL_MODE_REASONS, PENALTY_TYPES, RESULT_STATUS, SAFETY_CAR, SESSION_TYPES,
    TEAM_COLOURS, TEAMS, TRACKS, VISUAL_COMPOUNDS, WEATHER, mode_group, name_or, session_category,
)
from .engineer import Engineer
from .storage import Storage, is_restart, now_iso, outline_from, outline_ok, setup_hash

ERS_MAX_J = 4_000_000.0

# "aero" (active aero straight mode) and "ot" (Overtake Mode) come from Car Telemetry 2, format 2026 only;
# "us" (understeer angle), "lk" (lock-up) and "ws" (wheelspin) from Motion Ex, see balance()
SCALARS = ("t", "d", "spd", "thr", "brk", "str", "gear", "rpm", "drs", "clu",
           "x", "z", "glat", "glon", "gvert", "ers", "fuel", "aero", "ot", "us", "lk", "ws")
WHEEL_KEYS = ("bt", "ts", "ti", "tp", "sp", "wf", "tw")
LIVE_LAP_COLS = ("t", "d", "spd", "thr", "brk", "gear", "x", "z")  # what the Workstation draws of the lap being driven


def balance(mx) -> tuple:
    """Understeer angle (deg; + understeer, - oversteer), worst lock-up and rear wheelspin (slip ratio, 0..1).

    Wheels come as RL, RR, FL, FR. The understeer angle is how much more the front tyres slip sideways
    than the rears, which reads the same in left and right corners.
    """
    if not mx:
        return None, None, None
    sa, sr = mx["slip_angle"], mx["slip_ratio"]
    us = (abs(sa[2] + sa[3]) - abs(sa[0] + sa[1])) / 2 * 57.29578
    lock = max(0.0, -min(sr))
    spin = max(0.0, sr[0], sr[1])
    return round(max(-30.0, min(30.0, us)), 2), round(min(1.0, lock), 3), round(min(1.0, spin), 3)


def fmt_lap(ms) -> str:
    if not ms or ms <= 0:
        return "-"
    m, rem = divmod(int(ms), 60000)
    return f"{m}:{rem / 1000:06.3f}"


class LapBuffer:
    """Columnar sample store for one lap of the player's car."""

    def __init__(self):
        self.st: list[float] = []
        self.gen = 0  # bumped when samples are dropped, so readers following along know to start over
        self.cols = {k: [] for k in SCALARS}
        for k in WHEEL_KEYS:
            self.cols[k] = [[], [], [], []]

    def __len__(self):
        return len(self.st)

    def append(self, session_time: float, scalars: tuple, wheels: tuple):
        self.st.append(session_time)
        for k, v in zip(SCALARS, scalars):
            self.cols[k].append(v)
        for k, arr in zip(WHEEL_KEYS, wheels):
            dst = self.cols[k]
            for i in range(4):
                dst[i].append(arr[i])

    def trim_after(self, session_time: float):
        n = bisect.bisect_right(self.st, session_time)
        if n >= len(self.st):
            return
        self.gen += 1
        del self.st[n:]
        for k in SCALARS:
            del self.cols[k][n:]
        for k in WHEEL_KEYS:
            for i in range(4):
                del self.cols[k][i][n:]

    def columns(self) -> dict:
        return self.cols


def reference_from(cols: dict):
    """Builds a monotonic (distance, time) pair of lists for live delta lookups."""
    ds, ts = [], []
    last = -1e9
    for d, t in zip(cols.get("d", []), cols.get("t", [])):
        if d is None or t is None or d < 0 or d <= last:
            continue
        ds.append(d)
        ts.append(t)
        last = d
    return (ds, ts) if len(ds) > 20 else None


def ref_time_at(ref, d: float):
    ds, ts = ref
    if d < ds[0] or d > ds[-1]:
        return None
    i = bisect.bisect_left(ds, d)
    if i == 0:
        return ts[0]
    d0, d1, t0, t1 = ds[i - 1], ds[i], ts[i - 1], ts[i]
    return t0 + (t1 - t0) * ((d - d0) / (d1 - d0) if d1 > d0 else 0)


class Recorder:
    def __init__(self, store: Storage, settings: dict):
        self.store = store
        self.settings = settings
        self.lock = threading.RLock()
        self.packets_total = 0
        self.bad_packets = 0
        self.packet_counts: dict[int, int] = {}
        self.size_warnings: dict[int, int] = {}
        self.last_packet_at = 0.0
        self.pps_window: deque = deque()
        self.game = None
        self.demo_active = False
        self.feed: deque = deque(maxlen=40)
        self._snapshot_cache = (0.0, None)
        self.handlers = {
            0: self._on_motion, 1: self._on_session, 2: self._on_lap_data, 3: self._on_event,
            4: self._on_participants, 5: self._on_setups, 6: self._on_telemetry, 7: self._on_status,
            8: self._on_final, 10: self._on_damage, 11: self._on_history, 12: self._on_tyre_sets,
            13: self._on_motion_ex, 14: self._on_time_trial, 15: self._on_lap_positions,
            16: self._on_telemetry2,
        }
        self.session_uid = None
        self.engineer = Engineer(self)
        self._reset()

    # ------------------------------------------------------------------ state
    def _reset(self):
        self.session_id = None
        self.session: dict = {}
        self.player_idx = 0
        self.participants = None
        self.lap_data = None
        self.telemetry = None
        self.telemetry2 = None
        self.regs_2026 = None
        self.status = None
        self.damage = None
        self.motion = None
        self.motion_ex = None
        self.setup = None
        self.tyre_sets = None
        self.time_trial = None
        self.histories: dict[int, dict] = {}
        self.car_best_sectors: dict[int, list] = {}
        self.final = None
        self.positions_by_lap: dict[int, dict] = {}
        self.prev_lap_by_car: dict[int, int] = {}
        self.prev_result_by_car: dict[int, int] = {}
        self.finish_pending = None
        self.best_by_car: dict[int, int] = {}
        self.pending_events: list[dict] = []
        self.setup_ids: dict[str, int] = {}
        self.saved_laps: dict[int, int] = {}
        self.saved_lap_keys: dict[int, tuple] = {}
        self.out_laps: set[int] = set()
        self.session_best_ms = None
        self.session_best_ref = None
        self.session_best_sectors = [None, None, None]
        self.last_sectors = [0, 0, 0]
        self.pb_ms = None
        self.pb_ref = None
        self.track_outline = None
        self.outline_version = 0
        self.circuit = None        # bundled outline of this track (circuits.json), if there is one
        self.track_frame = None    # game coordinates -> circuit coordinates, once lined up
        self.circuit_outline = None
        self.align_busy = False
        self.align_next_d = 0.0
        self.cur_lap_num = None
        self.last_pl = None
        self.buf = LapBuffer()
        self.lap_ctx: dict = {}
        self.prev_lap_record = None
        self.prev_drs = 0
        self.prev_aero = 0
        self.prev_ot = 0
        self.last_flush = time.time()
        self.idle_finalized = False
        self.micro = micro.MicroTimer()
        self.engineer.reset()

    @property
    def min_dt(self) -> float:
        hz = max(5, min(60, int(self.settings.get("telemetry_hz", 20))))
        return 1.0 / hz - 0.004

    # ------------------------------------------------------------------ entry
    def handle(self, data: bytes):
        try:
            h, payload = packets.parse(data)
        except (ValueError, struct.error, IndexError):
            self.bad_packets += 1
            return
        with self.lock:
            now = time.time()
            self.packets_total += 1
            self.packet_counts[h.packet_id] = self.packet_counts.get(h.packet_id, 0) + 1
            self.last_packet_at = now
            self.pps_window.append(now)
            while self.pps_window and now - self.pps_window[0] > 2.0:
                self.pps_window.popleft()
            exp = packets.expected_size(h.packet_format, h.packet_id)
            if exp and len(data) != exp:
                self.size_warnings[h.packet_id] = len(data)
            self.game = {"year": h.game_year, "format": h.packet_format,
                         "version": f"{h.game_major}.{h.game_minor:02d}"}
            if h.session_uid == 0:
                return
            if h.session_uid != self.session_uid:
                self._finalize_session()
                self._reset()
                self.session_uid = h.session_uid
            self.idle_finalized = False
            if h.player_car_index < packets.MAX_CARS:
                self.player_idx = h.player_car_index
            fn = self.handlers.get(h.packet_id)
            if fn is not None and payload is not None:
                try:
                    fn(h, payload)
                except (IndexError, KeyError, TypeError, ValueError) as exc:  # malformed / partial packet
                    self.bad_packets += 1
                    if self.settings.get("debug"):
                        print(f"[recorder] packet {h.packet_id} error: {exc!r}")
            if now - self.last_flush > 20 and self.session_id:
                self._flush_session()

    def tick(self):
        """Called about once a second by the app; finalises sessions after the game goes quiet."""
        with self.lock:
            self._eng("tick")
            if self.finish_pending and self.last_pl and time.time() - self.finish_pending[0] > 3:
                self._finish_last_lap(self.last_pl, False)  # the game stopped sending right after the flag
            if self.session_id and not self.idle_finalized and time.time() - self.last_packet_at > 20:
                self._finalize_session()
                self.idle_finalized = True

    def shutdown(self):
        with self.lock:
            self._finalize_session()

    # ------------------------------------------------------------------ helpers
    def _eng(self, hook, *args):
        """Calls the race engineer; a mistake in a radio rule must never stop the recording."""
        try:
            getattr(self.engineer, hook)(*args)
        except Exception as exc:  # noqa: BLE001
            if self.settings.get("debug"):
                print(f"[engineer] {hook} failed: {exc!r}")

    def _driver_name(self, idx) -> str:
        if idx is None or idx >= packets.MAX_CARS:
            return "?"
        if self.participants and idx < len(self.participants["cars"]):
            name = self.participants["cars"][idx]["name"]
            if name:
                return name
        return f"Car {idx + 1}"

    def _team_id(self, idx):
        if self.participants and idx < len(self.participants["cars"]):
            return self.participants["cars"][idx]["team_id"]
        return None

    def _player(self, arr):
        if not arr:
            return None
        cars = arr["cars"] if isinstance(arr, dict) else arr
        return cars[self.player_idx] if self.player_idx < len(cars) else None

    def _category(self) -> str:
        return session_category(self.session.get("session_type", 0))

    def _ensure_session(self) -> int:
        if self.session_id:
            return self.session_id
        s = self.session
        pl = self.participants["cars"][self.player_idx] if self.participants and self.player_idx < len(self.participants["cars"]) else {}
        fields = {
            "game_year": (self.game or {}).get("year"), "packet_format": (self.game or {}).get("format"),
            "track_id": s.get("track_id"), "track_length": s.get("track_length"),
            "session_type": s.get("session_type"), "category": self._category(),
            "formula": s.get("formula"), "game_mode": s.get("game_mode"),
            "network_game": s.get("network_game"), "ai_difficulty": s.get("ai_difficulty"),
            "weather": s.get("weather"), "track_temp": s.get("track_temp"), "air_temp": s.get("air_temp"),
            "total_laps": s.get("total_laps"), "player_name": pl.get("name"), "team_id": pl.get("team_id"),
            "my_team": pl.get("my_team"), "assists": s.get("assists"),
        }
        fields.update(self._career_fields())
        self.session_id = self.store.create_session(str(self.session_uid), fields)
        if self.pending_events:
            self.store.add_events(self.session_id, self.pending_events)
            self.pending_events = []
        return self.session_id

    def _career_fields(self) -> dict:
        s = self.session
        return {"game_mode": s.get("game_mode"), "rule_set": s.get("rule_set"),
                "season_link": s.get("season_link"), "weekend_link": s.get("weekend_link"),
                "session_link": s.get("session_link"), "weekend_structure": s.get("weekend_structure")}

    def _load_track_refs(self):
        tid = self.session.get("track_id")
        if tid is None or tid < 0:
            return
        track = self.store.get_track(tid)
        self.track_outline = track["outline"] if track and track.get("outline") else None
        self.circuit = circuits.circuit(tid)
        self.track_frame = track.get("frame") if track and self.circuit else None
        self.circuit_outline = None
        self.align_next_d = 0.0
        self.outline_version += 1
        if self.circuit and not self.track_frame and self.track_outline:
            self._align_async(tid, [tuple(p) for p in self.track_outline])  # a lap recorded before: line it up now
        self.pb_ref = self.pb_ms = None
        # 2026-regulation cars and older cars are not compared with each other
        ref = self.store.best_reference_lap(tid, self._category(), self.regs_2026)
        cols = self.store.get_lap_telemetry(ref["id"]) if ref else None
        if cols:
            self.pb_ref = reference_from(cols)
            self.pb_ms = ref["lap_time_ms"]
        self._eng("set_reference", cols if self.pb_ref else None)
        s = self.session
        bnds = micro.bounds(s.get("track_length"), s.get("sector2_start"), s.get("sector3_start"))
        scope = (tid, self._category(), self.regs_2026, micro.key_of(bnds) if bnds else None)
        self.micro.configure(bnds, scope)
        if bnds:
            if self.micro.cur is None and self.last_pl:  # lap data came before the session packet
                self.micro.begin(self.last_pl["current_lap_ms"] / 1000.0, self.last_pl["lap_distance"])
            self._micro_records_async(scope, bnds)

    def _micro_records_async(self, scope, bnds):
        tid, category, regs = scope[:3]

        def work():
            try:
                best, ref, ref_ms = self.store.micro_records(tid, category, regs, bnds)
            except Exception as exc:  # noqa: BLE001 - a broken old lap must not stop the live view
                if self.settings.get("debug"):
                    print(f"[recorder] micro-sector records failed: {exc!r}")
                return
            with self.lock:
                self.micro.set_records(scope, best, ref, ref_ms)

        threading.Thread(target=work, name="micro-records", daemon=True).start()

    # ------------------------------------------------------------------ handlers
    def _on_session(self, h, s):
        prev_track = self.session.get("track_id")
        prev_type = self.session.get("session_type")
        if s.get("start_reaction") and not self.session.get("start_reaction"):
            self.feed.append({"session_time": round(h.session_time, 3), "lap": self.cur_lap_num, "code": "REAC",
                              "text": f"Start reaction time: {s['start_reaction']:.3f} s"})
        if self.regs_2026 is None and s.get("formula") == 13:  # F1 26 cars, before Car Telemetry 2 arrives
            self.regs_2026 = 1
        self.session = s
        if prev_track != s.get("track_id") or prev_type != s.get("session_type"):
            self._load_track_refs()
            if self.session_id:
                self.store.update_session(self.session_id, {
                    "track_id": s.get("track_id"), "session_type": s.get("session_type"),
                    "category": self._category(), "track_length": s.get("track_length")})
        if not s.get("spectating"):
            self._eng("on_session", s)

    def _on_participants(self, h, p):
        self.participants = p

    def _on_motion(self, h, p):
        self.motion = p

    def _on_motion_ex(self, h, p):
        self.motion_ex = p

    def _on_setups(self, h, p):
        car = self._player(p)
        if car and (car["front_wing"] or car["rear_wing"] or car["brake_bias"]):
            self.setup = car

    def _on_status(self, h, p):
        self.status = p
        st = self._player(p)
        if st and self.lap_ctx:
            self.lap_ctx["ers_deployed"] = st["ers_deployed"]
            self.lap_ctx["ers_harvested"] = st["ers_harvest_k"] + st["ers_harvest_h"]
            if self.lap_ctx.get("fuel_start") is None:
                self.lap_ctx["fuel_start"] = st["fuel"]
                self.lap_ctx["ers_store_start"] = st["ers_store"]
                self.lap_ctx["tyre_visual"] = st["visual_compound"]
                self.lap_ctx["tyre_actual"] = st["actual_compound"]
                self.lap_ctx["tyre_age"] = st["tyre_age"]

    def _on_damage(self, h, p):
        self.damage = p
        d = self._player(p)
        if d and self.lap_ctx and self.lap_ctx.get("wear_start") is None:
            self.lap_ctx["wear_start"] = d["tyre_wear"]
        if d and not self.session.get("spectating"):
            self._eng("on_damage", d)

    def _on_tyre_sets(self, h, p):
        if p["car"] == self.player_idx:
            self.tyre_sets = p

    def _on_time_trial(self, h, p):
        self.time_trial = p

    def _on_telemetry2(self, h, p):
        self.telemetry2 = p
        car = self._player(p)
        if car is None:
            return
        if car["regs_2026"] != self.regs_2026:
            self.regs_2026 = car["regs_2026"]
            if self.session:
                self._load_track_refs()
        ctx = self.lap_ctx
        if ctx and not self.session.get("spectating"):
            if car["aero_mode"] == 1 and not self.prev_aero:
                ctx["aero"] = ctx.get("aero", 0) + 1
            if car["ot_active"] and not self.prev_ot:
                ctx["ot"] = ctx.get("ot", 0) + 1
        self.prev_aero, self.prev_ot = car["aero_mode"], car["ot_active"]

    def _on_lap_positions(self, h, p):
        pass  # positions are tracked from Lap Data, which works for every packet format

    def _on_history(self, h, p):
        self.histories[p["car"]] = p
        best = [None, None, None]
        for lap in p["laps"]:
            for i, (key, bit) in enumerate((("s1_ms", 0x02), ("s2_ms", 0x04), ("s3_ms", 0x08))):
                v = lap[key]
                if v > 0 and lap["valid_flags"] & bit and (best[i] is None or v < best[i]):
                    best[i] = v
        self.car_best_sectors[p["car"]] = best
        if p["car"] != self.player_idx or not self.session_id:
            return
        changed = False
        for i, lap in enumerate(p["laps"]):
            n = i + 1
            lap_id = self.saved_laps.get(n)
            if not lap_id or lap["lap_ms"] <= 0:
                continue
            valid = 1 if lap["valid_flags"] & 0x01 and n not in self.out_laps else 0
            key = (lap["lap_ms"], lap["s1_ms"], lap["s2_ms"], lap["s3_ms"], valid)
            if self.saved_lap_keys.get(n) != key:
                self.saved_lap_keys[n] = key
                self.store.update_lap(lap_id, {"lap_time_ms": key[0], "s1_ms": key[1], "s2_ms": key[2],
                                               "s3_ms": key[3], "valid": valid})
                changed = True
        if changed:
            self.store.refresh_session_summary(self.session_id)

    def _on_final(self, h, p):
        first = self.final is None  # the game sends the classification more than once
        self.final = p
        sid = self._ensure_session()
        results = []
        for i, c in enumerate(p["cars"][:max(p["num_cars"], 0) or len(p["cars"])]):
            if c["position"] == 0:
                continue
            pc = self.participants["cars"][i] if self.participants and i < len(self.participants["cars"]) else {}
            results.append(dict(c, idx=i, name=self._driver_name(i), team_id=self._team_id(i),
                                is_player=i == self.player_idx, driver_id=pc.get("driver_id"),
                                ai=pc.get("ai"), my_team=pc.get("my_team"), race_number=pc.get("race_number")))
        results.sort(key=lambda r: r["position"])
        me = next((r for r in results if r["is_player"]), None)
        fields = {"results": results}
        if me and first:
            self._eng("on_final", me["position"], me["points"])
        if me:
            fields.update(final_position=me["position"], grid_position=me["grid"], points=me["points"],
                          result_status=me["result_status"])
        self.store.update_session(sid, fields)
        self._flush_session()

    def _on_event(self, h, ev):
        code = ev["code"]
        if code == "BUTN":
            return
        if code == "FLBK":
            self.buf.trim_after(ev["session_time"])
            if self.lap_ctx:
                self.lap_ctx["flashbacks"] = self.lap_ctx.get("flashbacks", 0) + 1
        if not self.session.get("spectating"):
            self._eng("on_event", ev)
        text = self._event_text(ev)
        if text is None:
            return
        entry = {"session_time": round(h.session_time, 3), "lap": self.cur_lap_num, "code": code,
                 "text": text, "data": ev}
        self.feed.append(entry)
        if code in ("SPTP", "OVTK") and ev.get("vehicle") != self.player_idx:
            return  # keep the feed lively but only persist events about the player
        if self.session_id:
            self.store.add_events(self.session_id, [entry])
        else:
            self.pending_events.append(entry)
        if code == "SEND" and self.session_id:
            self._flush_session()
            self.store.update_session(self.session_id, {"ended_at": now_iso()})

    def _event_text(self, ev):
        c = ev["code"]
        n = self._driver_name
        me = self.player_idx
        if c == "FTLP":
            return f"Fastest lap: {n(ev['vehicle'])} {fmt_lap(ev['lap_time'] * 1000)}"
        if c == "RTMT":
            return f"{n(ev['vehicle'])} retired"
        if c == "RCWN":
            return f"Race winner: {n(ev['vehicle'])}"
        if c == "PENA":
            pen = PENALTY_TYPES.get(ev["penalty_type"], "Penalty")
            inf = INFRINGEMENT_TYPES.get(ev["infringement"], "")
            extra = f" (+{ev['time']}s)" if ev["penalty_type"] == 4 and ev["time"] not in (0, 255) else ""
            return f"{n(ev['vehicle'])}: {pen}{extra} - {inf}"
        if c == "SPTP":
            if ev["vehicle"] != me and not ev["overall_fastest"]:
                return None
            tag = " (session fastest)" if ev["overall_fastest"] else ""
            return f"Speed trap {n(ev['vehicle'])}: {ev['speed']:.1f} km/h{tag}"
        if c == "STLG":
            return f"Start lights: {ev['lights']}"
        if c == "LGOT":
            return "Lights out!"
        if c == "DTSV":
            return f"{n(ev['vehicle'])} served a drive-through"
        if c == "SGSV":
            return f"{n(ev['vehicle'])} served a stop-go ({ev['stop_time']:.1f}s)"
        if c == "OVTK":
            if me not in (ev["vehicle"], ev["other_vehicle"]):
                return None
            return f"{n(ev['vehicle'])} overtook {n(ev['other_vehicle'])}"
        if c == "COLL":
            if me not in (ev["vehicle"], ev["other_vehicle"]):
                return None
            sev = COLLISION_SEVERITY.get(ev.get("severity"))
            return f"Collision{f' ({sev})' if sev else ''}: {n(ev['vehicle'])} / {n(ev['other_vehicle'])}"
        if c == "PMEN":
            why = PARTIAL_MODE_REASONS.get(ev.get("reason"))
            return f"Active aero partial mode enabled{f' ({why})' if why else ''}"
        if c == "SCAR":
            kind = {1: "Safety Car", 2: "Virtual Safety Car", 3: "Formation lap"}.get(ev["sc_type"], "Safety Car")
            what = {0: "deployed", 1: "returning", 2: "returned", 3: "race resumes"}.get(ev["sc_event"], "")
            return f"{kind} {what}".strip()
        if c == "TMPT":
            return "Team mate in the pits"
        return EVENT_NAMES.get(c, c)

    # ------------------------------------------------------------------ laps
    def _on_lap_data(self, h, p):
        self.lap_data = p["cars"]
        cars = p["cars"]
        for i, c in enumerate(cars):
            if c["result_status"] < 2:
                continue
            prev = self.prev_lap_by_car.get(i)
            crossed = prev is not None and c["lap"] > prev and prev > 0
            took_flag = self.prev_result_by_car.get(i) == 2 and c["result_status"] == 3
            if crossed or took_flag:
                self.positions_by_lap.setdefault(i, {})[prev if crossed else c["lap"]] = c["position"]
                if c["last_lap_ms"] > 0:
                    b = self.best_by_car.get(i)
                    if b is None or c["last_lap_ms"] < b:
                        self.best_by_car[i] = c["last_lap_ms"]
            self.prev_lap_by_car[i] = c["lap"]
            self.prev_result_by_car[i] = c["result_status"]

        pl = self._player(cars)
        if pl is None or self.session.get("spectating"):
            return
        lap = pl["lap"]
        finished = pl["result_status"] >= 3
        if self.cur_lap_num is None:
            self.cur_lap_num = lap
            self._begin_lap(pl)
            self.lap_ctx["finished"] = finished
        elif lap > self.cur_lap_num:
            if self.last_pl is not None and not self.lap_ctx.get("finished"):
                self._complete_lap(self.last_pl, pl)
            self.cur_lap_num = lap
            self._begin_lap(pl)
            self.lap_ctx["finished"] = finished
            self.finish_pending = None
        elif lap < self.cur_lap_num:
            self._rewind_to(lap, h.session_time, pl)
        elif finished and not self.lap_ctx.get("finished") and self.finish_pending is None                 and self.last_pl is not None:
            # Chequered flag: the game may not bump the lap counter, so finish the lap
            # as soon as the final lap time is published (or after a short timeout).
            self.finish_pending = (time.time(), self.last_pl)
        if self.finish_pending and lap == self.cur_lap_num:
            fresh = pl["last_lap_ms"] != self.finish_pending[1]["last_lap_ms"]
            if fresh or time.time() - self.finish_pending[0] > 3:
                self._finish_last_lap(pl, fresh)
        if pl["pit_status"] > 0:
            self.lap_ctx["pit_seen"] = True
        if pl["invalid"]:
            self.lap_ctx["invalid"] = True
        self.last_pl = pl
        done = [] if self.lap_ctx.get("finished") else \
            self.micro.update(pl["current_lap_ms"] / 1000.0, pl["lap_distance"])
        self._eng("on_lap_data", pl)
        if done:
            self._eng("on_micro", done, pl)

    def _finish_last_lap(self, pl, fresh):
        before = self.finish_pending[1]
        if not fresh and abs(pl["last_lap_ms"] - before["current_lap_ms"]) > 500:
            pl = dict(pl, last_lap_ms=0)  # still the lap before's time: use the timer from just before the line
        self._complete_lap(before, pl)  # (a final lap exactly as quick as the one before looks "not fresh")
        self.lap_ctx["finished"] = True
        self.finish_pending = None

    def _begin_lap(self, pl):
        st = self._player(self.status)
        dm = self._player(self.damage)
        self.lap_ctx = {
            "start_pit": pl["pit_status"] > 0 or pl["driver_status"] in (0, 3),
            "invalid": False, "pit_seen": False, "drs": 0, "aero": 0, "ot": 0, "top": 0, "flashbacks": 0,
            "fuel_start": st["fuel"] if st else None,
            "ers_store_start": st["ers_store"] if st else None,
            "tyre_visual": st["visual_compound"] if st else None,
            "tyre_actual": st["actual_compound"] if st else None,
            "tyre_age": st["tyre_age"] if st else None,
            "wear_start": dm["tyre_wear"] if dm else None,
            "ers_deployed": 0.0, "ers_harvested": 0.0,
            "max_bt": 0, "max_tt": 0,
        }
        self.buf = LapBuffer()
        self.micro.begin(pl["current_lap_ms"] / 1000.0, pl["lap_distance"])

    def _restart_lap(self, pl):
        """The lap starts over on the same lap number: a Time Trial run-up reaching the line, or "Restart lap"."""
        finished = self.lap_ctx.get("finished")
        self._begin_lap(pl)
        self.lap_ctx["start_pit"] = pl["pit_status"] > 0  # a run-up is at speed on track, not an out lap
        self.lap_ctx["finished"] = finished

    def _rewind_to(self, lap, session_time, pl):
        """A flashback (or restart) took us back over the start/finish line."""
        record = self.prev_lap_record
        if record and record["lap"] == lap:
            self.buf = record["buf"]
            self.lap_ctx = record["ctx"]
            self.buf.trim_after(session_time)
            self.micro.begin(pl["current_lap_ms"] / 1000.0, pl["lap_distance"])  # timed again from the next one
        else:
            self._begin_lap(pl)
        for n in [k for k in self.saved_laps if k >= lap]:
            self.saved_laps.pop(n, None)
            self.saved_lap_keys.pop(n, None)
            self.out_laps.discard(n)
        if self.session_id:
            self.store.delete_laps_from(self.session_id, lap)
            self.store.refresh_session_summary(self.session_id)
        self.cur_lap_num = lap
        self.prev_lap_record = None

    def _complete_lap(self, prev, now):
        lap_no = self.cur_lap_num
        lap_ms = now["last_lap_ms"] or prev["current_lap_ms"]
        if not lap_no or lap_ms <= 0 or len(self.buf) < 5:
            return
        ctx = self.lap_ctx
        s1, s2 = prev["s1_ms"], prev["s2_ms"]
        s3 = lap_ms - s1 - s2 if s1 > 0 and s2 > 0 and lap_ms > s1 + s2 else 0
        valid = 0 if (ctx.get("invalid") or prev["invalid"]) else 1
        if ctx.get("start_pit"):
            lap_type = "out"
        elif prev["pit_status"] > 0:
            lap_type = "in"
        else:
            lap_type = "flying"
        if lap_type != "flying" and self._category() in ("qualifying", "time_trial", "practice"):
            valid = 0 if lap_type == "out" else valid

        st = self._player(self.status)
        dm = self._player(self.damage)
        cols = self.buf.columns()
        spd = [v for v in cols["spd"] if v is not None]
        track_len = self.session.get("track_length") or 0
        ds = [d for d in cols["d"] if d is not None]
        complete = bool(ds) and len(ds) > 50 and min(ds) < 150 and (not track_len or max(ds) > track_len - 200)

        old_pb_ms, old_pb_ref, old_sb_ms = self.pb_ms, self.pb_ref, self.session_best_ms
        self.micro.finish(lap_ms)
        cells = self.micro.cur
        times = self.micro.lap_times()
        if times is None and complete and self.micro.bounds:
            times = micro.times_from_cols(cols, self.micro.bounds, lap_ms)
        sid = self._ensure_session()
        setup_id = None
        if self.setup:
            key = setup_hash(self.setup)
            setup_id = self.setup_ids.get(key)
            if setup_id is None:
                setup_id = self.store.save_setup(self.setup, self.session.get("track_id"),
                                                 self._team_id(self.player_idx), sid)
                self.setup_ids[key] = setup_id

        lap = {
            "lap_number": lap_no, "recorded_at": now_iso(), "track_id": self.session.get("track_id"),
            "category": self._category(), "lap_time_ms": lap_ms, "s1_ms": s1, "s2_ms": s2, "s3_ms": s3,
            "valid": valid, "lap_type": lap_type, "position": prev["position"],
            "tyre_visual": ctx.get("tyre_visual"), "tyre_actual": ctx.get("tyre_actual"),
            "tyre_age": ctx.get("tyre_age"), "wear_start": ctx.get("wear_start"),
            "wear_end": dm["tyre_wear"] if dm else None,
            "fuel_start": ctx.get("fuel_start"), "fuel_end": st["fuel"] if st else None,
            "ers_deployed": ctx.get("ers_deployed"), "ers_harvested": ctx.get("ers_harvested"),
            "ers_store_start": ctx.get("ers_store_start"), "ers_store_end": st["ers_store"] if st else None,
            "top_speed": max(ctx.get("top", 0), max(spd) if spd else 0),
            "avg_speed": round(track_len / (lap_ms / 1000) * 3.6, 1) if track_len and complete else
            (round(sum(spd) / len(spd), 1) if spd else None),
            "min_speed": min(spd) if spd else None, "drs_activations": ctx.get("drs", 0),
            "aero_activations": ctx.get("aero", 0) if self.telemetry2 else None,
            "overtake_activations": ctx.get("ot", 0) if self.telemetry2 else None,
            "regs_2026": self.regs_2026,
            "max_brake_temp": ctx.get("max_bt"), "max_tyre_temp": ctx.get("max_tt"),
            "weather": self.session.get("weather"), "track_temp": self.session.get("track_temp"),
            "air_temp": self.session.get("air_temp"), "setup_id": setup_id,
            "damage": {k: dm[k] for k in ("fl_wing", "fr_wing", "rear_wing", "floor", "diffuser", "sidepod",
                                          "gearbox", "engine", "tyre_damage", "brake_damage", "tyre_blisters",
                                          "drs_fault", "ers_fault")} if dm else None,
            "assists": {"tc": st["tc"], "abs": st["abs"]} if st else None,
            "sample_count": len(self.buf), "telemetry_complete": 1 if complete else 0,
            "micro": {"key": self.micro.key, "ms": times} if times and self.micro.key else None,
        }
        lap_id = self.store.save_lap(sid, lap, cols)
        self.saved_laps[lap_no] = lap_id
        if lap_type == "out" and self._category() != "race":
            self.out_laps.add(lap_no)
        else:
            self.out_laps.discard(lap_no)
        self.store.refresh_session_summary(sid)
        self.last_sectors = [s1, s2, s3]
        if valid:
            for i, v in enumerate((s1, s2, s3)):
                if v > 0 and (self.session_best_sectors[i] is None or v < self.session_best_sectors[i]):
                    self.session_best_sectors[i] = v

        new_pb = False
        if valid and complete:
            ref = reference_from(cols)
            if ref and (self.session_best_ms is None or lap_ms < self.session_best_ms):
                self.session_best_ms = lap_ms
                self.session_best_ref = ref
            if ref and (self.pb_ms is None or lap_ms < self.pb_ms):
                had_pb = self.pb_ms is not None
                self.pb_ms = lap_ms
                self.pb_ref = ref
                new_pb = True
                if had_pb:
                    self.feed.append({"session_time": None, "lap": lap_no, "code": "PB",
                                      "text": f"New personal best: {fmt_lap(lap_ms)}"})
            tid = self.session.get("track_id")
            if tid is not None and tid >= 0 and not self.track_outline:
                outline = outline_from(cols)
                if outline and outline_ok(outline, track_len):
                    self.store.save_track(tid, outline, track_len, self.session.get("sector2_start"),
                                          self.session.get("sector3_start"))
                    self.track_outline = outline
                    self.outline_version += 1
            if tid is not None and self.circuit and self.track_frame:
                err = circuits.fit_error(self.circuit, self.track_frame, list(zip(cols["d"], cols["x"], cols["z"])), track_len)
                if err is not None and err > 3 * circuits.MAX_RMS:  # the game's coordinates moved (an update?): line up again
                    self.track_frame = None
                    self.circuit_outline = None
                    self.outline_version += 1
                    self.store.save_track_frame(tid, None)
            if lap_type == "flying":
                self.micro.commit(times, lap_ms if new_pb else None)
        self.prev_lap_record = {"lap": lap_no, "buf": self.buf, "ctx": ctx}
        self._eng("lap_done", lap_no, lap_ms, valid, lap_type, cols, old_pb_ms, old_pb_ref, old_sb_ms, new_pb, now, cells)
        if new_pb:
            self._eng("set_reference", cols)

    def _on_telemetry(self, h, p):
        self.telemetry = p
        car = self._player(p)
        lp = self._player(self.lap_data)
        if car is None or lp is None or self.session.get("spectating"):
            return
        self._eng("on_car", car, lp)
        if not self.lap_ctx:
            return
        ctx = self.lap_ctx
        if car["drs"] and not self.prev_drs:
            ctx["drs"] = ctx.get("drs", 0) + 1
        self.prev_drs = car["drs"]
        if car["speed"] > ctx.get("top", 0):
            ctx["top"] = car["speed"]
        mbt = max(car["brake_temp"])
        if mbt > ctx.get("max_bt", 0):
            ctx["max_bt"] = mbt
        mtt = max(car["tyre_surface"])
        if mtt > ctx.get("max_tt", 0):
            ctx["max_tt"] = mtt
        if lp["driver_status"] == 0 or ctx.get("finished"):
            return
        st = h.session_time
        if self.buf.st and 0 <= st - self.buf.st[-1] < self.min_dt:
            return
        mo = self._player(self.motion)
        if self.buf.st and mo and not self.finish_pending:  # nothing restarts after the chequered flag
            c = self.buf.cols
            if is_restart((c["t"][-1], c["d"][-1], c["x"][-1], c["z"][-1]),
                          (lp["current_lap_ms"] / 1000.0, lp["lap_distance"], mo["x"], mo["z"]), st - self.buf.st[-1]):
                self._restart_lap(lp)
        mx = self.motion_ex
        status = self._player(self.status)
        dm = self._player(self.damage)
        t2 = self._player(self.telemetry2)
        scalars = (
            round(lp["current_lap_ms"] / 1000.0, 3), round(lp["lap_distance"], 1), car["speed"],
            round(car["throttle"] * 100, 1), round(car["brake"] * 100, 1), round(car["steer"], 3),
            car["gear"], car["rpm"], car["drs"], car["clutch"],
            round(mo["x"], 1) if mo else None, round(mo["z"], 1) if mo else None,
            round(mo["g_lat"], 2) if mo else None, round(mo["g_lon"], 2) if mo else None,
            round(mo["g_vert"], 2) if mo else None,
            round(status["ers_store"] / ERS_MAX_J * 100, 1) if status else None,
            round(status["fuel"], 2) if status else None,
            t2["aero_mode"] if t2 else None, t2["ot_active"] if t2 else None,
            *balance(mx),
        )
        none4 = (None, None, None, None)
        wheels = (
            car["brake_temp"], car["tyre_surface"], car["tyre_inner"],
            [round(v, 1) for v in car["tyre_pressure"]],
            [round(v, 1) for v in mx["susp_pos"]] if mx else none4,
            [round(v) for v in mx["vert_force"]] if mx else none4,
            dm["tyre_wear"] if dm else none4,
        )
        self.buf.append(st, scalars, wheels)
        d = lp["lap_distance"]
        if d < self.align_next_d - 500:  # a new lap
            self.align_next_d = 0.0
        if self.circuit and not self.track_frame and not self.align_busy and d >= self.align_next_d + 300:
            # line the bundled outline up with the game's coordinates from what has been driven of this lap
            self.align_next_d = d
            cols = self.buf.columns()
            self._align_async(self.session.get("track_id"), list(zip(cols["d"], cols["x"], cols["z"])))

    def _align_async(self, tid, samples):
        circ, track_len = self.circuit, self.session.get("track_length")
        self.align_busy = True

        def work():
            try:
                frame = circuits.align(circ, samples, track_len)
            except (ValueError, ZeroDivisionError, TypeError):
                frame = None
            with self.lock:
                self.align_busy = False
                if not frame or self.session.get("track_id") != tid or self.track_frame:
                    return
                self.track_frame = frame
                self.circuit_outline = None
                self.outline_version += 1
            self.store.save_track_frame(tid, frame)
            if self.settings.get("debug"):
                print(f"[recorder] track {tid} lined up with the bundled outline: rms {frame['rms']} m, mirror {frame['mirror']}")

        threading.Thread(target=work, name="align", daemon=True).start()

    # ------------------------------------------------------------------ persistence
    def _flush_session(self):
        self.last_flush = time.time()
        if not self.session_id:
            return
        drivers = []
        if self.participants:
            n = self.participants["num_active"] or len(self.participants["cars"])
            for i, c in enumerate(self.participants["cars"][:n]):
                drivers.append({"idx": i, "name": c["name"] or f"Car {i + 1}", "team_id": c["team_id"],
                                "race_number": c["race_number"], "ai": c["ai"], "nationality": c["nationality"],
                                "driver_id": c["driver_id"], "my_team": c["my_team"],
                                "colour": c["colours"][0] if c["colours"] else None})
        history = {}
        for idx, hst in self.histories.items():
            history[str(idx)] = {
                "laps": [[l["lap_ms"], l["s1_ms"], l["s2_ms"], l["s3_ms"], l["valid_flags"]] for l in hst["laps"]],
                "stints": hst["stints"], "best_lap_num": hst["best_lap_num"],
            }
        positions = {}
        for idx, laps in self.positions_by_lap.items():
            if laps:
                positions[str(idx)] = [laps.get(n) for n in range(1, max(laps) + 1)]
        grid = {}
        if self.lap_data:
            for i, c in enumerate(self.lap_data):
                if c["result_status"] >= 2 and c["grid"]:
                    grid[str(i)] = c["grid"]
        fields = {
            "drivers": drivers, "history": history, "positions": {"laps": positions, "grid": grid},
            "weather": self.session.get("weather"), "total_laps": self.session.get("total_laps"),
            "ai_difficulty": self.session.get("ai_difficulty"), "assists": self.session.get("assists"),
            "start_reaction": self.session.get("start_reaction") or None,
        }
        fields.update(self._career_fields())
        if self.time_trial and self._category() == "time_trial":
            fields["time_trial"] = self.time_trial
        self.store.update_session(self.session_id, fields)

    def _finalize_session(self):
        if not self.session_id:
            return
        self._flush_session()
        self.store.update_session(self.session_id, {"ended_at": now_iso()})
        self.store.refresh_session_summary(self.session_id)
        self.store.delete_empty_session(self.session_id)

    # ------------------------------------------------------------------ live view
    def status_info(self) -> dict:
        with self.lock:
            age = time.time() - self.last_packet_at if self.last_packet_at else None
            return {
                "connected": age is not None and age < 3,
                "last_packet_age": age, "packets": self.packets_total, "bad_packets": self.bad_packets,
                "pps": round(len(self.pps_window) / 2.0, 1), "packet_counts": self.packet_counts,
                "size_warnings": self.size_warnings, "game": self.game, "demo": self.demo_active,
                "session_id": self.session_id,
            }

    def live_lap(self, key: str = "", since: int = 0) -> dict:
        """The lap being driven, for following it as it is drawn: the samples after `since` when `key` still
        names this lap's buffer, otherwise all of them (a new lap, a restart or a flashback)."""
        with self.lock:
            buf = self.buf
            k = f"{self.session_id}:{self.cur_lap_num}:{id(buf)}:{buf.gen}"
            n = len(buf)
            start = since if k == key and 0 <= since <= n else 0
            cols = buf.columns()
            return {"key": k, "session_id": self.session_id, "track_id": self.session.get("track_id"), "lap": self.cur_lap_num, "start": start, "n": n,
                    "track_length": self.session.get("track_length"),
                    "cols": {c: cols[c][start:n] for c in LIVE_LAP_COLS}}

    def track_outline_for_live(self):
        with self.lock:
            frame, v = self.track_frame, self.outline_version
            if self.track_outline:
                return {"outline": self.track_outline, "frame": frame, "version": v}
            if self.circuit and frame:  # the bundled outline, in game coordinates
                if self.circuit_outline is None:
                    self.circuit_outline = circuits.outline_in_game(self.circuit, frame, self.session.get("track_length"))
                return {"outline": self.circuit_outline, "frame": frame, "version": v}
            if self.circuit:  # not lined up yet: cars are placed by lap distance (see _cars_snapshot)
                return {"outline": circuits.outline_display(self.circuit, self.session.get("track_length")),
                        "frame": None, "approx": True, "version": v}
            cols = self.buf.columns()
            pts = [[d, x, z] for d, x, z in zip(cols["d"], cols["x"], cols["z"])
                   if x is not None and d is not None and d >= 0][::4]  # d < 0: before the line, e.g. leaving the pits
            return {"outline": pts, "frame": None, "version": v, "partial": True}

    def snapshot(self) -> dict:
        now = time.time()
        ts, cached = self._snapshot_cache
        if cached is not None and now - ts < 0.05:
            return cached
        with self.lock:
            snap = self._build_snapshot()
        self._snapshot_cache = (now, snap)
        return snap

    def _build_snapshot(self) -> dict:
        info = self.status_info()
        s = self.session
        out = {"status": info, "session": None, "player": None, "cars": [], "events": list(self.feed)[-25:],
               "radio": self.engineer.snapshot(),
               "outline_version": self.outline_version, "has_outline": bool(self.track_outline or self.circuit)}
        if not s:
            return out
        stype = s.get("session_type", 0)
        out["session"] = {
            "uid": str(self.session_uid), "id": self.session_id,
            "track_id": s.get("track_id"), "track": name_or(TRACKS, s.get("track_id"), "Track "),
            "type": stype, "type_name": SESSION_TYPES.get(stype, "Session"), "category": self._category(),
            "weather": s.get("weather"), "weather_name": WEATHER.get(s.get("weather"), "-"),
            "track_temp": s.get("track_temp"), "air_temp": s.get("air_temp"),
            "total_laps": s.get("total_laps"), "time_left": s.get("time_left"), "duration": s.get("duration"),
            "track_length": s.get("track_length"), "sc": s.get("safety_car"),
            "sc_name": SAFETY_CAR.get(s.get("safety_car"), ""),
            "pit_ideal": s.get("pit_window_ideal"), "pit_latest": s.get("pit_window_latest"),
            "pit_rejoin": s.get("pit_rejoin_position"), "pit_speed_limit": s.get("pit_speed_limit"),
            "ai_difficulty": s.get("ai_difficulty"), "network": s.get("network_game"),
            "s2_start": s.get("sector2_start"), "s3_start": s.get("sector3_start"),
            "num_sc": s.get("num_sc"), "num_vsc": s.get("num_vsc"), "num_red": s.get("num_red_flags"),
            "zones": s.get("marshal_zones", []),
            "forecast": [f for f in s.get("forecast", []) if f["session_type"] == stype][:8],
            "game_mode": s.get("game_mode"), "mode_name": GAME_MODES.get(s.get("game_mode"), ""),
            "mode_group": mode_group(s.get("game_mode")), "season_link": s.get("season_link"),
            "formula": s.get("formula"), "formula_name": FORMULA.get(s.get("formula"), ""),
            "aero_partial": s.get("aero_partial"), "aero_zones": s.get("aero_zones_partial" if s.get("aero_partial")
                                                                       else "aero_zones_full"),
            "drs_zones": s.get("drs_zones"), "start_reaction": s.get("start_reaction"),
        }
        if self.time_trial and self._category() == "time_trial":
            out["time_trial"] = self._time_trial_snapshot()
        out["player"] = self._player_snapshot()
        out["cars"] = self._cars_snapshot()
        return out

    def _player_snapshot(self):
        lp = self._player(self.lap_data)
        if lp is None:
            return None
        tl = self._player(self.telemetry) or {}
        st = self._player(self.status) or {}
        dm = self._player(self.damage) or {}
        mo = self._player(self.motion) or {}
        mx = self.motion_ex or {}
        idx = self.player_idx
        team_id = self._team_id(idx)
        cur_t = lp["current_lap_ms"] / 1000.0
        d = lp["lap_distance"]
        delta_session = delta_pb = None
        if self.session_best_ref and d > 0:
            r = ref_time_at(self.session_best_ref, d)
            if r is not None:
                delta_session = round((cur_t - r) * 1000)
        if self.pb_ref and d > 0:
            r = ref_time_at(self.pb_ref, d)
            if r is not None:
                delta_pb = round((cur_t - r) * 1000)
        max_rpm = st.get("max_rpm") or 13000
        p = {
            "idx": idx, "name": self._driver_name(idx), "team_id": team_id,
            "team": name_or(TEAMS, team_id, "Team ") if team_id is not None else "",
            "position": lp["position"], "lap": lp["lap"], "lap_time_ms": lp["current_lap_ms"],
            "last_lap_ms": lp["last_lap_ms"], "best_lap_ms": self.session_best_ms or self.best_by_car.get(idx),
            "pb_ms": self.pb_ms, "sector": lp["sector"], "s1_ms": lp["s1_ms"], "s2_ms": lp["s2_ms"],
            "last_sectors": self.last_sectors, "best_sectors": self.session_best_sectors,
            "overall_best_sectors": [min((b[i] for b in self.car_best_sectors.values() if b[i]), default=None)
                                     for i in range(3)],
            "invalid": lp["invalid"], "lap_distance": d, "delta_front_ms": lp["delta_front_ms"],
            "delta_leader_ms": lp["delta_leader_ms"], "pit_status": lp["pit_status"], "pits": lp["pit_stops"],
            "penalties": lp["penalties"], "warnings": lp["warnings"], "cc_warnings": lp["corner_cutting_warnings"],
            "unserved": lp["unserved_dt"] + lp["unserved_sg"], "grid": lp["grid"],
            "driver_status": DRIVER_STATUS.get(lp["driver_status"], ""), "speed_trap": lp["speed_trap"],
            "delta_session_ms": delta_session, "delta_pb_ms": delta_pb,
            "speed": tl.get("speed", 0), "gear": tl.get("gear", 0), "rpm": tl.get("rpm", 0), "max_rpm": max_rpm,
            "rev_pct": tl.get("rev_lights", 0), "throttle": tl.get("throttle", 0), "brake": tl.get("brake", 0),
            "steer": tl.get("steer", 0), "clutch": tl.get("clutch", 0), "drs": tl.get("drs", 0),
            "suggested_gear": (self.telemetry or {}).get("suggested_gear", 0),
            "brake_temp": tl.get("brake_temp"), "tyre_surface": tl.get("tyre_surface"),
            "tyre_inner": tl.get("tyre_inner"), "tyre_pressure": tl.get("tyre_pressure"),
            "engine_temp": tl.get("engine_temp"), "surface": tl.get("surface"),
            "drs_allowed": st.get("drs_allowed"), "drs_distance": st.get("drs_distance"),
            "ers_pct": round(st.get("ers_store", 0) / ERS_MAX_J * 100, 1),
            "ers_mode": ERS_MODES.get(st.get("ers_mode"), "-"),
            "ers_deployed_pct": round(st.get("ers_deployed", 0) / ERS_MAX_J * 100, 1),
            "ers_harvested_pct": round((st.get("ers_harvest_k", 0) + st.get("ers_harvest_h", 0)) / ERS_MAX_J * 100, 1),
            "power_ice_kw": round(st.get("power_ice", 0) / 1000), "power_mguk_kw": round(st.get("power_mguk", 0) / 1000),
            "fuel": st.get("fuel"), "fuel_capacity": st.get("fuel_capacity"), "fuel_laps": st.get("fuel_laps"),
            "fuel_mix": FUEL_MIX.get(st.get("fuel_mix"), "-"), "brake_bias": st.get("brake_bias"),
            "tc": st.get("tc"), "abs": st.get("abs"), "pit_limiter": st.get("pit_limiter"),
            "fia_flag": st.get("fia_flag"),
            "tyre_visual": st.get("visual_compound"), "tyre_actual": st.get("actual_compound"),
            "tyre_name": VISUAL_COMPOUNDS.get(st.get("visual_compound"), "-"),
            "tyre_compound": ACTUAL_COMPOUNDS.get(st.get("actual_compound"), ""),
            "tyre_age": st.get("tyre_age"),
            "wear": dm.get("tyre_wear"), "tyre_damage": dm.get("tyre_damage"), "blisters": dm.get("tyre_blisters"),
            "brake_damage": dm.get("brake_damage"),
            "damage": {k: dm.get(k) for k in ("fl_wing", "fr_wing", "rear_wing", "floor", "diffuser", "sidepod",
                                              "gearbox", "engine", "drs_fault", "ers_fault", "wear_mguh", "wear_es",
                                              "wear_ce", "wear_ice", "wear_mguk", "wear_tc", "engine_blown",
                                              "engine_seized")} if dm else None,
            "g_lat": mo.get("g_lat", 0), "g_lon": mo.get("g_lon", 0), "g_vert": mo.get("g_vert", 0),
            "yaw": mo.get("yaw", 0),
            "susp_pos": mx.get("susp_pos"), "slip_ratio": mx.get("slip_ratio"), "vert_force": mx.get("vert_force"),
            "front_aero_height": mx.get("front_aero_height"), "rear_aero_height": mx.get("rear_aero_height"),
            "setup": self.setup, "samples": len(self.buf), "laps_saved": len(self.saved_laps),
            "micro": self.micro.snapshot(),
            "ers_harvest_limit_mj": round(st["ers_harvest_limit"] / 1e6, 2) if st.get("ers_harvest_limit") else None,
            "ers_deployed_mj": round(st.get("ers_deployed", 0) / 1e6, 2),
            "ers_harvested_mj": round((st.get("ers_harvest_k", 0) + st.get("ers_harvest_h", 0)) / 1e6, 2),
        }
        t2 = self._player(self.telemetry2)
        if t2:
            p.update(regs_2026=t2["regs_2026"], wrong_way=t2["wrong_way"], aero_mode=t2["aero_mode"],
                     aero_available=t2["aero_available"], aero_distance=t2["aero_distance"],
                     ot_available=t2["ot_available"], ot_active=t2["ot_active"], ot_distance=t2["ot_distance"])
        if self.tyre_sets:
            p["tyre_sets"] = [dict(ts, name=VISUAL_COMPOUNDS.get(ts["visual"], "?"),
                                   compound=ACTUAL_COMPOUNDS.get(ts["actual"], ""))
                              for ts in self.tyre_sets["sets"] if ts["available"]]
        return p

    def _time_trial_snapshot(self):
        out = {}
        for key, d in self.time_trial.items():
            if not d or not d.get("lap_ms"):
                out[key] = None
                continue
            out[key] = dict(d, name=self._driver_name(d["car"]) if d["car"] < packets.MAX_CARS else None)
        return out

    def _cars_snapshot(self):
        if not self.lap_data:
            return []
        n_active = (self.participants or {}).get("num_active") or len(self.lap_data)
        cars = []
        motion = (self.motion or {}).get("cars") or []
        status = (self.status or {}).get("cars") or []
        approx = self.circuit is not None and not self.track_frame and not self.track_outline
        track_len = self.session.get("track_length")
        for i, c in enumerate(self.lap_data):
            if c["result_status"] < 2 or i >= max(n_active, 1) and not self.participants:
                continue
            if c["position"] == 0:
                continue
            team_id = self._team_id(i)
            st = status[i] if i < len(status) else {}
            mo = motion[i] if i < len(motion) else {}
            hist = self.histories.get(i)
            best = None
            if hist and hist["best_lap_num"] and hist["best_lap_num"] <= len(hist["laps"]):
                best = hist["laps"][hist["best_lap_num"] - 1]["lap_ms"] or None
            cars.append({
                "idx": i, "pos": c["position"], "name": self._driver_name(i), "team_id": team_id,
                "team": name_or(TEAMS, team_id, "Team ") if team_id is not None else "",
                "color": TEAM_COLOURS.get(team_id, "#9aa0a6"), "lap": c["lap"],
                "last_ms": c["last_lap_ms"], "best_ms": best or self.best_by_car.get(i),
                "gap_leader_ms": c["delta_leader_ms"], "gap_front_ms": c["delta_front_ms"],
                "pit": c["pit_status"], "pits": c["pit_stops"], "penalties": c["penalties"],
                "warnings": c["warnings"], "status": RESULT_STATUS.get(c["result_status"], ""),
                "driver_status": c["driver_status"], "invalid": c["invalid"], "sector": c["sector"],
                "tyre": st.get("visual_compound"), "tyre_age": st.get("tyre_age"),
                "lap_distance": round(c["lap_distance"], 1), "total_distance": round(c["total_distance"], 1),
                "x": round(mo["x"], 1) if mo else None, "z": round(mo["z"], 1) if mo else None,
                **(dict(zip(("x", "z"), circuits.approx_xz(self.circuit, c["lap_distance"], track_len))) if approx else {}),
                "player": i == self.player_idx, "ai": (self.participants["cars"][i]["ai"]
                                                       if self.participants and i < len(self.participants["cars"]) else 1),
            })
        cars.sort(key=lambda r: r["pos"])
        return cars
