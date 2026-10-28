"""Race strategy: when to stop and on which tyres.

Reads how the fitted tyres are wearing and how the lap times are falling off in this race, takes the other
compounds' pace and life from the game's tyre-set data, then tries every one-stop and two-stop plan from the
lap being driven to the flag. The fuel burning off makes every plan quicker by the same amount, so it is taken
out of the lap times before fitting the drop-off and left out of the comparison.
"""
from __future__ import annotations

from .constants import VISUAL_COMPOUNDS

DRY = (16, 17, 18)  # visual compounds: soft, medium, hard
WET = (7, 8)
# used until this race has its own numbers: drop-off (s per lap of tyre age), pace (s slower than a new soft)
DEFAULT_DEG = {16: 0.085, 17: 0.055, 18: 0.035}
DEFAULT_PACE = {16: 0.0, 17: 0.35, 18: 0.7}
DEFAULT_LIFE = {16: 14, 17: 22, 18: 30}  # laps
DEFAULT_PIT_LOSS = 22.0  # s for the pit lane and the stop, against staying out
FUEL_S_PER_KG = 0.03
WEAR_LIMIT = 70.0  # % on the most worn tyre: past it the grip falls away
CLIFF_S = 0.4  # s per lap, growing each lap past the tyre's life
WINDOW_S = 1.0  # a pit lap within this of the best plan's time is "in the window"
MIN_FIT_LAPS = 3


def name(v) -> str:
    return VISUAL_COMPOUNDS.get(v, "?")


def _fit(xs, ys):
    """Least-squares line through (xs, ys): (intercept, slope)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return my, 0.0
    k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - k * mx, k


def clean_laps(laps: list[dict]) -> list[dict]:
    """Race laps that say something about pace: no lap 1, no in or out laps, nothing far off the pace."""
    rows = [l for l in laps if l.get("lap_time_ms") and l.get("lap_number", 0) > 1
            and (l.get("lap_type") or "flying") == "flying" and l.get("tyre_visual") is not None]
    if not rows:
        return []
    times = sorted(l["lap_time_ms"] for l in rows)
    med = times[len(times) // 2]
    return [l for l in rows if l["lap_time_ms"] <= med * 1.04]  # a spin, a safety car, traffic


def _wear_max(w):
    return max(w) if isinstance(w, (list, tuple)) and w and all(v is not None for v in w) else None


def model(laps: list[dict], current: dict, sets: list[dict]) -> dict:
    """Per dry compound: drop-off, pace, wear rate and life, each from this race, the game or a default."""
    clean = clean_laps(laps)
    out = {}
    by_c = {}
    for l in clean:
        by_c.setdefault(l["tyre_visual"], []).append(l)
    for c in DRY:
        m = {"visual": c, "name": name(c), "deg": None, "base": None, "wear_rate": None, "life": None, "source": "default"}
        rows = by_c.get(c, [])
        if len(rows) >= MIN_FIT_LAPS and all(r.get("tyre_age") is not None for r in rows):
            ages = [r["tyre_age"] for r in rows]
            ys = [r["lap_time_ms"] / 1000 - FUEL_S_PER_KG * (r.get("fuel_start") or 0) for r in rows]
            if max(ages) - min(ages) >= 2:
                base, k = _fit(ages, ys)
                m.update(deg=min(0.5, max(0.005, k)), base=base, source="this race")
        rates = []
        for r in rows:
            a, b = _wear_max(r.get("wear_start")), _wear_max(r.get("wear_end"))
            if a is not None and b is not None and b > a:
                rates.append(b - a)
        if len(rates) >= 2:
            rates.sort()
            m["wear_rate"] = rates[len(rates) // 2]
        out[c] = m
    # game data: usable life per compound, and pace from new sets' lap deltas (relative to each other)
    new_delta = {}
    for s in sets:
        c = s.get("visual")
        if c not in out:
            continue
        if s.get("usable_life"):
            out[c]["life"] = s["usable_life"]
        if (s.get("wear") or 0) == 0 and s.get("lap_delta_ms") is not None and not s.get("fitted"):
            new_delta.setdefault(c, s["lap_delta_ms"] / 1000)
    measured = [c for c in DRY if out[c]["base"] is not None]
    anchor = current.get("visual") if current.get("visual") in measured else (measured[0] if measured else None)
    # drop-off for compounds this race has not measured: the measured one's, scaled by the usual ratios
    for c in DRY:
        m = out[c]
        if m["deg"] is None:
            m["deg"] = out[anchor]["deg"] * DEFAULT_DEG[c] / DEFAULT_DEG[anchor] if anchor else DEFAULT_DEG[c]
        if m["life"] is None:
            m["life"] = DEFAULT_LIFE[c]
    # wear rates likewise
    wr = [c for c in DRY if out[c]["wear_rate"]]
    for c in DRY:
        if out[c]["wear_rate"] is None and wr:
            ref = wr[0]
            out[c]["wear_rate"] = out[ref]["wear_rate"] * DEFAULT_DEG[c] / DEFAULT_DEG[ref]
        if out[c]["wear_rate"]:  # the tyre's life is also where it reaches the wear limit
            out[c]["life"] = min(out[c]["life"], int(WEAR_LIMIT / out[c]["wear_rate"]))
    # pace: anchored on the measured compound, the rest from the game's deltas between new sets, else the usual gaps
    base0 = out[anchor]["base"] if anchor else 0.0
    use_game = anchor in new_delta and len(new_delta) >= 2 and any(abs(v) > 0.001 for v in new_delta.values())
    for c in DRY:
        m = out[c]
        if m["base"] is not None and c == anchor:
            m["pace_source"] = "this race"
            continue
        if use_game and c in new_delta:
            m["base"] = base0 + new_delta[c] - new_delta[anchor]
            m["pace_source"] = "game"
        else:
            m["base"] = base0 + DEFAULT_PACE[c] - (DEFAULT_PACE[anchor] if anchor else 0.0)
            m["pace_source"] = "default"
    return out


def stint_s(m: dict, age0: float, n: int, life: float | None = None) -> float:
    """Time for n laps on one set that starts at age0 (fuel left out)."""
    if n <= 0:
        return 0.0
    t = n * m["base"] + m["deg"] * (n * age0 + n * (n - 1) / 2)
    life = m["life"] if life is None else life
    over = age0 + n - life  # laps driven past the tyre's life
    if over > 0:
        k = min(over, n)
        t += CLIFF_S * k * (k + 1) / 2
    return t


def plan(laps: list[dict], current: dict, sets: list[dict], lap: int, total: int, stops_done: int = 0,
         used: set | None = None, pit_loss: float | None = None, pit_loss_source: str = "default") -> dict:
    """current: {visual, age, wear (max %)}; lap: the lap being driven; total: race laps.
    Returns the best plan for each number of stops, the window for the first stop and the model behind it."""
    out = {"available": False, "lap": lap, "total_laps": total, "laps_left": max(0, total - lap + 1)}
    cv = current.get("visual")
    if cv in WET:
        return {**out, "reason": "On intermediates or wets the weather decides the stops."}
    if cv not in DRY:
        return {**out, "reason": "Waiting for tyre data from the game."}
    if total - lap < 1:
        return {**out, "reason": "Last lap: no more stops to plan."}
    loss = DEFAULT_PIT_LOSS if pit_loss is None else pit_loss
    M = model(laps, current, sets)
    cm = M[cv]
    age = current.get("age") or 0
    # the fitted set's life from its own wear when we know how fast it wears
    cur_life = cm["life"]
    if current.get("wear") is not None and cm["wear_rate"]:
        cur_life = min(cur_life, age + max(0.0, (WEAR_LIMIT - current["wear"]) / cm["wear_rate"]))
    # the sets left, freshest first; a used set starts at the age its wear corresponds to
    avail = {}
    for s in sets:
        if s.get("available") and not s.get("fitted") and s.get("visual") in DRY:
            avail.setdefault(s["visual"], []).append(s.get("wear") or 0)
    for c in avail:
        avail[c].sort()
    age_of = lambda c, w: (w / M[c]["wear_rate"]) if M[c]["wear_rate"] else 0.0  # noqa: E731
    used = set(used or ()) | {cv}
    dry_race = all(c in DRY for c in used)
    rule = lambda cs: not dry_race or len((used | set(cs)) & set(DRY)) >= 2  # noqa: E731 - two dry compounds
    left = total - lap + 1  # laps to the flag, this one included

    plans = []
    if rule(()):
        plans.append({"stops": 0, "time": stint_s(cm, age, left, cur_life), "pits": [], "compounds": [cv]})
    best1, alls = {}, []
    for c, wears in avail.items():
        a1 = age_of(c, wears[0])
        if not rule((c,)):
            continue
        for p in range(lap, total):  # box at the end of lap p
            t = stint_s(cm, age, p - lap + 1, cur_life) + loss + stint_s(M[c], a1, total - p)
            if c not in best1 or t < best1[c]["time"]:
                best1[c] = {"stops": 1, "time": t, "pits": [p], "compounds": [cv, c]}
            alls.append((t, p, c))
    plans += best1.values()
    best2 = None
    for c2, w2 in avail.items():
        for c3, w3 in avail.items():
            if c2 == c3 and len(w2) < 2 or not rule((c2, c3)):
                continue
            a2, a3 = age_of(c2, w2[0]), age_of(c3, w3[1] if c2 == c3 else w3[0])
            for p1 in range(lap, total - 1):
                head = stint_s(cm, age, p1 - lap + 1, cur_life) + 2 * loss
                for p2 in range(p1 + 1, total):
                    t = head + stint_s(M[c2], a2, p2 - p1) + stint_s(M[c3], a3, total - p2)
                    if best2 is None or t < best2["time"]:
                        best2 = {"stops": 2, "time": t, "pits": [p1, p2], "compounds": [cv, c2, c3]}
    if best2:
        plans.append(best2)
    if not plans:
        return {**out, "reason": "No fresh sets left to plan a stop with."}
    plans.sort(key=lambda p: p["time"])
    top = plans[0]["time"]
    # the window: laps to box on for the best one-stop, within WINDOW_S of it
    win = None
    if alls:
        b = min(alls)
        laps_in = sorted(p for t, p, c in alls if c == b[2] and t <= b[0] + WINDOW_S)
        win = {"from": laps_in[0], "to": laps_in[-1], "best": b[1], "compound": b[2], "name": name(b[2])}
    shown = []
    for k in (0, 1, 2):  # the best plan for each number of stops, then the other one-stop compounds
        cand = [p for p in plans if p["stops"] == k]
        if cand:
            shown.append(cand[0])
    shown += [p for p in plans if p["stops"] == 1 and p not in shown]
    shown.sort(key=lambda p: p["time"])
    res = []
    for p in shown:
        bounds = [lap] + [x + 1 for x in p["pits"]] + [total + 1]
        stints = [{"visual": c, "name": name(c), "from": bounds[i], "to": bounds[i + 1] - 1, "laps": bounds[i + 1] - bounds[i]}
                  for i, c in enumerate(p["compounds"])]
        res.append({"stops": p["stops"], "pits": p["pits"], "stints": stints, "delta_s": round(p["time"] - top, 1),
                    "text": plan_text(p, stints)})
    over = None
    if cur_life is not None and age + left > cur_life:
        over = int(lap + max(0, cur_life - age))  # about where the fitted set is done
    return {**out, "available": True, "reason": None, "pit_loss_s": round(loss, 1), "pit_loss_source": pit_loss_source,
            "stops_done": stops_done, "used": sorted(used), "dry_rule": dry_race,
            "current": {"visual": cv, "name": name(cv), "age": age, "wear": current.get("wear"), "life_lap": over,
                        "deg": round(cm["deg"], 3), "wear_rate": round(cm["wear_rate"], 2) if cm["wear_rate"] else None},
            "compounds": [{"visual": c, "name": name(c), "deg": round(M[c]["deg"], 3), "pace": round(M[c]["base"] - M[cv]["base"], 2),
                           "life": M[c]["life"], "wear_rate": round(M[c]["wear_rate"], 2) if M[c]["wear_rate"] else None,
                           "sets": len(avail.get(c, [])), "source": M[c]["source"], "pace_source": M[c]["pace_source"]} for c in DRY],
            "window": win, "plans": res}


def plan_text(p, stints) -> str:
    if not p["stops"]:
        return f"No stop: {stints[0]['name'].lower()} to the flag."
    pits = " and ".join(str(x) for x in p["pits"])
    route = " → ".join(s["name"].lower() for s in stints)
    return f"{'One' if p['stops'] == 1 else 'Two'} stop{'s' if p['stops'] > 1 else ''}: {route}, box on lap{'s' if p['stops'] > 1 else ''} {pits}."


def measured_pit_loss(laps: list[dict]) -> float | None:
    """From this race's own stops: the in-lap and out-lap against the laps around them."""
    clean = [l["lap_time_ms"] for l in clean_laps(laps)]
    if len(clean) < 3:
        return None
    typical = sorted(clean)[len(clean) // 2] / 1000
    by_n = {l["lap_number"]: l for l in laps if l.get("lap_time_ms")}
    losses = []
    for l in laps:
        if l.get("lap_type") == "in" and l.get("lap_time_ms"):
            nxt = by_n.get(l["lap_number"] + 1)
            if nxt and nxt.get("lap_type") == "out":
                losses.append(l["lap_time_ms"] / 1000 + nxt["lap_time_ms"] / 1000 - 2 * typical)
    losses = [x for x in losses if 8 <= x <= 60]
    return sum(losses) / len(losses) if losses else None


def for_recorder(rec, pit_loss: float | None = None) -> dict:
    """The plan for the player's race as the recorder sees it now."""
    with rec.lock:
        s = dict(rec.session or {})
        pl = rec._player(rec.lap_data) or {}
        st = rec._player(rec.status) or {}
        dm = rec._player(rec.damage) or {}
        sets = list((rec.tyre_sets or {}).get("sets") or [])
        sid, category = rec.session_id, rec._category() if s else None
    if category != "race" or not s.get("total_laps") or not pl:
        return {"available": False, "reason": "The strategy helper works in races."}
    laps = rec.store.session_laps(sid) if sid else []
    used = {l["tyre_visual"] for l in laps if l.get("tyre_visual") is not None}
    measured = measured_pit_loss(laps)
    src = "given" if pit_loss is not None else "this race" if measured else "default"
    out = plan(laps, {"visual": st.get("visual_compound"), "age": st.get("tyre_age"), "wear": _wear_max(dm.get("tyre_wear"))},
               sets, pl.get("lap") or 1, s["total_laps"], pl.get("pit_stops") or 0, used,
               pit_loss if pit_loss is not None else measured, src)
    out["game_window"] = {"ideal": s.get("pit_window_ideal") or None, "latest": s.get("pit_window_latest") or None}
    out["measured_pit_loss_s"] = round(measured, 1) if measured else None
    return out
