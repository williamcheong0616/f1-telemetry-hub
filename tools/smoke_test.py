"""Checks a built app: starts it on an empty data folder, checks the dashboard, its pages and the guide are
served, checks a second start hands over to the running one, drives a simulated race into it and checks the laps,
the lap in progress, the strategy and a lap file round trip, then stops it. The GitHub workflow runs it on every
build; anything after the app's path is passed to the app.

    python tools/smoke_test.py dist/F1TelemetryHub.exe
    python tools/smoke_test.py "dist/F1 Telemetry Hub.app/Contents/MacOS/F1TelemetryHub" --no-window
    python tools/smoke_test.py python run.py
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from f1telemetry import __version__  # noqa: E402
from f1telemetry.simulator import Simulator  # noqa: E402

UDP_PORT, HTTP_PORT = 20998, 8798
BASE = f"http://127.0.0.1:{HTTP_PORT}"


def raw(path, body=None, method=None):
    req = urllib.request.Request(BASE + path, data=body, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def call(path, body=None, method=None):
    return json.loads(raw(path, body, method))


def wait(cond, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = cond()
        except OSError:
            v = None
        if v:
            return v
        time.sleep(0.5)
    raise AssertionError(f"timed out after {timeout} s waiting for {what}")


def stop(proc):
    """Stops the app as Ctrl+C would and returns its exit code. On Windows the exe's two processes (the unpacker
    and the app) are ended outright: there's no Ctrl+C to send to a process without a console of its own."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        return proc.wait(20)
    proc.send_signal(signal.SIGINT)
    try:
        return proc.wait(30)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("the app was still running 30 s after Ctrl+C") from None


def keeping_awake(proc, name):
    """Whether the app is keeping the computer awake (None when this computer won't say)."""
    if sys.platform == "darwin":
        return subprocess.run(["pgrep", "-f", f"caffeinate -i -w {proc.pid}"], capture_output=True).returncode == 0
    if os.name == "nt":  # powercfg needs an administrator, which GitHub's runners are
        out = subprocess.run(["powercfg", "/requests"], capture_output=True, text=True).stdout
        if "SYSTEM:" not in out:
            return None
        return name.lower() in out.split("SYSTEM:")[1].split("AWAYMODE:")[0].lower()
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("app", help="the built app (or python, followed by run.py)")
    a, extra = ap.parse_known_args()
    tmp = Path(tempfile.mkdtemp(prefix="f1th-smoke-"))
    data = tmp / "data folder"  # a space, as in the Mac app's Application Support folder
    log = tmp / "app-output.txt"
    cmd = [a.app, *extra, "--data-dir", str(data), "--udp-port", str(UDP_PORT), "--http-port", str(HTTP_PORT),
           "--no-browser"]
    try:
        other = call("/api/status")["data_dir"]
    except OSError:
        other = None
    if other:
        sys.exit(f"Port {HTTP_PORT} is in use by another copy of the app ({other}): stop it first.")
    print("starting:", " ".join(cmd), flush=True)
    with open(log, "wb") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    ok = False
    try:
        st = wait(lambda: proc.poll() is None and call("/api/status"), 90, "the app to answer")
        print(f"up: version {st['version']} on {st['platform']}, data in {st['data_dir']}")
        assert st["version"] == __version__, f"the app says {st['version']}, the source {__version__}"
        assert st["platform"] == sys.platform, st["platform"]
        assert Path(st["data_dir"]).resolve() == data.resolve(), st["data_dir"]
        assert not st.get("udp_error"), st["udp_error"]
        guide = raw("/api/guide").decode()
        assert guide.startswith("# F1 Telemetry Hub user guide"), guide[:60]
        for path, needle in (("/", 'data-route="guide"'), ("/js/main.js", "rig"), ("/js/views/live.js", "darwin"),
                             ("/js/views/rig.js", "Rig display"), ("/css/app.css", ".rig")):
            assert needle in raw(path).decode(), f"{path} doesn't contain {needle!r}"
        print(f"dashboard, pages and guide ({len(guide)} chars) served")

        t0 = time.time()
        second = subprocess.run(cmd, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        print(f"second start: exit {second.returncode} after {time.time() - t0:.1f} s: {second.stdout.strip()[:80]}")
        assert second.returncode == 0 and "already running" in second.stdout, second.stdout + second.stderr
        assert proc.poll() is None, "the first copy stopped"

        sim = Simulator("127.0.0.1", UDP_PORT, "race", laps=10, speed=8, rate=30, seed=12, circuit=7,
                        tyre_deg=0.0006)
        sim.start()
        got_strategy = got_lap = False
        awake = []
        while sim.running:
            time.sleep(1)
            s = call("/api/live/strategy")
            got_strategy = got_strategy or bool(s.get("available") and s.get("plans"))
            got_lap = got_lap or call("/api/live/lap")["n"] > 50
            if len(awake) < 3:
                awake.append(keeping_awake(proc, Path(a.app).name))
        print(f"race simulated: strategy {got_strategy}, lap in progress {got_lap}, "
              f"keeping the computer awake {'unknown here' if None in awake else any(awake)}")
        assert got_strategy and got_lap
        assert None in awake or any(awake), "the app let the computer sleep while the game was sending"

        race = wait(lambda: next((s for s in call("/api/sessions?limit=50") if s["laps_completed"] >= 8), None),
                    20, "the race's laps to be saved")
        laps = call(f"/api/sessions/{race['id']}")["laps"]
        lap = next(l for l in laps if l["sample_count"])
        assert call(f"/api/laps/{lap['id']}/telemetry")["cols"]["d"], "the lap has no telemetry"
        f = raw(f"/api/laps/{lap['id']}/export")
        g = call("/api/guest-laps", f, "POST")
        assert g["id"] < 0 and call(f"/api/laps/{g['id']}/telemetry")["cols"]["d"]
        call(f"/api/guest-laps/{g['id']}", method="DELETE")
        print(f"{race['laps_completed']} laps saved; lap file round trip {len(f)} bytes")

        code = stop(proc)
        if os.name != "nt":
            assert code == 0, f"the app exited with {code} after Ctrl+C"
        assert (data / "f1telemetry.db").exists()
        print("stopped cleanly" if os.name != "nt" else "stopped")
        ok = True
        print("SMOKE TEST PASSED")
    finally:
        if proc.poll() is None:
            stop(proc)
        if not ok:
            print("---- the app's output ----")
            print(log.read_text(encoding="utf-8", errors="replace")[-6000:])
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
