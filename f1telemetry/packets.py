"""Binary parser for the EA SPORTS F1 25 UDP telemetry formats.

Packet format 2026 (F1 25 with the 2026 Season Pack: 24 cars, Car Telemetry 2),
2025 and 2024 are understood; the structs that differ between them are selected
per packet. All values are little-endian and packed. Wheel arrays are always
ordered RL, RR, FL, FR.
"""
from __future__ import annotations

import struct

MAX_CARS = 24


def num_cars(packet_format: int) -> int:
    """Size of the per-car arrays: 24 from format 2026 (the 2026 grid has 11 teams), 22 before."""
    return 24 if packet_format >= 2026 else 22


HEADER = struct.Struct("<HBBBBBQfIIBB")  # 29 bytes

MOTION_CAR = struct.Struct("<ffffffhhhhhhffffff")  # 60
SESSION_HEAD = struct.Struct("<BbbBHBbBHHBBBBBB")  # 19
MARSHAL_ZONE = struct.Struct("<fb")  # 5
SESSION_MID = struct.Struct("<BBB")  # 3
FORECAST = struct.Struct("<BBBbbbbB")  # 8
SESSION_TAIL = struct.Struct("<BBIIIBBB" + "B" * 11 + "IB" + "BBBB" + "BBB" + "B" * 24 + "B" + "12B" + "ff")  # 85
LAP_CAR = struct.Struct("<IIHBHBHBHBfff" + "B" * 15 + "HHBfB")  # 57
PARTICIPANT_25 = struct.Struct("<BBBBBBB32sBBHBB12s")  # 57
PARTICIPANT_24 = struct.Struct("<BBBBBBB48sBBHB")  # 60
SETUP_CAR = struct.Struct("<BBBBffffBBBBBBBBBffffBf")  # 50
TELEMETRY_CAR = struct.Struct("<HfffBbHBBH4H4B4BH4f4B")  # 60
STATUS_CAR = struct.Struct("<BBBBBfffHHBBHBBBbfffBfffB")  # 55
FINAL_25 = struct.Struct("<BBBBBBBIdBBB8B8B8B")  # 46
FINAL_24 = struct.Struct("<BBBBBBIdBBB8B8B8B")  # 45
DAMAGE_25 = struct.Struct("<4f4B4B4B18B")  # 46
DAMAGE_24 = struct.Struct("<4f4B4B18B")  # 42
HISTORY_HEAD = struct.Struct("<7B")
HISTORY_LAP = struct.Struct("<IHBHBHBB")  # 14
HISTORY_STINT = struct.Struct("<BBB")
TYRE_SET = struct.Struct("<BBBBBBBhB")  # 10
MOTION_EX_25 = struct.Struct("<61f")
MOTION_EX_24 = struct.Struct("<52f")
TIME_TRIAL_SET = struct.Struct("<BBIIIIBBBBBB")  # 24

# Format 2026 changes: quantised g-forces, uint16 driver/network/team ids, uint8 engine
# temperature, ERS harvest limit, active aero / DRS zones in the session packet.
MOTION_CAR_26 = struct.Struct("<ffffffhhhhhhhhhfff")  # 54
SESSION_AERO_26 = struct.Struct("<BB16fB16fB8ffBBBBB")  # 173
PARTICIPANT_26 = struct.Struct("<BHHHBBB32sBBHBB12s")  # 60
TELEMETRY_CAR_26 = struct.Struct("<HfffBbHBBH4H4B4BB4f4B")  # 59
STATUS_CAR_26 = struct.Struct("<BBBBBfffHHBBHBBBbfffBffffB")  # 59
TIME_TRIAL_SET_26 = struct.Struct("<BHIIIIBBBBBB")  # 25
TELEMETRY2_CAR = struct.Struct("<BBHBBHBB")  # 10

# Expected packet sizes per format, used for diagnostics only.
EXPECTED_SIZES = {
    2025: {0: 1349, 1: 753, 2: 1285, 3: 45, 4: 1284, 5: 1133, 6: 1352, 7: 1239,
           8: 1042, 9: 954, 10: 1041, 11: 1460, 12: 231, 13: 273, 14: 101, 15: 1131},
    2026: {0: 1325, 1: 926, 2: 1399, 3: 45, 4: 1470, 5: 1233, 6: 1448, 7: 1445,
           8: 1134, 9: 1062, 10: 1133, 11: 1460, 12: 231, 13: 273, 14: 104, 15: 1231, 16: 269},
}


def expected_size(packet_format: int, packet_id: int):
    """Spec size of a packet, or None. Newer formats are checked against the latest known one."""
    if packet_format < 2025:
        return None
    return EXPECTED_SIZES[min(packet_format, max(EXPECTED_SIZES))].get(packet_id)


class Header:
    __slots__ = ("packet_format", "game_year", "game_major", "game_minor", "packet_version",
                 "packet_id", "session_uid", "session_time", "frame", "overall_frame",
                 "player_car_index", "secondary_player_car_index")

    def __init__(self, data: bytes):
        (self.packet_format, self.game_year, self.game_major, self.game_minor, self.packet_version,
         self.packet_id, self.session_uid, self.session_time, self.frame, self.overall_frame,
         self.player_car_index, self.secondary_player_car_index) = HEADER.unpack_from(data, 0)


def _iter_cars(st: struct.Struct, data: bytes, offset: int, count: int):
    available = max(0, (len(data) - offset) // st.size)
    for i in range(min(count, available)):
        yield st.unpack_from(data, offset + i * st.size)


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


# --------------------------------------------------------------------------- packets

def parse_motion(data: bytes, h: Header) -> dict:
    new = h.packet_format >= 2026
    st, g = (MOTION_CAR_26, 1000.0) if new else (MOTION_CAR, 1.0)  # 2026 g-forces are int16 / 1000
    cars = []
    for v in _iter_cars(st, data, HEADER.size, num_cars(h.packet_format)):
        cars.append({
            "x": v[0], "y": v[1], "z": v[2],
            "vx": v[3], "vy": v[4], "vz": v[5],
            "fwd": (v[6] / 32767.0, v[7] / 32767.0, v[8] / 32767.0),
            "right": (v[9] / 32767.0, v[10] / 32767.0, v[11] / 32767.0),
            "g_lat": v[12] / g, "g_lon": v[13] / g, "g_vert": v[14] / g,
            "yaw": v[15], "pitch": v[16], "roll": v[17],
        })
    return {"cars": cars}


def parse_session(data: bytes, h: Header) -> dict:
    o = HEADER.size
    v = SESSION_HEAD.unpack_from(data, o)
    o += SESSION_HEAD.size
    s = {
        "weather": v[0], "track_temp": v[1], "air_temp": v[2], "total_laps": v[3],
        "track_length": v[4], "session_type": v[5], "track_id": v[6], "formula": v[7],
        "time_left": v[8], "duration": v[9], "pit_speed_limit": v[10], "paused": v[11],
        "spectating": v[12], "spectator_car": v[13],
    }
    num_zones = min(v[15], 21)
    zones = []
    for i in range(21):
        start, flag = MARSHAL_ZONE.unpack_from(data, o + i * MARSHAL_ZONE.size)
        if i < num_zones:
            zones.append({"start": start, "flag": flag})
    o += 21 * MARSHAL_ZONE.size
    s["marshal_zones"] = zones
    sc, network, num_fc = SESSION_MID.unpack_from(data, o)
    o += SESSION_MID.size
    s["safety_car"] = sc
    s["network_game"] = network
    forecast = []
    for i in range(min(num_fc, 64)):
        f = FORECAST.unpack_from(data, o + i * FORECAST.size)
        forecast.append({
            "session_type": f[0], "offset": f[1], "weather": f[2], "track_temp": f[3],
            "track_temp_change": f[4], "air_temp": f[5], "air_temp_change": f[6], "rain": f[7],
        })
    o += 64 * FORECAST.size
    s["forecast"] = forecast
    if len(data) >= o + SESSION_TAIL.size:
        t = SESSION_TAIL.unpack_from(data, o)
        s.update({
            "forecast_accuracy": t[0], "ai_difficulty": t[1],
            "season_link": t[2], "weekend_link": t[3], "session_link": t[4],
            "pit_window_ideal": t[5], "pit_window_latest": t[6], "pit_rejoin_position": t[7],
            "assists": {
                "steering": t[8], "braking": t[9], "gearbox": t[10], "pit": t[11],
                "pit_release": t[12], "ers": t[13], "drs": t[14], "racing_line": t[15],
                "racing_line_type": t[16],
            },
            "game_mode": t[17], "rule_set": t[18], "time_of_day": t[19], "session_length": t[20],
            "speed_units": t[21], "temp_units": t[22],
            "num_sc": t[25], "num_vsc": t[26], "num_red_flags": t[27],
            "equal_performance": t[28],
            "weekend_structure": list(t[53:53 + min(t[52], 12)]),
            "sector2_start": t[65], "sector3_start": t[66],
        })
        o += SESSION_TAIL.size
        if h.packet_format >= 2026 and len(data) >= o + SESSION_AERO_26.size:
            a = SESSION_AERO_26.unpack_from(data, o)

            def zones(n, fl):
                return [[round(fl[2 * i], 4), round(fl[2 * i + 1], 4)] for i in range(min(n, len(fl) // 2))]
            s.update({
                "aero_partial": a[0],  # 0 = full active aero track, 1 = partial
                "aero_zones_full": zones(a[1], a[2:18]), "aero_zones_partial": zones(a[18], a[19:35]),
                "drs_zones": zones(a[35], a[36:44]), "start_reaction": round(a[44], 3),
            })
            s["assists"].update({"abs": a[45], "tc": a[46], "racing_line_hivis": a[47],
                                 "racing_line_colourblind": a[48], "rewind_prompt": a[49]})
    return s


def parse_lap_data(data: bytes, h: Header) -> dict:
    n = num_cars(h.packet_format)
    cars = []
    for v in _iter_cars(LAP_CAR, data, HEADER.size, n):
        cars.append({
            "last_lap_ms": v[0], "current_lap_ms": v[1],
            "s1_ms": v[2] + v[3] * 60000, "s2_ms": v[4] + v[5] * 60000,
            "delta_front_ms": v[6] + v[7] * 60000, "delta_leader_ms": v[8] + v[9] * 60000,
            "lap_distance": v[10], "total_distance": v[11], "sc_delta": v[12],
            "position": v[13], "lap": v[14], "pit_status": v[15], "pit_stops": v[16],
            "sector": v[17], "invalid": v[18], "penalties": v[19], "warnings": v[20],
            "corner_cutting_warnings": v[21], "unserved_dt": v[22], "unserved_sg": v[23],
            "grid": v[24], "driver_status": v[25], "result_status": v[26],
            "pit_lane_timer_active": v[27], "pit_lane_time_ms": v[28], "pit_stop_time_ms": v[29],
            "pit_should_serve_pen": v[30], "speed_trap": v[31], "speed_trap_lap": v[32],
        })
    o = HEADER.size + n * LAP_CAR.size
    tt_pb, tt_rival = (data[o], data[o + 1]) if len(data) >= o + 2 else (255, 255)
    return {"cars": cars, "tt_pb_car": tt_pb, "tt_rival_car": tt_rival}


def parse_event(data: bytes, h: Header) -> dict:
    code = data[29:33].decode("ascii", "replace")
    d = data[33:] + b"\x00" * 16
    ev: dict = {"code": code}
    if code == "FTLP":
        ev["vehicle"], ev["lap_time"] = struct.unpack_from("<Bf", d)
    elif code == "RTMT":
        ev["vehicle"], ev["reason"] = d[0], d[1]
    elif code == "DRSD":
        ev["reason"] = d[0]
    elif code in ("TMPT", "RCWN", "DTSV"):
        ev["vehicle"] = d[0]
    elif code == "PENA":
        (ev["penalty_type"], ev["infringement"], ev["vehicle"], ev["other_vehicle"],
         ev["time"], ev["lap"], ev["places_gained"]) = struct.unpack_from("<7B", d)
    elif code == "SPTP":
        (ev["vehicle"], ev["speed"], ev["overall_fastest"], ev["driver_fastest"],
         ev["fastest_vehicle"], ev["fastest_speed"]) = struct.unpack_from("<BfBBBf", d)
    elif code == "STLG":
        ev["lights"] = d[0]
    elif code == "SGSV":
        ev["vehicle"], ev["stop_time"] = struct.unpack_from("<Bf", d)
    elif code == "FLBK":
        ev["frame"], ev["session_time"] = struct.unpack_from("<If", d)
    elif code == "BUTN":
        ev["buttons"] = struct.unpack_from("<I", d)[0]
    elif code == "OVTK":
        ev["vehicle"], ev["other_vehicle"] = d[0], d[1]
    elif code == "SCAR":
        ev["sc_type"], ev["sc_event"] = d[0], d[1]
    elif code == "COLL":
        ev["vehicle"], ev["other_vehicle"] = d[0], d[1]
        if h.packet_format >= 2026:
            ev["severity"] = d[2]
    elif code == "PMEN":
        ev["reason"] = d[0]
    return ev


def parse_participants(data: bytes, h: Header) -> dict:
    num_active = data[HEADER.size]
    n = num_cars(h.packet_format)
    body = len(data) - HEADER.size - 1
    if h.packet_format >= 2026:
        st = PARTICIPANT_26
    else:
        st = PARTICIPANT_24 if body == n * PARTICIPANT_24.size or (
            h.packet_format < 2025 and body != n * PARTICIPANT_25.size) else PARTICIPANT_25
    cars = []
    for v in _iter_cars(st, data, HEADER.size + 1, n):
        p = {
            "ai": v[0], "driver_id": v[1], "network_id": v[2], "team_id": v[3], "my_team": v[4],
            "race_number": v[5], "nationality": v[6], "name": _cstr(v[7]),
            "telemetry_public": v[8], "show_online_names": v[9], "tech_level": v[10],
            "platform": v[11], "colours": [],
        }
        if st is not PARTICIPANT_24:
            raw = v[13]
            p["colours"] = ["#%02x%02x%02x" % (raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2])
                            for i in range(min(v[12], 4))]
        cars.append(p)
    return {"num_active": num_active, "cars": cars}


SETUP_KEYS = (
    "front_wing", "rear_wing", "diff_on_throttle", "diff_off_throttle",
    "front_camber", "rear_camber", "front_toe", "rear_toe",
    "front_suspension", "rear_suspension", "front_arb", "rear_arb",
    "front_ride_height", "rear_ride_height", "brake_pressure", "brake_bias", "engine_braking",
    "rl_pressure", "rr_pressure", "fl_pressure", "fr_pressure", "ballast", "fuel_load",
)


def parse_car_setups(data: bytes, h: Header) -> dict:
    n = num_cars(h.packet_format)
    cars = [dict(zip(SETUP_KEYS, v)) for v in _iter_cars(SETUP_CAR, data, HEADER.size, n)]
    o = HEADER.size + n * SETUP_CAR.size
    nxt = struct.unpack_from("<f", data, o)[0] if len(data) >= o + 4 else None
    return {"cars": cars, "next_front_wing": nxt}


def parse_car_telemetry(data: bytes, h: Header) -> dict:
    n = num_cars(h.packet_format)
    st = TELEMETRY_CAR_26 if h.packet_format >= 2026 else TELEMETRY_CAR
    cars = []
    for v in _iter_cars(st, data, HEADER.size, n):
        cars.append({
            "speed": v[0], "throttle": v[1], "steer": v[2], "brake": v[3], "clutch": v[4],
            "gear": v[5], "rpm": v[6], "drs": v[7], "rev_lights": v[8], "rev_bits": v[9],
            "brake_temp": list(v[10:14]), "tyre_surface": list(v[14:18]),
            "tyre_inner": list(v[18:22]), "engine_temp": v[22],
            "tyre_pressure": list(v[23:27]), "surface": list(v[27:31]),
        })
    o = HEADER.size + n * st.size
    suggested = struct.unpack_from("<b", data, o + 2)[0] if len(data) >= o + 3 else 0
    return {"cars": cars, "suggested_gear": suggested}


def parse_car_status(data: bytes, h: Header) -> dict:
    new = h.packet_format >= 2026
    cars = []
    for v in _iter_cars(STATUS_CAR_26 if new else STATUS_CAR, data, HEADER.size, num_cars(h.packet_format)):
        if new:  # 2026 adds the per-lap ERS harvest limit before the deployed energy
            limit, v = v[23], v[:23] + v[24:]
        else:
            limit = None
        cars.append({
            "tc": v[0], "abs": v[1], "fuel_mix": v[2], "brake_bias": v[3], "pit_limiter": v[4],
            "fuel": v[5], "fuel_capacity": v[6], "fuel_laps": v[7], "max_rpm": v[8],
            "idle_rpm": v[9], "max_gears": v[10], "drs_allowed": v[11], "drs_distance": v[12],
            "actual_compound": v[13], "visual_compound": v[14], "tyre_age": v[15],
            "fia_flag": v[16], "power_ice": v[17], "power_mguk": v[18], "ers_store": v[19],
            "ers_mode": v[20], "ers_harvest_k": v[21], "ers_harvest_h": v[22],
            "ers_deployed": v[23], "network_paused": v[24], "ers_harvest_limit": limit,
        })
    return {"cars": cars}


def parse_final_classification(data: bytes, h: Header) -> dict:
    num = data[HEADER.size]
    n = num_cars(h.packet_format)
    body = len(data) - HEADER.size - 1
    st = FINAL_24 if body == n * FINAL_24.size else FINAL_25
    cars = []
    for v in _iter_cars(st, data, HEADER.size + 1, n):
        if st is FINAL_25:
            pos, laps, grid, pts, pits, status, reason, best, total, pen_t, pen_n, stints = v[:12]
            rest = v[12:]
        else:
            pos, laps, grid, pts, pits, status, best, total, pen_t, pen_n, stints = v[:11]
            reason = 0
            rest = v[11:]
        cars.append({
            "position": pos, "laps": laps, "grid": grid, "points": pts, "pit_stops": pits,
            "result_status": status, "result_reason": reason, "best_lap_ms": best,
            "total_time": total, "penalty_time": pen_t, "num_penalties": pen_n,
            "stints": [{"actual": rest[i], "visual": rest[8 + i], "end_lap": rest[16 + i]}
                       for i in range(min(stints, 8))],
        })
    return {"num_cars": num, "cars": cars}


def parse_car_damage(data: bytes, h: Header) -> dict:
    n = num_cars(h.packet_format)
    body = len(data) - HEADER.size
    st = DAMAGE_24 if body == n * DAMAGE_24.size else DAMAGE_25
    cars = []
    for v in _iter_cars(st, data, HEADER.size, n):
        wear = [round(x, 2) for x in v[0:4]]
        tyre_dmg = list(v[4:8])
        brake_dmg = list(v[8:12])
        if st is DAMAGE_25:
            blisters = list(v[12:16])
            r = v[16:]
        else:
            blisters = [0, 0, 0, 0]
            r = v[12:]
        cars.append({
            "tyre_wear": wear, "tyre_damage": tyre_dmg, "brake_damage": brake_dmg,
            "tyre_blisters": blisters,
            "fl_wing": r[0], "fr_wing": r[1], "rear_wing": r[2], "floor": r[3], "diffuser": r[4],
            "sidepod": r[5], "drs_fault": r[6], "ers_fault": r[7], "gearbox": r[8], "engine": r[9],
            "wear_mguh": r[10], "wear_es": r[11], "wear_ce": r[12], "wear_ice": r[13],
            "wear_mguk": r[14], "wear_tc": r[15], "engine_blown": r[16], "engine_seized": r[17],
        })
    return {"cars": cars}


def parse_session_history(data: bytes, h: Header) -> dict:
    o = HEADER.size
    car, num_laps, num_stints, best_lap, best_s1, best_s2, best_s3 = HISTORY_HEAD.unpack_from(data, o)
    o += HISTORY_HEAD.size
    laps = []
    for i in range(min(num_laps, 100)):
        v = HISTORY_LAP.unpack_from(data, o + i * HISTORY_LAP.size)
        laps.append({
            "lap_ms": v[0], "s1_ms": v[1] + v[2] * 60000, "s2_ms": v[3] + v[4] * 60000,
            "s3_ms": v[5] + v[6] * 60000, "valid_flags": v[7],
        })
    o += 100 * HISTORY_LAP.size
    stints = []
    for i in range(min(num_stints, 8)):
        end, actual, visual = HISTORY_STINT.unpack_from(data, o + i * HISTORY_STINT.size)
        stints.append({"end_lap": end, "actual": actual, "visual": visual})
    return {
        "car": car, "laps": laps, "stints": stints, "best_lap_num": best_lap,
        "best_s1_lap": best_s1, "best_s2_lap": best_s2, "best_s3_lap": best_s3,
    }


def parse_tyre_sets(data: bytes, h: Header) -> dict:
    o = HEADER.size
    car = data[o]
    sets = []
    for v in _iter_cars(TYRE_SET, data, o + 1, 20):
        sets.append({
            "actual": v[0], "visual": v[1], "wear": v[2], "available": v[3],
            "recommended_session": v[4], "life_span": v[5], "usable_life": v[6],
            "lap_delta_ms": v[7], "fitted": v[8],
        })
    fo = o + 1 + 20 * TYRE_SET.size
    fitted = data[fo] if len(data) > fo else 255
    return {"car": car, "sets": sets, "fitted_index": fitted}


def parse_motion_ex(data: bytes, h: Header) -> dict:
    n = (len(data) - HEADER.size) // 4
    st = MOTION_EX_25 if n >= 61 else MOTION_EX_24
    v = st.unpack_from(data, HEADER.size)
    m = {
        "susp_pos": list(v[0:4]), "susp_vel": list(v[4:8]), "susp_acc": list(v[8:12]),
        "wheel_speed": list(v[12:16]), "slip_ratio": list(v[16:20]), "slip_angle": list(v[20:24]),
        "lat_force": list(v[24:28]), "long_force": list(v[28:32]), "cog_height": v[32],
        "local_vel": list(v[33:36]), "ang_vel": list(v[36:39]), "ang_acc": list(v[39:42]),
        "front_wheels_angle": v[42], "vert_force": list(v[43:47]),
        "front_aero_height": v[47], "rear_aero_height": v[48],
        "front_roll": v[49], "rear_roll": v[50], "chassis_yaw": v[51],
    }
    if st is MOTION_EX_25:
        m["chassis_pitch"] = v[52]
        m["camber"] = list(v[53:57])
        m["camber_gain"] = list(v[57:61])
    return m


def parse_time_trial(data: bytes, h: Header) -> dict:
    keys = ("car", "team", "lap_ms", "s1_ms", "s2_ms", "s3_ms", "tc", "gearbox", "abs",
            "equal_performance", "custom_setup", "valid")
    st = TIME_TRIAL_SET_26 if h.packet_format >= 2026 else TIME_TRIAL_SET  # 2026: uint16 team id
    sets = [dict(zip(keys, v)) for v in _iter_cars(st, data, HEADER.size, 3)]
    names = ("session_best", "personal_best", "rival")
    return {names[i]: s for i, s in enumerate(sets)}


def parse_lap_positions(data: bytes, h: Header) -> dict:
    o = HEADER.size
    num_laps, lap_start = data[o], data[o + 1]
    o += 2
    n = num_cars(h.packet_format)
    rows = []
    for i in range(min(num_laps, 50)):
        rows.append(list(data[o + i * n: o + (i + 1) * n]))
    return {"num_laps": num_laps, "lap_start": lap_start, "positions": rows}


def parse_car_telemetry2(data: bytes, h: Header) -> dict:
    """Packet 16 (format 2026): active aero, Overtake Mode and the 2026-regulations flag."""
    cars = []
    for v in _iter_cars(TELEMETRY2_CAR, data, HEADER.size, num_cars(h.packet_format)):
        cars.append({
            "aero_mode": v[0], "aero_available": v[1], "aero_distance": v[2],  # mode 0 = corner, 1 = straight
            "ot_available": v[3], "ot_active": v[4], "ot_distance": v[5],
            "regs_2026": v[6], "wrong_way": v[7],
        })
    return {"cars": cars}


PARSERS = {
    0: parse_motion,
    1: parse_session,
    2: parse_lap_data,
    3: parse_event,
    4: parse_participants,
    5: parse_car_setups,
    6: parse_car_telemetry,
    7: parse_car_status,
    8: parse_final_classification,
    10: parse_car_damage,
    11: parse_session_history,
    12: parse_tyre_sets,
    13: parse_motion_ex,
    14: parse_time_trial,
    15: parse_lap_positions,
    16: parse_car_telemetry2,
}


def parse(data: bytes):
    """Returns (header, payload) or (header, None) for packets we don't decode.

    Raises ValueError for datagrams that are not F1 telemetry.
    """
    if len(data) < HEADER.size:
        raise ValueError("datagram too short")
    h = Header(data)
    if h.packet_format < 2020 or h.packet_format > 2100:
        raise ValueError(f"unsupported packet format {h.packet_format}")
    fn = PARSERS.get(h.packet_id)
    if fn is None:
        return h, None
    return h, fn(data, h)
