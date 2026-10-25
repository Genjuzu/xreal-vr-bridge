from xreal_vr_bridge.opentrack import OPENTRACK_SIZE, pack_opentrack, unpack_opentrack


def test_packet_size():
    assert OPENTRACK_SIZE == 48


def test_pack_unpack_roundtrip():
    pkt = pack_opentrack(0.1, 0.2, 0.3, 10.0, 20.0, 30.0)
    assert len(pkt) == 48
    x, y, z, yaw, pitch, roll = unpack_opentrack(pkt)
    assert abs(x - 0.1) < 1e-9
    assert abs(yaw - 10.0) < 1e-9
    assert abs(pitch - 20.0) < 1e-9
    assert abs(roll - 30.0) < 1e-9


def test_defaults_are_zero():
    pkt = pack_opentrack()
    assert unpack_opentrack(pkt) == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
