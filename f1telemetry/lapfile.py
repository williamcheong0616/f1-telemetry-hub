"""Lap files (.f1lap) for comparing with friends: one lap with its telemetry and setup, gzipped JSON.

Imported files come from other people, so everything in them is checked and copied field by field: known lap
fields of the right type, known telemetry columns of numbers, a plain driver name, and size limits throughout.
"""
from __future__ import annotations

import gzip
import json
import re
import zlib

from . import constants as C
from .recorder import SCALARS, WHEEL_KEYS

FORMAT = "f1th-lap"
VERSION = 1
MAX_FILE = 8 * 1024 * 1024  # bytes as uploaded
MAX_JSON = 64 * 1024 * 1024  # bytes once unzipped
MAX_SAMPLES = 60000
# lap fields carried in the file: name -> accepted types
LAP_FIELDS = {
    "lap_number": int, "track_id": int, "category": str, "session_type": int, "game_year": int, "lap_time_ms": int,
    "s1_ms": int, "s2_ms": int, "s3_ms": int, "valid": int, "lap_type": str, "tyre_visual": int, "tyre_actual": int,
    "tyre_age": int, "weather": int, "track_temp": int, "air_temp": int, "regs_2026": int, "top_speed": (int, float),
    "recorded_at": str, "track_length": (int, float),
}
NUMBER = (int, float)


class LapFileError(ValueError):
    pass


def clean_name(s) -> str:
    s = re.sub(r"[^\w .'\-]", "", str(s or ""), flags=re.UNICODE).strip()[:32]
    return s or "Friend"


def export_lap(store, lap_id: int, app_version: str) -> tuple[str, bytes]:
    """The file name and gzipped contents for one of your laps."""
    lap = store.get_lap(lap_id)
    cols = store.get_lap_telemetry(lap_id) if lap else None
    if not lap or not cols:
        raise LookupError("no telemetry for this lap")
    sess = store.get_session(lap["session_id"]) or {}
    out = {k: lap.get(k) for k in LAP_FIELDS if lap.get(k) is not None}
    out["track_length"] = sess.get("track_length")
    if lap.get("micro"):
        out["micro"] = lap["micro"]
    setup = store.get_setup(lap["setup_id"]) if lap.get("setup_id") else None
    doc = {"format": FORMAT, "version": VERSION, "app": app_version, "driver": clean_name(lap.get("player_name") or "Driver"),
           "lap": out, "setup": (setup or {}).get("data"), "cols": cols}
    data = gzip.compress(json.dumps(doc, separators=(",", ":")).encode(), compresslevel=6)
    track = C.name_or(C.TRACKS, lap["track_id"], "Track ").replace(" ", "")
    t = lap["lap_time_ms"]
    name = f"{doc['driver'].replace(' ', '_')}_{track}_{t // 60000}m{t % 60000 / 1000:06.3f}.f1lap"
    return name, data


def _unzip(raw: bytes) -> bytes:
    if raw[:2] != b"\x1f\x8b":
        return raw
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(raw, MAX_JSON)
    if d.unconsumed_tail:
        raise LapFileError("the file is too large")
    return out


def _num_list(v, n):
    if not isinstance(v, list) or len(v) != n:
        raise LapFileError("telemetry columns differ in length")
    return [x if x is None or (isinstance(x, NUMBER) and not isinstance(x, bool)) else None for x in v]


def parse(raw: bytes) -> tuple[str, dict, dict | None, dict]:
    """(driver, lap fields, setup, telemetry columns) from an uploaded file, or LapFileError."""
    if len(raw) > MAX_FILE:
        raise LapFileError("the file is too large")
    try:
        doc = json.loads(_unzip(raw))
    except (ValueError, zlib.error) as e:
        raise LapFileError("not a lap file") from e
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise LapFileError("not a lap file from this app")
    if not isinstance(doc.get("version"), int) or doc["version"] > VERSION:
        raise LapFileError("this lap file needs a newer version of the app")
    src = doc.get("lap") if isinstance(doc.get("lap"), dict) else {}
    lap = {}
    for k, typ in LAP_FIELDS.items():
        v = src.get(k)
        if isinstance(v, typ) and not isinstance(v, bool):
            lap[k] = v[:40] if isinstance(v, str) else v
    if "track_id" not in lap or not lap.get("lap_time_ms") or lap["lap_time_ms"] <= 0:
        raise LapFileError("the lap has no circuit or lap time")
    m = src.get("micro")
    if isinstance(m, dict) and isinstance(m.get("key"), str) and isinstance(m.get("ms"), list) and len(m["ms"]) <= 64:
        lap["micro"] = {"key": m["key"][:40], "ms": [x if isinstance(x, int) else None for x in m["ms"]]}
    cin = doc.get("cols")
    if not isinstance(cin, dict) or not isinstance(cin.get("d"), list):
        raise LapFileError("the lap has no telemetry")
    n = len(cin["d"])
    if not 20 <= n <= MAX_SAMPLES:
        raise LapFileError("the lap's telemetry is too short or too long")
    cols = {k: _num_list(cin[k], n) for k in SCALARS if k in cin}
    for k in WHEEL_KEYS:
        v = cin.get(k)
        if isinstance(v, list) and len(v) == 4:
            cols[k] = [_num_list(w, n) for w in v]
    for k in ("t", "d", "spd"):
        if k not in cols:
            raise LapFileError("the lap's telemetry is incomplete")
    setup = None
    s = doc.get("setup")
    if isinstance(s, dict) and len(s) <= 64:
        setup = {str(k)[:40]: v for k, v in s.items() if isinstance(v, NUMBER) and not isinstance(v, bool)}
    return clean_name(doc.get("driver")), lap, setup, cols
