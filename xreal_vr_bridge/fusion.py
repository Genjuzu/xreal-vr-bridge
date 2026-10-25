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


class ComplementaryOrientation:
    AXIS_PITCH = 0
    AXIS_YAW = 1
    AXIS_ROLL = 2

    def __init__(self, alpha=0.96, use_gravity_ref=True):
        self.alpha = alpha
        self.use_gravity_ref = use_gravity_ref
        self.gain = 1.0
        self.yaw_deg = 0.0
        self.pitch_deg = 0.0
        self.roll_deg = 0.0
        self._pitch_acc = 0.0
        self._roll_acc = 0.0

    def set_gain(self, gain):
        self.gain = max(0.1, float(gain))

    def recenter(self):
        self.yaw_deg = 0.0
        self.pitch_deg = 0.0
        self.roll_deg = 0.0
        self._pitch_acc = 0.0
        self._roll_acc = 0.0

    def update(self, dt, gyro, accel, bias=None):
        gx, gy, gz = gyro
        ax, ay, az = accel
        if bias is not None:
            gx -= bias[0]
            gy -= bias[1]
            gz -= bias[2]

        pitch_rate = math.degrees(gx) * self.gain
        yaw_rate = math.degrees(gy) * self.gain
        roll_rate = math.degrees(gz) * self.gain

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
