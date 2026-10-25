import argparse
import socket
import time

from .fusion import ComplementaryOrientation, GyroBias
from .opentrack import pack_opentrack
from .protocol import frame_stream


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="xreal-bridge",
        description="XREAL One/Pro (X1) IMU -> OpenTrack UDP bridge for SteamVR / VRto3D / simulators",
    )
    p.add_argument("--host", default="169.254.2.1")
    p.add_argument("--imu-port", type=int, default=52998)
    p.add_argument("--udp-ip", default="127.0.0.1")
    p.add_argument("--udp-port", type=int, default=4242)
    p.add_argument("--calib-samples", type=int, default=500)
    p.add_argument("--max-rate", type=int, default=120, help="max UDP packets/sec")
    p.add_argument("--duration", type=float, default=0.0, help="exit after N seconds (0 = run forever)")
    p.add_argument("--dry-run", action="store_true", help="print orientation instead of sending UDP")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    print(f"connecting {args.host}:{args.imu_port} ...")
    sock = socket.create_connection((args.host, args.imu_port), timeout=5.0)
    sock.settimeout(10.0)
    print("connected")

    calib = GyroBias(args.calib_samples)
    for frame in frame_stream(sock):
        calib.feed(frame.gyro)
        if calib.done:
            break
    bias = calib.bias
    print(f"gyro bias (rad/s): {bias[0]:+.5f}, {bias[1]:+.5f}, {bias[2]:+.5f}")

    orientation = ComplementaryOrientation()
    udp = None
    if not args.dry_run:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    last = time.monotonic()
    last_packet = last
    count = 0
    t_start = last

    for frame in frame_stream(sock):
        now = time.monotonic()
        dt = max(1e-4, min(0.05, now - last))
        last = now
        orientation.update(dt, frame.gyro, frame.accel, bias)
        count += 1

        if args.dry_run:
            if count == 1 or count % 100 == 0:
                print(
                    f"yaw={orientation.yaw_deg:8.2f} pitch={orientation.pitch_deg:8.2f} "
                    f"roll={orientation.roll_deg:8.2f} deg"
                )
        else:
            if now - last_packet >= 1.0 / max(1, args.max_rate):
                packet = pack_opentrack(
                    0.0, 0.0, 0.0,
                    orientation.yaw_deg, orientation.pitch_deg, orientation.roll_deg,
                )
                udp.sendto(packet, (args.udp_ip, args.udp_port))
                last_packet = now

        if args.verbose and count % 1000 == 0:
            elapsed = now - t_start
            print(f"frames={count} rate={count / elapsed:.0f} Hz", flush=True)

        if args.duration and now - t_start >= args.duration:
            break

    if udp is not None:
        udp.close()
    sock.close()
    print(f"done: {count} frames processed")


if __name__ == "__main__":
    main()
