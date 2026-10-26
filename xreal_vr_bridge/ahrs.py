"""Quaternion head tracker for the XREAL One / One Pro IMU.

Frames
------
* Sensor frame of the One / One Pro IMU (measured, see README "Achsen-Check"):
  X = right, Y = down, Z = forward (RDF).  Gyro: +X = look up, +Y = turn right,
  +Z = tilt to the right shoulder.  At rest the accelerometer reads +9.81 m/s^2
  along "up", i.e. about (0, -9.8, 0) when the glasses are level.
* Internal / world frame = SteamVR frame: X = right, Y = up, Z = back (RUB).
  RDF -> RUB is (x, -y, -z), a proper rotation (180 deg about X).

Pipeline
--------
1. remap sensor -> RUB, subtract gyro bias (start value from the startup
   calibration, refined while the head is still),
2. Mahony-style gravity correction (proportional feedback of
   accel x predicted-up) so pitch/roll never drift,
3. exact quaternion integration of the body rates (no Euler angles in the loop,
   so rotations commute correctly and there is no gimbal lock),
4. output = yaw_reference^-1 * q * mount, where ``mount`` removes the IMU's
   mechanical tilt (~30 deg on the One Pro) and is learned from gravity at
   recenter time (user looks straight ahead and level),
5. decompose into the exact Euler order VRto3D re-composes
   (yaw about Y, then pitch about X, then roll about Z; VRto3D negates Yaw),
   so the pose VRto3D rebuilds is identical to the tracked quaternion.
"""

import math

G = 9.80665
IDENTITY = (1.0, 0.0, 0.0, 0.0)


def q_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def q_conj(q):
    return (q[0], -q[1], -q[2], -q[3])


def q_norm(q):
    n = math.sqrt(sum(c * c for c in q))
    if n < 1e-12:
        return IDENTITY
    return tuple(c / n for c in q)


def q_rotate(q, v):
    r = q_mul(q_mul(q, (0.0, v[0], v[1], v[2])), q_conj(q))
    return (r[1], r[2], r[3])


def q_axis_angle(axis, angle):
    n = math.sqrt(sum(c * c for c in axis))
    if n < 1e-12 or angle == 0.0:
        return IDENTITY
    s = math.sin(angle * 0.5) / n
    return (math.cos(angle * 0.5), axis[0] * s, axis[1] * s, axis[2] * s)


def q_from_rotvec(v):
    angle = math.sqrt(sum(c * c for c in v))
    if angle < 1e-15:
        return IDENTITY
    return q_axis_angle(v, angle)


def q_from_two_vectors(a, b):
    """Shortest rotation taking unit vector a onto unit vector b."""
    d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    if d < -0.999999:
        axis = cross((1.0, 0.0, 0.0), a)
        if sum(c * c for c in axis) < 1e-12:
            axis = cross((0.0, 0.0, 1.0), a)
        return q_axis_angle(axis, math.pi)
    c = cross(a, b)
    return q_norm((1.0 + d, c[0], c[1], c[2]))


def q_pow(q, k):
    """Scale the rotation angle of q by k (used for the sensitivity gain)."""
    if k == 1.0:
        return q
    w = max(-1.0, min(1.0, q[0]))
    if w < 0.0:
        q = tuple(-c for c in q)
        w = -w
    angle = 2.0 * math.acos(w)
    if angle < 1e-12:
        return IDENTITY
    return q_axis_angle(q[1:], angle * k)


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def rdf_to_rub(v):
    return (v[0], -v[1], -v[2])


def q_to_matrix(q):
    w, x, y, z = q
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
        (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
        (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)),
    )


def heading_rad(q):
    """Rotation about world up (Y) of q in the Y-X-Z decomposition."""
    m = q_to_matrix(q)
    if math.hypot(m[0][2], m[2][2]) < 1e-6:  # looking straight up/down
        return math.atan2(-m[2][0], m[0][0])
    return math.atan2(m[0][2], m[2][2])


def q_to_opentrack(q):
    """RUB head->world quaternion -> OpenTrack (yaw, pitch, roll) in degrees.

    q = Ry(a) * Rx(b) * Rz(c) is the order VRto3D uses in
    HmdQuaternion_FromEulerAngles(roll, pitch, -Yaw).  Result:
    Yaw = -a (turn right positive), Pitch = b (look up positive),
    Roll = c (rotation about +Z/back, i.e. tilt to the left shoulder positive).
    """
    m = q_to_matrix(q)
    cb = math.hypot(m[0][2], m[2][2])
    b = math.atan2(-m[1][2], cb)
    if cb < 1e-6:  # gimbal lock: only yaw +/- roll is defined, put it all in yaw
        a = math.atan2(-m[2][0], m[0][0])
        c = 0.0
    else:
        a = math.atan2(m[0][2], m[2][2])
        c = math.atan2(m[1][0], m[1][1])
    return -math.degrees(a), math.degrees(b), math.degrees(c)


def opentrack_to_q(yaw, pitch, roll):
    """Inverse of q_to_opentrack (what VRto3D builds from a packet)."""
    qy = q_axis_angle((0.0, 1.0, 0.0), -math.radians(yaw))
    qx = q_axis_angle((1.0, 0.0, 0.0), math.radians(pitch))
    qz = q_axis_angle((0.0, 0.0, 1.0), math.radians(roll))
    return q_mul(q_mul(qy, qx), qz)


class QuatAHRS:
    KP = 0.5                 # gravity feedback gain [rad/s per unit error]
    KP_INIT = 5.0            # faster pull-in during the first INIT_TIME seconds
    INIT_TIME = 1.0
    ACCEL_TOL = 0.1          # accept accel for correction if | |a|/g - 1 | < tol
    STILL_RATE = math.radians(2.0)   # rad/s, "head is still" threshold
    STILL_TIME = 0.5         # s of stillness before bias learning starts
    BIAS_TAU = 5.0           # s, bias low-pass time constant
    BIAS_TAU_FAST = 0.5      # s, used when the seeded bias is clearly wrong
    MAX_DT = 0.05
    # Stillness that does not trust the current bias estimate (a bias seeded
    # while the glasses were moving would otherwise make |omega| > STILL_RATE
    # forever, so it could never be corrected -> endless spin):
    STILL_JITTER = math.radians(1.2)   # rad/s, smoothed raw gyro deviation from its mean
    MAX_BIAS = math.radians(5.0)       # rad/s, larger raw rates are never bias
    ACC_STEADY = 0.03                  # change of unit gravity vector
    JITTER_TAU = 0.2                   # s
    # recenter('auto'): wait until the glasses are roughly upright and still
    AUTO_MAX_TILT = math.radians(50.0)
    AUTO_STILL_TIME = 0.5

    def __init__(self, use_gravity=True):
        self.use_gravity = use_gravity
        self.q = IDENTITY          # sensor(RUB) -> world
        self.mount = IDENTITY      # head -> sensor(RUB)
        self.yaw_ref = IDENTITY    # world heading that counts as "straight ahead"
        self.bias = (0.0, 0.0, 0.0)   # RUB, rad/s
        self.initialized = False
        self._pending_recenter = None
        self.auto_recentered = False
        self._time = 0.0
        self._still = 0.0
        self._gyro_lp = None
        self._up_lp = None

    def set_bias_sensor(self, bias_rdf):
        if bias_rdf is not None:
            self.bias = rdf_to_rub(bias_rdf)

    def update(self, dt, gyro_rdf, accel_rdf):
        gyro = rdf_to_rub(gyro_rdf)
        acc = rdf_to_rub(accel_rdf)
        an = math.sqrt(sum(c * c for c in acc))
        acc_ok = an > 1e-6 and abs(an / G - 1.0) < self.ACCEL_TOL

        if not self.initialized:
            if not acc_ok:
                return False
            up = tuple(c / an for c in acc)
            self.q = q_from_two_vectors(up, (0.0, 1.0, 0.0))
            self.initialized = True
            self._time = 0.0
            if self._pending_recenter and self._pending_recenter != "auto":
                self.recenter(self._pending_recenter)
            return True

        if dt <= 0.0:
            return True
        dt = min(dt, self.MAX_DT)
        self._time += dt

        omega = tuple(g - b for g, b in zip(gyro, self.bias))
        rate = math.sqrt(sum(c * c for c in omega))
        steady = acc_ok and self._steady(dt, gyro, acc, an)
        if acc_ok and (rate < self.STILL_RATE or steady):
            self._still += dt
            if self._still > self.STILL_TIME:
                # bias clearly wrong (glasses steady but |omega| large):
                # converge fast instead of spinning for many seconds
                tau = self.BIAS_TAU if rate < self.STILL_RATE else self.BIAS_TAU_FAST
                k = min(1.0, dt / tau)
                self.bias = tuple(b + k * (g - b) for b, g in zip(self.bias, gyro))
        else:
            self._still = 0.0

        if self.use_gravity and acc_ok:
            up_meas = tuple(c / an for c in acc)
            up_pred = q_rotate(q_conj(self.q), (0.0, 1.0, 0.0))
            err = cross(up_meas, up_pred)
            kp = self.KP_INIT if self._time < self.INIT_TIME else self.KP
            omega = tuple(o + kp * e for o, e in zip(omega, err))

        self.q = q_norm(q_mul(self.q, q_from_rotvec(tuple(o * dt for o in omega))))
        if self._pending_recenter == "auto":
            self._try_auto_recenter()
        return True

    def _steady(self, dt, gyro, acc, an):
        """True if the raw gyro is constant (pure bias, no motion) and gravity
        does not move -- independent of the current bias estimate."""
        up = tuple(c / an for c in acc)
        if self._gyro_lp is None:
            self._gyro_lp, self._up_lp = gyro, up
            self._jitter_lp = 1.0  # rad/s: start "not steady"
            return False
        k = min(1.0, dt / self.JITTER_TAU)
        jitter = math.sqrt(sum((g - l) ** 2 for g, l in zip(gyro, self._gyro_lp)))
        dup = math.sqrt(sum((u - l) ** 2 for u, l in zip(up, self._up_lp)))
        self._gyro_lp = tuple(l + k * (g - l) for g, l in zip(gyro, self._gyro_lp))
        self._up_lp = tuple(l + k * (u - l) for u, l in zip(up, self._up_lp))
        # per-sample gyro noise is ~0.6 deg/s on the One Pro -> smooth it
        self._jitter_lp += k * (jitter - self._jitter_lp)
        raw = math.sqrt(sum(g * g for g in gyro))
        return (self._jitter_lp < self.STILL_JITTER and dup < self.ACC_STEADY
                and raw < self.MAX_BIAS)

    def _try_auto_recenter(self):
        up_sensor = q_rotate(q_conj(self.q), (0.0, 1.0, 0.0))
        tilt = math.acos(max(-1.0, min(1.0, up_sensor[1])))
        if tilt < self.AUTO_MAX_TILT and self._still >= self.AUTO_STILL_TIME:
            self._pending_recenter = None
            self.recenter("level")
            self.auto_recentered = True

    def head(self):
        return q_mul(q_mul(q_conj(self.yaw_ref), self.q), self.mount)

    def recenter(self, mode="level"):
        """mode='level': current view = straight ahead AND level (learns the IMU
        mount tilt from gravity).  mode='yaw': only reset heading."""
        if mode == "auto":
            # Startup: do NOT learn the mount from whatever pose the glasses
            # happen to be in (lying on the desk, in the hand ...).  Wait until
            # they are roughly upright and still, then do a level recenter.
            self._pending_recenter = "auto"
            self.auto_recentered = False
            return
        if not self.initialized:
            self._pending_recenter = mode
            return
        self._pending_recenter = None
        if mode == "level":
            a = heading_rad(self.q)
            target = q_axis_angle((0.0, 1.0, 0.0), a)
            self.mount = q_mul(q_conj(self.q), target)
            self.yaw_ref = target
        else:
            a = heading_rad(q_mul(self.q, self.mount))
            self.yaw_ref = q_axis_angle((0.0, 1.0, 0.0), a)

    def reset(self):
        """Forget orientation (not bias / mount); re-init from gravity."""
        self.initialized = False
        self.yaw_ref = IDENTITY
