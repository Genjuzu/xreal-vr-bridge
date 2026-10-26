import socket
import struct
import threading
import time

from tools.mock_imu_server import build_frame

from xreal_vr_bridge.cli import main
from xreal_vr_bridge.opentrack import OPENTRACK_SIZE

MOCK_PORT = 52980


def start_mock_server(rate=1000.0):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", MOCK_PORT))
    srv.listen(1)
    period = 1.0 / rate
    stop = threading.Event()

    def run():
        conn, _ = srv.accept()
        seq = 0
        gyro = (0.0, struct.unpack("<f", struct.pack("<f", 0.0))[0], 0.0)
        while not stop.is_set():
            try:
                conn.sendall(build_frame(seq, gyro, (0.0, 0.0, 9.81), 25.0))
            except OSError:
                break
            seq = (seq + 1) & 0xFFFFFF
            time.sleep(period)
        try:
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return srv, stop


def start_udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    udp_port = sock.getsockname()[1]
    sock.settimeout(5.0)
    packets = []

    def run():
        while True:
            try:
                data, _ = sock.recvfrom(4096)
            except (socket.timeout, OSError):
                break
            packets.append(data)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return sock, packets, t, udp_port


def test_bridge_mock_to_udp():
    srv, stop = start_mock_server()
    sock, packets, listener, udp_port = start_udp_listener()
    try:
        main([
            "--host", "127.0.0.1",
            "--imu-port", str(MOCK_PORT),
            "--udp-ip", "127.0.0.1",
            "--udp-port", str(udp_port),
            "--calib-samples", "20",
            "--duration", "2.0",
        ])
        listener.join(timeout=6)
        assert len(packets) > 10
        for pkt in packets:
            assert len(pkt) == OPENTRACK_SIZE
            x, y, z, yaw, pitch, roll = struct.unpack("<dddddd", pkt)
            assert (x, y, z) == (0.0, 0.0, 0.0)
            assert abs(pitch) < 1e-6
            assert abs(roll) < 1e-6
            assert abs(yaw) < 1e-6
    finally:
        stop.set()
        srv.close()
        sock.close()


MOCK_PORT_BURST = 52981


def test_bridge_uses_device_timestamps_for_bursty_stream():
    """Glasses data arrives in TCP bursts. 1000 frames of +90 deg/s about sensor
    Y (= turn right) stamped 1 ms apart but sent as fast as possible must give
    yaw ~ +90 deg (host clock alone would see only a few ms)."""
    import math

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", MOCK_PORT_BURST))
    srv.listen(1)
    stop = threading.Event()
    level = (0.0, -9.81, 0.0)

    def run():
        conn, _ = srv.accept()
        ts = 1_000_000_000
        seq = 0
        burst = bytearray()
        # 50 calib + ~0.6 s still (start-up auto recenter waits for stillness)
        for i in range(1750):
            gyro = (0.0, math.radians(90.0), 0.0) if i >= 750 else (0.0, 0.0, 0.0)
            burst += build_frame(seq, gyro, level, 25.0, ts)
            seq += 1
            ts += 1_000_000
        try:
            conn.sendall(bytes(burst))
            while not stop.is_set():
                conn.sendall(build_frame(seq, (0.0, 0.0, 0.0), level, 25.0, ts))
                seq += 1
                ts += 1_000_000
                time.sleep(0.001)
        except OSError:
            pass
        finally:
            conn.close()

    threading.Thread(target=run, daemon=True).start()
    sock, packets, listener, udp_port = start_udp_listener()
    try:
        main([
            "--host", "127.0.0.1",
            "--imu-port", str(MOCK_PORT_BURST),
            "--udp-ip", "127.0.0.1",
            "--udp-port", str(udp_port),
            "--calib-samples", "50",
            "--fusion-mode", "ref",
            "--duration", "1.5",
        ])
        listener.join(timeout=6)
        assert packets
        _x, _y, _z, yaw, pitch, roll = struct.unpack("<dddddd", packets[-1])
        assert abs(yaw - 90.0) < 2.0, yaw
        assert abs(pitch) < 1.0 and abs(roll) < 1.0
    finally:
        stop.set()
        srv.close()
        sock.close()
