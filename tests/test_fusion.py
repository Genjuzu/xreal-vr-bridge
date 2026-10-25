import math

from xreal_vr_bridge.fusion import ComplementaryOrientation, GyroBias


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
