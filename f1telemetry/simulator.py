"""Synthetic F1 25 UDP packet generator.

Drives 20 cars (22 with the 2026 grid) around a fictional circuit ("Demo Circuit",
track id 99) and emits byte-exact F1 25 packets in format 2025 or 2026 to a UDP
target. Used for the in-app demo mode and for end-to-end tests without the game.

`circuit=<track id>` drives a real circuit from circuits.json instead, turned and moved
into made-up "game" coordinates, to test lining the bundled outlines up. Those laps are
stored under the real track id, so only use it with a separate data folder.

A Time Trial starts like the game's: on a run-up at speed, with the lap timer at zero until
the line, and lap 1 is a timed lap. `restart_lap=N` does what "Restart lap" does early in
lap N: the timer drops to zero, the car is put back on the run-up and crosses the line
again, all on the same lap number.
"""
from __future__ import annotations

import argparse
import copy
import math
import random
import socket
import struct
import threading
import time

from . import circuits
from . import packets as P

DEMO_TRACK_ID = 99
DEMO_SEASON_LINK = 990099  # every demo career weekend lands in the same demo season
G = 9.81
RUNUP_M = 1067.0  # a Time Trial restart puts the car this far before the line (F1 25, Silverstone)

CONTROL_POINTS = [
    (0, 0), (620, -10), (1010, 40), (1160, 190), (1110, 390), (900, 460), (760, 610), (820, 810),
    (1010, 900), (1120, 1100), (960, 1260), (610, 1210), (420, 1010), (210, 1060), (10, 960),
    (-150, 710), (-90, 450), (-260, 260), (-210, 70),
]

DRIVER_NAMES = [
    "Player", "A. Moreau", "K. Tanaka", "L. Fischer", "M. Silva", "J. Okafor", "R. Novak",
    "T. Lindqvist", "S. Ibrahim", "D. Kowalski", "E. Marino", "P. Haddad", "C. Duarte",
    "N. Volkov", "H. Park", "G. Bianchi", "F. Mensah", "I. Petrov", "B. Larsen", "O. Reyes",
    "V. Costa", "Y. Sato",
]
TEAM_ORDER = [8, 8, 2, 2, 1, 1, 0, 0, 4, 4, 5, 5, 3, 3, 6, 6, 7, 7, 9, 9]
# the 2026 cars: McLaren, Red Bull, Ferrari, Mercedes, Aston Martin, Alpine, Williams, RB, Haas, Audi, Cadillac
TEAM_ORDER_26 = [484, 484, 478, 478, 477, 477, 476, 476, 480, 480, 481, 481, 479, 479, 482, 482, 483, 483,
                 485, 485, 486, 486]


def _catmull_rom_closed(points, samples_per_seg=60):
    out = []
    n = len(points)
    for i in range(n):
        p0, p1, p2, p3 = points[(i - 1) % n], points[i], points[(i + 1) % n], points[(i + 2) % n]
        for s in range(samples_per_seg):
            t = s / samples_per_seg
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            z = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, z))
    return out


# a real circuit in simulated game coordinates: turned, moved and starting 90 m into the outline,
# so lining it up has an offset to find (the game's axes are assumed to need no mirroring)
CIRCUIT_TURN, CIRCUIT_SHIFT, CIRCUIT_START = 0.7, (-420.0, 1350.0), 9


def circuit_points(track_id):
    circ = circuits.circuit(track_id)
    if not circ:
        raise ValueError(f"no bundled outline for track {track_id}")
    pts = circ.pts[CIRCUIT_START:] + circ.pts[:CIRCUIT_START]
    c, s = math.cos(CIRCUIT_TURN), math.sin(CIRCUIT_TURN)
    return [(c * x - s * z + CIRCUIT_SHIFT[0], s * x + c * z + CIRCUIT_SHIFT[1]) for x, z in pts]


class Track:
    def __init__(self, target_length=4800.0, ds=2.0, points=None):
        if points is None:
            raw = _catmull_rom_closed(CONTROL_POINTS)
            per = sum(math.dist(raw[i], raw[(i + 1) % len(raw)]) for i in range(len(raw)))
            scale = target_length / per
            raw = [(x * scale, z * scale) for x, z in raw]
        else:  # real circuit, already in metres every ~10 m
            raw = _catmull_rom_closed(points, samples_per_seg=5)
        # resample at fixed arc length
        cum = [0.0]
        for i in range(1, len(raw) + 1):
            cum.append(cum[-1] + math.dist(raw[i - 1], raw[i % len(raw)]))
        self.length = cum[-1]
        self.ds = ds
        n = int(self.length / ds)
        self.n = n
        self.x, self.z = [], []
        j = 0
        for i in range(n):
            s = i * ds
            while cum[j + 1] < s:
                j += 1
            f = (s - cum[j]) / (cum[j + 1] - cum[j])
            a, b = raw[j % len(raw)], raw[(j + 1) % len(raw)]
            self.x.append(a[0] + (b[0] - a[0]) * f)
            self.z.append(a[1] + (b[1] - a[1]) * f)
        # signed curvature (Menger), smoothed
        k = []
        for i in range(n):
            ax, az = self.x[i - 1], self.z[i - 1]
            bx, bz = self.x[i], self.z[i]
            cx, cz = self.x[(i + 1) % n], self.z[(i + 1) % n]
            cross = (bx - ax) * (cz - az) - (bz - az) * (cx - ax)
            d = math.dist((ax, az), (bx, bz)) * math.dist((bx, bz), (cx, cz)) * math.dist((ax, az), (cx, cz))
            k.append(2 * cross / d if d > 1e-9 else 0.0)
        w = 6
        self.k = [sum(k[(i + o) % n] for o in range(-w, w + 1)) / (2 * w + 1) for i in range(n)]
        self.v = self._speed_profile(1.0)
        # DRS zone = the longest run of near-zero curvature; speed trap at its fastest point
        best, run_start, best_range = 0, None, (0, 0)
        for i in range(2 * n):
            straight = abs(self.k[i % n]) < 0.0025
            if straight and run_start is None:
                run_start = i
            if (not straight or i == 2 * n - 1) and run_start is not None:
                if i - run_start > best and i - run_start < n:
                    best, best_range = i - run_start, (run_start, i)
                run_start = None
        self.drs_zone = ((best_range[0] + 60) % n * ds, best_range[1] % n * ds)
        # active aero zones (format 2026): every straight longer than 250 m
        self.straights = []
        i0 = next((i for i in range(n) if abs(self.k[i]) >= 0.0025), 0)  # start scanning in a corner
        run = None
        for j in range(n + 1):
            straight = j < n and abs(self.k[(i0 + j) % n]) < 0.0025
            if straight and run is None:
                run = j
            elif not straight and run is not None:
                if (j - run) * ds > 250:
                    self.straights.append(((i0 + run + 30) % n * ds, (i0 + j) % n * ds))
                run = None
        self.straights.sort()
        self.trap_s = max(range(n), key=lambda i: self.v[i]) * ds

    def _speed_profile(self, grip):
        n = self.n
        vmax = 92.0
        alat = 4.3 * G * grip
        vc = [min(vmax, math.sqrt(alat / abs(k))) if abs(k) > 1e-6 else vmax for k in self.k]
        v = vc[:]
        start = min(range(n), key=lambda i: vc[i])
        for _ in range(2):
            for j in range(1, n + 1):
                i, p = (start + j) % n, (start + j - 1) % n
                acc = max(1.5, 13.0 * (1 - v[p] / 96.0)) * grip
                v[i] = min(v[i], math.sqrt(v[p] ** 2 + 2 * acc * self.ds))
            for j in range(n, 0, -1):
                i, nx = (start + j) % n, (start + j + 1) % n
                v[i] = min(v[i], math.sqrt(v[nx] ** 2 + 2 * 4.8 * G * grip * self.ds))
        return v

    def zone_at(self, lap_s):
        """(in an active aero zone, metres to the next one)."""
        best = None
        for a, b in self.straights:
            if (a <= lap_s <= b) if a < b else (lap_s >= a or lap_s <= b):
                return True, 0
            ahead = (a - lap_s) % self.length
            best = ahead if best is None else min(best, ahead)
        return False, best or 0

    def at(self, s):
        s %= self.length
        i = min(int(s / self.ds), self.n - 1)  # the last stretch before the line is a little longer than ds
        nx = (i + 1) % self.n
        f = min(1.0, (s - i * self.ds) / (self.ds if nx else self.length - i * self.ds))
        x = self.x[i] + (self.x[nx] - self.x[i]) * f
        z = self.z[i] + (self.z[nx] - self.z[i]) * f
        v = self.v[i] + (self.v[nx] - self.v[i]) * f
        acc = (self.v[nx] ** 2 - self.v[i] ** 2) / (2 * self.ds)
        dx, dz = self.x[nx] - self.x[i], self.z[nx] - self.z[i]
        norm = math.hypot(dx, dz) or 1
        return x, z, v, acc, self.k[i], dx / norm, dz / norm


class Car:
    def __init__(self, idx, pace, grid_pos):
        self.idx = idx
        self.pace = pace
        self.s = -12.0 - grid_pos * 9.0
        self.grid = grid_pos + 1
        self.lap = 1
        self.lap_start_t = 0.0
        self.s1 = self.s2 = 0
        self.last_lap_ms = 0
        self.laps: list[list[int]] = []
        self.invalid = 0
        self.finished = False
        self.finish_order = 0
        self.best_ms = None
        self.speed = 0.0
        self.noise = 1.0
        # the player's racing line and braking point vary a little from lap to lap
        self.line_r, self.line_shift, self.brake_shift = 330.0, 0.0, 0.0
        self.pit_status = 0
        self.position = grid_pos + 1
        self.timer_off = False  # after a restart: the lap timer stays at zero until the line


# the player's setup when nothing else is asked for (packets.SETUP_KEYS order, fuel load sent live)
DEFAULT_SETUP = dict(front_wing=28, rear_wing=24, diff_on_throttle=70, diff_off_throttle=55, front_camber=-3.2,
                     rear_camber=-1.6, front_toe=0.05, rear_toe=0.2, front_suspension=22, rear_suspension=8,
                     front_arb=12, rear_arb=6, front_ride_height=32, rear_ride_height=38, brake_pressure=100,
                     brake_bias=56, engine_braking=50, rl_pressure=22.5, rr_pressure=22.5, fl_pressure=25.0,
                     fr_pressure=25.0, ballast=6)


class Simulator:
    def __init__(self, host="127.0.0.1", port=20777, session="race", laps=5, speed=1.0, rate=30,
                 flashback_lap=None, seed=None, loop=False, fmt=2025, circuit=None, restart_lap=None,
                 setup=None, tyre_deg=0.0):
        """session: race | quali | tt | weekend (a Driver Career weekend: qualifying, then the race).

        fmt: UDP packet format, 2025 or 2026 (2026 Season Pack: 2026 cars, 24-car arrays, Car Telemetry 2).
        setup: changes to the player's car setup (keys of packets.SETUP_KEYS); wings, the front anti-roll bar
        and the on-throttle differential move the car's balance the way they would in the game.
        tyre_deg: how much slower the player gets per % of tyre wear (0.0006 is about 0.07 s a lap per lap).
        """
        self.target = (host, port)
        self.setup = dict(DEFAULT_SETUP, **(setup or {}))
        self.tyre_deg = tyre_deg
        self.fmt = fmt
        self.teams = TEAM_ORDER_26 if fmt >= 2026 else TEAM_ORDER
        self.mode = session
        self.session_kind = "quali" if session == "weekend" else session
        self.weekend_link = 0
        self.grid_order = None
        self.total_laps = laps
        self.speed = speed
        self.rate = rate
        self.flashback_lap = flashback_lap
        self.restart_lap = restart_lap
        self.loop = loop
        self.rng = random.Random(seed)
        self.mx_rng = random.Random(None if seed is None else seed + 13)  # own stream: balance noise leaves the race unchanged
        self.track_id = DEMO_TRACK_ID if circuit is None else circuit
        self.track = Track() if circuit is None else Track(points=circuit_points(circuit))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._stop = threading.Event()
        self.thread = None
        self.finished = False

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        self.thread = threading.Thread(target=self.run, name="f1-demo", daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def run(self):
        while not self._stop.is_set():
            if self.mode == "weekend":
                self.weekend_link = self.rng.getrandbits(31)
                self.grid_order = None
                for kind in ("quali", "race"):
                    if self._stop.is_set():
                        break
                    self.session_kind = kind
                    self._run_session()
                    self._stop.wait(2.0)  # back in the garage between sessions
            else:
                self._run_session()
            if not self.loop:
                break
        self.finished = True

    def _new_session(self):
        self.uid = self.rng.getrandbits(63)
        self.session_link = self.rng.getrandbits(31)
        self.t = 0.0
        self.frame = 0
        self.player = 0
        career = self.mode == "weekend"
        self.session_type = {"race": 15, "quali": 8 if career else 5, "tt": 18}[self.session_kind]
        self.game_mode = 28 if career else 5 if self.session_kind == "tt" else 3
        self.rule_set = {"race": 1, "quali": 0, "tt": 2}[self.session_kind]
        n_cars = 1 if self.session_kind == "tt" else len(self.teams)
        self.cars = []
        order = list(range(n_cars))
        if self.session_kind == "race":
            if self.grid_order:  # grid = qualifying result
                order = [self.grid_order.index(i) for i in range(n_cars)]
            else:
                self.rng.shuffle(order)
        for i in range(n_cars):
            # each AI driver keeps a characteristic pace, plus a little day-to-day form
            pace = 1.0 if i == 0 else 0.965 + (i * 7919 % 50) / 1000 + self.rng.uniform(-0.006, 0.006)
            car = Car(i, pace, order[i])
            if self.session_kind == "tt":  # a run-up at speed; the timer starts at the line, still lap 1
                car.s, car.timer_off = -RUNUP_M, True
                car.speed = self.track.at(car.s)[2]
            elif self.session_kind != "race":
                car.s = self.track.length * 0.62 - i * 140  # out lap from the pit exit
            self.cars.append(car)
        self.wear = [0.0, 0.0, 0.0, 0.0]
        self.btemp = [350.0] * 4
        self.tsurf = [85.0] * 4
        self.tinner = [92.0] * 4
        self.fuel = 15.0 if self.session_kind == "race" else 12.0
        self.ers = 4e6
        self.ers_deployed = 0.0
        self.ers_harvested = 0.0
        self.lights_until = 5.0 if self.session_kind == "race" else 0.0
        self.reaction = round(self.rng.uniform(0.18, 0.32), 3)
        self.lights_sent = 0
        self.fastest = None
        self.history_cursor = 0
        self.flashback_done = False
        self.restart_done = False
        self.snapshots = []
        self.fl_wing_damage = 0
        self.end_at = None

    # ------------------------------------------------------------------ simulation
    def _run_session(self):
        self._new_session()
        dt_wall = 1.0 / self.rate
        dt = dt_wall * self.speed
        self._event("SSTA")
        next_t = time.perf_counter()
        tick = 0
        while not self._stop.is_set():
            self._step(dt)
            self._send_all(tick)
            tick += 1
            if self.end_at is not None and self.t >= self.end_at:
                self._send_final()
                self._event("SEND")
                return
            out_laps = 1 if self.session_kind == "quali" else 0
            if self.session_kind != "race" and self.total_laps and self.cars[0].lap > self.total_laps + out_laps:
                if self.session_kind == "quali":
                    self._send_final()
                    self.grid_order = [c.idx for c in sorted(self.cars, key=lambda c: c.position)]
                self._event("SEND")
                return
            next_t += dt_wall
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.perf_counter()

    def _step(self, dt):
        tr = self.track
        if self.t < self.lights_until:
            lights = min(5, int(self.t) + 1)
            if lights > self.lights_sent:
                self.lights_sent = lights
                self._event("STLG", bytes([lights]))
            self.t += dt
            if self.t >= self.lights_until:
                self._event("LGOT")
                for c in self.cars:
                    c.lap_start_t = self.t
            return
        if self.flashback_lap and not self.flashback_done and self.cars[0].lap == self.flashback_lap \
                and (self.cars[0].s % tr.length) > tr.length * 0.6 and len(self.snapshots) > 6:
            self._flashback()
            return
        p = self.cars[0]
        if self.restart_lap and not self.restart_done and p.lap == self.restart_lap \
                and p.s - (p.lap - 1) * tr.length > tr.length * 0.1:
            if p.timer_off:
                self._restart()
            else:
                p.timer_off = True  # the game zeroes the lap timer a frame before it moves the car
        if int(self.t) != int(self.t - dt) or not self.snapshots:
            self.snapshots.append(self._snapshot())
            self.snapshots = self.snapshots[-12:]
        self.t += dt
        for c in self.cars:
            if c.finished:
                c.speed = max(0.0, c.speed - 20 * dt)
                c.s += c.speed * dt
                continue
            x, z, v, acc, k, *_ = tr.at(max(c.s, 0.0))
            target = v * c.pace * c.noise
            if c.idx == 0 and self.tyre_deg:
                target *= 1 - self.tyre_deg * max(self.wear)
            if target > c.speed:
                target = min(target, c.speed + max(2.0, 13.0 * (1 - c.speed / 96.0)) * dt)
            c.speed = target
            prev_s = c.s
            c.s += c.speed * dt
            self._timing(c, prev_s)
        self._player_physics(dt)
        if self.session_kind == "race":
            ranking = sorted(self.cars, key=lambda c: (0, c.finish_order) if c.finished else (1, -c.s))
        else:  # qualifying order is by best lap
            ranking = sorted(self.cars, key=lambda c: (c.best_ms or 10 ** 9, -c.s))
        for pos, c in enumerate(ranking, 1):
            c.position = pos

    def _timing(self, c, prev_s):
        tr = self.track
        L = tr.length
        lap_s = c.s - (c.lap - 1) * L
        prev_lap_s = prev_s - (c.lap - 1) * L
        if c.timer_off:
            if prev_lap_s < 0 <= lap_s:  # over the line at the end of the run-up: the lap starts again
                c.timer_off = False
                c.lap_start_t = self.t
            return
        lap_ms = int((self.t - c.lap_start_t) * 1000)
        if prev_lap_s < L / 3 <= lap_s:
            c.s1 = lap_ms
        if prev_lap_s < 2 * L / 3 <= lap_s:
            c.s2 = lap_ms - c.s1
        if c.idx == 0 and prev_lap_s < tr.trap_s <= lap_s:
            self._event("SPTP", struct.pack("<BfBBBf", 0, c.speed * 3.6, 1, 1, 0, c.speed * 3.6))
        if c.idx == 0 and self.session_kind == "race" and c.lap == 2 and prev_lap_s < 50 <= lap_s:
            self._event("DRSE")
        if c.idx == 0 and not c.invalid and prev_lap_s < L * 0.45 <= lap_s and self.rng.random() < 0.12:
            c.invalid = 1
            self._event("PENA", bytes([5, 7, 0, 255, 255, c.lap, 255]))
        if lap_s >= L:
            c.last_lap_ms = lap_ms
            s3 = lap_ms - c.s1 - c.s2
            out_lap = self.session_kind == "quali" and c.lap == 1
            c.laps.append([lap_ms, c.s1, c.s2, s3, 0x08 if out_lap else 0x0E if c.invalid else 0x0F])  # out lap: only S3 was a full sector
            if not c.invalid and not out_lap and (c.best_ms is None or lap_ms < c.best_ms):
                c.best_ms = lap_ms
            if not c.invalid and not out_lap and (self.fastest is None or lap_ms < self.fastest):
                self.fastest = lap_ms
                self._event("FTLP", struct.pack("<Bf", c.idx, lap_ms / 1000))
            c.lap += 1
            c.lap_start_t = self.t
            if c.idx == 0:
                self.ers_deployed = self.ers_harvested = 0.0
            c.s1 = c.s2 = 0
            c.invalid = 0
            c.noise = self.rng.uniform(0.985, 1.008)
            c.line_r, c.line_shift = self.rng.uniform(220, 440), self.rng.uniform(-14, 14)
            c.brake_shift = self.rng.uniform(-10, 10)
            if self.session_kind == "race" and c.lap > self.total_laps:
                c.finished = True
                c.finish_order = sum(1 for o in self.cars if o.finished)
                c.lap = self.total_laps
                if c.idx == 0 and self.end_at is None:
                    self.end_at = self.t + 4.0
                    self._event("CHQF")

    def _player_physics(self, dt):
        p = self.cars[0]
        x, z, v, acc, k, *_ = self.track.at(max(p.s + p.brake_shift, 0))
        speed = p.speed
        braking = acc < -3 and not p.finished
        throttle = 0.0 if braking else (1.0 if acc > 0.5 else 0.55 + 0.3 * self.rng.random())
        brake = min(1.0, -acc / (4.8 * G)) if braking else 0.0
        self.p_inputs = (throttle, brake, k, acc)
        heat = brake * 900 * dt
        for i in range(4):
            front = i >= 2
            self.btemp[i] += heat * (1.25 if front else 0.9) - (self.btemp[i] - 300) * 0.35 * dt
            lat = abs(speed * speed * k) / G
            target = 82 + lat * 6 + brake * 20 + (8 if front else 4)
            self.tsurf[i] += (target - self.tsurf[i]) * 1.5 * dt
            self.tinner[i] += (self.tsurf[i] + 6 - self.tinner[i]) * 0.05 * dt
            rate = 0.00030 * (1.25 if front else 1.0) * (1 + lat / 5)
            self.wear[i] += speed * dt * rate
        self.fuel = max(0.0, self.fuel - speed * dt * 0.00034 * (0.4 + throttle))
        if throttle > 0.9 and self.ers > 0 and self.ers_deployed < 4e6:
            d = min(self.ers, 120_000 * dt)
            self.ers -= d
            self.ers_deployed += d
        if brake > 0.1:
            h = 200_000 * brake * dt
            self.ers = min(4e6, self.ers + h)
            self.ers_harvested += h

    def _snapshot(self):
        return (self.t, copy.deepcopy(self.cars), list(self.wear), self.fuel, self.ers)

    def _flashback(self):
        t, cars, wear, fuel, ers = self.snapshots[-6]
        self.t, self.cars, self.wear, self.fuel, self.ers = t, cars, wear, fuel, ers
        self.flashback_done = True
        self.snapshots = []
        self._event("FLBK", struct.pack("<If", self.frame, t))

    def _restart(self):
        p = self.cars[0]
        p.s = (p.lap - 1) * self.track.length - RUNUP_M
        p.speed = self.track.at(p.s)[2]
        p.s1 = p.s2 = 0
        p.invalid = 0
        self.restart_done = True

    # ------------------------------------------------------------------ packets
    def _hdr(self, pid):
        return P.HEADER.pack(self.fmt, 25, 1, 12, 1, pid, self.uid, self.t, self.frame, self.frame, self.player, 255)

    def _send(self, data):
        try:
            self.sock.sendto(data, self.target)
        except OSError:
            pass

    def _event(self, code, details=b""):
        self._send(self._hdr(3) + code.encode() + details.ljust(12, b"\x00"))

    def _send_all(self, tick):
        self.frame += 1
        self._send(self._motion())
        self._send(self._lap_data())
        self._send(self._telemetry())
        self._send(self._status())
        self._send(self._motion_ex())
        if self.fmt >= 2026:
            self._send(self._telemetry2())
        if tick % 3 == 0:
            self._send(self._damage())
            self._send(self._history())
        if tick % 15 == 0:
            self._send(self._session())
            self._send(self._setups())
            self._send(self._tyre_sets())
            if self.session_kind == "tt":
                self._send(self._time_trial())
        if tick % 60 == 0:
            self._send(self._participants())

    def _slots(self):
        """One entry per car slot in the packet arrays (22 or 24), None for empty slots."""
        return [self.cars[i] if i < len(self.cars) else None for i in range(P.num_cars(self.fmt))]

    @property
    def _new(self):
        return self.fmt >= 2026

    def _motion(self):
        out = [self._hdr(0)]
        st = P.MOTION_CAR_26 if self._new else P.MOTION_CAR
        for c in self._slots():
            if c is None:
                out.append(bytes(st.size))
                continue
            x, z, v, acc, k, fx, fz = self.track.at(c.s)
            if c.idx == 0 and c.s > 0:  # towards the inside of corners, outside-inside-outside
                off = max(-5.0, min(5.0, self.track.at(c.s + c.line_shift)[4] * c.line_r))
                x, z = x - fz * off, z + fx * off
            if c.s < 0 and self.session_kind == "race":
                # grid slots sit behind the line on the main straight
                x0, z0, *_r, fx0, fz0 = self.track.at(0)
                x, z = x0 + fx0 * c.s, z0 + fz0 * c.s
            vx, vz = fx * c.speed, fz * c.speed
            glat = (c.speed ** 2) * k / G
            glon = acc / G if c.idx != 0 else (self.p_inputs[3] / G if hasattr(self, "p_inputs") else 0)
            yaw = math.atan2(fx, fz)
            gs = (glat, glon, 1.0 + self.rng.uniform(-0.15, 0.15))
            if self._new:  # quantised: int16 thousandths of a g
                gs = tuple(max(-32768, min(32767, round(g * 1000))) for g in gs)
            out.append(st.pack(
                x, 0.0, z, vx, 0.0, vz,
                int(fx * 32767), 0, int(fz * 32767), int(-fz * 32767), 0, int(fx * 32767),  # right = forward turned clockwise seen from above (+Z down)
                *gs, yaw, 0.0, 0.0))
        return b"".join(out)

    def _lap_data(self):
        out = [self._hdr(2)]
        L = self.track.length
        leader = min(self.cars, key=lambda c: c.position)
        ranked = sorted(self.cars, key=lambda c: c.position)
        for c in self._slots():
            if c is None:
                out.append(bytes(P.LAP_CAR.size))
                continue
            lap_s = c.s - (c.lap - 1) * L
            if lap_s < 0 and c.lap > 1:  # on the run-up after a restart the game counts on from the track length
                lap_s += L
            cur_ms = int(max(0.0, self.t - c.lap_start_t) * 1000) if self.t >= self.lights_until and not c.timer_off else 0
            gap_lead = int(max(0.0, leader.s - c.s) / max(c.speed, 40) * 1000)
            front = ranked[c.position - 2] if c.position > 1 else c
            gap_front = int(max(0.0, front.s - c.s) / max(c.speed, 40) * 1000)
            if self.session_kind == "race":
                dstatus = 4
            else:
                dstatus = 3 if c.lap == 1 else 1  # also through a Time Trial's lap 1, which is timed: the worst case
            out.append(P.LAP_CAR.pack(
                c.last_lap_ms, cur_ms, c.s1 % 60000, c.s1 // 60000, c.s2 % 60000, c.s2 // 60000,
                gap_front % 60000, gap_front // 60000, gap_lead % 60000, gap_lead // 60000,
                lap_s, c.s, 0.0, c.position, c.lap, c.pit_status, 0,
                0 if lap_s < L / 3 else (1 if lap_s < 2 * L / 3 else 2), c.invalid, 0, 0, 0, 0, 0,
                c.grid, dstatus, 3 if c.finished else 2, 0, 0, 0, 0, 0.0, 255))
        return b"".join(out) + bytes([255, 255])

    def _telemetry(self):
        out = [self._hdr(6)]
        st = P.TELEMETRY_CAR_26 if self._new else P.TELEMETRY_CAR
        for c in self._slots():
            if c is None:
                out.append(bytes(st.size))
                continue
            kmh = c.speed * 3.6
            gears = [0, 95, 135, 170, 205, 240, 270, 300, 400]
            gear = next(g for g in range(1, 9) if kmh < gears[g])
            lo, hi = gears[gear - 1], gears[gear]
            rpm = int(4200 + (kmh - lo) / max(hi - lo, 1) * 7600) if kmh > 2 else 4000
            if c.idx == 0 and hasattr(self, "p_inputs"):
                thr, brk, k, _ = self.p_inputs
                steer = max(-1.0, min(1.0, k * 14))
                lap_s = c.s % self.track.length
                z0, z1 = self.track.drs_zone
                in_zone = (z0 <= lap_s <= z1) if z0 < z1 else (lap_s >= z0 or lap_s <= z1)
                drs = 1 if in_zone and thr > 0.9 and (c.lap >= 2 or self.session_kind != "race") and not self._new else 0
                bt = [int(b) for b in self.btemp]
                ts = [int(t) for t in self.tsurf]
                ti = [int(t) for t in self.tinner]
                tp = [22.0 + (t - 85) * 0.035 for t in self.tinner]
            else:
                thr, brk, steer, drs = 1.0, 0.0, 0.0, 0
                bt, ts, ti, tp = [400] * 4, [90] * 4, [95] * 4, [23.0] * 4
            out.append(st.pack(
                int(kmh), thr, steer, brk, 0, gear, min(rpm, 12500), drs,
                min(100, int(rpm / 125)), 0, *bt, *ts, *ti, 105, *tp, 0, 0, 0, 0))
        return b"".join(out) + bytes([0, 255, 0])

    def _status(self):
        out = [self._hdr(7)]
        st = P.STATUS_CAR_26 if self._new else P.STATUS_CAR
        for c in self._slots():
            if c is None:
                out.append(bytes(st.size))
                continue
            me = c.idx == 0
            fuel = self.fuel if me else 10.0
            ers = self.ers if me else 2e6
            harvest = (self.ers_harvested * 0.6 if me else 0, self.ers_harvested * 0.4 if me else 0)
            if self._new:  # 2026: no MGU-H, a per-lap harvest limit, no DRS
                harvest = (self.ers_harvested if me else 0, 0.0, 8.5e6)
            out.append(st.pack(
                0, 0, 1, 56, 0, fuel, 110.0, fuel / 1.6 - (self.total_laps - c.lap) if me else 3.0,
                12500, 4000, 8, 1 if c.lap >= 2 and not self._new else 0, 0,
                18, 16 if self.session_kind != "race" else (16 + c.idx % 2), c.lap - 1, 0,
                560000.0, 120000.0, ers, 1, *harvest,
                self.ers_deployed if me else 0, 0))
        return b"".join(out)

    def _telemetry2(self):
        """Car Telemetry 2 (format 2026): active aero on the straights, Overtake Mode for the player."""
        out = [self._hdr(16)]
        L = self.track.length
        racing = self.t >= self.lights_until
        thr = getattr(self, "p_inputs", (0,))[0]
        for c in self._slots():
            if c is None:
                out.append(bytes(P.TELEMETRY2_CAR.size))
                continue
            lap_s = c.s % L if c.s >= 0 else 0.0
            in_zone, to_zone = self.track.zone_at(lap_s)
            aero = 1 if in_zone and racing and c.speed > 50 and (c.idx != 0 or thr > 0.9) else 0
            # Overtake Mode: race only, from lap 2, when chasing (here: not leading); used on the longest straight
            ot_avail = 1 if c.idx == 0 and self.session_kind == "race" and c.lap >= 2 and c.position > 1 else 0
            z0, z1 = self.track.drs_zone
            in_ot = (z0 <= lap_s <= z1) if z0 < z1 else (lap_s >= z0 or lap_s <= z1)
            ot_active = 1 if ot_avail and in_ot and thr > 0.9 and not c.finished else 0
            out.append(P.TELEMETRY2_CAR.pack(aero, 1 if in_zone else 0, 0 if in_zone else int(to_zone),
                                             ot_avail, ot_active, 0 if ot_avail else int(L - lap_s), 1, 0))
        return b"".join(out)

    def _damage(self):
        out = [self._hdr(10)]
        for c in self._slots():
            if c is None:
                out.append(bytes(P.DAMAGE_25.size))
                continue
            me = c.idx == 0
            wear = self.wear if me else [c.lap * 1.5] * 4
            if me and self.rng.random() < 0.002:
                self.fl_wing_damage = min(100, self.fl_wing_damage + 12)
            out.append(P.DAMAGE_25.pack(
                *wear, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                self.fl_wing_damage if me else 0, 0, 0, 3 if me else 0, 0, 0, 0, 0, 2, 4,
                8, 6, 5, 7, 6, 3, 0, 0))
        return b"".join(out)

    def _history(self):
        c = self.cars[self.history_cursor % len(self.cars)]
        self.history_cursor += 1
        laps = c.laps[-99:] + ([] if c.finished else [[0, c.s1, c.s2, 0, 0x0F]])  # current partial lap
        valid = [i for i, l in enumerate(c.laps) if l[4] & 1]
        best = (min(valid, key=lambda i: c.laps[i][0]) + 1) if valid else 0
        out = [self._hdr(11), P.HISTORY_HEAD.pack(c.idx, len(laps), 1, best, best, best, best)]
        for i in range(100):
            if i < len(laps):
                ms, s1, s2, s3, fl = laps[i]
                out.append(P.HISTORY_LAP.pack(ms, s1 % 60000, s1 // 60000, s2 % 60000, s2 // 60000,
                                              s3 % 60000, s3 // 60000, fl))
            else:
                out.append(bytes(P.HISTORY_LAP.size))
        out.append(P.HISTORY_STINT.pack(255, 18, 17))
        out.append(bytes(P.HISTORY_STINT.size * 7))
        return b"".join(out)

    def _session(self):
        L = int(self.track.length)
        head = P.SESSION_HEAD.pack(1, 34, 25, self.total_laps if self.session_kind == "race" else 0, L,
                                   self.session_type, self.track_id, 13 if self._new else 0,
                                   max(0, int(3600 - self.t)), 3600, 80, 0, 0, 255, 0, 3)
        zones = b"".join(P.MARSHAL_ZONE.pack(z, 0) for z in (0.0, 0.33, 0.66)) + bytes(P.MARSHAL_ZONE.size * 18)
        mid = P.SESSION_MID.pack(0, 0, 6)
        fc = b"".join(P.FORECAST.pack(self.session_type, off, w, 34, 2, 25, 2, rain)
                      for off, w, rain in ((0, 1, 5), (5, 1, 8), (10, 2, 15), (15, 2, 22), (30, 3, 45), (45, 2, 30)))
        fc += bytes(P.FORECAST.size * 58)
        career = self.mode == "weekend"
        structure = [8, 15] if career else [self.session_type]
        tail_vals = ([0, 95, DEMO_SEASON_LINK if career else 0, self.weekend_link, self.session_link, 12, 18, 9,
                      0, 0, 1, 0, 0, 0, 0, 0, 0, self.game_mode, self.rule_set, 840, 7, 1, 0, 1, 0, 0, 0, 0]
                     + [0] * 24 + [len(structure)] + structure + [0] * (12 - len(structure)) + [L / 3, 2 * L / 3])
        tail = P.SESSION_TAIL.pack(*tail_vals)
        if self._new:
            full = [v for a, b in self.track.straights[:8] for v in (a / L, b / L)]
            partial = [self.track.drs_zone[0] / L, self.track.drs_zone[1] / L]
            react = self.reaction if self.session_kind == "race" and self.t >= self.lights_until else 0.0
            tail += P.SESSION_AERO_26.pack(0, len(full) // 2, *full, *[0.0] * (16 - len(full)),
                                           1, *partial, *[0.0] * 14, 0, *[0.0] * 8, react, 0, 0, 0, 0, 1)
        return self._hdr(1) + head + zones + mid + fc + tail

    def _setups(self):
        me = P.SETUP_CAR.pack(*(self.setup[k] for k in P.SETUP_KEYS[:-1]), self.fuel)
        return self._hdr(5) + me + bytes(P.SETUP_CAR.size * (P.num_cars(self.fmt) - 1)) + struct.pack("<f", 28.0)

    def _participants(self):
        out = [self._hdr(4), bytes([len(self.cars)])]
        st = P.PARTICIPANT_26 if self._new else P.PARTICIPANT_25
        for c in self._slots():
            if c is None:
                out.append(bytes(st.size))
                continue
            name = DRIVER_NAMES[c.idx].encode()[:31].ljust(32, b"\x00")
            me_id = 65535 if self._new else 255  # 2026 widened driver ids to uint16
            out.append(st.pack(0 if c.idx == 0 else 1, me_id if c.idx == 0 else 100 + c.idx, 0, self.teams[c.idx],
                               0, c.idx + 2, 1, name, 1, 1, 0, 1, 1, bytes([200, 30, 30]) + bytes(9)))
        return b"".join(out)

    def _tyre_sets(self):
        out = [self._hdr(12), bytes([0])]
        # the fitted soft, a new soft, two new mediums and a new hard; lap deltas against the fitted (worn) set
        sets = [(18, 16), (18, 16), (19, 17), (19, 17), (20, 18)]
        life, pace = {16: 14, 17: 22, 18: 30}, {16: 0, 17: 350, 18: 700}
        worn = max(self.wear)
        for i in range(20):
            if i < len(sets):
                a, v = sets[i]
                fitted = i == 0
                delta = 0 if fitted else pace[v] - int(worn * 1000 * self.tyre_deg * 90)
                out.append(P.TYRE_SET.pack(a, v, int(worn) if fitted else 0, 1, 0, life[v], life[v], delta, 1 if fitted else 0))
            else:
                out.append(bytes(P.TYRE_SET.size))
        out.append(bytes([0]))
        return b"".join(out)

    def _motion_ex(self):
        thr, brk, k, acc = getattr(self, "p_inputs", (0, 0, 0, 0))
        p = self.cars[0]
        v = p.speed
        susp = [8 + brk * 6 + self.rng.uniform(-1, 1) for _ in range(4)]
        # tyre slip angles (rad) roughly 1.5 deg per g; the car pushes in slow corners and a little in fast
        # ones, and gets loose on the brakes and on the power out of slow corners
        r = self.mx_rng
        base = v * v * k / 9.81 * 0.026
        low, high = max(0.0, 1 - v / 45), max(0.0, min(1.0, (v - 55) / 20))
        exit_ = thr if thr > 0.9 and abs(k) > 0.004 and v < 45 else 0.0
        su = self.setup  # more front wing grips the front in fast corners, a stiffer front bar pushes in slow ones,
        fw, arb, diff = (su["front_wing"] - 28) / 10, (su["front_arb"] - 12) / 10, (su["diff_on_throttle"] - 70) / 30
        front = base * (1 + 0.5 * low + 0.15 * high - 0.4 * fw * high + 0.6 * arb * low + r.uniform(-0.05, 0.05))
        rear = base * (1 + 0.6 * exit_ * (1 - 0.5 * diff) + 0.3 * brk + r.uniform(-0.05, 0.05))  # an open diff rotates
        spin = 0.02 * thr + (0.06 + 0.12 * r.random() if exit_ and v < 40 else 0.0)
        lock = 0.03 * brk + (0.25 + 0.5 * r.random() if brk > 0.8 and r.random() < 0.06 else 0.0)
        vals = (susp + [0.0] * 8 + [v] * 4 + [spin, spin, -lock, -lock] + [rear, rear, front, front] + [v * v * k * 180] * 4
                + [acc * 180] * 4 + [0.28, 0.0, 0.0, v, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, k * 0.2]
                + [3500 + v * v * 0.9] * 4 + [0.03, 0.06, 0.0, 0.0, 0.0, 0.0] + [-0.05] * 4 + [0.0] * 4)
        return self._hdr(13) + P.MOTION_EX_25.pack(*vals)

    def _time_trial(self):
        p = self.cars[0]
        valid = [lap for lap in p.laps if lap[4] & 1]
        best = min(valid, key=lambda lap: lap[0]) if valid else None
        pb = [65_300, 19_810, 22_240, 23_250]  # the game's stored personal best for this track
        if best and best[0] < pb[0]:
            pb = best
        rival = [64_250, 19_620, 21_980, 22_650]

        st = P.TIME_TRIAL_SET_26 if self._new else P.TIME_TRIAL_SET

        def entry(car, team, lap, tc, gearbox, abs_):
            return st.pack(car, team, *(lap[:4] if lap else (0, 0, 0, 0)), tc, gearbox, abs_, 1, 0,
                                         1 if lap else 0)
        return (self._hdr(14) + entry(0, self.teams[0], best, 1, 3, 1) + entry(0, self.teams[0], pb, 1, 3, 1)
                + entry(255, self.teams[2], rival, 0, 1, 0))

    def _send_final(self):
        out = [self._hdr(8), bytes([len(self.cars)])]
        pts = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1] if self.session_kind == "race" else [0] * 10
        for c in self._slots():
            if c is None:
                out.append(bytes(P.FINAL_25.size))
                continue
            valid = [l[0] for l in c.laps if l[4] & 1]
            total = sum(l[0] for l in c.laps) / 1000
            stint = [18] + [0] * 7, [17] + [0] * 7, [255] + [0] * 7
            out.append(P.FINAL_25.pack(c.position, len(c.laps), c.grid if self.session_kind == "race" else 0,
                                       pts[c.position - 1] if c.position <= 10 else 0, 0, 3, 0,
                                       min(valid) if valid else 0, total, 0, 0, 1, *stint[0], *stint[1], *stint[2]))
        self._send(b"".join(out))


def main():
    ap = argparse.ArgumentParser(description="Send synthetic F1 25 telemetry over UDP")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=20777)
    ap.add_argument("--session", choices=["race", "quali", "tt", "weekend"], default="race",
                    help="weekend = a Driver Career weekend (qualifying then race)")
    ap.add_argument("--laps", type=int, default=5)
    ap.add_argument("--speed", type=float, default=1.0, help="time multiplier")
    ap.add_argument("--rate", type=int, default=30, help="packets per second per type")
    ap.add_argument("--flashback-lap", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--format", type=int, choices=[2025, 2026], default=2025,
                    help="UDP packet format (2026 = 2026 Season Pack cars)")
    ap.add_argument("--circuit", type=int, default=None,
                    help="drive this real track id from circuits.json (stored under that id: use a separate data folder)")
    ap.add_argument("--restart-lap", type=int, default=None, help='a Time Trial "Restart lap" early in this lap')
    a = ap.parse_args()
    sim = Simulator(a.host, a.port, a.session, a.laps, a.speed, a.rate, a.flashback_lap, a.seed, fmt=a.format,
                    circuit=a.circuit, restart_lap=a.restart_lap)
    print(f"Simulating {a.session} ({a.laps} laps, format {a.format}) on {a.host}:{a.port} at {a.speed}x - Ctrl+C to stop")
    try:
        sim.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
