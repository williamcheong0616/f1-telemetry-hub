"""Application wiring: settings, UDP listener, recorder, recordings and replays, HTTP server, demo mode."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

from . import APP_NAME, __version__
from . import recordings
from .recorder import Recorder
from .server import make_server
from .simulator import DEMO_SEASON_LINK, DEMO_TRACK_ID, Simulator
from .storage import Storage

DEFAULT_SETTINGS = {
    "udp_host": "0.0.0.0",
    "udp_port": 20777,
    "http_port": 8777,
    "lan_access": False,
    "open_browser": True,
    "telemetry_hz": 20,
    "forward": [],
    "speed_unit": "kmh",
    "temp_unit": "c",
    "theme": "dark",
    "auto_record": False,       # save the game's raw data of every session (see recordings.py)
    "recordings_max_gb": 5,     # the oldest recordings go once they take more than this
    "debug": False,
}


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    """data\\ next to the app, so the whole thing can live in one folder (or on a USB stick). When that folder
    can't be written to (the exe in Program Files, say), the user's local app data instead. The Mac app always
    uses Application Support: macOS runs a downloaded app from a read-only copy, and an update replaces the
    whole app."""
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        return Path.home() / "Library" / "Application Support" / APP_NAME
    here = base_dir() / "data"
    try:
        here.mkdir(parents=True, exist_ok=True)
        probe = here / ".write-test"
        probe.write_bytes(b"")
        probe.unlink()
        return here
    except OSError:
        root = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(root) / APP_NAME.replace(" ", "") / "data"


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", base_dir()))
    return Path(__file__).resolve().parent


def _parse_target(t: str):
    host, _, port = str(t).strip().rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"forward target must look like host:port, got {t!r}")
    return host, int(port)


class UdpListener:
    def __init__(self, host: str, port: int, on_packet, forward):
        self.host, self.port = host, port
        self.on_packet = on_packet
        self.forward = [_parse_target(t) for t in forward]
        self.error = None
        self._stop = threading.Event()
        self.sock = None
        self.thread = threading.Thread(target=self._run, name="udp-listener", daemon=True)

    def start(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            self.sock.bind((self.host, self.port))
            self.sock.settimeout(0.5)
        except OSError as e:
            self.error = f"Could not listen on UDP {self.host}:{self.port} - {e.strerror or e}. " \
                         f"Is another telemetry app using this port?"
            return False
        self.thread.start()
        return True

    def stop(self):
        self._stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=2)
        if self.sock:
            self.sock.close()

    def _run(self):
        fwd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if self.forward else None
        while not self._stop.is_set():
            try:
                data, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue  # Windows reports ICMP port-unreachable as recv errors
            if fwd:
                for t in self.forward:
                    try:
                        fwd.sendto(data, t)
                    except OSError:
                        pass
            self.on_packet(data)


class StayAwake:
    """Keeps the computer from going to sleep while the game is sending: with the game on a console or another
    PC nobody touches this one, and a laptop would sleep mid-race. The screen can still turn off. It lets go a
    few minutes after the data stops."""
    HOLD_S = 300

    def __init__(self):
        self.until = 0.0
        self.held = False
        self.proc = None  # macOS: caffeinate, which holds it for as long as it runs

    def update(self, receiving: bool):
        """Called every second (from the same thread: on Windows the request belongs to the thread)."""
        now = time.monotonic()
        if receiving:
            self.until = now + self.HOLD_S
        want = now < self.until
        if want != self.held:
            self.held = want
            self._set(want)

    def release(self):
        self.until = 0.0
        self.update(False)

    def _set(self, on: bool):
        try:
            if sys.platform == "darwin":
                if on:  # -i: no idle sleep; -w: ends with this app, even if it crashes
                    self.proc = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
                elif self.proc:
                    self.proc.terminate()
                    self.proc = None
            elif os.name == "nt":
                import ctypes
                es_continuous, es_system_required = 0x80000000, 0x00000001
                ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | (es_system_required if on else 0))
        except (OSError, AttributeError) as e:
            print(f"[warn] could not {'keep the computer awake' if on else 'let the computer sleep'}: {e!r}")


class App:
    def __init__(self, data_dir: Path, overrides: dict | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.data_dir / "settings.json"
        self.settings = dict(DEFAULT_SETTINGS)
        if self.settings_path.exists():
            try:
                self.settings.update(json.loads(self.settings_path.read_text(encoding="utf-8")))
            except ValueError:
                print("[warn] settings.json is not valid JSON - using defaults")
        self.runtime_overrides = overrides or {}
        self.settings.update(self.runtime_overrides)
        self.store = Storage(self.data_dir / "f1telemetry.db")
        self.recorder = Recorder(self.store, self.settings)
        self.recordings_dir = self.data_dir / "recordings"
        self.capture = recordings.Capture(self.recordings_dir, self.settings, lambda: self.recorder.demo_active)
        self.replay: recordings.Replay | None = None
        self.listener: UdpListener | None = None
        self.demo: Simulator | None = None
        self.httpd = None
        self.http_port = None
        self.stopping = False
        self.awake = StayAwake()

    # ------------------------------------------------------------------ settings
    def _save_settings(self):
        persist = {k: v for k, v in self.settings.items() if k not in self.runtime_overrides}
        self.settings_path.write_text(json.dumps(persist, indent=2), encoding="utf-8")

    def update_settings(self, new: dict) -> dict:
        allowed = set(DEFAULT_SETTINGS)
        changed = {}
        for k, v in new.items():
            if k not in allowed:
                continue
            default = DEFAULT_SETTINGS[k]
            if isinstance(default, str):
                v = str(v)
            elif isinstance(default, bool):
                v = bool(v)
            elif isinstance(default, int):
                v = int(v)
            elif isinstance(default, list):
                v = [str(x).strip() for x in (v if isinstance(v, list) else str(v).split(",")) if str(x).strip()]
                for t in v:
                    _parse_target(t)
            if self.settings.get(k) != v:
                changed[k] = v
        if "udp_port" in changed and not 1 <= changed["udp_port"] <= 65535:
            raise ValueError("UDP port must be between 1 and 65535")
        if "telemetry_hz" in changed:
            changed["telemetry_hz"] = max(5, min(60, changed["telemetry_hz"]))
        if "recordings_max_gb" in changed:
            changed["recordings_max_gb"] = max(1, min(1000, changed["recordings_max_gb"]))
        self.settings.update(changed)
        for k in changed:
            self.runtime_overrides.pop(k, None)
        self._save_settings()
        if {"udp_port", "udp_host", "forward"} & set(changed):
            self.start_listener()
        restart_needed = bool({"http_port", "lan_access"} & set(changed))
        return {"settings": self.settings, "restart_required": restart_needed, "listener": self.listener_info()}

    # ------------------------------------------------------------------ udp
    def start_listener(self):
        if self.listener:
            self.listener.stop()
        self.listener = UdpListener(self.settings["udp_host"], int(self.settings["udp_port"]),
                                    self._on_packet, self.settings.get("forward") or [])
        ok = self.listener.start()
        if not ok:
            print(f"[error] {self.listener.error}")
        return ok

    def _on_packet(self, data: bytes):
        self.capture.feed(data)
        self.recorder.handle(data)

    def listener_info(self) -> dict:
        l = self.listener
        return {"udp_host": l.host if l else None, "udp_port": l.port if l else None,
                "udp_error": l.error if l else "not started", "http_port": self.http_port,
                "local_ips": local_ips()}

    # ------------------------------------------------------------------ demo
    def start_demo(self, session="race", laps=5, speed=1.0, fmt=2025):
        self.stop_demo()
        port = self.listener.port if self.listener else int(self.settings["udp_port"])
        kind = session if session in ("race", "quali", "tt", "weekend") else "race"
        self.demo = Simulator("127.0.0.1", port, kind,
                              max(1, min(laps, 60)), max(0.25, min(speed, 20.0)), rate=30, loop=False,
                              fmt=2026 if fmt == 2026 else 2025)
        self.demo.start()
        self.recorder.demo_active = True

    def stop_demo(self):
        if self.demo:
            self.demo.stop()
            self.demo = None
        self.recorder.demo_active = False

    def demo_info(self) -> dict:
        d = self.demo
        if d and not d.running:
            self.recorder.demo_active = False
        return {"running": bool(d and d.running), "session": d.mode if d else None,
                "laps": d.total_laps if d else None, "speed": d.speed if d else None,
                "format": d.fmt if d else None}

    def delete_demo_data(self) -> int:
        st = self.store
        with st.lock:
            n = st.db.execute("SELECT COUNT(*) FROM sessions WHERE track_id=?", (DEMO_TRACK_ID,)).fetchone()[0]
            st.db.execute("DELETE FROM sessions WHERE track_id=? AND id IS NOT ?", (DEMO_TRACK_ID, self.recorder.session_id))
            st.db.execute("DELETE FROM setups WHERE track_id=?", (DEMO_TRACK_ID,))
            st.db.execute("DELETE FROM tracks WHERE track_id=?", (DEMO_TRACK_ID,))
            st.db.execute("DELETE FROM seasons WHERE season_link=?", (DEMO_SEASON_LINK,))
            st.db.commit()
        return n

    def open_data_folder(self, sub=None):
        folder = self.recordings_dir if sub == "recordings" else self.data_dir
        folder.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(folder))  # noqa: S606 - local folder chosen by the app
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])  # noqa: S603,S607 - Finder, on a folder chosen by the app

    # ------------------------------------------------------------------ recordings & replay
    @property
    def live(self) -> Recorder:
        """The recorder the Live page shows: the replay's while one is running."""
        r = self.replay
        return r.rec if r and r.rec else self.recorder

    def recording_path(self, name: str) -> Path:
        if not recordings.is_name(name):
            raise ValueError("not a recording name")
        path = self.recordings_dir / name
        if not path.exists():
            raise FileNotFoundError(name)
        return path

    def recordings_info(self) -> dict:
        items = recordings.list_recordings(self.recordings_dir, self.store, self.capture.current_name())
        return {"capture": self.capture.info(), "items": items, "total_bytes": sum(i["size"] for i in items),
                "max_gb": self.settings.get("recordings_max_gb"), "folder": str(self.recordings_dir),
                "replay": self.replay_info()}

    def delete_recording(self, name: str):
        path = self.recording_path(name)
        if name == self.capture.current_name():
            raise PermissionError("this recording is still being written")
        if self.replay and self.replay.name == name:
            self.stop_replay()
        recordings.delete(path)

    def start_replay(self, name: str, speed: float = 1.0):
        path = self.recording_path(name)
        self.stop_replay()
        self.capture.protected.add(name)
        self.replay = recordings.Replay(self, path, speed)
        self.replay.start()

    def stop_replay(self):
        r, self.replay = self.replay, None
        if r:
            r.stop()
            self.capture.protected.discard(r.name)

    def replay_info(self) -> dict:
        return self.replay.info() if self.replay else {"running": False}

    # ------------------------------------------------------------------ run
    def start_http(self):
        host = "0.0.0.0" if self.settings.get("lan_access") else "127.0.0.1"
        port = int(self.settings["http_port"])
        last_err = None
        for p in range(port, port + 10):
            try:
                self.httpd = make_server(self, host, p, resource_dir() / "web")
                self.http_port = p
                break
            except OSError as e:
                last_err = e
        if not self.httpd:
            raise SystemExit(f"Could not start the web server: {last_err}")
        threading.Thread(target=self.httpd.serve_forever, name="http", daemon=True).start()

    def _ticker(self):
        while not self.stopping:
            time.sleep(1.0)
            try:
                self.recorder.tick()
                r = self.replay
                if r:
                    r.tick()
            except Exception as e:  # noqa: BLE001
                print(f"[warn] recorder tick failed: {e!r}")
            last = self.recorder.last_packet_at
            self.awake.update(bool(last) and time.time() - last < 3)
        self.awake.release()

    def start(self) -> str:
        """Starts listening and serving; returns the dashboard's address."""
        self.start_listener()
        self.start_http()
        threading.Thread(target=self._ticker, name="ticker", daemon=True).start()
        return f"http://localhost:{self.http_port}/"

    def run(self, open_browser=True, window=False):
        url = self.start()
        banner(self, url)
        if open_browser and self.settings.get("open_browser", True):
            webbrowser.open(url)
        try:
            if window:
                from .window import StatusWindow
                StatusWindow(self, url).run()
            else:
                while True:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.shutdown()

    def shutdown(self):
        self.stopping = True
        self.stop_demo()
        self.stop_replay()
        if self.listener:
            self.listener.stop()
        self.capture.shutdown()
        self.recorder.shutdown()
        if self.httpd:
            self.httpd.shutdown()
        self.store.close()


def local_ips() -> list[str]:
    if sys.platform == "darwin":
        return _mac_ips()
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def _mac_ips() -> list[str]:
    """The Mac's addresses from ifconfig. The usual tricks (looking up the computer's own .local name, connecting
    a UDP socket) count as using the local network, which macOS asks the user about first."""
    try:
        out = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ips = set(re.findall(r"^\s*inet (\d+\.\d+\.\d+\.\d+)", out, re.M))
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))


def game_ip() -> str:
    """What goes in the game's UDP IP Address: 127.0.0.1 when the game runs on this computer, which it can't on
    a Mac, so there it's the Mac's address on the network the console or PC is on."""
    if sys.platform != "darwin":
        return "127.0.0.1"
    return " or ".join(local_ips()[:2]) or "this Mac's IP address (System Settings > Network)"


def banner(app: App, url: str):
    l = app.listener
    print("=" * 64)
    print(f"  {APP_NAME} v{__version__}")
    print("=" * 64)
    print(f"  Dashboard : {url}")
    if app.settings.get("lan_access"):
        for ip in local_ips():
            print(f"              http://{ip}:{app.http_port}/  (other devices)")
    if l and not l.error:
        print(f"  Telemetry : listening on UDP port {l.port}")
    else:
        print(f"  Telemetry : NOT LISTENING - {l.error if l else 'not started'}")
    print(f"  Data      : {app.data_dir}")
    print("-" * 64)
    print("  In the game: Settings > Telemetry Settings")
    print(f"    UDP Telemetry: On | UDP Broadcast Mode: Off | UDP IP: {game_ip()}")
    print(f"    UDP Port: {l.port if l else app.settings['udp_port']} | UDP Send Rate: 20-60Hz")
    print("    UDP Format: 2025 (2026 with the 2026 Season Pack) | Your Telemetry: Public")
    print(f"  Guide     : {url}#/guide")
    print("-" * 64)
    print("  Keep this window open while you drive. Close it or press Ctrl+C to quit.")
    print("=" * 64, flush=True)


def set_title(text: str):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(text)
        except (OSError, AttributeError):
            pass


def running_instance(data_dir: Path, port: int) -> str | None:
    """The address of this app already running on the same data folder, if there is one."""
    url = f"http://localhost:{port}/"
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=0.8) as r:
            s = json.loads(r.read())
        same = Path(s["data_dir"]).resolve() == data_dir.resolve()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return url if same else None


def use_window(argv=None) -> bool:
    """The app's own window instead of a console: the Mac app has no console, so there it's the default."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--no-window" in argv:
        return False
    want = "--window" in argv or (sys.platform == "darwin" and getattr(sys, "frozen", False))
    if want and importlib.util.find_spec("tkinter") is None:
        print("The app's window needs Tk, which this build doesn't have: running in this console instead.")
        return False
    return want


def log_to(path: Path):
    """With the app's window there's no console: what it would show goes to app.log in the data folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115 - for the app's life


def main(argv=None):
    """Runs the app. From the exe, a failure stays on screen instead of the window closing on it; with the app's
    window, the window shows it."""
    window = use_window(argv)
    set_title(f"{APP_NAME} - keep this window open while you drive")
    try:
        _main(argv, window)
    except KeyboardInterrupt:
        pass
    except (Exception, SystemExit) as e:  # noqa: BLE001
        if isinstance(e, SystemExit) and e.code in (0, None):
            raise
        if not (getattr(sys, "frozen", False) or window):
            raise
        print()
        if isinstance(e, SystemExit):
            print(f"  {e.code}")
        else:
            traceback.print_exc()
        if window:
            from .window import show_error
            show_error(str(e.code) if isinstance(e, SystemExit) else f"{type(e).__name__}: {e}")
            sys.exit(1)
        print("\n  F1 Telemetry Hub could not start. The guide's Troubleshooting section covers the usual causes.")
        try:
            input("  Press Enter to close this window.")
        except EOFError:
            pass
        sys.exit(1)


def _main(argv=None, window=False):
    ap = argparse.ArgumentParser(description=f"{APP_NAME} - local F1 25/26 telemetry recorder")
    ap.add_argument("--data-dir", default=os.environ.get("F1TH_DATA_DIR"),
                    help="folder for the database and settings (default: ./data next to the app; the Mac "
                         "app's is ~/Library/Application Support/F1 Telemetry Hub)")
    ap.add_argument("--udp-port", type=int, help="UDP port the game sends telemetry to (default 20777)")
    ap.add_argument("--http-port", type=int, help="port for the dashboard (default 8777)")
    ap.add_argument("--no-browser", action="store_true", help="don't open the dashboard automatically")
    ap.add_argument("--window", action="store_true",
                    help="show the app's own window instead of using this console (the Mac app's default; "
                         "needs Tk, which the Windows exe leaves out)")
    ap.add_argument("--no-window", action="store_true",
                    help="no app window, even in the Mac app: run in this terminal and stop with Ctrl+C")
    ap.add_argument("--demo", choices=["race", "quali", "tt", "weekend"],
                    help="start the built-in demo session (weekend = career qualifying + race)")
    ap.add_argument("--demo-speed", type=float, default=1.0)
    ap.add_argument("--demo-laps", type=int, default=5)
    ap.add_argument("--demo-format", type=int, choices=[2025, 2026], default=2025,
                    help="UDP format of the demo: 2025, or 2026 for the 2026 Season Pack cars")
    a = ap.parse_args(argv)
    overrides = {}
    if a.udp_port:
        overrides["udp_port"] = a.udp_port
    if a.http_port:
        overrides["http_port"] = a.http_port
    data_dir = Path(a.data_dir) if a.data_dir else default_data_dir()
    if not a.demo:  # started twice: show the one that is running rather than fight it for the ports
        port = a.http_port
        if not port:
            try:
                port = json.loads((data_dir / "settings.json").read_text(encoding="utf-8")).get("http_port")
            except (OSError, ValueError, AttributeError):
                port = None
        url = running_instance(data_dir, int(port or DEFAULT_SETTINGS["http_port"]))
        if url:
            print(f"{APP_NAME} is already running: opening {url}")
            if not a.no_browser:
                webbrowser.open(url)
            time.sleep(3)
            return
    if window:
        log_to(data_dir / "app.log")
    app = App(data_dir, overrides)
    if a.demo:
        threading.Timer(1.0, app.start_demo, args=(a.demo, a.demo_laps, a.demo_speed, a.demo_format)).start()
    app.run(open_browser=not a.no_browser, window=window)


if __name__ == "__main__":
    main()
