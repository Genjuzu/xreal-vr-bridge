"""Smooth, evenly paced OpenTrack output.

Why: the glasses deliver IMU frames in TCP bursts.  The old inline sender only
sent when the *host* clock had advanced 1/max_rate since the last packet, i.e.
the first (oldest) frame of a burst went out and the newest frames of the burst
were dropped, and packets were spaced by the burst rhythm.  VRto3D samples the
latest packet at 2x the display rate (60 Hz XREAL -> 120 Hz) with no
prediction, so uneven pose age shows up directly as judder while turning.

PoseSender sends the LATEST pose on its own steady clock.
QuatOneEuro is an optional, speed-adaptive (low latency when moving fast)
smoothing on the full orientation quaternion (no Euler wrap issues).
"""

import math
import threading
import time

from .ahrs import opentrack_to_q, q_conj, q_mul, q_norm, q_to_opentrack
from .opentrack import pack_opentrack


def _slerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0.0:
        b = tuple(-c for c in b)
        d = -d
    if d > 0.9995:
        return q_norm(tuple(x + t * (y - x) for x, y in zip(a, b)))
    th = math.acos(min(1.0, d))
    s = math.sin(th)
    wa = math.sin((1.0 - t) * th) / s
    wb = math.sin(t * th) / s
    return tuple(wa * x + wb * y for x, y in zip(a, b))


def _angle(a, b):
    d = abs(sum(x * y for x, y in zip(a, b)))
    return 2.0 * math.acos(min(1.0, d))


class QuatOneEuro:
    """One-Euro filter on orientation.  cutoff = min_cutoff + beta * speed[deg/s].
    min_cutoff in Hz.  min_cutoff <= 0 disables the filter (pass-through)."""

    def __init__(self, min_cutoff=0.0, beta=0.3, d_cutoff=5.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.reset()

    @property
    def enabled(self):
        return self.min_cutoff > 0.0

    def reset(self):
        self._q = None
        self._speed = 0.0

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter_q(self, q, dt):
        if not self.enabled:
            return q
        if self._q is None or dt <= 0.0:
            self._q = q
            return q
        raw_speed = math.degrees(_angle(self._q, q)) / dt
        self._speed += self._alpha(self.d_cutoff, dt) * (raw_speed - self._speed)
        cutoff = self.min_cutoff + self.beta * self._speed
        self._q = q_norm(_slerp(self._q, q, self._alpha(cutoff, dt)))
        return self._q

    def filter_euler(self, yaw, pitch, roll, dt):
        """OpenTrack degrees in/out."""
        if not self.enabled:
            return yaw, pitch, roll
        q = self.filter_q(opentrack_to_q(yaw, pitch, roll), dt)
        return q_to_opentrack(q)


class PoseSender(threading.Thread):
    """Sends the latest (yaw, pitch, roll) at a fixed rate on a steady clock."""

    def __init__(self, sock, addr, rate_hz):
        super().__init__(daemon=True)
        self.sock = sock
        self.addr = addr
        self.period = 1.0 / max(1, int(rate_hz))
        self._pose = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.sent = 0

    def update(self, yaw, pitch, roll):
        with self._lock:
            self._pose = (yaw, pitch, roll)

    def _send(self):
        with self._lock:
            pose = self._pose
        if pose is None:
            return
        try:
            self.sock.sendto(pack_opentrack(0.0, 0.0, 0.0, *pose), self.addr)
            self.sent += 1
        except OSError:
            pass

    def run(self):
        nxt = time.perf_counter()
        while not self._stop.is_set():
            self._send()
            nxt += self.period
            delay = nxt - time.perf_counter()
            if delay > 0:
                # time.sleep is high-resolution on Windows (Python >= 3.11);
                # Event.wait() is not (~15.6 ms ticks -> measured only 129 of
                # 500 packets/s with 16 ms gaps).
                time.sleep(delay)
            else:
                nxt = time.perf_counter()  # fell behind: resync, no catch-up burst

    def stop(self):
        self._stop.set()
        if self.is_alive():
            self.join(timeout=1.0)
        self._send()  # final pose
