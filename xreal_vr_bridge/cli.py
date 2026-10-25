import argparse
import ctypes
import json
import os
import socket
import tempfile
import threading
import time
from ctypes import wintypes

from .fusion import ComplementaryOrientation, GyroBias
from .opentrack import pack_opentrack
from .protocol import frame_stream

try:
    import msvcrt
except ImportError:
    msvcrt = None

DEFAULT_VRTO3D_CONFIG = r"C:\Program Files (x86)\Steam\config\vrto3d\default_config.json"

PARAM_RANGES = {
    "depth": (0.0, 0.5, 0.01),
    "convergence": (0.1, 10.0, 0.25),
    "fov": (40.0, 110.0, 1.0),
}

VK_NAMES = {
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}

_HOTKEY_ID = 1
_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312


def parse_hotkey(name):
    return VK_NAMES.get((name or "").upper(), 0)


class HotkeyListener(threading.Thread):
    def __init__(self, vk, on_hotkey):
        super().__init__(daemon=True)
        self.vk = vk
        self.on_hotkey = on_hotkey
        self.registered = False

    def run(self):
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, _HOTKEY_ID, _MOD_NOREPEAT, self.vk):
            return
        self.registered = True
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == _WM_HOTKEY:
                self.on_hotkey()


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
    p.add_argument("--no-gravity-ref", action="store_true",
                   help="use gyro-only integration (no accelerometer pull); recommended for VR")
    p.add_argument("--no-auto-recenter", action="store_true",
                   help="do not recenter automatically after bias calibration")
    p.add_argument("--vrto3d-config", default=DEFAULT_VRTO3D_CONFIG,
                   help="path to VRto3D default_config.json (used by image-parameter keys)")
    p.add_argument("--recenter-hotkey", default="F9",
                   help="global hotkey for recenter (default F9; works while game has focus)")
    return p.parse_args(argv)


def print_help():
    print("[Menü] r = Recenter (geradeaus) | h = Hilfe | q = Ende")
    print("       +/- = Empfindlichkeit (0.1 Schritte) | 1/2/3 = Bild-Param wählen (Tiefe/Konvergenz/FOV)")
    print("       Im Bild-Param-Modus ändern +/- den Wert (schreibt VRto3D-Config); 0 = Modus verlassen")


def load_vrto3d_config(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_vrto3d_config(path, cfg):
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def poll_keys():
    if msvcrt is None:
        return []
    keys = []
    while msvcrt.kbhit():
        ch = msvcrt.getwch()
        keys.append(ch)
    return keys


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

    orientation = ComplementaryOrientation(use_gravity_ref=not args.no_gravity_ref)
    if not args.no_auto_recenter:
        orientation.recenter()
        print("Recenter (geradeaus): Initial ausgerichtet nach Kalibrierung")

    udp = None
    if not args.dry_run:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    last = time.monotonic()
    last_packet = last
    count = 0
    t_start = last

    edit_param = None
    vr_cfg = load_vrto3d_config(args.vrto3d_config)
    if vr_cfg is None:
        print(f"(Hinweis: VRto3D-Config nicht gefunden unter {args.vrto3d_config} – Bild-Param-Tasten inaktiv)")

    recenter_flag = threading.Event()

    def _hotkey_recenter():
        recenter_flag.set()

    vk = parse_hotkey(args.recenter_hotkey)
    hotkey = None
    if vk and os.name == "nt":
        hotkey = HotkeyListener(vk, _hotkey_recenter)
        hotkey.start()
        time.sleep(0.1)
        if hotkey.registered:
            print(f"Globaler Recenter-Hotkey aktiv: {args.recenter_hotkey}")
        else:
            hotkey = None
            print(f"(Hinweis: Hotkey {args.recenter_hotkey} konnte nicht registriert werden)")

    print_help()

    for frame in frame_stream(sock):
        now = time.monotonic()
        dt = max(1e-4, min(0.05, now - last))
        last = now
        orientation.update(dt, frame.gyro, frame.accel, bias)
        count += 1

        if recenter_flag.is_set():
            recenter_flag.clear()
            orientation.recenter()
            print(">>> Recenter (Hotkey): geradeaus ausgerichtet")

        for ch in poll_keys():
            if ch == "r":
                orientation.recenter()
                print(">>> Recenter: geradeaus ausgerichtet")
            elif ch == "q":
                print("Beende auf Wunsch")
                sock.close()
                if udp is not None:
                    udp.close()
                return
            elif ch == "h":
                print_help()
            elif ch == "+" or ch == "=":
                if edit_param and vr_cfg is not None:
                    lo, hi, step = PARAM_RANGES[edit_param]
                    vr_cfg[edit_param] = round(min(hi, max(lo, vr_cfg.get(edit_param, lo) + step)), 2)
                    if save_vrto3d_config(args.vrto3d_config, vr_cfg):
                        print(f">>> {edit_param} = {vr_cfg[edit_param]} (VRto3D-Config geschrieben; im Spiel Ctrl+Shift+F10 zum Neuladen)")
                    else:
                        print(">>> Fehler beim Schreiben der VRto3D-Config")
                else:
                    orientation.set_gain(orientation.gain + 0.1)
                    print(f">>> Empfindlichkeit = {orientation.gain:.1f}")
            elif ch == "-":
                if edit_param and vr_cfg is not None:
                    lo, hi, step = PARAM_RANGES[edit_param]
                    vr_cfg[edit_param] = round(min(hi, max(lo, vr_cfg.get(edit_param, hi) - step)), 2)
                    if save_vrto3d_config(args.vrto3d_config, vr_cfg):
                        print(f">>> {edit_param} = {vr_cfg[edit_param]} (VRto3D-Config geschrieben; im Spiel Ctrl+Shift+F10 zum Neuladen)")
                    else:
                        print(">>> Fehler beim Schreiben der VRto3D-Config")
                else:
                    orientation.set_gain(orientation.gain - 0.1)
                    print(f">>> Empfindlichkeit = {orientation.gain:.1f}")
            elif ch in ("1", "2", "3"):
                edit_param = ("depth", "convergence", "fov")[int(ch) - 1]
                if vr_cfg is not None:
                    print(f">>> Bild-Param: {edit_param} = {vr_cfg.get(edit_param)}  (+/- ändern, 0 beenden)")
                else:
                    print(f">>> Bild-Param: {edit_param} (Config nicht verfügbar)")
            elif ch == "0":
                edit_param = None
                print(">>> Bild-Param-Modus beendet")
            elif ch == "a":
                orientation.recenter()
                print(">>> Recenter: geradeaus ausgerichtet")

        if args.dry_run:
            if count == 1 or count % 100 == 0:
                print(
                    f"yaw={orientation.yaw_deg:8.2f} pitch={orientation.pitch_deg:8.2f} "
                    f"roll={orientation.roll_deg:8.2f} deg gain={orientation.gain:.1f}"
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
