import math
import struct

FRAME_SIZE = 134
GYRO_OFFSET = 34
ACCEL_OFFSET = 46
TEMP_OFFSET = 70

MAGIC_A = (0x28, 0x36)
MAGIC_B = (0x27, 0x36)
VALID_MAGICS = (MAGIC_A, MAGIC_B)


class IMUFrame:
    __slots__ = ("gyro", "accel", "temp_c")

    def __init__(self, gyro, accel, temp_c):
        self.gyro = gyro
        self.accel = accel
        self.temp_c = temp_c

    def __repr__(self):
        gx, gy, gz = self.gyro
        ax, ay, az = self.accel
        return (
            f"IMUFrame(gyro=({gx:.4f},{gy:.4f},{gz:.4f}) rad/s, "
            f"accel=({ax:.3f},{ay:.3f},{az:.3f}) m/s^2, "
            f"temp={self.temp_c:.1f} C)"
        )


def parse_frame(frame):
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"frame len {len(frame)} != {FRAME_SIZE}")
    gyro = struct.unpack_from("<fff", frame, GYRO_OFFSET)
    accel = struct.unpack_from("<fff", frame, ACCEL_OFFSET)
    temp_c = struct.unpack_from("<f", frame, TEMP_OFFSET)[0]
    return IMUFrame(gyro, accel, temp_c)


def is_magic(byte0, byte1):
    return (byte0, byte1) in VALID_MAGICS


def has_valid_sensor_data(frame):
    if any(not math.isfinite(v) for v in struct.unpack_from("<fff", frame, GYRO_OFFSET)):
        return False
    if any(not math.isfinite(v) for v in struct.unpack_from("<fff", frame, ACCEL_OFFSET)):
        return False
    return True


def frame_stream(sock, buffer_size=65536):
    buf = bytearray()
    while True:
        chunk = sock.recv(buffer_size)
        if not chunk:
            return
        buf.extend(chunk)
        while len(buf) >= FRAME_SIZE:
            if is_magic(buf[0], buf[1]):
                frame = bytes(buf[:FRAME_SIZE])
                del buf[:FRAME_SIZE]
                if has_valid_sensor_data(frame):
                    yield parse_frame(frame)
            else:
                del buf[0]
