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
            except socket.timeout:
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
