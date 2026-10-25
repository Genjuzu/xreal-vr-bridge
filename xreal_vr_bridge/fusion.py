import math


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


class ComplementaryOrientation:
    AXIS_PITCH = 0
    AXIS_YAW = 1
    AXIS_ROLL = 2

    def __init__(self, alpha=0.96, use_gravity_ref=True, axis_map="default",
                 invert_yaw=False, invert_pitch=False, yz_tilt_deg=0.0,
                 rate_smoothing=0.0):
        self.alpha = alpha
        self.use_gravity_ref = use_gravity_ref
        self.gain = 1.0
        self.axis_map = axis_map
        self.invert_yaw = invert_yaw
        self.invert_pitch = invert_pitch
        self.yz_tilt_deg = float(yz_tilt_deg)
        self.rate_smoothing = max(0.0, min(1.0, float(rate_smoothing)))
        self._smooth = None
        self.yaw_deg = 0.0
        self.pitch_deg = 0.0
        self.roll_deg = 0.0
        self._pitch_acc = 0.0
        self._roll_acc = 0.0

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

    def recenter(self):
        self.yaw_deg = 0.0
        self.pitch_deg = 0.0
        self.roll_deg = 0.0
        self._pitch_acc = 0.0
        self._roll_acc = 0.0

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
            self._smooth = (pitch_rate, yaw_rate, roll_rate)
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

    def update(self, dt, gyro, accel, bias=None):
        ax, ay, az = accel

        pitch_rate, yaw_rate, roll_rate = self._decompose(gyro, bias)

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
