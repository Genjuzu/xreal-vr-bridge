import math

from .ahrs import QuatAHRS, q_pow, q_to_opentrack


class GyroBias:
    def __init__(self, samples=500):
        self.samples = samples
        self._sum = [0.0, 0.0, 0.0]
        self.count = 0

    @property
    def done(self):
        return self.count >= self.samples

    def feed(self, gyro):
        for i in range(3):
            self._sum[i] += gyro[i]
        self.count += 1

    @property
    def bias(self):
        n = max(1, self.count)
        return tuple(v / n for v in self._sum)


AXIS_MAPS = {
    "default": (0, 1, 2),
    "swap_yz": (0, 2, 1),
    "swap_xy": (1, 0, 2),
    "rotate": (2, 0, 1),
}


def quat_multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def quat_normalize(q):
    w, x, y, z = q
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm < 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    return (w / norm, x / norm, y / norm, z / norm)


def quat_to_euler_degrees(q):
    w, x, y, z = q
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x)))))
    yaw = math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))
    roll = math.degrees(math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)))
    return yaw, pitch, roll


class ComplementaryOrientation:
    AXIS_PITCH = 0
    AXIS_YAW = 1
    AXIS_ROLL = 2

    FUSION_MODES = ("legacy", "quat_old", "quat_new", "ref")

    def __init__(self, alpha=0.96, use_gravity_ref=True, axis_map="default",
                 invert_yaw=False, invert_pitch=False, yz_tilt_deg=0.0,
                 rate_smoothing=0.0, fusion_mode="legacy"):
        self.alpha = alpha
        self.use_gravity_ref = use_gravity_ref
        self.gain = 1.0
        self.axis_map = axis_map
        self.invert_yaw = invert_yaw
        self.invert_pitch = invert_pitch
        self.yz_tilt_deg = float(yz_tilt_deg)
        self.rate_smoothing = max(0.0, min(1.0, float(rate_smoothing)))
        self.fusion_mode = fusion_mode if fusion_mode in self.FUSION_MODES else "legacy"
        self._smooth = None
        self._q = (1.0, 0.0, 0.0, 0.0)
        self.yaw_deg = 0.0
        self.pitch_deg = 0.0
        self.roll_deg = 0.0
        self._pitch_acc = 0.0
        self._roll_acc = 0.0
        self._ahrs = QuatAHRS(use_gravity=use_gravity_ref)
        self._ahrs_bias_seeded = False
        self.yaw_offset_deg = 0.0

    def set_yaw_offset(self, deg):
        """Extra heading added to every output (and therefore after every
        recenter): 180 = after F9 you face what was behind you (e.g. the
        SteamVR dashboard).  Normalised to [-180, 180)."""
        self.yaw_offset_deg = (float(deg) + 180.0) % 360.0 - 180.0

    def output_euler(self):
        """(yaw, pitch, roll) in OpenTrack degrees incl. yaw offset.  Because
        VRto3D applies yaw first (Ry(-yaw) * Rx(pitch) * Rz(roll)), adding to
        yaw is exactly a world-heading rotation; pitch/roll are untouched."""
        yaw = (self.yaw_deg + self.yaw_offset_deg + 180.0) % 360.0 - 180.0
        return yaw, self.pitch_deg, self.roll_deg

    def set_fusion_mode(self, mode):
        if mode in self.FUSION_MODES:
            self.fusion_mode = mode

    def set_yz_tilt(self, deg):
        self.yz_tilt_deg = float(deg)

    def set_rate_smoothing(self, value):
        self.rate_smoothing = max(0.0, min(1.0, float(value)))

    def set_gain(self, gain):
        self.gain = max(0.1, float(gain))

    def set_axis_map(self, axis_map):
        if axis_map not in AXIS_MAPS:
            raise ValueError(f"unknown axis_map {axis_map!r}")
        self.axis_map = axis_map

    def set_invert_yaw(self, invert):
        self.invert_yaw = bool(invert)

    def set_invert_pitch(self, invert):
        self.invert_pitch = bool(invert)

    def recenter(self, mode="level"):
        """ref mode: mode='level' = current view becomes straight ahead and
        level (also learns the IMU mount tilt); mode='yaw' = heading only.
        Gyro bias is kept (it used to be thrown away on every recenter)."""
        if self.fusion_mode == "ref":
            self._ahrs.recenter(mode)
            if self._ahrs.initialized:
                self._ref_publish()
            else:
                self.yaw_deg = self.pitch_deg = self.roll_deg = 0.0
            return
        self._q = (1.0, 0.0, 0.0, 0.0)
        self.yaw_deg = 0.0
        self.pitch_deg = 0.0
        self.roll_deg = 0.0
        self._pitch_acc = 0.0
        self._roll_acc = 0.0

    def _ref_update(self, dt, gyro, accel, bias):
        if bias is not None and not self._ahrs_bias_seeded:
            self._ahrs.set_bias_sensor(bias)
            self._ahrs_bias_seeded = True
        if self._ahrs.update(dt, gyro, accel):
            self._ref_publish()

    def _ref_publish(self):
        q = q_pow(self._ahrs.head(), self.gain)
        yaw, pitch, roll = q_to_opentrack(q)
        if self.invert_yaw:
            yaw = -yaw
        if self.invert_pitch:
            pitch = -pitch
        self.yaw_deg, self.pitch_deg, self.roll_deg = yaw, pitch, roll

    def _decompose(self, gyro, bias):
        gx, gy, gz = gyro
        if bias is not None:
            gx -= bias[0]
            gy -= bias[1]
            gz -= bias[2]
        p_i, y_i, r_i = AXIS_MAPS[self.axis_map]
        raw = (gx, gy, gz)
        pitch_rate = math.degrees(raw[p_i]) * self.gain
        yaw_rate = math.degrees(raw[y_i]) * self.gain
        roll_rate = math.degrees(raw[r_i]) * self.gain
        if self.yz_tilt_deg and self.axis_map == "default":
            tilt = math.radians(self.yz_tilt_deg)
            c = math.cos(tilt)
            s = math.sin(tilt)
            yaw_rate, roll_rate = (
                yaw_rate * c - roll_rate * s,
                yaw_rate * s + roll_rate * c,
            )
        if self.invert_pitch:
            pitch_rate = -pitch_rate
        if self.invert_yaw:
            yaw_rate = -yaw_rate
        if self.rate_smoothing and self._smooth is None:
            self._smooth = (0.0, 0.0, 0.0)
        if self.rate_smoothing:
            a = self.rate_smoothing
            sp, sy, sr = self._smooth
            self._smooth = (
                (1.0 - a) * sp + a * pitch_rate,
                (1.0 - a) * sy + a * yaw_rate,
                (1.0 - a) * sr + a * roll_rate,
            )
            pitch_rate, yaw_rate, roll_rate = self._smooth
        return pitch_rate, yaw_rate, roll_rate

    def _quat_integrate(self, dt, rates_deg, args_deg):
        roll, pitch, yaw = args_deg
        if dt <= 0.0:
            return
        roll = math.radians(roll) * dt
        pitch = math.radians(pitch) * dt
        yaw = math.radians(yaw) * dt
        if abs(roll) < 1e-12 and abs(pitch) < 1e-12 and abs(yaw) < 1e-12:
            return
        cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
        cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
        cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
        dq = (
            cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
        )
        self._q = quat_normalize(quat_multiply(self._q, dq))
        self.yaw_deg, self.pitch_deg, self.roll_deg = quat_to_euler_degrees(self._q)

    def update(self, dt, gyro, accel, bias=None):
        ax, ay, az = accel

        if self.fusion_mode == "ref":
            self._ref_update(dt, gyro, accel, bias)
            return

        pitch_rate, yaw_rate, roll_rate = self._decompose(gyro, bias)

        if self.fusion_mode == "legacy":
            a = self.alpha
            if self.use_gravity_ref:
                gravity = math.sqrt(ax * ax + ay * ay + az * az)
                if gravity > 1e-6:
                    self._pitch_acc = math.degrees(math.atan2(ay, math.sqrt(ax * ax + az * az)))
                    self._roll_acc = math.degrees(math.atan2(-ax, az))
                self.pitch_deg = a * (self.pitch_deg + pitch_rate * dt) + (1.0 - a) * self._pitch_acc
                self.roll_deg = a * (self.roll_deg + roll_rate * dt) + (1.0 - a) * self._roll_acc
            else:
                self.pitch_deg = self.pitch_deg + pitch_rate * dt
                self.roll_deg = self.roll_deg + roll_rate * dt
            self.yaw_deg = self.yaw_deg + yaw_rate * dt
            return

        if self.fusion_mode == "quat_new":
            args_deg = (pitch_rate, yaw_rate, roll_rate)
        else:
            args_deg = (roll_rate, pitch_rate, yaw_rate)
        self._quat_integrate(dt, (pitch_rate, yaw_rate, roll_rate), args_deg)

        a = self.alpha
        if self.use_gravity_ref:
            gravity = math.sqrt(ax * ax + ay * ay + az * az)
            if gravity > 1e-6:
                self._pitch_acc = math.degrees(math.atan2(ay, math.sqrt(ax * ax + az * az)))
                self._roll_acc = math.degrees(math.atan2(-ax, az))
            self.pitch_deg = a * (self.pitch_deg + pitch_rate * dt) + (1.0 - a) * self._pitch_acc
            self.roll_deg = a * (self.roll_deg + roll_rate * dt) + (1.0 - a) * self._roll_acc
        else:
            self.pitch_deg = self.pitch_deg + pitch_rate * dt
            self.roll_deg = self.roll_deg + roll_rate * dt
        self.yaw_deg = self.yaw_deg + yaw_rate * dt
