"""Recordings: the game's raw UDP data saved to a file while you drive, and played back later.

A recording holds every datagram exactly as the game sent it, with its arrival time, so a replay goes
through the very same code as the live session (laps, micro-sectors, race engineer and all). There is one
file per game session (the game gives every session its own UID), in the "recordings" folder of the data
folder: a gzip stream of "F1REC1\\n" followed by (milliseconds since the start, length, datagram) records,
with a small .json file beside it describing the recording.

A replay runs on its own copy of the history with the recorded session itself taken out, so personal
bests, micro-sector records and the race engineer behave as they did on the day, and nothing it records
is added to the real history.
"""
from __future__ import annotations

import gzip
import json
import queue
import re
import sqlite3
import struct
import threading
import time
import zlib
from datetime import datetime
from pathlib import Path

from .recorder import Recorder
from .storage import Storage

MAGIC = b"F1REC1\n"
REC = struct.Struct("<IH")   # milliseconds since the start of the recording, datagram length
FMT = struct.Struct("<H")    # packet format, first field of every packet header
UID = struct.Struct("<Q")    # session UID, at byte 7 of every packet header
HEADER_SIZE = 29
EXT = ".f1rec"
IDLE_CLOSE_S = 30.0          # a recording ends after this long without data
FLUSH_S = 10.0               # what an app crash can cost at most
NAME_RX = re.compile(r"^[\w\-]+\.f1rec$")
SPEEDS = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0)


def meta_path(path: Path) -> Path:
    return path.with_suffix(".json")


def read_meta(path: Path) -> dict:
    try:
        return json.loads(meta_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_meta(path: Path, meta: dict):
    try:
        meta_path(path).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    except OSError:
        pass


def read_packets(path: Path):
    """Yields (seconds since the start, datagram). A recording cut short (the app closed while it was
    being written) simply ends where the data stops."""
    with gzip.open(path, "rb") as f:
        if f.read(len(MAGIC)) != MAGIC:
            raise ValueError(f"{path.name} is not a recording")
        while True:
            try:
                head = f.read(REC.size)
                if len(head) < REC.size:
                    return
                ms, n = REC.unpack(head)
                data = f.read(n)
            except (EOFError, OSError, zlib.error):
                return
            if len(data) < n:
                return
            yield ms / 1000.0, data


def is_name(name: str) -> bool:
    return bool(NAME_RX.match(name or ""))


# --------------------------------------------------------------------------- capture
class _Writer:
    def __init__(self, path: Path, t0: float, uid: int, data: bytes):
        self.path, self.t0, self.uid = path, t0, uid
        self.f = gzip.open(path, "wb", compresslevel=3)
        self.f.write(MAGIC)
        self.packets = 0
        self.last = t0
        self.flushed = t0
        self.meta = {"version": 1, "started_at": datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
                     "session_uid": str(uid) if uid else None, "packet_format": FMT.unpack_from(data, 0)[0],
                     "game_year": data[2], "packets": 0, "duration_s": None}
        _write_meta(path, self.meta)

    def write(self, t: float, data: bytes):
        self.f.write(REC.pack(max(0, int((t - self.t0) * 1000)), len(data)))
        self.f.write(data)
        self.packets += 1
        self.last = t
        if t - self.flushed > FLUSH_S:
            self.f.flush()
            self.flushed = t

    def close(self):
        try:
            self.f.close()
        finally:
            self.meta.update(packets=self.packets, duration_s=round(self.last - self.t0, 1),
                             ended_at=datetime.fromtimestamp(self.last).isoformat(timespec="seconds"),
                             session_uid=str(self.uid) if self.uid else None)
            _write_meta(self.path, self.meta)


class Capture:
    """Writes every datagram from the game to a recording while armed: by the Record button, or always
    when auto-record is on. The UDP thread only queues; a writer thread compresses and writes."""

    def __init__(self, folder: Path, settings: dict, paused=lambda: False):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.paused = paused            # e.g. while the demo is running
        self.manual = False
        self.protected: set[str] = set()  # recordings being replayed are never cleaned up
        self.cur: _Writer | None = None
        self.lock = threading.Lock()
        self.q: queue.SimpleQueue = queue.SimpleQueue()
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self.thread.start()

    @property
    def auto(self) -> bool:
        return bool(self.settings.get("auto_record"))

    @property
    def armed(self) -> bool:
        return self.manual or self.auto

    def feed(self, data: bytes):
        """Called for every datagram the listener receives."""
        if self.armed and not self.paused():
            self.q.put((time.time(), data))

    def set_manual(self, on: bool):
        self.manual = bool(on)
        self.q.put((time.time(), None))  # wakes the writer so a stop takes effect now

    def info(self) -> dict:
        with self.lock:
            w = self.cur
            size = None
            if w:
                try:
                    size = w.path.stat().st_size
                except OSError:
                    pass
            return {"armed": self.armed, "manual": self.manual, "auto": self.auto, "active": bool(w),
                    "name": w.path.name if w else None, "seconds": round(w.last - w.t0, 1) if w else 0,
                    "packets": w.packets if w else 0, "bytes": size}

    def current_name(self):
        with self.lock:
            return self.cur.path.name if self.cur else None

    def shutdown(self):
        self._stop.set()
        self.q.put((time.time(), None))
        self.thread.join(timeout=3)

    def _run(self):
        while not self._stop.is_set():
            try:
                t, data = self.q.get(timeout=1.0)
            except queue.Empty:
                t, data = time.time(), None
            with self.lock:
                try:
                    if data is not None and self.armed:
                        self._write(t, data)
                    if self.cur and (not self.armed or time.time() - self.cur.last > IDLE_CLOSE_S):
                        self._close()
                except OSError as e:  # disk full, folder gone...
                    print(f"[warn] recording stopped: {e}")
                    self.cur = None
                    self.manual = False
        with self.lock:
            self._close()

    def _write(self, t: float, data: bytes):
        if len(data) < HEADER_SIZE or not 2020 <= FMT.unpack_from(data, 0)[0] <= 2100:
            return  # not F1 telemetry
        uid = UID.unpack_from(data, 7)[0]
        if self.cur and uid and self.cur.uid and uid != self.cur.uid:
            self._close()  # a new session: a new file
        if not self.cur:
            self.cur = _Writer(self._new_path(t), t, uid, data)
        elif uid and not self.cur.uid:
            self.cur.uid = uid
        self.cur.write(t, data)

    def _new_path(self, t: float) -> Path:
        base = datetime.fromtimestamp(t).strftime("%Y-%m-%d_%H-%M-%S")
        path, n = self.folder / (base + EXT), 2
        while path.exists():
            path, n = self.folder / f"{base}_{n}{EXT}", n + 1
        return path

    def _close(self):
        if not self.cur:
            return
        w, self.cur = self.cur, None
        w.close()
        if w.packets == 0:
            delete(w.path)
        self._enforce_cap()

    def _enforce_cap(self):
        """Removes the oldest recordings once they take more than the size limit."""
        cap = max(1, int(self.settings.get("recordings_max_gb") or 5)) * 1024 ** 3
        files = []
        for p in self.folder.glob("*" + EXT):
            try:
                files.append((p.stat().st_mtime, p.stat().st_size, p))
            except OSError:
                pass
        total = sum(f[1] for f in files)
        for _, size, p in sorted(files):
            if total <= cap:
                break
            if p.name in self.protected:
                continue
            delete(p)
            total -= size


def delete(path: Path):
    for p in (path, meta_path(path)):
        try:
            p.unlink()
        except OSError:
            pass


def list_recordings(folder: Path, store, active: str | None = None) -> list[dict]:
    out = []
    for p in sorted(Path(folder).glob("*" + EXT), reverse=True):
        try:
            st = p.stat()
        except OSError:
            continue
        meta = read_meta(p)
        item = {
            "name": p.name, "size": st.st_size, "recording": p.name == active,
            "started_at": meta.get("started_at") or datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "duration_s": meta.get("duration_s"), "packets": meta.get("packets"),
            "game_year": meta.get("game_year"), "packet_format": meta.get("packet_format"), "session": None,
        }
        uid = meta.get("session_uid")
        row = store.get_session_by_uid(uid) if uid else None
        if row:
            s = store.get_session(row["id"]) or {}
            item["session"] = {k: s.get(k) for k in ("id", "track_id", "session_type", "category", "best_lap_ms",
                                                     "laps_completed", "total_laps", "game_mode", "started_at")}
        out.append(item)
    return out


def recording_for(folder: Path, uid: str) -> str | None:
    """Name of the newest recording of the session with this UID."""
    for p in sorted(Path(folder).glob("*" + EXT), reverse=True):
        if read_meta(p).get("session_uid") == uid:
            return p.name
    return None


# --------------------------------------------------------------------------- replay
class Replay:
    """Plays a recording into its own Recorder at a chosen speed, with pause and seek."""

    def __init__(self, app, path: Path, speed: float = 1.0):
        self.app = app
        self.path = Path(path)
        self.name = self.path.name
        self.meta = read_meta(self.path)
        self.duration = self.meta.get("duration_s")
        self.speed = speed if speed in SPEEDS else 1.0
        self.paused = False
        self.done = False
        self.error = None
        self.pos = 0.0
        self.rec: Recorder | None = None
        self.store: Storage | None = None
        self.tmp = self.path.parent / ".replay.db"
        self._seek = None
        self._ff = None
        self._anchor_wall = time.time()
        self._anchor_t = 0.0
        self._cmd = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="replay", daemon=True)

    # ---------------------------------------------------------------- control (any thread)
    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self.thread.join(timeout=5)
        if self.store:
            self.store.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(self.tmp) + suffix).unlink()
            except OSError:
                pass

    def pause(self, on: bool):
        with self._cmd:
            if self.paused and not on:
                self._anchor(self.pos)
                if self.rec:
                    self.rec.last_packet_at = time.time()  # a long pause is not the game going quiet
            self.paused = bool(on)
        self._wake.set()

    def set_speed(self, v: float):
        with self._cmd:
            self.speed = min(SPEEDS, key=lambda s: abs(s - float(v)))
            self._anchor(self.pos)
        self._wake.set()

    def seek(self, seconds: float):
        with self._cmd:
            self._seek = max(0.0, float(seconds))
        self._wake.set()

    def tick(self):
        if self.rec and not self.paused and not self._ff:
            self.rec.tick()

    def info(self) -> dict:
        return {"running": True, "name": self.name, "pos_s": round(self.pos, 1), "duration_s": self.duration,
                "speed": self.speed, "paused": self.paused, "done": self.done, "seeking": self._ff is not None,
                "loading": self.rec is None and not self.error, "error": self.error,
                "started_at": self.meta.get("started_at"), "session": self._session_info()}

    def _session_info(self):
        rec = self.rec
        if not rec or not rec.session:
            return None
        s = rec.session
        return {"track_id": s.get("track_id"), "session_type": s.get("session_type")}

    # ---------------------------------------------------------------- playback thread
    def _anchor(self, t):
        self._anchor_wall, self._anchor_t = time.time(), t

    def _prepare(self):
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(self.tmp) + suffix).unlink()
            except OSError:
                pass
        dst = sqlite3.connect(str(self.tmp))
        try:
            with self.app.store.lock:
                self.app.store.db.backup(dst)
        finally:
            dst.close()
        self.store = Storage(self.tmp)
        self.uids = {self.meta["session_uid"]} if self.meta.get("session_uid") else self._scan_uids()
        if self.duration is None:  # the app closed while this was being recorded
            last = 0.0
            for t, _ in read_packets(self.path):
                last = t
            self.duration = round(last, 1)

    def _scan_uids(self) -> set:
        uids = set()
        for i, (_, data) in enumerate(read_packets(self.path)):
            if len(data) >= HEADER_SIZE and UID.unpack_from(data, 7)[0]:
                uids.add(str(UID.unpack_from(data, 7)[0]))
            if i > 20000:
                break
        return uids

    def _fresh_recorder(self):
        """A new Recorder on the copy of the history, without the recorded session (or an earlier pass of it)."""
        for uid in self.uids:
            row = self.store.get_session_by_uid(uid)
            if row:
                self.store.delete_session(row["id"])
        self.rec = Recorder(self.store, dict(self.app.settings))

    def _run(self):
        try:
            self._prepare()
            self._loop()
        except Exception as e:  # noqa: BLE001 - shown on the Live page instead of a dead replay
            self.error = f"{type(e).__name__}: {e}"
            print(f"[warn] replay failed: {e!r}")

    def _loop(self):
        gen, pending = None, None
        while not self._stop.is_set():
            if gen is None:
                self._fresh_recorder()
                gen, pending, self.pos = read_packets(self.path), None, 0.0
                self._anchor(0.0)
            with self._cmd:
                seek, self._seek = self._seek, None
            if seek is not None:
                if seek < self.pos:
                    gen, self._ff = None, seek  # back to the start, then fast-forward
                    continue
                self._ff = seek
                self.done = False
            if self.paused and self._ff is None:
                self._wake.wait(0.25)
                self._wake.clear()
                continue
            if pending is None:
                try:
                    pending = next(gen)
                except StopIteration:
                    self.done, self._ff = True, None
                    self._wake.wait(0.5)
                    self._wake.clear()
                    continue
            t, data = pending
            if self._ff is None:
                with self._cmd:
                    delay = self._anchor_wall + (t - self._anchor_t) / self.speed - time.time()
                if delay > 0.002:
                    self._wake.wait(min(delay, 0.1))
                    self._wake.clear()
                    continue
            elif t >= self._ff:
                self._ff = None
                self._anchor(t)
                self.rec.engineer.pending = []  # nothing queued while skipping is worth saying now
            self.rec.handle(data)
            self.pos, pending, self.done = t, None, False
