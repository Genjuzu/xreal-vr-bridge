import socket
import struct

from xreal_vr_bridge.protocol import (
    ACCEL_OFFSET,
    FRAME_SIZE,
    GYRO_OFFSET,
    IMUFrame,
    MAGIC_A,
    MAGIC_B,
    TEMP_OFFSET,
    is_magic,
    parse_frame,
)


def make_frame(gyro=(0.0, 0.0, 0.0), accel=(0.0, 0.0, 9.81), temp=25.0, magic=MAGIC_A):
    frame = bytearray(FRAME_SIZE)
    frame[0], frame[1] = magic
    struct.pack_into("<fff", frame, GYRO_OFFSET, *gyro)
    struct.pack_into("<fff", frame, ACCEL_OFFSET, *accel)
    struct.pack_into("<f", frame, TEMP_OFFSET, temp)
    return bytes(frame)


class FakeSocket:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def recv(self, n):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def test_parse_frame_values():
    f = parse_frame(make_frame(gyro=(0.1, -0.2, 0.3), accel=(1.0, 2.0, 9.81), temp=25.5))
    assert isinstance(f, IMUFrame)
    assert abs(f.gyro[0] - 0.1) < 1e-6
    assert abs(f.gyro[1] + 0.2) < 1e-6
    assert abs(f.gyro[2] - 0.3) < 1e-6
    assert abs(f.accel[2] - 9.81) < 1e-4
    assert abs(f.temp_c - 25.5) < 1e-4


def test_parse_frame_rejects_short():
    try:
        parse_frame(b"\x00" * 133)
        assert False
    except ValueError:
        pass


def test_is_magic():
    assert is_magic(*MAGIC_A)
    assert is_magic(*MAGIC_B)
    assert not is_magic(0x00, 0x00)


def test_frame_stream_single_chunk():
    frames = [make_frame(), make_frame()]
    fake = FakeSocket([frames[0] + frames[1]])
    out = list(iter_stream(fake))
    assert len(out) == 2


def test_frame_stream_fragmented():
    f = make_frame()
    fake = FakeSocket([f[:10], f[10:80], f[80:]])
    out = list(iter_stream(fake))
    assert len(out) == 1
    assert out[0].temp_c == 25.0


def test_frame_stream_resync_after_garbage():
    garbage = b"\xde\xad\xbe\xef" + make_frame()
    fake = FakeSocket([garbage])
    out = list(iter_stream(fake))
    assert len(out) == 1


def test_frame_stream_both_magics():
    fake = FakeSocket([make_frame(magic=MAGIC_A), make_frame(magic=MAGIC_B)])
    out = list(iter_stream(fake))
    assert len(out) == 2


def test_frame_stream_skips_nan_frames():
    nan_frame = make_frame(gyro=(float("nan"), 0.0, 0.0))
    fake = FakeSocket([nan_frame, make_frame(), nan_frame])
    out = list(iter_stream(fake))
    assert len(out) == 1
    assert out[0].temp_c == 25.0


def iter_stream(fake_sock):
    from xreal_vr_bridge.protocol import frame_stream

    return frame_stream(fake_sock)
