"""Local HTTP server: static dashboard, JSON API and a live Server-Sent-Events stream."""
from __future__ import annotations

import csv
import io
import json
import math
import mimetypes
import os
import re
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, advisor, career, coach, constants as C, lapfile, recordings, strategy
from .recorder import SCALARS, WHEEL_KEYS, fmt_lap

LIVE_HZ = 15

# Windows' registry can map .js to text/plain, which browsers refuse for ES modules.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


def _clean(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def to_json(obj) -> bytes:
    try:
        return json.dumps(obj, separators=(",", ":"), allow_nan=False, default=str).encode()
    except ValueError:
        return json.dumps(_clean(obj), separators=(",", ":"), default=str).encode()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


ROUTES: list[tuple[str, re.Pattern, str]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn.__name__))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    server_version = f"F1TelemetryHub/{__version__}"
    app = None  # injected
    web_root: Path = None

    def log_message(self, fmt, *args):
        if self.app.settings.get("debug"):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------------ plumbing
    def _dispatch(self, method):
        url = urlparse(self.path)
        self.query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        path = url.path
        try:
            if path.startswith("/api/"):
                for m, rx, name in ROUTES:
                    if m != method:
                        continue
                    mt = rx.match(path)
                    if mt:
                        return getattr(self, name)(*mt.groups())
                raise ApiError(404, "not found")
            if method != "GET":
                raise ApiError(405, "method not allowed")
            return self._static(path)
        except ApiError as e:
            self._json({"error": str(e)}, e.status)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001 - surface unexpected errors to the UI
            self._json({"error": repr(e)}, 500)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            raise ApiError(400, "invalid JSON body")

    def _send(self, body: bytes, ctype: str, status=200, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(to_json(obj), "application/json; charset=utf-8", status)

    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        target = (self.web_root / path.lstrip("/")).resolve()
        if self.web_root.resolve() not in target.parents or not target.is_file():
            target = self.web_root / "index.html"
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(target.read_bytes(), ctype)

    def _int(self, name, default=None):
        v = self.query.get(name)
        if v in (None, ""):
            return default
        try:
            return int(v)
        except ValueError:
            raise ApiError(400, f"{name} must be an integer")

    # ------------------------------------------------------------------ live
    @route("GET", r"/api/status")
    def api_status(self):
        info = self.app.recorder.status_info()
        info.update(self.app.listener_info())
        info["replay"] = self.app.replay_info()
        info["recording"] = self.app.capture.info()
        info["version"] = __version__
        info["data_dir"] = str(self.app.data_dir)
        info["db_size"] = self.app.store.db_size()
        self._json(info)

    def _live_snapshot(self) -> dict:
        r = self.app.replay
        if r and not r.rec:  # a replay still loading: not the game's live data in the meantime
            snap = {"session": None, "player": None, "cars": [], "events": [], "radio": [], "status": {"connected": False}}
        else:
            snap = self.app.live.snapshot()
        return {**snap, "replay": self.app.replay_info(), "recording": self.app.capture.info()}

    @route("GET", r"/api/live")
    def api_live(self):
        self._json(self._live_snapshot())

    @route("GET", r"/api/live/lap")
    def api_live_lap(self):
        self._json(self.app.live.live_lap(self.query.get("key", ""), self._int("since", 0)))

    @route("GET", r"/api/live/strategy")
    def api_live_strategy(self):
        loss = self.query.get("pit_loss")
        try:
            loss = min(60.0, max(5.0, float(loss))) if loss else None
        except ValueError:
            loss = None
        self._json(strategy.for_recorder(self.app.live, loss))

    @route("GET", r"/api/live/track")
    def api_live_track(self):
        self._json(self.app.live.track_outline_for_live())

    @route("GET", r"/api/live/stream")
    def api_live_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        interval = 1.0 / LIVE_HZ
        try:
            while not self.app.stopping:
                t0 = time.perf_counter()
                self.wfile.write(b"data: " + to_json(self._live_snapshot()) + b"\n\n")
                self.wfile.flush()
                time.sleep(max(0.0, interval - (time.perf_counter() - t0)))
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return

    @route("GET", r"/api/guide")
    def api_guide(self):
        # GUIDE.md sits beside the web folder in the exe, and at the top of the source tree
        for path in (self.web_root.parent / "GUIDE.md", self.web_root.parent.parent / "GUIDE.md"):
            if path.is_file():
                self._send(path.read_bytes(), "text/markdown; charset=utf-8")
                return
        raise ApiError(404, "the guide is not included in this build")

    # ------------------------------------------------------------------ meta & settings
    @route("GET", r"/api/meta")
    def api_meta(self):
        self._json({
            "tracks": C.TRACKS, "session_types": C.SESSION_TYPES, "teams": C.TEAMS,
            "team_colours": C.TEAM_COLOURS, "visual_compounds": C.VISUAL_COMPOUNDS,
            "actual_compounds": C.ACTUAL_COMPOUNDS, "weather": C.WEATHER, "result_status": C.RESULT_STATUS,
            "formula": C.FORMULA, "game_modes": C.GAME_MODES, "safety_car": C.SAFETY_CAR,
            "mode_groups": {m: C.mode_group(m) for m in C.GAME_MODES},
            "tt_gearbox": C.TT_GEARBOX, "tt_traction": C.TT_TRACTION, "version": __version__,
        })

    @route("GET", r"/api/settings")
    def api_get_settings(self):
        self._json(self.app.settings)

    @route("POST", r"/api/settings")
    def api_post_settings(self):
        try:
            result = self.app.update_settings(self._body())
        except ValueError as e:
            raise ApiError(400, str(e))
        self._json(result)

    @route("POST", r"/api/open-folder")
    def api_open_folder(self):
        self.app.open_data_folder(self._body().get("folder"))
        self._json({"ok": True})

    # ------------------------------------------------------------------ recordings & replay
    @route("GET", r"/api/recordings")
    def api_recordings(self):
        self._json(self.app.recordings_info())

    @route("POST", r"/api/recordings")
    def api_recordings_post(self):
        action = self._body().get("action")
        if action not in ("start", "stop"):
            raise ApiError(400, "action must be start or stop")
        self.app.capture.set_manual(action == "start")
        self._json(self.app.capture.info())

    def _recording(self, name):
        try:
            return self.app.recording_path(name)
        except (ValueError, FileNotFoundError):
            raise ApiError(404, "recording not found")

    @route("GET", r"/api/recordings/([\w\-]+\.f1rec)")
    def api_recording_download(self, name):
        path = self._recording(name)
        self._send(path.read_bytes(), "application/octet-stream",
                   extra={"Content-Disposition": f'attachment; filename="{name}"'})

    @route("DELETE", r"/api/recordings/([\w\-]+\.f1rec)")
    def api_recording_delete(self, name):
        self._recording(name)
        try:
            self.app.delete_recording(name)
        except PermissionError as e:
            raise ApiError(409, str(e))
        self._json({"ok": True})

    @route("GET", r"/api/replay")
    def api_replay(self):
        self._json(self.app.replay_info())

    @route("POST", r"/api/replay")
    def api_replay_post(self):
        b = self._body()
        action, r = b.get("action"), self.app.replay
        if action == "start":
            self._recording(b.get("name"))
            self.app.start_replay(b["name"], float(b.get("speed") or 1.0))
        elif action == "stop":
            self.app.stop_replay()
        elif not r:
            raise ApiError(409, "no replay running")
        elif action in ("pause", "resume"):
            r.pause(action == "pause")
        elif action == "speed":
            r.set_speed(float(b.get("value") or 1.0))
        elif action == "seek":
            r.seek(float(b.get("value") or 0.0))
        else:
            raise ApiError(400, "unknown action")
        self._json(self.app.replay_info())

    # ------------------------------------------------------------------ demo
    @route("GET", r"/api/demo")
    def api_demo_status(self):
        self._json(self.app.demo_info())

    @route("POST", r"/api/demo")
    def api_demo(self):
        b = self._body()
        if b.get("action") == "stop":
            self.app.stop_demo()
        else:
            self.app.start_demo(b.get("session", "race"), int(b.get("laps", 5)), float(b.get("speed", 1.0)),
                                int(b.get("format", 2025)))
        self._json(self.app.demo_info())

    @route("DELETE", r"/api/demo/data")
    def api_demo_delete(self):
        n = self.app.delete_demo_data()
        self._json({"deleted_sessions": n})

    # ------------------------------------------------------------------ sessions
    @route("GET", r"/api/sessions")
    def api_sessions(self):
        group = self.query.get("mode") or None
        if group and group not in C.MODE_GROUPS:
            raise ApiError(400, f"unknown mode group {group}")
        rows = self.app.store.list_sessions(self._int("track"), self.query.get("category") or None,
                                            100000 if group else self._int("limit", 300),
                                            0 if group else self._int("offset", 0))
        for r in rows:
            r["mode_group"] = C.mode_group(r["game_mode"])
        if group:
            rows = [r for r in rows if r["mode_group"] == group][:self._int("limit", 300)]
        self._json(rows)

    @route("GET", r"/api/sessions/(\d+)")
    def api_session(self, sid):
        st = self.app.store
        s = st.get_session(int(sid))
        if not s:
            raise ApiError(404, "session not found")
        laps = st.session_laps(int(sid))
        s["mode_group"] = C.mode_group(s["game_mode"])
        s["mode_name"] = C.GAME_MODES.get(s["game_mode"], "")
        if s.get("season_link") and s["mode_group"] in ("career", "championship"):
            meta = st.season_meta().get(s["season_link"]) or {}
            s["season_name"] = meta.get("name")
        setup_ids = sorted({l["setup_id"] for l in laps if l.get("setup_id")})
        s["recording"] = recordings.recording_for(self.app.recordings_dir, s["session_uid"])
        self._json({
            "session": s, "laps": laps, "events": st.session_events(int(sid)),
            "setups": [st.get_setup(i) for i in setup_ids], "track": st.get_track(s["track_id"]) if s["track_id"] is not None else None,
        })

    @route("PATCH", r"/api/sessions/(\d+)")
    def api_session_patch(self, sid):
        b = self._body()
        self.app.store.update_session(int(sid), {k: b[k] for k in ("notes",) if k in b})
        self._json({"ok": True})

    @route("DELETE", r"/api/sessions/(\d+)")
    def api_session_delete(self, sid):
        if self.app.recorder.session_id == int(sid):
            raise ApiError(409, "this session is currently being recorded")
        self.app.store.delete_session(int(sid))
        self._json({"ok": True})

    @route("GET", r"/api/coach/(\d+)")
    def api_coach(self, sid):
        res = coach.analyse_session(self.app.store, int(sid), self._int("ref"),
                                    mph=self.app.settings.get("speed_unit") == "mph")
        if res is None:
            raise ApiError(404, "session not found")
        self._json(res)

    # ------------------------------------------------------------------ laps
    @route("GET", r"/api/laps/(-?\d+)")
    def api_lap(self, lap_id):
        lap = self.app.store.get_lap(int(lap_id))
        if not lap:
            raise ApiError(404, "lap not found")
        self._json(lap)

    @route("GET", r"/api/laps/(-?\d+)/telemetry")
    def api_lap_telemetry(self, lap_id):
        st = self.app.store
        lap = st.get_lap(int(lap_id))
        if not lap:
            raise ApiError(404, "lap not found")
        cols = st.get_lap_telemetry(int(lap_id))
        self._json({"lap": lap, "cols": cols})

    @route("GET", r"/api/laps/(\d+)/export")
    def api_lap_export(self, lap_id):
        try:
            name, data = lapfile.export_lap(self.app.store, int(lap_id), __version__)
        except LookupError:
            raise ApiError(404, "no telemetry for this lap")
        self._send(data, "application/octet-stream", extra={"Content-Disposition": f'attachment; filename="{name}"'})

    # ------------------------------------------------------------------ friends' laps
    @route("GET", r"/api/guest-laps")
    def api_guest_laps(self):
        rows = self.app.store.guest_laps(self._int("track"))
        for r in rows:
            r["track"] = C.name_or(C.TRACKS, r["track_id"], "Track ")
        self._json(rows)

    @route("POST", r"/api/guest-laps")
    def api_guest_import(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            raise ApiError(400, "no file")
        if n > lapfile.MAX_FILE:
            raise ApiError(413, "the file is too large")
        try:
            driver, lap, setup, cols = lapfile.parse(self.rfile.read(n))
        except lapfile.LapFileError as e:
            raise ApiError(400, str(e))
        lid = self.app.store.add_guest_lap(driver, lap, setup, cols)
        self._json(self.app.store.get_lap(lid))

    @route("DELETE", r"/api/guest-laps/-?(\d+)")
    def api_guest_delete(self, gid):
        self.app.store.delete_guest_lap(int(gid))
        self._json({"ok": True})

    # ------------------------------------------------------------------ tracks
    @route("GET", r"/api/tracks")
    def api_tracks(self):
        rows = self.app.store.track_summaries()
        for r in rows:
            r["name"] = C.name_or(C.TRACKS, r["track_id"], "Track ")
            parts = [r["best_s1"], r["best_s2"], r["best_s3"]]
            r["theoretical_ms"] = sum(parts) if all(parts) else None
            t = self.app.store.get_track(r["track_id"])
            r["outline"] = t["outline"][::2] if t and t.get("outline") else None
            r["frame"] = t.get("frame") if t else None
        self._json(rows)

    @route("GET", r"/api/tracks/(-?\d+)")
    def api_track(self, tid):
        st = self.app.store
        tid = int(tid)
        t = st.get_track(tid) or {"track_id": tid}
        t["name"] = C.name_or(C.TRACKS, tid, "Track ")
        cats = st.best_by_category(tid)
        for c in cats:
            parts = [c["best_s1"], c["best_s2"], c["best_s3"]]
            c["theoretical_ms"] = sum(parts) if all(parts) else None
        t["best_by_category"] = cats
        t["top_laps"] = st.laps_for_track(tid, self.query.get("category") or None, True, 50)
        t["sessions"] = st.list_sessions(tid, None, 500, 0)
        t["setups"] = st.list_setups(tid)
        t["time_trial"] = st.time_trial_for_track(tid)
        self._json(t)

    # ------------------------------------------------------------------ career
    @route("GET", r"/api/career")
    def api_career(self):
        st = self.app.store
        self._json(career.season_list(st.season_sessions(with_results=True), st.season_meta()))

    @route("GET", r"/api/career/(\d+)")
    def api_career_season(self, link):
        st = self.app.store
        link = int(link)
        sessions = career.group_seasons(st.season_sessions(link, with_results=True)).get(link)
        if not sessions:
            raise ApiError(404, "season not found")
        self._json(career.build_season(link, sessions, st.season_meta().get(link)))

    @route("PATCH", r"/api/career/(\d+)")
    def api_career_patch(self, link):
        self.app.store.update_season(int(link), self._body())
        self._json({"ok": True})

    # ------------------------------------------------------------------ setups
    @route("GET", r"/api/setups")
    def api_setups(self):
        rows = self.app.store.list_setups(self._int("track"))
        for r in rows:
            r["track_name"] = C.name_or(C.TRACKS, r["track_id"], "Track ") if r["track_id"] is not None else "-"
        self._json(rows)

    @route("GET", r"/api/setups/(\d+)")
    def api_setup(self, sid):
        s = self.app.store.get_setup(int(sid))
        if not s:
            raise ApiError(404, "setup not found")
        self._json(s)

    @route("GET", r"/api/setups/(\d+)/advice")
    def api_setup_advice(self, sid):
        rep = advisor.setup_report(self.app.store, int(sid))
        if rep is None:
            raise ApiError(404, "setup not found")
        self._json(rep)

    @route("PATCH", r"/api/setups/(\d+)")
    def api_setup_patch(self, sid):
        self.app.store.update_setup(int(sid), self._body())
        self._json(self.app.store.get_setup(int(sid)))

    @route("DELETE", r"/api/setups/(\d+)")
    def api_setup_delete(self, sid):
        self.app.store.delete_setup(int(sid))
        self._json({"ok": True})

    # ------------------------------------------------------------------ stats
    @route("GET", r"/api/stats")
    def api_stats(self):
        self._json(self.app.store.overview_stats())

    # ------------------------------------------------------------------ exports
    @route("GET", r"/api/export/lap/(\d+)\.csv")
    def api_export_lap(self, lap_id):
        st = self.app.store
        lap = st.get_lap(int(lap_id))
        cols = st.get_lap_telemetry(int(lap_id))
        if not lap or not cols:
            raise ApiError(404, "no telemetry for this lap")
        buf = io.StringIO()
        w = csv.writer(buf)
        wheel_hdr = [f"{k}_{wn}" for k in WHEEL_KEYS for wn in C.WHEELS]
        scalars = [k for k in SCALARS if k in cols]  # older laps lack the 2026 channels
        w.writerow(scalars + wheel_hdr)
        n = len(cols["t"])
        for i in range(n):
            row = [cols[k][i] for k in scalars]
            for k in WHEEL_KEYS:
                row.extend(cols[k][j][i] for j in range(4))
            w.writerow(row)
        name = f"lap_{lap['lap_number']}_{C.name_or(C.TRACKS, lap['track_id'])}_{fmt_lap(lap['lap_time_ms']).replace(':', 'm')}.csv"
        self._send(buf.getvalue().encode(), "text/csv; charset=utf-8",
                   extra={"Content-Disposition": f'attachment; filename="{name}"'})

    @route("GET", r"/api/export/session/(\d+)\.csv")
    def api_export_session(self, sid):
        st = self.app.store
        s = st.get_session(int(sid))
        if not s:
            raise ApiError(404, "session not found")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["lap", "lap_time", "lap_ms", "s1_ms", "s2_ms", "s3_ms", "valid", "type", "position",
                    "tyre", "tyre_age", "fuel_start", "fuel_end", "top_speed", "wear_end_RL", "wear_end_RR",
                    "wear_end_FL", "wear_end_FR", "ers_deployed_J", "drs_activations"])
        for l in st.session_laps(int(sid)):
            wear = l.get("wear_end") or [None] * 4
            w.writerow([l["lap_number"], fmt_lap(l["lap_time_ms"]), l["lap_time_ms"], l["s1_ms"], l["s2_ms"],
                        l["s3_ms"], l["valid"], l["lap_type"], l["position"],
                        C.VISUAL_COMPOUNDS.get(l["tyre_visual"], ""), l["tyre_age"], l["fuel_start"], l["fuel_end"],
                        l["top_speed"], *wear, l["ers_deployed"], l["drs_activations"]])
        name = f"session_{sid}_{C.name_or(C.TRACKS, s['track_id'])}.csv"
        self._send(buf.getvalue().encode(), "text/csv; charset=utf-8",
                   extra={"Content-Disposition": f'attachment; filename="{name}"'})


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second program bind a port that is already in use, so two copies
    # of the app would silently share 8777. Claim the port exclusively instead; a busy port then fails
    # and start_http moves on to the next one.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        # A browser dropping an idle keep-alive connection (a reload, a closed tab) is not worth a traceback
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def make_server(app, host: str, port: int, web_root: Path) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app, "web_root": web_root})
    srv = Server((host, port), handler)
    srv.daemon_threads = True
    return srv
