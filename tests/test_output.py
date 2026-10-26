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


def test_aligned_offsets_saved_in_state(tmp_path, monkeypatch):
    import tempfile
    from xreal_vr_bridge import cli
    from xreal_vr_bridge.fusion import ComplementaryOrientation
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    o = ComplementaryOrientation(fusion_mode="ref")
    o.set_yaw_offset(180.0)
    o.aligned_offsets = None
    cli.apply_align_action(o, "yaw", 5.0, (180.0, 0.0))
    cli.apply_align_action(o, "pitch", -1.0, (180.0, 0.0))
    assert "aligned_yaw_offset_deg" not in (cli.load_state() or {})   # live only
    cli.apply_align_action(o, "save", 0.0, (180.0, 0.0))
    st = cli.load_state()
    assert st["aligned_yaw_offset_deg"] == -175.0 and st["aligned_pitch_offset_deg"] == -1.0
    o.recenter()                                   # F9 keeps the alignment
    assert (o.yaw_offset_deg, o.pitch_offset_deg) == (-175.0, -1.0)
    cli.apply_align_action(o, "reset", 0.0, (180.0, 0.0))
    assert (o.yaw_offset_deg, o.pitch_offset_deg) == (-180.0, 0.0)
    assert "aligned_yaw_offset_deg" not in cli.load_state()


def test_pitch_offset_is_about_local_right_axis():
    from xreal_vr_bridge.ahrs import opentrack_to_q, q_axis_angle, q_mul
    from xreal_vr_bridge.fusion import ComplementaryOrientation
    o = ComplementaryOrientation(fusion_mode="ref")
    o.set_pitch_offset(10.0)
    assert all(abs(a - b) < 1e-9 for a, b in zip(o.output_euler(), (0.0, 10.0, 0.0)))
    o.yaw_deg = 30.0                       # head turned right: still pure pitch-up
    y, p, r = o.output_euler()
    assert abs(y - 30.0) < 1e-6 and abs(p - 10.0) < 1e-6 and abs(r) < 1e-6
    o.set_yaw_offset(-5.0)                 # yaw offset left
    y, p, r = o.output_euler()
    assert abs(y - 25.0) < 1e-6 and abs(p - 10.0) < 1e-6
    o.yaw_deg, o.pitch_deg, o.roll_deg = 20.0, 5.0, 15.0   # general pose
    want = q_mul(q_mul(q_axis_angle((0.0, 1.0, 0.0), math.radians(5.0)),
                       opentrack_to_q(20.0, 5.0, 15.0)),
                 q_axis_angle((1.0, 0.0, 0.0), math.radians(10.0)))
    got = opentrack_to_q(*o.output_euler())
    assert abs(abs(sum(a * b for a, b in zip(want, got))) - 1.0) < 1e-9


def test_console_arrow_keys_and_hotkey_parsing():
    from xreal_vr_bridge import cli
    assert cli.translate_keys(["\xe0", "K", "\xe0", "H", "\r", "\x08", "b"]) == \
        ["LEFT", "UP", "ENTER", "BACKSPACE", "b"]
    assert cli.translate_keys(["\x00", "M"], shift=True) == ["S-RIGHT"]
    assert cli.parse_hotkey_ex("Ctrl+Alt+Left") == (0x25, 0x0002 | 0x0001)
    assert cli.parse_hotkey_ex("Ctrl+Alt+Shift+Down") == (0x28, 0x0007)
    assert cli.parse_hotkey_ex("Ctrl+Alt+Enter")[0] == 0x0D
    assert cli.parse_hotkey_ex("Foo+F9") == (0, 0)
    assert cli.ALIGN_KEYS["LEFT"] == ("yaw", -5.0) and cli.ALIGN_KEYS["S-UP"] == ("pitch", 1.0)
