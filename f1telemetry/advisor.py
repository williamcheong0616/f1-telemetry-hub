"""Setup advisor: how the car is balanced with a setup, what to try next, and what each change did.

Balance is the understeer angle (how much more the front tyres slip sideways than the rears, from the
game's Motion Ex data) while cornering: above zero the car pushes, below zero it slides. It is split by
corner speed (slow, medium, fast) and by phase (braking into the corner, the middle, back on the power).
"""
from __future__ import annotations

import statistics

from .coach import lap_series

BANDS = (("slow", 0, 120), ("medium", 120, 200), ("fast", 200, 1e9))  # km/h
PHASES = ("entry", "mid", "exit")
NOTICE = 0.5      # degrees of understeer angle worth a remark
STRONG = 1.2      # ... and a clear one
MIN_SAMPLES = 30  # cornering samples a band or phase needs before it says anything

LABELS = {
    "front_wing": "Front wing", "rear_wing": "Rear wing", "diff_on_throttle": "On-throttle differential",
    "diff_off_throttle": "Off-throttle differential", "front_camber": "Front camber", "rear_camber": "Rear camber",
    "front_toe": "Front toe", "rear_toe": "Rear toe", "front_suspension": "Front suspension",
    "rear_suspension": "Rear suspension", "front_arb": "Front anti-roll bar", "rear_arb": "Rear anti-roll bar",
    "front_ride_height": "Front ride height", "rear_ride_height": "Rear ride height", "brake_pressure": "Brake pressure",
    "brake_bias": "Front brake bias", "engine_braking": "Engine braking", "rl_pressure": "Rear left pressure",
    "rr_pressure": "Rear right pressure", "fl_pressure": "Front left pressure", "fr_pressure": "Front right pressure",
    "ballast": "Ballast",
}
UNITS = {"diff_on_throttle": "%", "diff_off_throttle": "%", "brake_pressure": "%", "brake_bias": "%", "engine_braking": "%",
         "front_camber": "°", "rear_camber": "°", "front_toe": "°", "rear_toe": "°",
         "rl_pressure": " psi", "rr_pressure": " psi", "fl_pressure": " psi", "fr_pressure": " psi"}
DECIMALS = {"front_camber": 2, "rear_camber": 2, "front_toe": 2, "rear_toe": 2,
            "rl_pressure": 1, "rr_pressure": 1, "fl_pressure": 1, "fr_pressure": 1}
# the game's ranges and a sensible step for a suggestion (F1 25)
RANGES = {"front_wing": (0, 50, 1), "rear_wing": (0, 50, 1), "diff_on_throttle": (10, 100, 5),
          "diff_off_throttle": (10, 100, 5), "front_arb": (1, 21, 1), "rear_arb": (1, 21, 1),
          "front_suspension": (1, 41, 1), "rear_suspension": (1, 41, 1), "brake_bias": (50, 70, 1),
          "brake_pressure": (80, 100, 2)}


def fmt_value(key, v) -> str:
    if v is None:
        return "–"
    d = DECIMALS.get(key, 0)
    return f"{v:.{d}f}{UNITS.get(key, '')}" if isinstance(v, (int, float)) else str(v)


def step(setup: dict, key: str, direction: int, clicks: int = 1) -> str | None:
    """'Front wing 28 → 29', or None when the setting is already at the end of its range."""
    cur = (setup or {}).get(key)
    if cur is None or key not in RANGES:
        return None
    lo, hi, st = RANGES[key]
    new = min(hi, max(lo, cur + direction * st * clicks))
    if new == cur:
        return None
    return f"{LABELS[key]} {fmt_value(key, cur)} → {fmt_value(key, new)}"


# ---------------------------------------------------------------------- balance of a lap
def lap_profile(p: dict) -> dict:
    """Sums over one lap, so laps can be added up: understeer angle per corner-speed band and corner phase,
    lock-ups under braking, wheelspin on the power and the tyres' surface temperatures."""
    acc = {"band": {b: [0.0, 0] for b, _, _ in BANDS}, "phase": {ph: [0.0, 0] for ph in PHASES},
           "lock": [0, 0], "spin": [0, 0], "ts_f": [0.0, 0], "ts_r": [0.0, 0]}
    us, spd, brk, thr, glat = p["us"], p["spd"], p["brk"], p["thr"], p["glat"]
    lk, ws = p["lk"], p["ws"]
    for i in range(len(p["d"])):
        v = spd[i]
        if v is None:
            continue
        b, t = (brk[i] or 0) if brk else 0, (thr[i] or 0) if thr else 0
        if us and us[i] is not None and v >= 60 and (glat is None or glat[i] is None or abs(glat[i]) >= 0.8):
            u = us[i]
            for name, lo, hi in BANDS:
                if lo <= v < hi:
                    acc["band"][name][0] += u
                    acc["band"][name][1] += 1
            ph = "entry" if b > 5 else "exit" if t >= 50 else "mid"
            acc["phase"][ph][0] += u
            acc["phase"][ph][1] += 1
        if lk and b > 20 and lk[i] is not None:
            acc["lock"][1] += 1
            acc["lock"][0] += lk[i] > 0.15
        if ws and t > 50 and v < 200 and ws[i] is not None:
            acc["spin"][1] += 1
            acc["spin"][0] += ws[i] > 0.10
        for k in ("ts_f", "ts_r"):
            vals = p.get(k)
            if vals and vals[i] is not None:
                acc[k][0] += vals[i]
                acc[k][1] += 1
    return acc


def _merge(profiles: list[dict]) -> dict:
    out = {"band": {b: [0.0, 0] for b, _, _ in BANDS}, "phase": {ph: [0.0, 0] for ph in PHASES},
           "lock": [0, 0], "spin": [0, 0], "ts_f": [0.0, 0], "ts_r": [0.0, 0]}
    for pr in profiles:
        for grp in ("band", "phase"):
            for k, (s, n) in pr[grp].items():
                out[grp][k][0] += s
                out[grp][k][1] += n
        for k in ("lock", "spin", "ts_f", "ts_r"):
            out[k][0] += pr[k][0]
            out[k][1] += pr[k][1]
    return out


def summarise(acc: dict) -> dict:
    avg = lambda s, n: s / n if n >= MIN_SAMPLES else None  # noqa: E731
    pct = lambda s, n: 100 * s / n if n >= MIN_SAMPLES else None  # noqa: E731
    return {
        "bands": {k: {"us": avg(*v), "n": v[1]} for k, v in acc["band"].items()},
        "phases": {k: {"us": avg(*v), "n": v[1]} for k, v in acc["phase"].items()},
        "lock_pct": pct(*acc["lock"]), "spin_pct": pct(*acc["spin"]),
        "ts_f": acc["ts_f"][0] / acc["ts_f"][1] if acc["ts_f"][1] else None,
        "ts_r": acc["ts_r"][0] / acc["ts_r"][1] if acc["ts_r"][1] else None,
    }


# ---------------------------------------------------------------------- suggestions
def suggestions(prof: dict, setup: dict) -> list[dict]:
    """What to try, most important first; each names the setting and the value to move it to."""
    out = []

    def add(strength, area, text, *changes):
        ch = [c for c in changes if c]
        out.append({"strength": strength, "area": area, "text": text, "changes": ch})

    bands, phases = prof["bands"], prof["phases"]
    fast, med, slow = bands["fast"]["us"], bands["medium"]["us"], bands["slow"]["us"]
    entry, exit_ = phases["entry"]["us"], phases["exit"]["us"]
    big = lambda u: 2 if abs(u) >= STRONG else 1  # noqa: E731
    if fast is not None and fast >= NOTICE:
        add(fast, "Fast corners", f"Understeer in fast corners ({fast:+.1f}°): more front wing gives the front grip where downforce counts.",
            step(setup, "front_wing", 1, big(fast)))
    elif fast is not None and fast <= -NOTICE:
        add(-fast, "Fast corners", f"Oversteer in fast corners ({fast:+.1f}°): more rear wing, or less front wing if you need the top speed.",
            step(setup, "rear_wing", 1, big(fast)), step(setup, "front_wing", -1))
    if slow is not None and slow >= NOTICE:
        add(slow, "Slow corners", f"Understeer in slow corners ({slow:+.1f}°): a softer front anti-roll bar lets the front bite.",
            step(setup, "front_arb", -1, big(slow)))
    elif slow is not None and slow <= -NOTICE:
        add(-slow, "Slow corners", f"Oversteer in slow corners ({slow:+.1f}°): a softer rear anti-roll bar gives the rear more grip.",
            step(setup, "rear_arb", -1, big(slow)))
    if med is not None and abs(med) >= NOTICE and not (fast is not None and abs(fast) >= NOTICE and slow is not None and abs(slow) >= NOTICE):
        if med > 0:
            add(med * 0.9, "Medium corners", f"Understeer in medium-speed corners ({med:+.1f}°): soften the front suspension a click.",
                step(setup, "front_suspension", -1))
        else:
            add(-med * 0.9, "Medium corners", f"Oversteer in medium-speed corners ({med:+.1f}°): soften the rear suspension a click.",
                step(setup, "rear_suspension", -1))
    if entry is not None and entry >= NOTICE:
        add(entry * 0.8, "Corner entry", f"Pushing on the way in ({entry:+.1f}° under braking): brake bias back a notch or a more open off-throttle differential helps it turn in.",
            step(setup, "brake_bias", -1), step(setup, "diff_off_throttle", -1))
    elif entry is not None and entry <= -NOTICE:
        add(-entry * 0.8, "Corner entry", f"Loose on the way in ({entry:+.1f}° under braking): brake bias forward or a more locked off-throttle differential calms it.",
            step(setup, "brake_bias", 1), step(setup, "diff_off_throttle", 1))
    spin = prof["spin_pct"]
    if exit_ is not None and exit_ >= NOTICE:
        add(exit_ * 0.8, "Corner exit", f"Understeer on the power ({exit_:+.1f}°): a more open on-throttle differential lets the car rotate out of the corner.",
            step(setup, "diff_on_throttle", -1))
    elif (exit_ is not None and exit_ <= -NOTICE) or (spin is not None and spin >= 8):
        what = f"wheelspin on {spin:.0f}% of the way out of slow corners" if spin is not None and spin >= 8 else f"oversteer on the power ({exit_:+.1f}°)"
        add(max(abs(exit_ or 0), (spin or 0) / 10) * 0.8, "Corner exit", f"Traction: {what}. A more locked on-throttle differential, or a softer rear anti-roll bar, and a smoother right foot.",
            step(setup, "diff_on_throttle", 1), step(setup, "rear_arb", -1))
    lock = prof["lock_pct"]
    if lock is not None and lock >= 5:
        add(lock / 10, "Braking", f"Lock-ups on {lock:.0f}% of the braking: a little less brake pressure, or move the bias away from the end that locks.",
            step(setup, "brake_pressure", -1))
    tf, tr = prof["ts_f"], prof["ts_r"]
    if tf is not None and tr is not None and abs(tf - tr) >= 6:
        if tf > tr:
            add(0.4, "Tyres", f"The fronts run {tf - tr:.0f}°C hotter than the rears: they do the work, which goes with understeer and wears them first.")
        else:
            add(0.4, "Tyres", f"The rears run {tr - tf:.0f}°C hotter than the fronts: protect them on the way out of corners, or they will go off first.")
    out.sort(key=lambda s: -s["strength"])
    if not out:
        if all(b["us"] is None for b in bands.values()):
            out.append({"strength": 0, "area": "Balance", "text": "Not enough cornering with balance data yet: it needs a few laps (and the game's Motion Ex data, sent with UDP Format 2024 or newer).", "changes": []})
        else:
            out.append({"strength": 0, "area": "Balance", "text": "The car is balanced: no corner speed shows a clear push or slide. The time is in the driving now (see the Coach page).", "changes": []})
    for s in out:
        del s["strength"]
    return out[:4]


# ---------------------------------------------------------------------- a setup's report
def _profile_of(store, laps) -> dict:
    profs = []
    for l in laps:
        p = lap_series(store, l["id"])
        if p:
            profs.append(lap_profile(p))
    return summarise(_merge(profs))


def _times(laps):
    valid = [l["lap_time_ms"] for l in laps if l["valid"] and (l["lap_type"] or "flying") == "flying"]
    if not valid:
        return None, None
    best = min(valid)
    near = [v for v in valid if v <= best * 1.03]
    return best, round(statistics.median(near))


def setup_report(store, setup_id: int, with_previous: bool = True) -> dict | None:
    st = store.get_setup(setup_id)
    if not st:
        return None
    laps = store.setup_laps(setup_id)
    prof = _profile_of(store, laps)
    best, typical = _times(laps)
    out = {"setup_id": setup_id, "laps": len(laps), "best_ms": best, "typical_ms": typical, "profile": prof,
           "suggestions": suggestions(prof, st["data"]) if laps else [],
           "conditions": _conditions(laps)}
    if with_previous:
        order = store.setups_in_use_order(st["track_id"])
        ids = [s["id"] for s in order]
        if setup_id in ids and ids.index(setup_id) > 0:
            prev = order[ids.index(setup_id) - 1]
            out["previous"] = compare(store, prev, st, out)
        out["history"] = [{"id": s["id"], "name": s["name"], "first_used": s["first_used"], "laps": s["laps"]} for s in order]
    return out


def _conditions(laps) -> dict:
    return {"tyres": sorted({l["tyre_visual"] for l in laps if l["tyre_visual"] is not None}),
            "weather": sorted({l["weather"] for l in laps if l["weather"] is not None}),
            "track_temp": round(statistics.mean([l["track_temp"] for l in laps if l["track_temp"] is not None]))
            if any(l["track_temp"] is not None for l in laps) else None,
            "categories": sorted({l["category"] for l in laps if l["category"]})}


def compare(store, prev: dict, cur: dict, cur_report: dict) -> dict:
    """What changed from the setup driven before this one, and what it did."""
    a, b = prev["data"] or {}, cur["data"] or {}
    changes = [{"key": k, "label": LABELS[k], "from": fmt_value(k, a.get(k)), "to": fmt_value(k, b.get(k))}
               for k in LABELS if fmt_value(k, a.get(k)) != fmt_value(k, b.get(k))]
    rep = setup_report(store, prev["id"], with_previous=False)
    pa, pb = rep["profile"], cur_report["profile"]
    effects = []
    for grp, names in (("bands", ("slow", "medium", "fast")), ("phases", ("entry", "mid", "exit"))):
        for k in names:
            u0, u1 = pa[grp][k]["us"], pb[grp][k]["us"]
            if u0 is not None and u1 is not None and abs(u1 - u0) >= 0.3:
                label = f"{k} corners" if grp == "bands" else {"entry": "corner entry", "mid": "mid-corner", "exit": "corner exit"}[k]
                effects.append({"what": label, "from": u0, "to": u1, "text": f"{label[0].upper() + label[1:]}: {_shift(u0, u1)} ({u0:+.1f}° → {u1:+.1f}°)"})
    for k, label in (("spin_pct", "wheelspin out of slow corners"), ("lock_pct", "lock-ups under braking")):
        v0, v1 = pa[k], pb[k]
        if v0 is not None and v1 is not None and abs(v1 - v0) >= 3:
            effects.append({"what": label, "from": v0, "to": v1, "text": f"{label}: {v0:.0f}% → {v1:.0f}%"})
    for k, label in (("ts_f", "front tyres"), ("ts_r", "rear tyres")):
        v0, v1 = pa[k], pb[k]
        if v0 is not None and v1 is not None and abs(v1 - v0) >= 3:
            effects.append({"what": label, "from": v0, "to": v1, "text": f"{label}: {v0:.0f}°C → {v1:.0f}°C"})
    caveats = []
    ca, cb = rep["conditions"], cur_report["conditions"]
    if ca["tyres"] != cb["tyres"]:
        caveats.append("different tyres")
    if ca["weather"] != cb["weather"]:
        caveats.append("different weather")
    if ca["track_temp"] is not None and cb["track_temp"] is not None and abs(ca["track_temp"] - cb["track_temp"]) >= 5:
        caveats.append(f"track {ca['track_temp']}°C → {cb['track_temp']}°C")
    if ca["categories"] != cb["categories"]:
        caveats.append("different session types (fuel loads)")
    return {"id": prev["id"], "name": prev["name"], "laps": rep["laps"], "best_ms": rep["best_ms"], "typical_ms": rep["typical_ms"],
            "changes": changes, "effects": effects, "caveats": caveats,
            "best_delta_ms": cur_report["best_ms"] - rep["best_ms"] if cur_report["best_ms"] and rep["best_ms"] else None,
            "typical_delta_ms": cur_report["typical_ms"] - rep["typical_ms"] if cur_report["typical_ms"] and rep["typical_ms"] else None}


def _balance_word(u) -> str:
    return "understeer" if u >= 0.25 else "oversteer" if u <= -0.25 else "neutral"


def _shift(u0, u1) -> str:
    """'more oversteer', 'understeer → neutral', ... for a balance change."""
    w0, w1 = _balance_word(u0), _balance_word(u1)
    if w0 != w1:
        return f"{w0} → {w1}"
    if w0 == "neutral":
        return "more to the oversteer side" if u1 < u0 else "more to the understeer side"
    return f"{'more' if abs(u1) > abs(u0) else 'less'} {w0}"
