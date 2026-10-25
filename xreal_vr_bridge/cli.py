import argparse
import ctypes
import json
import os
import socket
import tempfile
import threading
import time
from ctypes import wintypes

from .fusion import AXIS_MAPS, ComplementaryOrientation, GyroBias
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

_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312


def parse_hotkey(name):
    return VK_NAMES.get((name or "").upper(), 0)


class HotkeyManager(threading.Thread):
    def __init__(self, bindings):
        super().__init__(daemon=True)
        self.bindings = bindings
        self.registered = 0

    def run(self):
        user32 = ctypes.windll.user32
        for idx, (vk, _cb) in enumerate(self.bindings, start=1):
            if not vk:
                continue
            if user32.RegisterHotKey(None, idx, _MOD_NOREPEAT, vk):
                self.registered += 1
        if not self.registered:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == _WM_HOTKEY:
                idx = msg.wParam - 1
                if 0 <= idx < len(self.bindings):
                    vk, cb = self.bindings[idx]
                    if vk:
                        cb()


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
    p.add_argument("--axis-hotkey", default="F10",
                   help="global hotkey to cycle gyro axis mapping (default F10)")
    p.add_argument("--invert-yaw-hotkey", default="F11",
                   help="global hotkey to toggle yaw sign (default F11)")
    p.add_argument("--invert-pitch-hotkey", default="F12",
                   help="global hotkey to toggle pitch sign (default F12)")
    p.add_argument("--axis-map", default="default",
                   choices=["default", "swap_yz", "swap_xy", "rotate"],
                   help="gyro axis -> (pitch,yaw,roll) mapping. default: (X,Y,Z). "
                        "swap_yz: (X,Z,Y) if yaw/roll appear swapped, etc.")
    p.add_argument("--invert-yaw", action="store_true")
    p.add_argument("--invert-pitch", action="store_true")
    return p.parse_args(argv)


def print_help():
    print("[Menü] r = Recenter (geradeaus) | h = Hilfe | q = Ende")
    print("       +/- = Empfindlichkeit (0.1 Schritte) | 1/2/3 = Bild-Param wählen (Tiefe/Konvergenz/FOV)")
    print("       Im Bild-Param-Modus ändern +/- den Wert (schreibt VRto3D-Config); 0 = Modus verlassen")
    print("       a = Achsen-Mapping wechseln (wenn links/rechts die Welt kippt) | y = Yaw-Vorzeichen toggeln")
    print("       p = Pitch-Vorzeichen toggeln (jede Änderung recentert automatisch)")


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

    orientation = ComplementaryOrientation(
        use_gravity_ref=not args.no_gravity_ref,
        axis_map=args.axis_map,
        invert_yaw=args.invert_yaw,
        invert_pitch=args.invert_pitch,
    )
    if not args.no_auto_recenter:
        orientation.recenter()
        print(
            f"Recenter (geradeaus): Initial ausgerichtet nach Kalibrierung "
            f"[axis_map={orientation.axis_map} yaw_sign={'I' if orientation.invert_yaw else '+'} "
            f"pitch_sign={'I' if orientation.invert_pitch else '+'}]"
        )

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
    axis_flag = threading.Event()
    yaw_flag = threading.Event()
    pitch_flag = threading.Event()

    def cycle_axis():
        maps = list(AXIS_MAPS)
        idx = maps.index(orientation.axis_map)
        orientation.set_axis_map(maps[(idx + 1) % len(maps)])
        orientation.recenter()
        print(
            f">>> Achsen-Mapping = {orientation.axis_map} "
            f"(pitch/yaw/roll <- {AXIS_MAPS[orientation.axis_map]}) – recenter"
        )

    def toggle_yaw():
        orientation.set_invert_yaw(not orientation.invert_yaw)
        orientation.recenter()
        print(f">>> Yaw-Vorzeichen = {'invertiert' if orientation.invert_yaw else 'normal'} – recenter")

    def toggle_pitch():
        orientation.set_invert_pitch(not orientation.invert_pitch)
        orientation.recenter()
        print(f">>> Pitch-Vorzeichen = {'invertiert' if orientation.invert_pitch else 'normal'} – recenter")

    hotkey_names = [
        args.recenter_hotkey,
        args.axis_hotkey,
        args.invert_yaw_hotkey,
        args.invert_pitch_hotkey,
    ]
    bindings = [
        (parse_hotkey(hotkey_names[0]), lambda: recenter_flag.set()),
        (parse_hotkey(hotkey_names[1]), lambda: axis_flag.set()),
        (parse_hotkey(hotkey_names[2]), lambda: yaw_flag.set()),
        (parse_hotkey(hotkey_names[3]), lambda: pitch_flag.set()),
    ]
    hotkey = None
    if os.name == "nt":
        hotkey = HotkeyManager(bindings)
        hotkey.start()
        time.sleep(0.1)
        if hotkey.registered:
            active = [n for n, (vk, _cb) in zip(hotkey_names, bindings) if vk]
            print(f"Globale Hotkeys aktiv: {', '.join(active)}")
        else:
            hotkey = None
            print("(Hinweis: Keine Hotkeys konnten registriert werden)")

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
        if axis_flag.is_set():
            axis_flag.clear()
            cycle_axis()
        if yaw_flag.is_set():
            yaw_flag.clear()
            toggle_yaw()
        if pitch_flag.is_set():
            pitch_flag.clear()
            toggle_pitch()

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
                cycle_axis()
            elif ch == "y":
                toggle_yaw()
            elif ch == "p":
                toggle_pitch()

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
