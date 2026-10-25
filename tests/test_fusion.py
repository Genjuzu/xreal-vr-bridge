import math

from xreal_vr_bridge.fusion import (
    AXIS_MAPS,
    ComplementaryOrientation,
    GyroBias,
    quat_multiply,
    quat_normalize,
    quat_to_euler_degrees,
)


def test_gyro_bias_mean():
    b = GyroBias(samples=4)
    for _ in range(4):
        b.feed((1.0, 2.0, 3.0))
    assert b.done
    bias = b.bias
    assert abs(bias[0] - 1.0) < 1e-9
    assert abs(bias[1] - 2.0) < 1e-9
    assert abs(bias[2] - 3.0) < 1e-9


def test_gyro_bias_requires_feed():
    b = GyroBias(samples=10)
    assert not b.done
    for _ in range(10):
        b.feed((0.0, 0.0, 0.0))
    assert b.done


def test_yaw_integrates_gyro():
    o = ComplementaryOrientation()
    o.update(1.0, (0.0, math.radians(90.0), 0.0), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg - 90.0) < 1e-6
    assert abs(o.pitch_deg) < 1e-6
    assert abs(o.roll_deg) < 1e-6


def test_pitch_follows_gravity_when_static():
    o = ComplementaryOrientation()
    for _ in range(200):
        o.update(0.01, (0.0, 0.0, 0.0), (0.0, 9.81, 0.0))
    assert o.pitch_deg > 80.0


def test_bias_removed_from_gyro():
    o = ComplementaryOrientation()
    bias = (0.5, 0.0, 0.0)
    for _ in range(10):
        o.update(0.01, (0.5, 0.0, 0.0), (0.0, 0.0, 9.81), bias)
    assert abs(o.pitch_deg) < 1e-6
    assert abs(o.yaw_deg) < 1e-6


def test_recenter_resets():
    o = ComplementaryOrientation()
    o.update(1.0, (0.0, math.radians(45.0), 0.0), (0.0, 0.0, 9.81))
    o.recenter()
    assert o.yaw_deg == 0.0
    assert o.pitch_deg == 0.0
    assert o.roll_deg == 0.0


def test_gravity_ref_false_keeps_pitch():
    o = ComplementaryOrientation(use_gravity_ref=False)
    for _ in range(200):
        o.update(0.01, (0.0, 0.0, 0.0), (0.0, 9.81, 0.0))
    assert abs(o.pitch_deg) < 1e-9
    assert abs(o.roll_deg) < 1e-9


def test_gain_scales_rates():
    o = ComplementaryOrientation(use_gravity_ref=False)
    o.set_gain(2.0)
    o.update(1.0, (0.0, math.radians(10.0), 0.0), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg - 20.0) < 1e-6


def test_gain_minimum():
    o = ComplementaryOrientation()
    o.set_gain(0.0)
    assert o.gain == 0.1


def test_default_maps_gyro_y_to_yaw():
    o = ComplementaryOrientation(use_gravity_ref=False)
    o.update(1.0, (0.0, math.radians(30.0), 0.0), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg - 30.0) < 1e-6
    assert abs(o.roll_deg) < 1e-6


def test_swap_yz_maps_gyro_z_to_yaw():
    o = ComplementaryOrientation(use_gravity_ref=False, axis_map="swap_yz")
    o.update(1.0, (0.0, 0.0, math.radians(30.0)), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg - 30.0) < 1e-6
    assert abs(o.roll_deg) < 1e-6
    o.update(1.0, (0.0, math.radians(45.0), 0.0), (0.0, 0.0, 9.81))
    assert abs(o.roll_deg - 45.0) < 1e-6
    assert abs(o.yaw_deg - 30.0) < 1e-6


def test_invert_yaw():
    o = ComplementaryOrientation(use_gravity_ref=False, invert_yaw=True)
    o.update(1.0, (0.0, math.radians(30.0), 0.0), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg + 30.0) < 1e-6


def test_invert_pitch():
    o = ComplementaryOrientation(use_gravity_ref=False, invert_pitch=True)
    o.update(1.0, (math.radians(30.0), 0.0, 0.0), (0.0, 0.0, 9.81))
    assert abs(o.pitch_deg + 30.0) < 1e-6


def test_set_axis_map_rejects_unknown():
    o = ComplementaryOrientation()
    try:
        o.set_axis_map("nope")
        assert False
    except ValueError:
        pass


def test_axis_maps_cover_all_permutations():
    assert sorted(AXIS_MAPS.values()) == [(0, 1, 2), (0, 2, 1), (1, 0, 2), (2, 0, 1)]


def test_yz_tilt_decouples_yaw_from_roll():
    amp = 30.0
    tilt = math.degrees(math.atan2(0.5, 1.0))
    o = ComplementaryOrientation(use_gravity_ref=False, yz_tilt_deg=tilt)
    gy = math.radians(amp * math.cos(math.atan2(0.5, 1.0)))
    gz = math.radians(-amp * math.sin(math.atan2(0.5, 1.0)))
    o.update(1.0, (0.0, gy, gz), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg - amp) < 1e-6
    assert abs(o.roll_deg) < 1e-6


def _from_euler_angles_deg(roll, pitch, yaw):
    import math as _m

    cr, sr = _m.cos(_m.radians(roll) * 0.5), _m.sin(_m.radians(roll) * 0.5)
    cp, sp = _m.cos(_m.radians(pitch) * 0.5), _m.sin(_m.radians(pitch) * 0.5)
    cy, sy = _m.cos(_m.radians(yaw) * 0.5), _m.sin(_m.radians(yaw) * 0.5)
    return quat_normalize((
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ))


def test_quaternion_helpers_roundtrip():
    roll, pitch, yaw = 10.0, 20.0, 30.0
    q = _from_euler_angles_deg(roll, pitch, yaw)
    y, p, r = quat_to_euler_degrees(q)
    assert abs(y - yaw) < 1e-6
    assert abs(p - pitch) < 1e-6
    assert abs(r - roll) < 1e-6


def test_yz_tilt_only_with_default_map():
    o = ComplementaryOrientation(use_gravity_ref=False, axis_map="swap_yz", yz_tilt_deg=30.0)
    o.update(1.0, (0.0, 0.0, math.radians(30.0)), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg - 30.0) < 1e-6


def test_legacy_no_roll_drift_on_return_to_center():
    o = ComplementaryOrientation(use_gravity_ref=False)
    for _ in range(90):
        o.update(0.01, (0.0, math.radians(100.0), 0.0), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg - 90.0) < 0.5
    for _ in range(90):
        o.update(0.01, (0.0, math.radians(-100.0), 0.0), (0.0, 0.0, 9.81))
    for _ in range(90):
        o.update(0.01, (math.radians(100.0), 0.0, 0.0), (0.0, 0.0, 9.81))
    for _ in range(90):
        o.update(0.01, (math.radians(-100.0), 0.0, 0.0), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg) < 0.5
    assert abs(o.pitch_deg) < 0.5
    assert abs(o.roll_deg) < 0.5


def test_legacy_pure_nick_creates_no_roll():
    o = ComplementaryOrientation(use_gravity_ref=False)
    for _ in range(70):
        o.update(0.01, (math.radians(100.0), 0.0, 0.0), (0.0, 0.0, 9.81))
    assert abs(o.pitch_deg - 70.0) < 0.5
    assert abs(o.roll_deg) < 0.5
    assert abs(o.yaw_deg) < 0.5


def test_quat_old_gyro_y_maps_to_yaw_field():
    o = ComplementaryOrientation(use_gravity_ref=False, fusion_mode="quat_old")
    for _ in range(300):
        o.update(0.001, (0.0, math.radians(100.0), 0.0), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg - 30.0) < 0.5
    assert abs(o.pitch_deg) < 0.5
    assert abs(o.roll_deg) < 0.5


def test_quat_new_gyro_y_maps_to_pitch_field():
    o = ComplementaryOrientation(use_gravity_ref=False, fusion_mode="quat_new")
    for _ in range(300):
        o.update(0.001, (0.0, math.radians(100.0), 0.0), (0.0, 0.0, 9.81))
    assert abs(o.pitch_deg - 30.0) < 0.5
    assert abs(o.yaw_deg) < 0.5
    assert abs(o.roll_deg) < 0.5


def test_rate_smoothing_limits_initial_jump():
    o = ComplementaryOrientation(use_gravity_ref=False, rate_smoothing=0.2)
    o.update(1.0, (0.0, math.radians(30.0), 0.0), (0.0, 0.0, 9.81))
    assert o.yaw_deg < 15.0
    o.recenter()
    for _ in range(1000):
        o.update(0.001, (0.0, math.radians(30.0), 0.0), (0.0, 0.0, 9.81))
    assert abs(o.yaw_deg - 30.0) < 1.0
