import argparse
import socket
import struct
import time

from xreal_vr_bridge.protocol import (
    ACCEL_OFFSET, FRAME_SIZE, GYRO_OFFSET, TEMP_OFFSET, TIMESTAMP_OFFSET,
)


def build_frame(seq, gyro, accel, temp_c, timestamp_ns=0):
    frame = bytearray(FRAME_SIZE)
    frame[0] = 0x28
    frame[1] = 0x36
    frame[2] = (seq >> 16) & 0xFF
    frame[3] = (seq >> 8) & 0xFF
    frame[4] = seq & 0xFF
    struct.pack_into("<fff", frame, GYRO_OFFSET, *gyro)
    struct.pack_into("<fff", frame, ACCEL_OFFSET, *accel)
    struct.pack_into("<f", frame, TEMP_OFFSET, temp_c)
    struct.pack_into("<Q", frame, TIMESTAMP_OFFSET, timestamp_ns)
    return bytes(frame)


def main():
    p = argparse.ArgumentParser(description="Mock XREAL X1 IMU server (for testing without glasses)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=52998)
    p.add_argument("--rate", type=float, default=1000.0)
    p.add_argument("--gyro", type=float, nargs=3, default=(0.0, 0.0, 0.0))
    p.add_argument("--accel", type=float, nargs=3, default=(0.0, -9.81, 0.0),
                   help="m/s^2; glasses level = (0, -9.81, 0) (sensor Y points down)")
    p.add_argument("--yaw-rate", type=float, default=0.0, help="deg/s around Y axis")
    args = p.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(1)
    print(f"mock IMU listening on {args.host}:{args.port}")

    period = 1.0 / args.rate
    seq = 0
    while True:
        conn, addr = srv.accept()
        print(f"client connected: {addr}")
        try:
            while True:
                gyro = args.gyro
                if args.yaw_rate:
                    gyro = (gyro[0], math.radians(args.yaw_rate), gyro[2])
                conn.sendall(build_frame(seq, gyro, args.accel, 25.0, int(time.monotonic() * 1e9)))
                seq = (seq + 1) & 0xFFFFFF
                time.sleep(period)
        except (ConnectionResetError, BrokenPipeError, OSError):
            conn.close()


if __name__ == "__main__":
    import math

    main()
