"""Bundled circuit outlines (circuits.json) and lining them up with the game's world coordinates.

The game never sends a track layout, so the app ships an outline of every circuit in real-world metres
(+X east, +Z south, built by tools/make_circuits.py from the MIT-licensed f1-circuits data). The game's own
coordinates are the same circuit turned, possibly mirrored, and moved. `align` finds that transform from a
stretch of driving (lap distance + position); after that the outline can be given in game coordinates and
every map can show the circuit north-up. Until then `approx_xz` puts cars on the outline by lap distance.
"""
from __future__ import annotations

import bisect
import json
import math
import sys
from functools import lru_cache
from pathlib import Path

MAX_RMS = 12.0     # m: worst average distance between driven line and outline that still counts as a match
MIN_SPAN = 700.0   # m of lap driven before a match is attempted
MIN_TURN = 1.6     # rad of heading change in that stretch, so straights alone can't be matched


def _path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "circuits.json"
    return Path(__file__).resolve().parent / "circuits.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"tracks": {}, "reverse": {}}


class Circuit:
    """Closed outline starting at (or near) the start line, in race direction."""

    def __init__(self, name: str, pts: list[tuple[float, float]]):
        self.name, self.pts = name, pts
        n = len(pts)
        self.cum = [0.0]
        for i in range(n):
            self.cum.append(self.cum[-1] + math.dist(pts[i], pts[(i + 1) % n]))
        self.length = self.cum[-1]

    def at(self, u: float) -> tuple[float, float]:
        u %= self.length
        i = min(bisect.bisect_right(self.cum, u) - 1, len(self.pts) - 1)
        a, b = self.pts[i], self.pts[(i + 1) % len(self.pts)]
        f = (u - self.cum[i]) / ((self.cum[i + 1] - self.cum[i]) or 1.0)
        return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f

    def nearest(self, x: float, z: float, u0: float, window: float = 80.0) -> tuple[float, float]:
        """Closest outline point to (x, z) within `window` metres of arc length u0."""
        n = len(self.pts)
        i0 = bisect.bisect_right(self.cum, u0 % self.length) - 1
        span = int(window / (self.length / n)) + 2
        best, bd = None, math.inf
        for k in range(i0 - span, i0 + span + 1):
            a, b = self.pts[k % n], self.pts[(k + 1) % n]
            vx, vz = b[0] - a[0], b[1] - a[1]
            ll = vx * vx + vz * vz or 1.0
            f = max(0.0, min(1.0, ((x - a[0]) * vx + (z - a[1]) * vz) / ll))
            px, pz = a[0] + vx * f, a[1] + vz * f
            d = (px - x) ** 2 + (pz - z) ** 2
            if d < bd:
                bd, best = d, (px, pz)
        return best


@lru_cache(maxsize=64)
def circuit(track_id) -> Circuit | None:
    if track_id is None:
        return None
    data = _data()
    key = str(track_id)
    rev = data.get("reverse", {}).get(key)
    t = data["tracks"].get(str(rev) if rev is not None else key)
    if not t:
        return None
    pts = [tuple(p) for p in t["pts"]]
    if rev is not None:  # reverse layout: same start, other direction
        pts = [pts[0]] + pts[:0:-1]
    return Circuit(t["name"], pts)


# ---------------------------------------------------------------------------- alignment
def _procrustes(P, Q, mirror):
    """Best scale * rotation (after an optional mirror of Z) taking points P onto Q, both lists of (x, z).
    Returns (cos, sin, scale, pc, qc, rms)."""
    n = len(P)
    pcx = sum(p[0] for p in P) / n
    pcz = sum(p[1] for p in P) / n
    qcx = sum(q[0] for q in Q) / n
    qcz = sum(q[1] for q in Q) / n
    m = -1.0 if mirror else 1.0
    sxx = sxy = spp = sqq = 0.0
    for (px, pz), (qx, qz) in zip(P, Q):
        px -= pcx
        pz = (pz - pcz) * m
        qx -= qcx
        qz -= qcz
        sxx += px * qx + pz * qz
        sxy += px * qz - pz * qx
        spp += px * px + pz * pz
        sqq += qx * qx + qz * qz
    norm = math.hypot(sxx, sxy)
    if spp <= 0 or norm <= 0:
        return None
    rms = math.sqrt(max(sqq - norm * norm / spp, 0.0) / n)
    return sxx / norm, sxy / norm, norm / spp, (pcx, pcz), (qcx, qcz), rms


def _frame(c, s, scale, pc, qc, mirror):
    # display = A @ game + t, with A = scale * R(theta) * diag(1, -1 if mirror)
    m = -1.0 if mirror else 1.0
    a, b, cc, d = scale * c, -scale * s * m, scale * s, scale * c * m
    return {"a": a, "b": b, "c": cc, "d": d, "tx": qc[0] - (a * pc[0] + b * pc[1]), "tz": qc[1] - (cc * pc[0] + d * pc[1])}


def _apply(f, x, z):
    return f["a"] * x + f["b"] * z + f["tx"], f["c"] * x + f["d"] * z + f["tz"]


def _turning(pts):
    total, prev = 0.0, None
    for a, b in zip(pts[::3], pts[3::3]):
        hd = math.atan2(b[1] - a[1], b[0] - a[0])
        if prev is not None:
            total += abs((hd - prev + math.pi) % (2 * math.pi) - math.pi)
        prev = hd
    return total


def align(circ: Circuit, samples, track_len) -> dict | None:
    """Transform from game coordinates to the circuit's, from (lap_distance, x, z) samples of driving.

    Lap distance gives the correspondence: game distance d sits at circuit arc offset + dir * d * ratio.
    A coarse search over offset, direction and mirroring, then a finer one, then a few rounds of matching
    each driven point to the nearest outline point (dropping the worst 15%, e.g. the pit lane).
    """
    track_len = track_len or circ.length
    pts, last = [], None
    for d, x, z in sorted((s for s in samples if s[0] is not None and s[1] is not None and 0 <= s[0] <= track_len),
                          key=lambda s: s[0]):
        if last is None or d - last >= 10:
            pts.append((d, x, z))
            last = d
    if len(pts) < 50 or pts[-1][0] - pts[0][0] < MIN_SPAN or _turning([(p[1], p[2]) for p in pts]) < MIN_TURN:
        return None
    ratio = circ.length / track_len
    P = [(p[1], p[2]) for p in pts]

    def score(sub, phi, direction, mirror):
        Q = [circ.at(phi + direction * p[0] * ratio) for p in sub]
        return _procrustes([(p[1], p[2]) for p in sub], Q, mirror)

    coarse = pts[::max(1, len(pts) // 60)]
    results = []
    for direction in (1, -1):
        for k in range(int(circ.length // 8)):
            phi = k * 8.0
            Q = [circ.at(phi + direction * p[0] * ratio) for p in coarse]
            Pc = [(p[1], p[2]) for p in coarse]
            for mirror in (False, True):
                r = _procrustes(Pc, Q, mirror)
                if r and 0.85 < r[2] < 1.15:
                    results.append((r[5], phi, direction, mirror))
    if not results:
        return None
    results.sort()
    best = results[0]
    # a clearly different placement that fits almost as well means the stretch is ambiguous
    for rms, phi, direction, mirror in results[1:]:
        dphi = abs((phi - best[1] + circ.length / 2) % circ.length - circ.length / 2)
        if (direction, mirror) != best[2:] or dphi > 60:
            if rms < best[0] * 1.25:
                return None
            break
    _, phi0, direction, mirror = best
    phi = min((phi0 + k * 0.5 for k in range(-16, 17)), key=lambda f: (score(pts, f, direction, mirror) or (0, 0, 0, 0, 0, math.inf))[5])
    r = score(pts, phi, direction, mirror)
    if not r:
        return None
    f = _frame(*r[:5], mirror)
    us = [phi + direction * p[0] * ratio for p in pts]
    rms = r[5]
    for _ in range(6):
        pairs = []
        for (x, z), u in zip(P, us):
            X, Z = _apply(f, x, z)
            q = circ.nearest(X, Z, u)
            pairs.append(((X - q[0]) ** 2 + (Z - q[1]) ** 2, (x, z), q))
        pairs.sort(key=lambda t: t[0])
        keep = pairs[:max(30, int(len(pairs) * 0.85))]
        r = _procrustes([p[1] for p in keep], [p[2] for p in keep], mirror)
        if not r:
            break
        f = _frame(*r[:5], mirror)
        rms = r[5]
    if rms > MAX_RMS or not 0.9 < r[2] < 1.1:
        return None
    out = {k: round(f[k], 6) for k in ("a", "b", "c", "d")}
    out.update({"tx": round(f["tx"], 2), "tz": round(f["tz"], 2), "mirror": mirror, "rms": round(rms, 2),
                "scale": round(r[2], 4), "offset": round(phi % circ.length, 1), "dir": direction,
                "ratio": round(ratio, 6), "points": len(pts)})
    return out


def fit_error(circ: Circuit, frame: dict, samples, track_len) -> float | None:
    """Median distance (m) between driven points and the outline under `frame`: does it still fit?"""
    track_len = track_len or circ.length
    errs, last = [], None
    for d, x, z in samples:
        if d is None or x is None or not 0 <= d <= track_len or (last is not None and d - last < 20):
            continue
        last = d
        X, Z = _apply(frame, x, z)
        q = circ.nearest(X, Z, frame["offset"] + frame["dir"] * d * frame["ratio"])
        errs.append(math.hypot(X - q[0], Z - q[1]))
    if len(errs) < 20:
        return None
    errs.sort()
    return errs[len(errs) // 2]


# ---------------------------------------------------------------------------- outlines
def outline_in_game(circ: Circuit, frame: dict, track_len) -> list[list]:
    """The circuit as [lap_distance, x, z] in game coordinates (needs an `align` result)."""
    track_len = track_len or circ.length
    det = frame["a"] * frame["d"] - frame["b"] * frame["c"]
    ia, ib, ic, idd = frame["d"] / det, -frame["b"] / det, -frame["c"] / det, frame["a"] / det
    out = []
    for i, (X, Z) in enumerate(circ.pts):
        X -= frame["tx"]
        Z -= frame["tz"]
        d = (frame["dir"] * (circ.cum[i] - frame["offset"]) / frame["ratio"]) % track_len
        out.append([round(d), round(ia * X + ib * Z, 1), round(ic * X + idd * Z, 1)])
    out.sort(key=lambda p: p[0])
    return out


def outline_display(circ: Circuit, track_len) -> list[list]:
    """The circuit as [lap_distance, x, z] in its own (north-up) coordinates, before it is lined up."""
    ratio = circ.length / (track_len or circ.length)
    return [[round(circ.cum[i] / ratio), x, z] for i, (x, z) in enumerate(circ.pts)]


def approx_xz(circ: Circuit, lap_distance, track_len) -> tuple[float, float]:
    """Where a car at this lap distance is on the un-aligned outline (start line = start of the outline)."""
    x, z = circ.at((lap_distance or 0.0) * circ.length / (track_len or circ.length))
    return round(x, 1), round(z, 1)
