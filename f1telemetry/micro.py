"""Micro-sectors: every sector split into equal stretches, timed live and stored with each lap.

A micro-sector is purple when it beats your own record there (your best time for that stretch over
every valid lap on this track, in this kind of session and generation of car), green when it is at
least as quick as your personal-best lap there, and yellow when it is slower.
"""
from __future__ import annotations

import bisect

PER_SECTOR = 8
RECORD, FASTER, SLOWER, FIRST = "p", "g", "y", "n"  # FIRST: nothing recorded there yet to compare with


def bounds(track_len, s2=None, s3=None, per=PER_SECTOR) -> list[float] | None:
    """Lap distances where the micro-sectors start, plus the lap length at the end."""
    if not track_len or track_len < 500:
        return None
    if not s2 or not s3 or not 0 < s2 < s3 < track_len:
        s2, s3 = track_len / 3, 2 * track_len / 3
    out = []
    for a, b in ((0.0, s2), (s2, s3), (s3, float(track_len))):
        out += [a + (b - a) * i / per for i in range(per)]
    out.append(float(track_len))
    return [round(x, 1) for x in out]


def key_of(bnds) -> str:
    """Identifies a set of boundaries; stored times only count where the boundaries are the same."""
    n = len(bnds) - 1
    per = n // 3
    return f"{n}:{round(bnds[-1])}:{round(bnds[per])}:{round(bnds[2 * per])}"


def label(i, per=PER_SECTOR) -> str:
    return f"{i // per + 1}.{i % per + 1}"


def times_from_cols(cols, bnds, lap_ms) -> list | None:
    """Micro-sector times (ms) of a recorded lap, from its distance / lap-time samples."""
    ds, ts, last = [], [], -1e9
    for d, t in zip(cols.get("d") or [], cols.get("t") or []):
        if d is None or t is None or d < 0 or d <= last:
            continue
        ds.append(d)
        ts.append(t)
        last = d
    if len(ds) < 20 or not lap_ms:
        return None

    def at(b):
        if b < ds[0] or b > ds[-1]:
            return None
        i = bisect.bisect_left(ds, b)
        if i == 0:
            return ts[0]
        d0, d1, t0, t1 = ds[i - 1], ds[i], ts[i - 1], ts[i]
        return t0 + (t1 - t0) * (b - d0) / (d1 - d0)

    cross = [0.0 if ds[0] < 30 else None] + [at(b) for b in bnds[1:-1]] + [lap_ms / 1000.0]
    out = []
    for a, b in zip(cross, cross[1:]):
        out.append(round((b - a) * 1000) if a is not None and b is not None and b > a else None)
    return out if sum(v is not None for v in out) * 2 >= len(out) else None


def status(ms, best, ref) -> str | None:
    if ms is None:
        return None
    if best is None and ref is None:
        return FIRST
    if best is not None and ms < best:
        return RECORD
    if ref is not None and ms <= ref:
        return FASTER
    return SLOWER


class MicroTimer:
    """Times the micro-sectors of the lap being driven, from the Lap Data stream (lap time, lap distance)."""

    def __init__(self):
        self.bounds = None
        self.key = None
        self.scope = None     # (track, session category, 2026 cars, key): whose records these are
        self.best = None      # record per micro-sector (ms)
        self.ref = None       # the personal-best lap's times
        self.ref_lap_ms = None
        self.cur = self.last = None   # [[ms, status, ms vs PB lap] or None] per micro-sector
        self.seq = 0          # counts finished micro-sectors, so the dashboard can play a tone for each
        self.last_done = None
        self._cross = []
        self._next = 0
        self._prev = None

    @property
    def n(self):
        return len(self.bounds) - 1 if self.bounds else 0

    def configure(self, bnds, scope):
        if bnds != self.bounds:
            self.bounds = bnds
            self.key = key_of(bnds) if bnds else None
            self.cur = self.last = None
        if scope != self.scope:
            self.scope = scope
            self.best = self.ref = self.ref_lap_ms = None

    def set_records(self, scope, best, ref, ref_lap_ms):
        """Records loaded from the database; keeps anything quicker set meanwhile."""
        n = self.n
        if not n or scope != self.scope:
            return
        mine = self.best or [None] * n
        self.best = [min((v for v in (a, b) if v is not None), default=None)
                     for a, b in zip(best or [None] * n, mine)]
        if ref and (self.ref_lap_ms is None or (ref_lap_ms and ref_lap_ms < self.ref_lap_ms)):
            self.ref, self.ref_lap_ms = ref, ref_lap_ms

    def begin(self, t, d):
        n = self.n
        if not n:
            self.cur = None
            return
        if self.cur and any(self.cur):
            self.last = self.cur
        self.cur = [None] * n
        self._cross = [None] * (n + 1)
        if d < 30:  # at the line (or on a Time Trial run-up before it)
            self._cross[0] = 0.0
            self._next = 1
        else:       # joined mid-lap: the micro-sector we're in can't be timed
            self._next = max(1, bisect.bisect_right(self.bounds, d))
        self._prev = (t, d)

    def update(self, t, d) -> list[int]:
        """Feeds one Lap Data sample; returns the micro-sectors finished by it."""
        if self.cur is None:
            return []
        prev, self._prev = self._prev, (t, d)
        if prev is None:
            return []
        t0, d0 = prev
        if t < t0 - 0.2:  # the timer went back
            if t > 0.3 and 0 <= d < d0:
                self._rewind(d)  # a flashback within the lap
            return []
        # timer stopped (Time Trial run-up), going backwards, or a jump no car can make (put back on track)
        if not (t > t0 and d > d0) or d - d0 > 150 or d - d0 > 130 * (t - t0) + 5:
            return []
        done = []
        while self._next < self.n and d0 < self.bounds[self._next] <= d:
            k = self._next
            tb = t0 + (t - t0) * (self.bounds[k] - d0) / (d - d0)
            self._cross[k] = tb
            if self._cross[k - 1] is not None:
                self._finish_one(k - 1, round((tb - self._cross[k - 1]) * 1000))
                done.append(k - 1)
            self._next += 1
        return done

    def finish(self, lap_ms) -> list[int]:
        """The lap is over: times the last micro-sector from the official lap time."""
        n = self.n
        if self.cur is None or not n or not lap_ms:
            return []
        a = self._cross[n - 1]
        if a is None or self.cur[n - 1] is not None:
            return []
        ms = round(lap_ms - a * 1000)
        if ms <= 0:
            return []
        self._finish_one(n - 1, ms)
        return [n - 1]

    def lap_times(self):
        """This lap's micro-sector times when every one of them was timed live, else None."""
        if not self.cur or not all(self.cur):
            return None
        return [c[0] for c in self.cur]

    def commit(self, times, new_pb_ms=None):
        """A valid lap: its micro-sectors become records where they're quicker; a new PB becomes the reference."""
        if not times or not self.n or len(times) != self.n:
            return
        best = self.best or [None] * self.n
        self.best = [v if b is None or (v is not None and v < b) else b for v, b in zip(times, best)]
        if new_pb_ms and all(v is not None for v in times):
            self.ref, self.ref_lap_ms = list(times), new_pb_ms

    def ideal_ms(self):
        return sum(self.best) if self.best and all(v is not None for v in self.best) else None

    def _finish_one(self, i, ms):
        best = self.best[i] if self.best else None
        ref = self.ref[i] if self.ref else None
        self.cur[i] = [ms, status(ms, best, ref), ms - ref if ref is not None else None]
        self.seq += 1
        self.last_done = [i, self.cur[i][1]]

    def _rewind(self, d):
        k = max(1, bisect.bisect_right(self.bounds, d))
        for j in range(k, self.n + 1):
            self._cross[j] = None
        for j in range(k - 1, self.n):
            self.cur[j] = None
        self._next = k

    def snapshot(self):
        if not self.n or self.cur is None:
            return None
        return {"per": self.n // 3, "cur": self.cur, "last": self.last, "at": min(self._next - 1, self.n - 1),
                "ideal_ms": self.ideal_ms(), "has_ref": bool(self.ref), "has_best": bool(self.best),
                "seq": self.seq, "last_done": self.last_done}
