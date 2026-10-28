"""SQLite persistence for sessions, laps, lap telemetry, setups, events and track maps."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import zlib
from datetime import datetime
from pathlib import Path

from . import micro as micro_mod

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    session_uid TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    game_year INTEGER,
    packet_format INTEGER,
    track_id INTEGER,
    track_length INTEGER,
    session_type INTEGER,
    category TEXT,
    formula INTEGER,
    game_mode INTEGER,
    rule_set INTEGER,
    season_link INTEGER,
    weekend_link INTEGER,
    session_link INTEGER,
    my_team INTEGER,
    weekend_structure TEXT,
    time_trial TEXT,
    network_game INTEGER,
    ai_difficulty INTEGER,
    weather INTEGER,
    track_temp INTEGER,
    air_temp INTEGER,
    total_laps INTEGER,
    player_name TEXT,
    team_id INTEGER,
    laps_completed INTEGER DEFAULT 0,
    best_lap_ms INTEGER,
    best_lap_id INTEGER,
    final_position INTEGER,
    grid_position INTEGER,
    points INTEGER,
    result_status INTEGER,
    distance_m REAL DEFAULT 0,
    drive_time_s REAL DEFAULT 0,
    assists TEXT,
    start_reaction REAL,
    results TEXT,
    drivers TEXT,
    history TEXT,
    positions TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_track ON sessions(track_id, category);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);

CREATE TABLE IF NOT EXISTS laps (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    lap_number INTEGER NOT NULL,
    recorded_at TEXT,
    track_id INTEGER,
    category TEXT,
    lap_time_ms INTEGER,
    s1_ms INTEGER,
    s2_ms INTEGER,
    s3_ms INTEGER,
    valid INTEGER DEFAULT 1,
    lap_type TEXT,
    position INTEGER,
    tyre_visual INTEGER,
    tyre_actual INTEGER,
    tyre_age INTEGER,
    wear_start TEXT,
    wear_end TEXT,
    fuel_start REAL,
    fuel_end REAL,
    ers_deployed REAL,
    ers_harvested REAL,
    ers_store_start REAL,
    ers_store_end REAL,
    top_speed REAL,
    avg_speed REAL,
    min_speed REAL,
    drs_activations INTEGER,
    aero_activations INTEGER,
    overtake_activations INTEGER,
    regs_2026 INTEGER,
    max_brake_temp INTEGER,
    max_tyre_temp INTEGER,
    weather INTEGER,
    track_temp INTEGER,
    air_temp INTEGER,
    setup_id INTEGER,
    damage TEXT,
    assists TEXT,
    sample_count INTEGER DEFAULT 0,
    telemetry_complete INTEGER DEFAULT 0,
    micro TEXT,
    UNIQUE(session_id, lap_number)
);
CREATE INDEX IF NOT EXISTS idx_laps_track ON laps(track_id, category, valid, lap_time_ms);

CREATE TABLE IF NOT EXISTS lap_telemetry (
    lap_id INTEGER PRIMARY KEY REFERENCES laps(id) ON DELETE CASCADE,
    data BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS setups (
    id INTEGER PRIMARY KEY,
    hash TEXT NOT NULL,
    track_id INTEGER,
    team_id INTEGER,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    created_at TEXT,
    name TEXT,
    notes TEXT,
    favorite INTEGER DEFAULT 0,
    data TEXT NOT NULL,
    UNIQUE(hash, track_id)
);

CREATE TABLE IF NOT EXISTS seasons (
    season_link INTEGER PRIMARY KEY,
    name TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    session_time REAL,
    lap INTEGER,
    code TEXT,
    text TEXT,
    data TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);

-- laps imported from friends' .f1lap files; the app shows them with negative ids (guest 3 is lap -3)
CREATE TABLE IF NOT EXISTS guest_laps (
    id INTEGER PRIMARY KEY,
    imported_at TEXT,
    driver TEXT,
    track_id INTEGER,
    category TEXT,
    lap_time_ms INTEGER,
    lap TEXT,
    setup TEXT,
    data BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS tracks (
    track_id INTEGER PRIMARY KEY,
    outline TEXT,
    length INTEGER,
    s2_start REAL,
    s3_start REAL,
    updated_at TEXT,
    frame TEXT
);
"""

# columns added after the first release; older databases get them via ALTER TABLE
MIGRATIONS = {
    "sessions": [("rule_set", "INTEGER"), ("season_link", "INTEGER"), ("weekend_link", "INTEGER"),
                 ("session_link", "INTEGER"), ("my_team", "INTEGER"), ("weekend_structure", "TEXT"),
                 ("time_trial", "TEXT"), ("start_reaction", "REAL")],
    "laps": [("aero_activations", "INTEGER"), ("overtake_activations", "INTEGER"), ("regs_2026", "INTEGER"),
             ("micro", "TEXT")],
    "tracks": [("frame", "TEXT")],
}

SESSION_COLUMNS = {
    "ended_at", "game_year", "packet_format", "track_id", "track_length", "session_type",
    "category", "formula", "game_mode", "rule_set", "season_link", "weekend_link", "session_link",
    "my_team", "weekend_structure", "time_trial", "network_game", "ai_difficulty", "weather", "track_temp",
    "air_temp", "total_laps", "player_name", "team_id", "laps_completed", "best_lap_ms",
    "best_lap_id", "final_position", "grid_position", "points", "result_status", "distance_m",
    "drive_time_s", "assists", "start_reaction", "results", "drivers", "history", "positions", "notes",
}

LAP_COLUMNS = (
    "lap_number", "recorded_at", "track_id", "category", "lap_time_ms", "s1_ms", "s2_ms", "s3_ms",
    "valid", "lap_type", "position", "tyre_visual", "tyre_actual", "tyre_age", "wear_start",
    "wear_end", "fuel_start", "fuel_end", "ers_deployed", "ers_harvested", "ers_store_start",
    "ers_store_end", "top_speed", "avg_speed", "min_speed", "drs_activations", "aero_activations",
    "overtake_activations", "regs_2026", "max_brake_temp",
    "max_tyre_temp", "weather", "track_temp", "air_temp", "setup_id", "damage", "assists",
    "sample_count", "telemetry_complete", "micro",
)

JSON_FIELDS = {"assists", "results", "drivers", "history", "positions", "wear_start", "wear_end",
               "damage", "data", "outline", "weekend_structure", "time_trial", "frame", "micro", "lap", "setup"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row(cur, row) -> dict:
    d = {}
    for i, col in enumerate(cur.description):
        v = row[i]
        if col[0] in JSON_FIELDS and isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                pass
        d[col[0]] = v
    return d


def encode_telemetry(columns: dict) -> bytes:
    return zlib.compress(json.dumps(columns, separators=(",", ":")).encode(), 6)


def decode_telemetry(blob: bytes) -> dict:
    return json.loads(zlib.decompress(blob))


# A Time Trial starts on a run-up (the car already at speed before the line) and "Restart lap" puts the
# car back on it: the lap timer stays at zero until the line and the lap number never changes, so the
# run-up and any abandoned attempt would end up in the lap. The lap really starts where the timer does.
TELEPORT_M = 80.0


def is_restart(prev, cur, dt=0.0) -> bool:
    """prev, cur: (lap time s, lap distance, x, z) of consecutive samples, dt seconds apart."""
    t0, d0, x0, z0 = prev
    t1, d1, x1, z1 = cur
    if None in (t0, d0, t1, d1) or t1 > 0.25:  # lap timer running (a flashback rewinds it, but not to zero)
        return False
    if t1 <= 0.05 and None not in (x0, z0, x1, z1) and \
            math.hypot(x1 - x0, z1 - z0) > TELEPORT_M + 100 * max(dt, 0.0):
        return True  # moved further than a car can: put back on the run-up
    # the run-up reaching the line (the timer starts), or a restart further back along it
    return t0 <= 0.05 and (d0 < 0 <= d1 or d1 < d0 - 40)


def drop_restarts(cols: dict) -> dict:
    """Lap telemetry from the last restart on (laps recorded before restarts were spotted live)."""
    t, d, x, z = (cols.get(k) or [] for k in ("t", "d", "x", "z"))
    if not len(t) == len(d) == len(x) == len(z):
        return cols
    start = 0
    for i in range(1, len(t)):
        dt = t[i] - t[i - 1] if t[i] is not None and t[i - 1] is not None else 0.0
        if is_restart((t[i - 1], d[i - 1], x[i - 1], z[i - 1]), (t[i], d[i], x[i], z[i]), dt):
            start = i
    if not start:
        return cols
    return {k: [w[start:] for w in v] if v and isinstance(v[0], list) else v[start:] for k, v in cols.items()}


def outline_from(cols: dict) -> list | None:
    """[[lap distance, x, z]] at least 8 m apart, for the track map."""
    pts, last = [], None
    for d, x, z in zip(cols.get("d", []), cols.get("x", []), cols.get("z", [])):
        if d is None or x is None or d < 0:
            continue
        if last is None or d - last >= 8:
            pts.append([round(d), round(x, 1), round(z, 1)])
            last = d
    return pts if len(pts) > 30 else None


def outline_ok(pts, length=None) -> bool:
    """Covers the whole lap without holes (a restart mid-lap used to leave one kilometres long)."""
    if not pts or len(pts) <= 30 or pts[0][0] > 150 or (length and pts[-1][0] < length - 200):
        return False
    return all(b[0] - a[0] <= 250 for a, b in zip(pts, pts[1:]))


def setup_hash(setup: dict) -> str:
    keyed = {k: round(v, 3) if isinstance(v, float) else v for k, v in setup.items() if k != "fuel_load"}
    return hashlib.sha1(json.dumps(keyed, sort_keys=True).encode()).hexdigest()[:16]


class Storage:
    def __init__(self, db_path: Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self):
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols:
                if name not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_season ON sessions(season_link, started_at)")

    # ------------------------------------------------------------------ helpers
    def _q(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            cur = self.db.execute(sql, args)
            return [_row(cur, r) for r in cur.fetchall()]

    def _q1(self, sql: str, args=()) -> dict | None:
        rows = self._q(sql, args)
        return rows[0] if rows else None

    def _exec(self, sql: str, args=()) -> int:
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    @staticmethod
    def _val(k, v):
        if k in JSON_FIELDS and v is not None and not isinstance(v, str):
            return json.dumps(v, separators=(",", ":"))
        return v

    def close(self):
        with self.lock:
            self.db.close()

    # ------------------------------------------------------------------ sessions
    def get_session_by_uid(self, uid: str) -> dict | None:
        return self._q1("SELECT id FROM sessions WHERE session_uid=?", (uid,))

    def create_session(self, uid: str, fields: dict) -> int:
        existing = self.get_session_by_uid(uid)
        if existing:
            self.update_session(existing["id"], fields)
            return existing["id"]
        sid = self._exec("INSERT INTO sessions(session_uid, started_at) VALUES (?, ?)", (uid, now_iso()))
        self.update_session(sid, fields)
        return sid

    def update_session(self, sid: int, fields: dict):
        cols = [k for k in fields if k in SESSION_COLUMNS]
        if not cols:
            return
        sql = "UPDATE sessions SET " + ", ".join(f"{c}=?" for c in cols) + " WHERE id=?"
        self._exec(sql, [self._val(c, fields[c]) for c in cols] + [sid])

    def delete_session(self, sid: int):
        self._exec("DELETE FROM sessions WHERE id=?", (sid,))

    def delete_empty_session(self, sid: int):
        with self.lock:
            row = self.db.execute(
                "SELECT (SELECT COUNT(*) FROM laps WHERE session_id=?), results FROM sessions WHERE id=?",
                (sid, sid)).fetchone()
            if row and row[0] == 0 and not row[1]:
                self.db.execute("DELETE FROM sessions WHERE id=?", (sid,))
                self.db.commit()
                return True
        return False

    def list_sessions(self, track_id=None, category=None, limit=200, offset=0, game_modes=None) -> list[dict]:
        where, args = [], []
        if track_id is not None:
            where.append("track_id=?")
            args.append(track_id)
        if category:
            where.append("category=?")
            args.append(category)
        if game_modes is not None:
            where.append("game_mode IN (" + ",".join("?" * len(game_modes)) + ")" if game_modes else "0")
            args.extend(game_modes)
        sql = ("SELECT id, session_uid, started_at, ended_at, game_year, track_id, track_length, "
               "session_type, category, formula, game_mode, rule_set, season_link, weekend_link, my_team, "
               "network_game, ai_difficulty, weather, "
               "track_temp, air_temp, total_laps, player_name, team_id, laps_completed, best_lap_ms, "
               "best_lap_id, final_position, grid_position, points, result_status, distance_m, "
               "drive_time_s, notes FROM sessions")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?"
        return self._q(sql, args + [limit, offset])

    def get_session(self, sid: int) -> dict | None:
        return self._q1("SELECT * FROM sessions WHERE id=?", (sid,))

    # ------------------------------------------------------------------ laps
    def save_lap(self, session_id: int, lap: dict, telemetry: dict | None) -> int:
        cols = [c for c in LAP_COLUMNS if c in lap]
        with self.lock:
            self.db.execute("DELETE FROM laps WHERE session_id=? AND lap_number=?",
                            (session_id, lap["lap_number"]))
            cur = self.db.execute(
                "INSERT INTO laps(session_id, " + ", ".join(cols) + ") VALUES (?" + ", ?" * len(cols) + ")",
                [session_id] + [self._val(c, lap[c]) for c in cols])
            lap_id = cur.lastrowid
            if telemetry:
                self.db.execute("INSERT INTO lap_telemetry(lap_id, data) VALUES (?, ?)",
                                (lap_id, encode_telemetry(telemetry)))
            self.db.commit()
        return lap_id

    def update_lap(self, lap_id: int, fields: dict):
        cols = [k for k in fields if k in LAP_COLUMNS]
        if cols:
            self._exec("UPDATE laps SET " + ", ".join(f"{c}=?" for c in cols) + " WHERE id=?",
                       [self._val(c, fields[c]) for c in cols] + [lap_id])

    def delete_laps_from(self, session_id: int, lap_number: int):
        self._exec("DELETE FROM laps WHERE session_id=? AND lap_number>=?", (session_id, lap_number))

    def session_laps(self, sid: int) -> list[dict]:
        return self._q("SELECT * FROM laps WHERE session_id=? ORDER BY lap_number", (sid,))

    def get_lap(self, lap_id: int) -> dict | None:
        if lap_id < 0:
            return self.get_guest_lap(-lap_id)
        return self._q1(
            "SELECT l.*, s.session_type, s.started_at, s.player_name, s.team_id, s.game_year "
            "FROM laps l JOIN sessions s ON s.id = l.session_id WHERE l.id=?", (lap_id,))

    def get_lap_telemetry(self, lap_id: int) -> dict | None:
        with self.lock:
            if lap_id < 0:
                row = self.db.execute("SELECT data FROM guest_laps WHERE id=?", (-lap_id,)).fetchone()
            else:
                row = self.db.execute("SELECT data FROM lap_telemetry WHERE lap_id=?", (lap_id,)).fetchone()
        return drop_restarts(decode_telemetry(row[0])) if row else None

    # ------------------------------------------------------------------ friends' laps
    def add_guest_lap(self, driver: str, lap: dict, setup: dict | None, cols: dict) -> int:
        gid = self._exec(
            "INSERT INTO guest_laps (imported_at, driver, track_id, category, lap_time_ms, lap, setup, data) VALUES (?,?,?,?,?,?,?,?)",
            (now_iso(), driver, lap["track_id"], lap.get("category"), lap["lap_time_ms"], json.dumps(lap),
             json.dumps(setup) if setup else None, encode_telemetry(cols)))
        return -gid

    def _guest(self, row: dict) -> dict:
        lap = row.pop("lap") or {}
        out = {**lap, **row, "id": -row["id"], "guest": True, "session_id": None, "player_name": row["driver"],
               "started_at": lap.get("recorded_at"), "sample_count": 1, "telemetry_complete": 1}
        out.setdefault("valid", 1)
        out.setdefault("lap_number", 0)
        return out

    def guest_laps(self, track_id: int | None = None) -> list[dict]:
        sql = "SELECT id, imported_at, driver, track_id, category, lap_time_ms, lap FROM guest_laps"
        rows = self._q(sql + (" WHERE track_id=?" if track_id is not None else "") + " ORDER BY track_id, lap_time_ms",
                       (track_id,) if track_id is not None else ())
        return [self._guest(r) for r in rows]

    def get_guest_lap(self, gid: int) -> dict | None:
        row = self._q1("SELECT id, imported_at, driver, track_id, category, lap_time_ms, lap, setup FROM guest_laps WHERE id=?", (gid,))
        return self._guest(row) if row else None

    def delete_guest_lap(self, gid: int):
        self._exec("DELETE FROM guest_laps WHERE id=?", (gid,))

    def refresh_session_summary(self, sid: int):
        with self.lock:
            row = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(lap_time_ms),0) FROM laps WHERE session_id=? AND lap_time_ms>0",
                (sid,)).fetchone()
            best = self.db.execute(
                "SELECT id, lap_time_ms FROM laps WHERE session_id=? AND valid=1 AND lap_time_ms>0 "
                "ORDER BY lap_time_ms LIMIT 1", (sid,)).fetchone()
            length = self.db.execute("SELECT track_length FROM sessions WHERE id=?", (sid,)).fetchone()
            self.db.execute(
                "UPDATE sessions SET laps_completed=?, drive_time_s=?, distance_m=?, best_lap_ms=?, "
                "best_lap_id=? WHERE id=?",
                (row[0], row[1] / 1000.0, row[0] * ((length[0] if length else 0) or 0),
                 best[1] if best else None, best[0] if best else None, sid))
            self.db.commit()

    def best_reference_lap(self, track_id: int, category: str, regs_2026=None) -> dict | None:
        """Fastest complete valid lap; with regs_2026 set, only laps in cars of the same generation."""
        sql = ("SELECT l.id, l.lap_time_ms FROM laps l WHERE l.track_id=? AND l.category=? AND l.valid=1 "
               "AND l.telemetry_complete=1 AND l.lap_time_ms>0")
        args = [track_id, category]
        if regs_2026 is not None:
            sql += " AND COALESCE(l.regs_2026, 0)=?"
            args.append(1 if regs_2026 else 0)
        return self._q1(sql + " ORDER BY l.lap_time_ms LIMIT 1", args)

    def micro_records(self, track_id: int, category: str, regs_2026, bnds) -> tuple:
        """(record per micro-sector, the reference lap's micro-sectors, its lap time) over the valid laps.

        Laps recorded before micro-sectors existed (or with other boundaries) are timed from their
        telemetry once and the result is stored with the lap.
        """
        key = micro_mod.key_of(bnds)
        n = len(bnds) - 1
        sql = ("SELECT id, lap_time_ms, micro FROM laps WHERE track_id=? AND category=? AND valid=1 "
               "AND telemetry_complete=1 AND lap_time_ms>0 AND COALESCE(lap_type, 'flying')='flying'")
        args = [track_id, category]
        if regs_2026 is not None:
            sql += " AND COALESCE(regs_2026, 0)=?"
            args.append(1 if regs_2026 else 0)
        best, ref, ref_ms = [None] * n, None, None
        for r in self._q(sql + " ORDER BY lap_time_ms", args):
            m = r["micro"]
            if not (isinstance(m, dict) and m.get("key") == key):
                cols = self.get_lap_telemetry(r["id"])
                m = {"key": key, "ms": micro_mod.times_from_cols(cols, bnds, r["lap_time_ms"]) if cols else None}
                self.update_lap(r["id"], {"micro": m})
            times = m.get("ms")
            if not times or len(times) != n:
                continue
            if ref is None and all(v is not None for v in times):
                ref, ref_ms = times, r["lap_time_ms"]  # the quickest lap with every micro-sector timed
            best = [v if b is None or (v is not None and v < b) else b for v, b in zip(times, best)]
        return best, ref, ref_ms

    def laps_for_track(self, track_id: int, category=None, valid_only=True, limit=500) -> list[dict]:
        sql = ("SELECT l.id, l.session_id, l.lap_number, l.lap_time_ms, l.s1_ms, l.s2_ms, l.s3_ms, "
               "l.valid, l.lap_type, l.tyre_visual, l.tyre_actual, l.recorded_at, l.category, "
               "l.telemetry_complete, l.top_speed, l.setup_id, l.weather, l.regs_2026, s.session_type, "
               "s.team_id, s.game_year FROM laps l JOIN sessions s ON s.id=l.session_id "
               "WHERE l.track_id=? AND l.lap_time_ms>0")
        args = [track_id]
        if category:
            sql += " AND l.category=?"
            args.append(category)
        if valid_only:
            sql += " AND l.valid=1"
        sql += " ORDER BY l.lap_time_ms LIMIT ?"
        args.append(limit)
        return self._q(sql, args)

    # ------------------------------------------------------------------ setups
    def save_setup(self, setup: dict, track_id, team_id, session_id) -> int:
        h = setup_hash(setup)
        existing = self._q1("SELECT id FROM setups WHERE hash=? AND track_id IS ?", (h, track_id))
        if existing:
            return existing["id"]
        return self._exec(
            "INSERT INTO setups(hash, track_id, team_id, session_id, created_at, data) VALUES (?,?,?,?,?,?)",
            (h, track_id, team_id, session_id, now_iso(), json.dumps(setup)))

    def list_setups(self, track_id=None) -> list[dict]:
        sql = ("SELECT st.*, (SELECT MIN(l.lap_time_ms) FROM laps l WHERE l.setup_id=st.id AND l.valid=1 "
               "AND l.lap_time_ms>0) AS best_lap_ms, (SELECT COUNT(*) FROM laps l WHERE l.setup_id=st.id) "
               "AS laps FROM setups st")
        args = []
        if track_id is not None:
            sql += " WHERE st.track_id=?"
            args.append(track_id)
        sql += " ORDER BY st.favorite DESC, st.created_at DESC"
        return self._q(sql, args)

    def setup_laps(self, setup_id: int, limit=40) -> list[dict]:
        """The most recent complete laps driven with a setup."""
        return self._q("SELECT id, session_id, lap_number, lap_time_ms, valid, lap_type, tyre_visual, weather, track_temp, "
                       "category, recorded_at, regs_2026 FROM laps WHERE setup_id=? AND lap_time_ms>0 "
                       "AND telemetry_complete=1 ORDER BY recorded_at DESC, id DESC LIMIT ?", (setup_id, limit))

    def setups_in_use_order(self, track_id) -> list[dict]:
        """A track's setups in the order they were first driven."""
        return self._q("SELECT st.id, st.name, st.data, MIN(l.recorded_at) AS first_used, COUNT(l.id) AS laps "
                       "FROM setups st JOIN laps l ON l.setup_id=st.id WHERE st.track_id IS ? "
                       "GROUP BY st.id ORDER BY first_used, st.id", (track_id,))

    def get_setup(self, setup_id: int) -> dict | None:
        return self._q1("SELECT * FROM setups WHERE id=?", (setup_id,))

    def update_setup(self, setup_id: int, fields: dict):
        cols = [k for k in fields if k in ("name", "notes", "favorite")]
        if cols:
            self._exec("UPDATE setups SET " + ", ".join(f"{c}=?" for c in cols) + " WHERE id=?",
                       [fields[c] for c in cols] + [setup_id])

    def delete_setup(self, setup_id: int):
        self._exec("UPDATE laps SET setup_id=NULL WHERE setup_id=?", (setup_id,))
        self._exec("DELETE FROM setups WHERE id=?", (setup_id,))

    # ------------------------------------------------------------------ events
    def add_events(self, session_id: int, events: list[dict]):
        if not events:
            return
        with self.lock:
            self.db.executemany(
                "INSERT INTO events(session_id, session_time, lap, code, text, data) VALUES (?,?,?,?,?,?)",
                [(session_id, e.get("session_time"), e.get("lap"), e.get("code"), e.get("text"),
                  json.dumps(e.get("data") or {})) for e in events])
            self.db.commit()

    def session_events(self, sid: int) -> list[dict]:
        return self._q("SELECT session_time, lap, code, text, data FROM events WHERE session_id=? "
                       "ORDER BY session_time, id", (sid,))

    # ------------------------------------------------------------------ tracks
    def get_track(self, track_id: int) -> dict | None:
        t = self._q1("SELECT * FROM tracks WHERE track_id=?", (track_id,))
        if t and t.get("outline") and not outline_ok(t["outline"], t.get("length")):
            t["outline"] = self._redraw_outline(track_id, t.get("length"))
        return t

    def _redraw_outline(self, track_id: int, length):
        """A stored outline with a hole in it: draw it again from the best laps here, or drop it."""
        outline = None
        for r in self._q("SELECT id FROM laps WHERE track_id=? AND valid=1 AND telemetry_complete=1 "
                         "AND lap_time_ms>0 ORDER BY lap_time_ms LIMIT 5", (track_id,)):
            cols = self.get_lap_telemetry(r["id"])
            pts = outline_from(cols) if cols else None
            if pts and outline_ok(pts, length):
                outline = pts
                break
        self._exec("UPDATE tracks SET outline=? WHERE track_id=?",
                   (json.dumps(outline, separators=(",", ":")) if outline else None, track_id))
        return outline

    def save_track(self, track_id: int, outline: list, length, s2, s3):
        self._exec(
            "INSERT INTO tracks(track_id, outline, length, s2_start, s3_start, updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(track_id) DO UPDATE SET outline=excluded.outline, length=excluded.length, "
            "s2_start=excluded.s2_start, s3_start=excluded.s3_start, updated_at=excluded.updated_at",
            (track_id, json.dumps(outline, separators=(",", ":")), length, s2, s3, now_iso()))

    # how the game's coordinates sit on the bundled circuit outline (circuits.align)
    def save_track_frame(self, track_id: int, frame: dict):
        self._exec(
            "INSERT INTO tracks(track_id, frame, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(track_id) DO UPDATE SET frame=excluded.frame",
            (track_id, json.dumps(frame, separators=(",", ":")), now_iso()))

    def track_summaries(self) -> list[dict]:
        return self._q(
            "SELECT s.track_id, COUNT(DISTINCT s.id) AS sessions, "
            "(SELECT COUNT(*) FROM laps l WHERE l.track_id=s.track_id AND l.lap_time_ms>0) AS laps, "
            "(SELECT MIN(l.lap_time_ms) FROM laps l WHERE l.track_id=s.track_id AND l.valid=1 AND l.lap_time_ms>0) AS best_lap_ms, "
            "(SELECT MIN(l.s1_ms) FROM laps l WHERE l.track_id=s.track_id AND l.valid=1 AND l.s1_ms>0) AS best_s1, "
            "(SELECT MIN(l.s2_ms) FROM laps l WHERE l.track_id=s.track_id AND l.valid=1 AND l.s2_ms>0) AS best_s2, "
            "(SELECT MIN(l.s3_ms) FROM laps l WHERE l.track_id=s.track_id AND l.valid=1 AND l.s3_ms>0) AS best_s3, "
            "MAX(s.started_at) AS last_driven, SUM(s.distance_m) AS distance_m "
            "FROM sessions s WHERE s.track_id IS NOT NULL GROUP BY s.track_id ORDER BY last_driven DESC")

    def best_by_category(self, track_id: int) -> list[dict]:
        return self._q(
            "SELECT category, MIN(lap_time_ms) AS best_lap_ms, MIN(s1_ms) AS best_s1, MIN(s2_ms) AS best_s2, "
            "MIN(s3_ms) AS best_s3, COUNT(*) AS laps FROM laps WHERE track_id=? AND valid=1 AND lap_time_ms>0 "
            "GROUP BY category", (track_id,))

    def time_trial_for_track(self, track_id: int) -> dict | None:
        """The game's own Time Trial data (session best, personal best, rival) from the latest TT session."""
        return self._q1("SELECT id AS session_id, started_at, team_id, time_trial FROM sessions "
                        "WHERE track_id=? AND time_trial IS NOT NULL ORDER BY started_at DESC, id DESC LIMIT 1",
                        (track_id,))

    # ------------------------------------------------------------------ career
    def season_sessions(self, season_link=None, with_results=False) -> list[dict]:
        cols = ("id, started_at, ended_at, game_year, track_id, session_type, category, game_mode, rule_set, "
                "season_link, weekend_link, session_link, team_id, my_team, player_name, final_position, "
                "grid_position, points, result_status, best_lap_ms, laps_completed, total_laps")
        if with_results:
            cols += ", results"
        sql = f"SELECT {cols} FROM sessions WHERE season_link IS NOT NULL AND season_link != 0"
        args = []
        if season_link is not None:
            sql += " AND season_link=?"
            args.append(season_link)
        return self._q(sql + " ORDER BY started_at, id", args)

    def season_meta(self) -> dict[int, dict]:
        return {r["season_link"]: r for r in self._q("SELECT season_link, name, notes FROM seasons")}

    def update_season(self, season_link: int, fields: dict):
        cols = [k for k in fields if k in ("name", "notes")]
        if not cols:
            return
        self._exec("INSERT INTO seasons(season_link) VALUES (?) ON CONFLICT(season_link) DO NOTHING", (season_link,))
        self._exec("UPDATE seasons SET " + ", ".join(f"{c}=?" for c in cols) + " WHERE season_link=?",
                   [fields[c] or None for c in cols] + [season_link])

    # ------------------------------------------------------------------ stats
    def overview_stats(self) -> dict:
        with self.lock:
            q = lambda sql, a=(): self.db.execute(sql, a).fetchone()
            totals = q("SELECT COUNT(*), COALESCE(SUM(distance_m),0), COALESCE(SUM(drive_time_s),0), "
                       "COALESCE(SUM(laps_completed),0) FROM sessions")
            races = q("SELECT COUNT(*), SUM(final_position=1), SUM(final_position<=3), "
                      "COALESCE(SUM(points),0), AVG(final_position), SUM(result_status IN (4,5,7)) "
                      "FROM sessions WHERE category='race' AND final_position>0")
            valid = q("SELECT COUNT(*) FROM laps WHERE valid=1 AND lap_time_ms>0")
            poles = q("SELECT COUNT(*) FROM sessions WHERE category='qualifying' AND final_position=1")
        by_cat = self._q("SELECT category, COUNT(*) AS sessions, SUM(laps_completed) AS laps "
                         "FROM sessions GROUP BY category")
        activity = self._q("SELECT substr(started_at,1,10) AS day, COUNT(*) AS sessions, "
                           "SUM(laps_completed) AS laps, SUM(distance_m) AS distance_m "
                           "FROM sessions GROUP BY day ORDER BY day")
        finishes = self._q("SELECT final_position AS position, COUNT(*) AS count FROM sessions "
                           "WHERE category='race' AND final_position>0 GROUP BY final_position "
                           "ORDER BY final_position")
        race_list = self._q("SELECT id, started_at, track_id, final_position, grid_position, points "
                            "FROM sessions WHERE category='race' AND final_position>0 ORDER BY started_at")
        return {
            "sessions": totals[0], "distance_m": totals[1], "drive_time_s": totals[2],
            "laps": totals[3], "valid_laps": valid[0],
            "races": races[0] or 0, "wins": races[1] or 0, "podiums": races[2] or 0,
            "points": races[3] or 0, "avg_finish": races[4], "dnfs": races[5] or 0,
            "poles": poles[0] or 0,
            "by_category": by_cat, "activity": activity, "finishes": finishes, "race_list": race_list,
        }

    def db_size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0
