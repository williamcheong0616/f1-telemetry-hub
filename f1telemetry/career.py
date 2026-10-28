"""Career and championship seasons rebuilt from recorded sessions.

The Session packet carries link identifiers that persist across saves: one for the season, one per
race weekend and one per session. Sessions that share a season link are grouped into a season and
their weekends into rounds. Standings come from the Final Classification of every race the app
recorded; sessions the game simulates send no UDP data, so they can't be counted.
"""
from __future__ import annotations

from collections import Counter

from .constants import CAREER_MODES, CHAMPIONSHIP_MODES, GAME_MODES, MY_TEAM_MODES, TEAMS, TRACKS, name_or

RETIRED = {4, 5, 6, 7}           # DNF, DSQ, not classified, retired
MAIN_QUALI = set(range(5, 10))   # Q1-Q3, short and one-shot qualifying (not the sprint shootout)


def driver_key(r: dict) -> str:
    """Stable identity for a driver across the sessions of a season."""
    if r.get("is_player"):
        return "you"
    did = r.get("driver_id")
    if did is not None and did not in (255, 65535) and r.get("ai", 1):  # 65535 = network human (2026)
        return f"d{did}"
    return "n" + str(r.get("name") or r.get("idx"))


def _status_text(code) -> str | None:
    return {4: "DNF", 5: "DSQ", 6: "NC", 7: "Ret"}.get(code)


def _dedupe(sessions: list[dict]) -> list[dict]:
    """A restarted session gets a new UID but keeps its session link: keep the attempt that counts."""
    by_link: dict = {}
    order = []
    for s in sessions:
        key = s.get("session_link") or f"id{s['id']}"
        if key not in by_link:
            order.append(key)
            by_link[key] = s
            continue
        cur = by_link[key]
        if s.get("results") or not cur.get("results"):
            by_link[key] = s
    return [by_link[k] for k in order]


def group_seasons(rows: list[dict]) -> dict[int, list[dict]]:
    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["season_link"], []).append(r)
    out = {}
    for link, sessions in groups.items():
        modes = {s["game_mode"] for s in sessions}
        weekends = {s["weekend_link"] for s in sessions if s["weekend_link"]}
        if modes & (CAREER_MODES | CHAMPIONSHIP_MODES) or len(weekends) > 1:
            out[link] = sessions
    return out


def _weekends(sessions: list[dict]) -> list[list[dict]]:
    wk: dict = {}
    for s in sessions:  # already chronological
        key = s.get("weekend_link") or f"{s['track_id']}|{(s['started_at'] or '')[:10]}"
        wk.setdefault(key, []).append(s)
    return list(wk.values())


def _session_brief(s: dict) -> dict:
    return {k: s.get(k) for k in ("id", "session_type", "category", "started_at", "final_position",
                                  "grid_position", "points", "result_status", "best_lap_ms", "laps_completed")}


def build_season(link: int, sessions: list[dict], meta: dict | None = None) -> dict:
    sessions = sorted(sessions, key=lambda s: (s["started_at"] or "", s["id"]))
    modes = Counter(s["game_mode"] for s in sessions if s["game_mode"] is not None)
    mode = modes.most_common(1)[0][0] if modes else None
    last = sessions[-1]
    my_team = mode in MY_TEAM_MODES or bool(last.get("my_team"))

    drivers: dict[str, dict] = {}
    teams: dict = {}
    rounds = []
    progression_rounds = []
    for wk in _weekends(sessions):
        wk = _dedupe(wk)
        n = len(rounds) + 1
        races = [s for s in wk if s["category"] == "race"]
        race_types = sorted({s["session_type"] for s in races})
        main_type = race_types[-1] if race_types else None
        rnd = {
            "round": n, "weekend_link": wk[0].get("weekend_link"), "track_id": wk[0]["track_id"],
            "track": name_or(TRACKS, wk[0]["track_id"], "Track "), "started_at": wk[0]["started_at"],
            "sessions": [_session_brief(s) for s in wk], "quali": None, "sprint": None, "race": None,
            "points": 0, "pole": False,
        }
        quali = [s for s in wk if s["session_type"] in MAIN_QUALI and s.get("final_position")]
        if quali:
            rnd["quali"] = quali[-1]["final_position"]
        for s in races:
            results = s.get("results") or []
            if not results:
                continue
            sprint = s["session_type"] != main_type
            fastest = min((r["best_lap_ms"] for r in results if r.get("best_lap_ms")), default=None)
            for r in results:
                key = driver_key(r)
                d = drivers.setdefault(key, {
                    "key": key, "name": r.get("name"), "team_id": r.get("team_id"), "my_team": r.get("my_team"),
                    "is_player": bool(r.get("is_player")), "points": 0, "wins": 0, "podiums": 0, "poles": 0,
                    "fastest_laps": 0, "dnfs": 0, "sprint_wins": 0, "starts": 0, "finishes": Counter(), "results": {}})
                d.update(name=r.get("name") or d["name"], team_id=r.get("team_id"), my_team=r.get("my_team"))
                pts = r.get("points") or 0
                d["points"] += pts
                status = r.get("result_status")
                fl = bool(fastest and r.get("best_lap_ms") == fastest)
                cell = d["results"].setdefault(n, {"points": 0})
                cell["points"] += pts
                if sprint:
                    cell["sprint"] = _status_text(status) or r.get("position")
                    d["sprint_wins"] += r.get("position") == 1 and status not in RETIRED
                else:
                    d["starts"] += 1
                    cell["race"] = _status_text(status) or r.get("position")
                    cell["fl"] = fl
                    cell["pole"] = r.get("grid") == 1
                    if status in RETIRED:
                        d["dnfs"] += 1
                    else:
                        d["finishes"][r.get("position")] += 1
                        d["wins"] += r.get("position") == 1
                        d["podiums"] += (r.get("position") or 99) <= 3
                    d["poles"] += r.get("grid") == 1
                    d["fastest_laps"] += fl
                t = teams.setdefault(r.get("team_id"), {"team_id": r.get("team_id"), "my_team": r.get("my_team"),
                                                        "points": 0, "wins": 0, "podiums": 0, "drivers": set()})
                t["points"] += pts
                t["drivers"].add(key)
                if not sprint and status not in RETIRED:
                    t["wins"] += r.get("position") == 1
                    t["podiums"] += (r.get("position") or 99) <= 3
                if r.get("is_player"):
                    rnd["points"] += pts
                    entry = {"session_id": s["id"], "position": r.get("position"), "grid": r.get("grid"),
                             "points": pts, "status": status, "status_text": _status_text(status),
                             "best_lap_ms": r.get("best_lap_ms"), "fastest_lap": fl}
                    if sprint:
                        rnd["sprint"] = entry
                    else:
                        rnd["race"] = entry
                        rnd["pole"] = r.get("grid") == 1
        if rnd["quali"] is None and rnd["race"]:
            rnd["quali"] = rnd["race"]["grid"]
        rounds.append(rnd)
        progression_rounds.append({k: d["points"] for k, d in drivers.items()})

    def countback(d):
        return (-d["points"], -d["wins"], *(-d["finishes"].get(p, 0) for p in range(2, 23)), d["name"] or "")

    standings = sorted(drivers.values(), key=countback)
    for i, d in enumerate(standings, 1):
        d["position"] = i
        d["finishes"] = dict(d["finishes"])
        d["team_name"] = "My Team" if d.get("my_team") else name_or(TEAMS, d["team_id"], "Team ")
        d["progression"] = [pr.get(d["key"], 0) for pr in progression_rounds]
    team_rows = sorted(teams.values(), key=lambda t: (-t["points"], -t["wins"]))
    for i, t in enumerate(team_rows, 1):
        t["position"] = i
        t["team_name"] = "My Team" if t.get("my_team") else name_or(TEAMS, t["team_id"], "Team ")
        t["drivers"] = [drivers[k]["name"] for k in sorted(t["drivers"], key=lambda k: -drivers[k]["points"])]

    me = drivers.get("you")
    raced = [r for r in rounds if r["race"]]
    classified = [r["race"]["position"] for r in raced if r["race"]["status"] not in RETIRED and r["race"]["position"]]
    grids = [r["race"]["grid"] for r in raced if r["race"]["grid"]]
    summary = {
        "championship_position": me["position"] if me else None, "drivers": len(standings),
        "points": me["points"] if me else 0, "leader_points": standings[0]["points"] if standings else 0,
        "wins": me["wins"] if me else 0, "podiums": me["podiums"] if me else 0,
        "poles": sum(1 for r in rounds if r["pole"]), "fastest_laps": me["fastest_laps"] if me else 0,
        "dnfs": me["dnfs"] if me else 0, "races": len(raced), "rounds": len(rounds),
        "best_finish": min(classified) if classified else None,
        "avg_finish": sum(classified) / len(classified) if classified else None,
        "avg_grid": sum(grids) / len(grids) if grids else None,
    }

    name = (meta or {}).get("name")
    team_name = "My Team" if my_team else name_or(TEAMS, last.get("team_id"), "Team ")
    return {
        "id": link, "season_link": link, "name": name,
        "default_name": f"{GAME_MODES.get(mode, 'Season')} · {team_name}",
        "notes": (meta or {}).get("notes"), "game_mode": mode, "mode_name": GAME_MODES.get(mode, ""),
        "my_team": my_team, "team_id": last.get("team_id"), "team_name": team_name,
        "player_name": last.get("player_name"), "game_year": last.get("game_year"),
        "first_at": sessions[0]["started_at"], "last_at": last["started_at"],
        "sessions": len(sessions), "summary": summary, "rounds": rounds,
        "standings": standings, "teams": team_rows, "head_to_head": _head_to_head(sessions, rounds),
    }


def _head_to_head(sessions: list[dict], rounds: list[dict]) -> dict | None:
    """You vs. the driver who most often shared your team in main races."""
    by_id = {s["id"]: s for s in sessions}
    mates: Counter = Counter()
    pairs = []
    for rnd in rounds:
        if not rnd["race"]:
            continue
        results = by_id[rnd["race"]["session_id"]].get("results") or []
        me = next((r for r in results if r.get("is_player")), None)
        if not me:
            continue
        mate = next((r for r in results if not r.get("is_player") and r.get("team_id") == me.get("team_id")), None)
        if mate:
            mates[driver_key(mate)] += 1
            pairs.append((me, mate))
    if not mates:
        return None
    key = mates.most_common(1)[0][0]
    out = {"name": None, "races": 0, "quali": [0, 0], "race": [0, 0], "points": [0, 0]}
    for me, mate in pairs:
        if driver_key(mate) != key:
            continue
        out["name"] = mate.get("name")
        out["races"] += 1
        if me.get("grid") and mate.get("grid"):
            out["quali"][0 if me["grid"] < mate["grid"] else 1] += 1
        me_out, mate_out = me.get("result_status") in RETIRED, mate.get("result_status") in RETIRED
        if not (me_out and mate_out):
            ahead = mate_out or (not me_out and me["position"] < mate["position"])
            out["race"][0 if ahead else 1] += 1
        out["points"][0] += me.get("points") or 0
        out["points"][1] += mate.get("points") or 0
    return out


def season_list(rows: list[dict], meta: dict) -> list[dict]:
    out = []
    for link, sessions in group_seasons(rows).items():
        s = build_season(link, sessions, meta.get(link))
        out.append({k: s[k] for k in ("id", "name", "default_name", "game_mode", "mode_name", "my_team", "team_id",
                                      "team_name", "player_name", "game_year", "first_at", "last_at",
                                      "sessions", "summary")}
                   | {"tracks": [r["track_id"] for r in s["rounds"]]})
    out.sort(key=lambda s: s["last_at"] or "", reverse=True)
    return out

