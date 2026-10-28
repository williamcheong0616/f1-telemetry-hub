"""Corner coach and post-session debrief.

Every lap of a session is cut into the corners of its best lap (found the way the Telemetry page finds
them). For each corner and lap: braking point, lowest speed, line at the apex, where full throttle comes
back, exit speed and the time from entry to exit. Against the best lap that shows where a typical lap
loses time and why; the spread from lap to lap shows how consistent each corner is.
"""
from __future__ import annotations

import bisect
import math
import statistics
import threading
from collections import OrderedDict

from .engineer import corner_points, delta_say

MPH = 0.621371
MAX_LAP_FACTOR = 1.07     # laps slower than this times the best (traffic, safety car, a spin) are left out
MIN_LOSS_S = 0.05         # a corner has to cost at least this much to be worth a fix
MISTAKE_S = 0.6           # more than this in one corner on one of only two laps is a mistake, not a habit
CACHE_LAPS = 160

_cache: OrderedDict = OrderedDict()
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------- lap series
def prepare(cols: dict | None) -> dict | None:
    """The lap's samples with strictly increasing lap distance, as plain lists; tyre temperatures as
    front and rear averages (wheels come as RL, RR, FL, FR)."""
    if not cols:
        return None
    d = cols.get("d") or []
    keep, last = [], -1e9
    for i, v in enumerate(d):
        if v is None or v < 0 or v <= last:
            continue
        keep.append(i)
        last = v
    if len(keep) < 50:
        return None
    out = {}
    for k in ("d", "t", "spd", "thr", "brk", "str", "x", "z", "glat", "us", "lk", "ws"):
        src = cols.get(k)
        out[k] = [src[i] for i in keep] if src and len(src) == len(d) else None
    for k in ("ts", "ti"):
        w = cols.get(k)
        if w and len(w) == 4 and all(a and len(a) == len(d) for a in w):
            out[k + "_f"] = [_mean2(w[2][i], w[3][i]) for i in keep]
            out[k + "_r"] = [_mean2(w[0][i], w[1][i]) for i in keep]
    if out["t"] is None or out["spd"] is None:
        return None
    return out


def _mean2(a, b):
    return None if a is None or b is None else (a + b) / 2


def lap_series(store, lap_id: int) -> dict | None:
    """Prepared telemetry of a saved lap; kept in memory, since a lap never changes once saved."""
    key = (str(store.path), lap_id)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    p = prepare(store.get_lap_telemetry(lap_id))
    with _cache_lock:
        _cache[key] = p
        while len(_cache) > CACHE_LAPS:
            _cache.popitem(last=False)
    return p


def at(xs, ys, x):
    """ys at x, linear between samples; None outside the lap or across a gap in the data."""
    if ys is None or not xs or x < xs[0] or x > xs[-1]:
        return None
    i = bisect.bisect_left(xs, x)
    if i == 0:
        return ys[0]
    y0, y1 = ys[i - 1], ys[i]
    if y0 is None or y1 is None:
        return y1 if y0 is None else y0
    x0, x1 = xs[i - 1], xs[i]
    return y0 + (y1 - y0) * ((x - x0) / (x1 - x0) if x1 > x0 else 0)


def _pos(p, d):
    x, z = at(p["d"], p["x"], d), at(p["d"], p["z"], d)
    return None if x is None or z is None else (x, z)


def _heading(p, d):
    a, b = _pos(p, d - 4), _pos(p, d + 4)
    if not a or not b:
        return None
    hx, hz = b[0] - a[0], b[1] - a[1]
    n = math.hypot(hx, hz)
    return (hx / n, hz / n) if n > 0.5 else None


# ---------------------------------------------------------------------- corners
def corner_stats(p, d, lo, hi) -> dict:
    """Braking point, apex (lowest speed), full-throttle point, exit speed and time of one lap in one corner."""
    ds, spd, brk, thr = p["d"], p["spd"], p["brk"], p["thr"]
    apex = vmin = None
    k0 = bisect.bisect_left(ds, d - 90)
    for k in range(k0, len(ds)):
        if ds[k] > d + 90:
            break
        if spd[k] is not None and (vmin is None or spd[k] < vmin):
            vmin, apex = spd[k], ds[k]
    brake = throttle = None
    if apex is not None and brk:
        for k in range(max(1, bisect.bisect_left(ds, lo)), len(ds)):
            if ds[k] > apex:
                break
            if (brk[k] or 0) > 10 and not (brk[k - 1] or 0) > 10:
                brake = ds[k]
                break
    if apex is not None and thr:
        for k in range(bisect.bisect_right(ds, apex), len(ds)):
            if ds[k] > hi + 150:
                break
            if (thr[k] or 0) >= 90:
                throttle = ds[k]
                break
    t0, t1 = at(ds, p["t"], lo), at(ds, p["t"], hi)
    return {"apex": apex, "min": vmin, "brake": brake, "throttle": throttle, "exit": at(ds, spd, hi),
            "time": None if t0 is None or t1 is None else t1 - t0, "line": None}


def line_offset(ref, lap, apex_d, d) -> float | None:
    """Metres the lap ran from the reference's line at the reference's apex: + wider, - tighter."""
    if ref["x"] is None or lap["x"] is None:
        return None
    o, hd, q = _pos(ref, apex_d), _heading(ref, apex_d), _pos(lap, apex_d)
    h_in, h_out = _heading(ref, d - 40), _heading(ref, d + 40)
    if not (o and hd and q and h_in and h_out):
        return None
    off = hd[1] * (q[0] - o[0]) - hd[0] * (q[1] - o[1])
    turn = h_in[1] * h_out[0] - h_in[0] * h_out[1]
    if abs(off) < 0.25 or abs(turn) < 0.05:
        return 0.0
    # either sign convention of the game's coordinates flips both, so comparing them is safe
    return (-1 if (off > 0) == (turn > 0) else 1) * abs(off)


def _median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def _spread(vals):
    vals = [v for v in vals if v is not None]
    return statistics.pstdev(vals) if len(vals) >= 3 else None


# ---------------------------------------------------------------------- session analysis
def coachable_laps(laps: list[dict], category: str | None) -> list[dict]:
    """Complete flying laps with telemetry, without the race start or anything far off the pace."""
    out = [l for l in laps if (l.get("lap_time_ms") or 0) > 0 and l.get("sample_count") and l.get("telemetry_complete")
           and (l.get("lap_type") or "flying") == "flying" and not (category == "race" and l.get("lap_number") == 1)]
    best = min((l["lap_time_ms"] for l in out if l.get("valid")), default=None)
    if best is None:
        return []
    return [l for l in out if l["lap_time_ms"] <= best * MAX_LAP_FACTOR]


def analyse_session(store, sid: int, ref_lap_id: int | None = None, mph: bool = False) -> dict | None:
    """Corner by corner: where a typical lap of the session loses time against the reference (by default
    the session's best lap) and why, how consistent each corner is, and the three fixes worth most."""
    s = store.get_session(sid)
    if not s:
        return None
    laps = coachable_laps(store.session_laps(sid), s.get("category"))
    out = {"session_id": sid, "track_id": s.get("track_id"), "category": s.get("category"),
           "laps_used": [l["id"] for l in laps], "corners": [], "fixes": [], "ref": None, "unit": "mph" if mph else "km/h"}
    valid = sorted((l for l in laps if l.get("valid")), key=lambda l: l["lap_time_ms"])
    ref_row = store.get_lap(ref_lap_id) if ref_lap_id else (valid[0] if valid else None)
    if not ref_row or (ref_lap_id and ref_row.get("track_id") != s.get("track_id")):
        out["note"] = "Needs at least one complete valid lap."
        return out
    ref = lap_series(store, ref_row["id"])
    if not ref:
        out["note"] = "The reference lap has no telemetry."
        return out
    series = {}
    for l in laps:
        p = lap_series(store, l["id"])
        if p:
            series[l["id"]] = (l, p)
    others = [lid for lid in series if lid != ref_row["id"]]
    out["ref"] = {"id": ref_row["id"], "lap_number": ref_row.get("lap_number"), "lap_time_ms": ref_row["lap_time_ms"],
                  "session_id": ref_row.get("session_id"), "same_session": ref_row.get("session_id") == sid,
                  "guest": bool(ref_row.get("guest")), "driver": ref_row.get("driver")}
    out["laps"] = [{"id": l["id"], "lap_number": l["lap_number"], "lap_time_ms": l["lap_time_ms"], "valid": l["valid"]}
                   for l, _ in series.values()]
    times = [l["lap_time_ms"] for l, _ in series.values() if l.get("valid")]
    out["lap_spread_ms"] = round(statistics.pstdev(times)) if len(times) >= 3 else None
    out["typical_ms"] = round(statistics.median(times)) if times else None
    conv = MPH if mph else 1.0

    pts = corner_points({"d": ref["d"], "spd": ref["spd"]})
    ideal_gain = 0.0
    for name, d, lo, hi in pts:
        r = corner_stats(ref, d, lo, hi)
        if r["time"] is None:
            continue
        per = {}
        for lid, (l, p) in series.items():
            st = r if lid == ref_row["id"] else corner_stats(p, d, lo, hi)
            if lid != ref_row["id"] and r["apex"] is not None:
                st["line"] = line_offset(ref, p, r["apex"], d)
            per[lid] = st
        diffs = [per[lid] for lid in others if per[lid]["time"] is not None]
        loss = _median([st["time"] - r["time"] for st in diffs])
        best_lid = min((lid for lid in per if per[lid]["time"] is not None), key=lambda lid: per[lid]["time"], default=None)
        best_gain = r["time"] - per[best_lid]["time"] if best_lid is not None else 0.0
        if best_lid is not None and best_gain > 0.005 and series[best_lid][0].get("valid"):
            ideal_gain += best_gain
        rel = lambda k: _median([st[k] - r[k] for st in diffs if st[k] is not None and r[k] is not None])
        c = {
            "name": name, "n": int(name[1:]), "d": round(d), "lo": round(lo), "hi": round(hi), "laps": len(diffs),
            "ref": {"time": r["time"], "brake": r["brake"], "min": _cv(r["min"], conv), "throttle": r["throttle"],
                    "exit": _cv(r["exit"], conv), "apex": r["apex"]},
            "loss_s": loss,
            "brake_m": rel("brake"), "min_v": _cv(rel("min"), conv), "throttle_m": rel("throttle"),
            "exit_v": _cv(rel("exit"), conv), "line_m": _median([st["line"] for st in diffs]),
            "spread": {"brake_m": _spread([st["brake"] for st in per.values()]),
                       "min_v": _cv(_spread([st["min"] for st in per.values()]), conv),
                       "throttle_m": _spread([st["throttle"] for st in per.values()]),
                       "time_s": _spread([st["time"] for st in per.values()])},
            "best": {"lap_id": best_lid, "lap_number": series[best_lid][0]["lap_number"], "gain_s": best_gain}
            if best_lid is not None and best_lid != ref_row["id"] and best_gain > 0.005 else None,
            "per_lap": {lid: {"time": st["time"], "brake": st["brake"], "min": _cv(st["min"], conv),
                              "throttle": st["throttle"], "exit": _cv(st["exit"], conv), "line": st["line"]}
                        for lid, st in per.items()},
        }
        c["text"], c["say"], c["detail"] = fix_text(c, mph)
        out["corners"].append(c)
    out["ideal_ms"] = round(ref_row["lap_time_ms"] - ideal_gain * 1000) if out["corners"] else None
    ranked = sorted((c for c in out["corners"] if c["loss_s"] is not None and c["loss_s"] >= MIN_LOSS_S),
                    key=lambda c: -c["loss_s"])
    out["fixes"] = [{"name": c["name"], "n": c["n"], "loss_s": c["loss_s"], "text": c["text"], "say": c["say"], "detail": c["detail"]}
                    for c in ranked[:3]]
    loose = sorted((c for c in out["corners"] if c["spread"]["time_s"] is not None), key=lambda c: -c["spread"]["time_s"])
    out["least_consistent"] = [c["name"] for c in loose[:3] if c["spread"]["time_s"] >= 0.05]
    out["total_loss_s"] = sum(c["loss_s"] for c in out["corners"] if c["loss_s"] and c["loss_s"] > 0)
    return out


def _cv(v, conv):
    return None if v is None else v * conv


def fix_text(c: dict, mph: bool = False) -> tuple[str, str, str]:
    """What a typical lap does differently from the best one in this corner: (text, speech, the text without
    the corner and the time lost)."""
    unit = "mph" if mph else "km/h"
    b, m, th, ex, ln = c["brake_m"], c["min_v"], c["throttle_m"], c["exit_v"], c["line_m"]
    m_thr = 2 if mph else 3
    parts, causes = [], []
    over = b is not None and b >= 5 and m is not None and m <= -m_thr
    if b is not None and b <= -5:
        parts.append(f"brake {round(-b)} m earlier than on your best lap")
        causes.append(f"You're braking {round(-b)} metres early.")
    elif over:
        parts.append(f"brake {round(b)} m later but carry {round(-m)} {unit} less through the apex, so the entry is overdriven")
        causes.append(f"You're braking {round(b)} metres later and losing {round(-m)} {unit} at the apex. Don't overdrive it.")
    elif b is not None and b >= 5:
        parts.append(f"brake {round(b)} m later")
        causes.append(f"You're braking {round(b)} metres later.")
    if m is not None and m <= -m_thr and not over:
        parts.append(f"are {round(-m)} {unit} slower at the apex")
        causes.append(f"{round(-m)} {unit} down at the apex.")
    if ln is not None and abs(ln) >= 1.0:
        parts.append(f"run {abs(ln):.1f} m {'wider' if ln > 0 else 'tighter'} through the apex")
        causes.append(f"You're {abs(ln):.1f} metres {'wide' if ln > 0 else 'tight'} at the apex.")
    if th is not None and th >= 8:
        parts.append(f"are back on full throttle {round(th)} m later")
        causes.append(f"Full throttle {round(th)} metres later.")
    if ex is not None and ex <= -(3 if mph else 4) and not (th is not None and th >= 8):
        parts.append(f"exit {round(-ex)} {unit} slower")
        causes.append(f"Exit speed {round(-ex)} {unit} down.")
    loss, n = c["loss_s"], c["laps"]
    typical = "on a typical lap" if n >= 3 else "on your other lap" if n == 1 else "on your other laps"
    head = f"Corner {c['n']}: losing {loss:.2f} s {typical}." if loss is not None and loss > 0 else f"Corner {c['n']}:"
    if parts:
        body = "You " + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]) + "."
        if m is not None and abs(m) < m_thr and not over:
            body += " Your minimum speed is fine."
    elif loss is not None and loss >= MIN_LOSS_S:
        body = "Nothing stands out: the time goes all through the corner. Compare the traces on the Telemetry page."
    else:
        body = "As quick as your best lap."
    if loss is not None and loss >= MISTAKE_S and n <= 2:
        body += " That looks like a mistake (an off or a spin) more than a habit."
    sp = c["spread"]["brake_m"]
    if sp is not None and sp >= 8:
        body += f" Your braking point varies by ±{round(sp)} m from lap to lap."
    say = f"Corner {c['n']}, {delta_say(loss)}. " + (causes[0] if causes else "The time is all through the corner.") \
        if loss is not None and loss > 0 else ""
    return f"{head} {body}", say, body
