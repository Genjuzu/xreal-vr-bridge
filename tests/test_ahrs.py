import math
import random

from xreal_vr_bridge.ahrs import (
    QuatAHRS,
    opentrack_to_q,
    q_axis_angle,
    q_conj,
    q_from_rotvec,
    q_mul,
    q_norm,
    q_rotate,
    q_to_opentrack,
    rdf_to_rub,
)
from xreal_vr_bridge.cli import frame_dt
from xreal_vr_bridge.fusion import ComplementaryOrientation

G = 9.80665
DT = 0.001
X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
# IMU mechanical tilt inside the One Pro (~30 deg about sensor X, FusionHub doc).
MOUNT = q_axis_angle(X, math.radians(30.0))  # head -> sensor (RUB)


def q_angle_deg(a, b):
    d = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2.0 * math.acos(min(1.0, d)))


def q_to_rotvec(q):
    if q[0] < 0:
        q = tuple(-c for c in q)
    s = math.sqrt(q[1] ** 2 + q[2] ** 2 + q[3] ** 2)
    if s < 1e-12:
        return (0.0, 0.0, 0.0)
    ang = 2.0 * math.atan2(s, q[0])
    return tuple(c / s * ang for c in q[1:])


def vrto3d_from_packet(yaw, pitch, roll):
    """Independent copy of VRto3D's HmdQuaternion_FromEulerAngles(roll, pitch, -yaw)."""
    r, p, y = math.radians(roll), math.radians(pitch), math.radians(-yaw)
    cr, sr = math.cos(r * 0.5), math.sin(r * 0.5)
    cp, sp = math.cos(p * 0.5), math.sin(p * 0.5)
    cy, sy = math.cos(y * 0.5), math.sin(y * 0.5)
    return (
        cr * cp * cy + sr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        sr * cp * cy - cr * sp * sy,
    )


class HeadSim:
    """Generates RDF gyro/accel exactly as the glasses would for a head motion."""

    def __init__(self, mount=MOUNT, gyro_bias=(0.0, 0.0, 0.0)):
        self.q_head = (1.0, 0.0, 0.0, 0.0)
        self.mount = mount
        self.gyro_bias = gyro_bias
        self.samples = []

    def _sensor(self, qh):
        return q_mul(qh, q_conj(self.mount))

    def emit(self, q_next):
        qs0, qs1 = self._sensor(self.q_head), self._sensor(q_next)
        w = tuple(c / DT for c in q_to_rotvec(q_mul(q_conj(qs0), qs1)))
        gyro = tuple(a + b for a, b in zip(rdf_to_rub(w), self.gyro_bias))
        accel = rdf_to_rub(q_rotate(q_conj(qs1), (0.0, G, 0.0)))
        self.samples.append((gyro, accel))
        self.q_head = q_next

    def hold(self, seconds):
        for _ in range(int(seconds / DT)):
            self.emit(self.q_head)

    def rotate_world(self, axis, deg, seconds=1.0):
        """Rotate the head about a world axis (yaw about up, etc.)."""
        n = int(seconds / DT)
        step = q_axis_angle(axis, math.radians(deg) / n)
        for _ in range(n):
            self.emit(q_norm(q_mul(step, self.q_head)))

    def rotate_head(self, axis, deg, seconds=1.0):
        """Rotate about a head-fixed axis (nod about head X, tilt about head Z)."""
        n = int(seconds / DT)
        step = q_axis_angle(axis, math.radians(deg) / n)
        for _ in range(n):
            self.emit(q_norm(q_mul(self.q_head, step)))


def run(sim, mode="ref", use_gravity=True, bias=None, **kw):
    o = ComplementaryOrientation(use_gravity_ref=use_gravity, fusion_mode=mode, **kw)
    o.recenter()
    for gyro, accel in sim.samples:
        o.update(DT, gyro, accel, bias)
    return o


def start_sim(**kw):
    sim = HeadSim(**kw)
    sim.hold(0.5)  # wearer looks straight ahead and level at start (auto recenter)
    return sim


def assert_center(o, tol=1.0):
    assert abs(o.yaw_deg) < tol, o.yaw_deg
    assert abs(o.pitch_deg) < tol, o.pitch_deg
    assert abs(o.roll_deg) < tol, o.roll_deg


# --- Euler conversion matches what VRto3D rebuilds ---------------------------

def test_opentrack_euler_roundtrip_matches_vrto3d():
    rnd = random.Random(1)
    for _ in range(500):
        q = q_norm(tuple(rnd.uniform(-1, 1) for _ in range(4)))
        yaw, pitch, roll = q_to_opentrack(q)
        assert q_angle_deg(vrto3d_from_packet(yaw, pitch, roll), q) < 1e-4
        assert q_angle_deg(opentrack_to_q(yaw, pitch, roll), q) < 1e-4


def test_opentrack_euler_gimbal_lock_still_exact():
    for pitch in (90.0, -90.0):
        q = q_mul(q_axis_angle(Y, math.radians(25)), q_axis_angle(X, math.radians(pitch)))
        assert q_angle_deg(vrto3d_from_packet(*q_to_opentrack(q)), q) < 1e-4


# --- signs with the real sensor axes (RDF) and 30 deg mount tilt -----------

def test_level_start_reads_zero_despite_mount_tilt():
    o = run(start_sim())
    assert_center(o, 0.2)


def test_turn_right_gives_positive_yaw_only():
    sim = start_sim()
    sim.rotate_world(Y, -40.0)  # -40 deg about world up = turn right
    o = run(sim)
    assert abs(o.yaw_deg - 40.0) < 1.0
    assert abs(o.pitch_deg) < 1.0 and abs(o.roll_deg) < 1.0


def test_look_up_gives_positive_pitch_only():
    sim = start_sim()
    sim.rotate_head(X, 45.0)
    o = run(sim)
    assert abs(o.pitch_deg - 45.0) < 1.0
    assert abs(o.yaw_deg) < 1.0 and abs(o.roll_deg) < 1.0


def test_tilt_left_gives_positive_roll_only():
    sim = start_sim()
    sim.rotate_head(Z, 30.0)  # +Z (back) = left ear down
    o = run(sim)
    assert abs(o.roll_deg - 30.0) < 1.0
    assert abs(o.yaw_deg) < 1.0 and abs(o.pitch_deg) < 1.0


# --- the user's symptom ------------------------------------------------------

def _look_up_turn_come_back():
    sim = start_sim()
    sim.rotate_head(X, 80.0)          # look far up
    sim.rotate_world(Y, -40.0)        # turn the body/head right while looking up
    sim.rotate_world(Y, 40.0)         # and back
    sim.rotate_world(Y, -25.0)
    sim.rotate_head(X, -80.0)         # look level again (now facing 25 deg right)
    sim.rotate_world(Y, 25.0)         # face straight ahead again
    sim.hold(0.2)
    return sim


def test_ref_returns_to_center_after_looking_up_and_turning():
    sim = _look_up_turn_come_back()
    assert_center(run(sim), 1.0)
    assert_center(run(sim, use_gravity=False), 1.0)


def test_legacy_euler_integration_reproduces_tilt_bug():
    # Documents the root cause: same motion, old Euler integration
    # (the user's current setup: legacy, --no-gravity-ref, yz_tilt 32).
    sim = _look_up_turn_come_back()
    o = run(sim, mode="legacy", use_gravity=False, yz_tilt_deg=32.0)
    assert max(abs(o.yaw_deg), abs(o.pitch_deg), abs(o.roll_deg)) > 10.0


def test_pitch_80_and_back_no_residual():
    sim = start_sim()
    for _ in range(3):
        sim.rotate_head(X, 80.0, 0.6)
        sim.rotate_head(X, -160.0, 1.0)
        sim.rotate_head(X, 80.0, 0.6)
    assert_center(run(sim), 0.5)


def test_full_vertical_loop_and_full_turn():
    sim = start_sim()
    sim.rotate_head(X, 360.0, 3.0)    # complete somersault
    sim.rotate_head(X, 60.0)
    sim.rotate_world(Y, 360.0, 3.0)   # full turn while looking up 60 deg
    sim.rotate_head(X, -60.0)
    sim.hold(0.2)
    assert_center(run(sim), 1.0)


def test_straight_up_tracks_exactly():
    sim = start_sim()
    sim.rotate_head(X, 90.0)
    sim.rotate_world(Y, -30.0)
    o = run(sim)
    rebuilt = vrto3d_from_packet(o.yaw_deg, o.pitch_deg, o.roll_deg)
    assert q_angle_deg(rebuilt, sim.q_head) < 1.0


# --- bias, recenter, timing ---------------------------------------------------

def test_residual_gyro_bias_is_learned_while_still():
    bias = (math.radians(0.5), math.radians(-0.8), math.radians(0.3))
    sim = start_sim(gyro_bias=bias)
    sim.hold(30.0)
    o = run(sim, bias=(0.0, 0.0, 0.0))  # startup calibration missed the bias
    for got, want in zip(rdf_to_rub(o._ahrs.bias), bias):
        assert abs(got - want) < math.radians(0.05)
    assert abs(o.pitch_deg) < 0.5 and abs(o.roll_deg) < 0.5


def test_startup_bias_is_used_and_survives_recenter():
    bias = (0.01, -0.02, 0.005)
    sim = start_sim(gyro_bias=bias)
    sim.hold(2.0)
    o = run(sim, bias=bias)
    assert abs(o.yaw_deg) < 0.1
    o.recenter()
    for got, want in zip(rdf_to_rub(o._ahrs.bias), bias):
        assert abs(got - want) < 1e-6


def test_recenter_yaw_only_keeps_tilt():
    sim = start_sim()
    sim.rotate_world(Y, -50.0)
    sim.rotate_head(X, 20.0)
    o = run(sim)
    o.recenter("yaw")
    assert abs(o.yaw_deg) < 0.5
    assert abs(o.pitch_deg - 20.0) < 1.0


def test_gain_scales_whole_rotation():
    sim = start_sim()
    sim.rotate_world(Y, -30.0)
    o = run(sim)
    o.set_gain(2.0)
    o._ref_publish()
    assert abs(o.yaw_deg - 60.0) < 1.5


def test_frame_dt_prefers_device_timestamps():
    assert abs(frame_dt(1_000_000, 2_000_000, 0.0) - 0.001) < 1e-12
    assert frame_dt(0, 2_000_000, 0.002) == 0.002          # no previous stamp
    assert frame_dt(5_000_000, 5_000_000, 0.003) == 0.003  # stamp missing/repeated
    assert frame_dt(1, 10_000_000_000, 0.2) == 0.05        # implausible -> clamp host


def test_ahrs_waits_for_valid_gravity_before_init():
    a = QuatAHRS()
    assert not a.update(DT, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    assert a.update(DT, (0.0, 0.0, 0.0), (0.0, -G, 0.0))
    assert a.initialized
    assert q_angle_deg(a.q, q_from_rotvec((0.0, 0.0, 0.0))) < 1e-6


# --- start-up robustness (yaw drift / "dreht sich sofort") -------------------

def test_wrong_startup_bias_is_corrected_when_still():
    """Calibration taken while the glasses moved -> seed bias off by 4 deg/s
    on yaw.  Old code: |omega| > STILL_RATE forever -> endless yaw spin."""
    sim = start_sim()
    sim.hold(20.0)
    wrong = (0.0, math.radians(4.0), 0.0)
    o = run(sim, bias=wrong)
    y0 = o.yaw_deg
    sim2 = HeadSim()
    sim2.q_head = sim.q_head
    sim2.hold(5.0)
    for gyro, accel in sim2.samples:
        o.update(DT, gyro, accel, None)
    assert abs(o.yaw_deg - y0) < 1.0, (y0, o.yaw_deg)
    assert max(abs(b) for b in o._ahrs.bias) < math.radians(0.3)


def test_auto_recenter_waits_until_upright_and_still():
    sim = HeadSim()
    sim.q_head = q_axis_angle(X, math.radians(-80.0))  # lying on the desk
    sim.hold(2.0)
    o = ComplementaryOrientation(fusion_mode="ref")
    o.recenter("auto")
    for gyro, accel in sim.samples:
        o.update(DT, gyro, accel, None)
    assert not o._ahrs.auto_recentered
    sim.samples = []
    sim.rotate_head(X, 80.0)   # put on, look straight ahead
    sim.rotate_world(Y, 40.0)
    sim.hold(1.5)
    for gyro, accel in sim.samples:
        o.update(DT, gyro, accel, None)
    assert o._ahrs.auto_recentered
    assert_center(o)


def test_calibrate_skips_moving_window():
    from xreal_vr_bridge.cli import calibrate

    class F:
        def __init__(self, g):
            self.gyro = g
    rnd = random.Random(1)
    moving = [F((rnd.uniform(-0.3, 0.3), rnd.uniform(-0.3, 0.3), 0.1)) for _ in range(100)]
    still = [F((0.002 + rnd.gauss(0, 0.001), -0.003, 0.001)) for _ in range(100)]
    bias = calibrate(iter(moving + still), 100, verbose=False)
    assert abs(bias[0] - 0.002) < 0.001 and abs(bias[1] + 0.003) < 1e-9
    assert calibrate(iter(moving * 3), 100, max_windows=3, verbose=False) == (0.0, 0.0, 0.0)
