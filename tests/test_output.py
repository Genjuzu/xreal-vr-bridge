import math
import socket
import struct
import time

from xreal_vr_bridge.output import PoseSender, QuatOneEuro


def test_sender_paces_and_sends_latest_pose():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(0.5)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s = PoseSender(tx, rx.getsockname(), 200)
    s.start()
    for i in range(50):           # a "burst" of poses: only the newest matters
        s.update(float(i), 0.0, 0.0)
    time.sleep(0.5)
    s.stop()
    pkts = []
    try:
        while True:
            pkts.append(struct.unpack("<dddddd", rx.recv(64)))
    except socket.timeout:
        pass
    tx.close()
    rx.close()
    assert 60 <= len(pkts) <= 130, len(pkts)
    assert all(p[3] == 49.0 for p in pkts)


def test_one_euro_off_is_passthrough():
    f = QuatOneEuro(0.0)
    assert f.filter_euler(10.0, 5.0, 1.0, 0.001) == (10.0, 5.0, 1.0)


def test_one_euro_smooths_jitter_but_follows_fast_turns():
    dt = 0.001
    f = QuatOneEuro(3.0, 0.3)
    # still head with +-0.3 deg jitter -> output jitter much smaller
    out = []
    for i in range(2000):
        y, _p, _r = f.filter_euler(0.3 * (1 if i % 2 else -1), 0.0, 0.0, dt)
        out.append(y)
    assert max(abs(v) for v in out[-500:]) < 0.15
    # fast turn 200 deg/s: lag stays small
    f.reset()
    yaw = 0.0
    for i in range(500):
        yaw += 200.0 * dt
        y, _p, _r = f.filter_euler(yaw, 0.0, 0.0, dt)
    assert abs(yaw - y) < 3.0, (yaw, y)


def test_yaw_offset_is_world_heading_and_survives_recenter():
    from xreal_vr_bridge.ahrs import opentrack_to_q, q_axis_angle, q_mul
    from xreal_vr_bridge.fusion import ComplementaryOrientation
    o = ComplementaryOrientation(fusion_mode="ref")
    o.set_yaw_offset(180.0)
    assert o.yaw_offset_deg == -180.0
    o.yaw_deg, o.pitch_deg, o.roll_deg = 30.0, 20.0, 5.0
    y, p, r = o.output_euler()
    assert (p, r) == (20.0, 5.0) and abs(y - (-150.0)) < 1e-9
    # same as rotating the whole head pose about world up (VRto3D convention)
    want = q_mul(q_axis_angle((0.0, 1.0, 0.0), math.radians(-180.0)), opentrack_to_q(30.0, 20.0, 5.0))
    got = opentrack_to_q(y, p, r)
    assert abs(abs(sum(a * b for a, b in zip(want, got))) - 1.0) < 1e-9
    o.recenter()   # not initialised -> zero, offset kept
    assert o.output_euler()[0] == -180.0
    o.set_yaw_offset(o.yaw_offset_deg + 15.0)
    assert abs(o.yaw_offset_deg - (-165.0)) < 1e-9


def test_yaw_offset_saved_in_state(tmp_path, monkeypatch):
    import tempfile
    from xreal_vr_bridge import cli
    from xreal_vr_bridge.fusion import ComplementaryOrientation
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    o = ComplementaryOrientation(fusion_mode="ref")
    o.set_yaw_offset(90.0)
    cli.save_state(o)
    assert cli.load_state()["yaw_offset_deg"] == 90.0
