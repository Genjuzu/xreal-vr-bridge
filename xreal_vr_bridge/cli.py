import argparse
import ctypes
import json
import math
import os
import queue
import socket
import tempfile
import threading
import time
from ctypes import wintypes

from .fusion import AXIS_MAPS, ComplementaryOrientation, GyroBias
from .opentrack import pack_opentrack
from .output import PoseSender, QuatOneEuro
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

QUIET_MEAN_THRESHOLD_RAD = math.radians(0.3)
QUIET_SAMPLES = 3000


def quiet_bias_step(bias, gyro, q_state, mean_threshold=QUIET_MEAN_THRESHOLD_RAD,
                    samples=QUIET_SAMPLES):
    q_count, q_sum = q_state
    q_sum = tuple(s + g for s, g in zip(q_sum, gyro))
    q_count += 1
    if q_count >= samples:
        mean = tuple(s / q_count for s in q_sum)
        if max(map(abs, mean)) < mean_threshold:
            return mean, (0, (0.0, 0.0, 0.0)), True
        return bias, (0, (0.0, 0.0, 0.0)), False
    return bias, (q_count, q_sum), False

MAX_FRAME_DT = 0.05


def frame_dt(prev_ts_ns, ts_ns, host_dt):
    """Integration step for one IMU frame.

    Frames arrive in TCP bursts, so the host clock gives ~0 for most frames of
    a burst and one large gap for the first.  The glasses stamp every frame
    (u64 ns @ offset 14); use that when it is plausible, else the host clock.
    """
    if prev_ts_ns and ts_ns and ts_ns > prev_ts_ns:
        d = (ts_ns - prev_ts_ns) * 1e-9
        if 1e-5 <= d <= MAX_FRAME_DT:
            return d
    return max(1e-4, min(MAX_FRAME_DT, host_dt))


VK_NAMES = {
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "ENTER": 0x0D,
    "BACKSPACE": 0x08,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}

_MOD_NOREPEAT = 0x4000
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_ALT = 0x0001
_WM_HOTKEY = 0x0312

_MODIFIERS = {
    "CTRL": _MOD_CONTROL,
    "SHIFT": _MOD_SHIFT,
    "ALT": _MOD_ALT,
}


def parse_hotkey(name):
    vk, _mod = parse_hotkey_ex(name)
    return vk


def parse_hotkey_ex(name):
    """'F9', 'Ctrl+F11', 'Ctrl+Alt+Shift+Left' -> (vk, modifier bits)."""
    name = (name or "").upper()
    mod = 0
    if "+" in name:
        *prefixes, name = name.split("+")
        for prefix in prefixes:
            bit = _MODIFIERS.get(prefix.strip(), 0)
            if not bit:
                return 0, 0
            mod |= bit
    return VK_NAMES.get(name.strip(), 0), mod


class HotkeyManager(threading.Thread):
    def __init__(self, bindings):
        super().__init__(daemon=True)
        self.bindings = bindings
        self.registered = 0

    def run(self):
        user32 = ctypes.windll.user32
        for idx, (vk, mod, _cb) in enumerate(self.bindings, start=1):
            if not vk:
                continue
            if user32.RegisterHotKey(None, idx, _MOD_NOREPEAT | mod, vk):
                self.registered += 1
        if not self.registered:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == _WM_HOTKEY:
                idx = msg.wParam - 1
                if 0 <= idx < len(self.bindings):
                    vk, mod, cb = self.bindings[idx]
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
    p.add_argument("--max-rate", type=int, default=500,
                   help="UDP packets/sec (default 500; VRto3D samples at 2x display Hz)")
    p.add_argument("--sender", choices=["thread", "inline"], default="thread",
                   help="thread = send latest pose on a steady clock (default, less judder); "
                        "inline = old behaviour (send from the IMU loop)")
    p.add_argument("--smooth", type=float, default=0.0, metavar="HZ",
                   help="One-Euro smoothing min cutoff in Hz (0 = off; try 2..5). "
                        "Adaptive: almost no lag on fast turns")
    p.add_argument("--smooth-beta", type=float, default=0.3,
                   help="One-Euro speed coefficient (higher = less lag when turning)")
    p.add_argument("--duration", type=float, default=0.0, help="exit after N seconds (0 = run forever)")
    p.add_argument("--dry-run", action="store_true", help="print orientation instead of sending UDP")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--no-gravity-ref", action="store_true",
                   help="use gyro-only integration (no accelerometer pull); recommended for VR")
    p.add_argument("--no-auto-recenter", action="store_true",
                   help="do not recenter automatically after bias calibration")
    p.add_argument("--vrto3d-config", default=DEFAULT_VRTO3D_CONFIG,
                   help="path to VRto3D default_config.json (used by image-parameter keys)")
    p.add_argument("--recenter-yaw-offset", type=float, default=None, metavar="DEG",
                   help="heading added after every recenter (180 = face what is behind you, "
                        "e.g. the SteamVR dashboard). Default for Backspace; a position saved "
                        "with Enter wins")
    p.add_argument("--recenter-pitch-offset", type=float, default=0.0, metavar="DEG",
                   help="pitch added after every recenter (+ = view up); default for Backspace")
    p.add_argument("--align-modifier", default="Ctrl+Alt",
                   help="modifier for the global alignment hotkeys (arrows/Enter/Backspace); "
                        "'' disables them")
    p.add_argument("--flip-hotkey", default="F8",
                   help="global hotkey: toggle extra 180 deg view flip (default F8)")
    p.add_argument("--recenter-hotkey", default="F9",
                   help="global hotkey for recenter (default F9; works while game has focus)")
    p.add_argument("--axis-hotkey", default="F10",
                   help="global hotkey to cycle gyro axis mapping (default F10)")
    p.add_argument("--invert-yaw-hotkey", default="F11",
                   help="global hotkey to toggle yaw sign (default F11)")
    p.add_argument("--invert-pitch-hotkey", default="F12",
                   help="global hotkey to toggle pitch sign (default F12)")
    p.add_argument("--tilt-up-hotkey", default="Ctrl+F11",
                   help="global hotkey to increase YZ tilt by 1 deg (default Ctrl+F11)")
    p.add_argument("--tilt-down-hotkey", default="Ctrl+F10",
                   help="global hotkey to decrease YZ tilt by 1 deg (default Ctrl+F10)")
    p.add_argument("--tilt-reset-hotkey", default="Ctrl+F12",
                   help="global hotkey to reset YZ tilt to 0 (default Ctrl+F12)")
    p.add_argument("--disable-quiet-calib", action="store_true",
                   help="disable continuous gyro bias recalibration while the head is still")
    p.add_argument("--rate-smoothing", type=float, default=0.0,
                   help="exponential rate smoothing factor 0..1 (e.g. 0.2 reduces jitter)")
    p.add_argument("--fusion-mode", default=None,
                   choices=["legacy", "quat_old", "quat_new", "ref"],
                   help="orientation integration mode (default ref = community-validated XREAL "
                        "pipeline with gravity alignment + bias learning; toggle live with 'f'). "
                        "An explicit value always wins over the saved state file.")
    p.add_argument("--axis-map", default="default",
                   choices=["default", "swap_yz", "swap_xy", "rotate"],
                   help="gyro axis -> (pitch,yaw,roll) mapping. default: (X,Y,Z). "
                        "swap_yz: (X,Z,Y) if yaw/roll appear swapped, etc.")
    p.add_argument("--invert-yaw", action="store_true")
    p.add_argument("--invert-pitch", action="store_true")
    p.add_argument("--yz-tilt", type=float, default=32.0,
                   help="sensor tilt in the YZ plane, degrees (only with --axis-map default). "
                        "Measured ~32 deg on the XREAL One Pro; tune with Ctrl+F10/F11/F12.")
    return p.parse_args(argv)


def print_help():
    print("[Menü] r = Recenter (geradeaus) | h = Hilfe | q = Ende")
    print("       +/- = Empfindlichkeit (0.1 Schritte) | 1/2/3 = Bild-Param wählen (Tiefe/Konvergenz/FOV)")
    print("       Im Bild-Param-Modus ändern +/- den Wert (schreibt VRto3D-Config); 0 = Modus verlassen")
    print("       a = Achsen-Mapping wechseln (wenn links/rechts die Welt kippt) | y = Yaw-Vorzeichen toggeln")
    print("       p = Pitch-Vorzeichen toggeln (jede Änderung recentert automatisch)")
    print("       s = Diagnose: Roh-Gyro-Werte (Grad/s) live anzeigen (zur Achsen-Prüfung)")
    print("       t/u = YZ-Tilt um +1/-1 Grad (T/U = +5/-5) – nur bei axis_map=default sinnvoll")
    print("       f = Fusion-Modus wechseln (legacy -> quat_old -> quat_new -> ref) – recentert")
    print("       R (Shift+r) = nur Blickrichtung (Yaw) zurücksetzen, Neigung bleibt")
    print("       Im ref-Modus: r/F9 = geradeaus UND waagerecht schauen, dann drücken")
    print("       (lernt dabei die ~30° Einbauneigung des IMU)")
    print("       Globale Hotkeys: Ctrl+F10 = Tilt -1, Ctrl+F11 = Tilt +1, Ctrl+F12 = Tilt Reset")
    print("       Ausrichten: Pfeil links/rechts = Blickrichtung ±5° (Shift = 1°), Pfeil hoch/runter = Neigung")
    print("       Enter = Ausrichtung speichern (bleibt bei F9 und Neustart) | Backspace = Standard")
    print("       Im Spiel: Ctrl+Alt+Pfeile / Ctrl+Alt+Enter / Ctrl+Alt+Backspace")
    print("       b / F8 = Ansicht um 180° drehen | [ / ] = Blickrichtung -15/+15°")


def load_vrto3d_config(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def state_path():
    return os.path.join(tempfile.gettempdir(), "xreal_bridge_state.json")


def load_state():
    try:
        with open(state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_state(orientation):
    try:
        payload = {
            "axis_map": orientation.axis_map,
            "invert_yaw": orientation.invert_yaw,
            "invert_pitch": orientation.invert_pitch,
            "yz_tilt_deg": orientation.yz_tilt_deg,
            "fusion_mode": orientation.fusion_mode,
        }
        aligned = getattr(orientation, "aligned_offsets", None)
        if aligned is not None:
            payload["aligned_yaw_offset_deg"] = aligned[0]
            payload["aligned_pitch_offset_deg"] = aligned[1]
        with open(state_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        pass


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


_CONSOLE_ARROWS = {"K": "LEFT", "M": "RIGHT", "H": "UP", "P": "DOWN"}


def _shift_down():
    try:
        return bool(ctypes.windll.user32.GetKeyState(0x10) & 0x8000)
    except (AttributeError, OSError):
        return False


def translate_keys(raw, shift=False):
    """Console chars -> tokens: arrows become 'LEFT'/'S-LEFT' (Shift),
    Enter 'ENTER', Backspace 'BACKSPACE'; everything else unchanged."""
    out = []
    it = iter(raw)
    for ch in it:
        if ch in ("\x00", "\xe0"):
            code = next(it, "")
            name = _CONSOLE_ARROWS.get(code)
            if name:
                out.append(("S-" if shift else "") + name)
            continue
        if ch == "\r":
            out.append("ENTER")
        elif ch == "\x08":
            out.append("BACKSPACE")
        else:
            out.append(ch)
    return out


def poll_keys():
    if msvcrt is None:
        return []
    keys = []
    while msvcrt.kbhit():
        ch = msvcrt.getwch()
        keys.append(ch)
        if ch in ("\x00", "\xe0") and msvcrt.kbhit():
            keys.append(msvcrt.getwch())
    return translate_keys(keys, _shift_down()) if keys else []


ALIGN_STEP = 5.0
ALIGN_FINE_STEP = 1.0
ALIGN_KEYS = {
    "LEFT": ("yaw", -ALIGN_STEP), "RIGHT": ("yaw", ALIGN_STEP),
    "UP": ("pitch", ALIGN_STEP), "DOWN": ("pitch", -ALIGN_STEP),
    "S-LEFT": ("yaw", -ALIGN_FINE_STEP), "S-RIGHT": ("yaw", ALIGN_FINE_STEP),
    "S-UP": ("pitch", ALIGN_FINE_STEP), "S-DOWN": ("pitch", -ALIGN_FINE_STEP),
    "ENTER": ("save", 0.0), "BACKSPACE": ("reset", 0.0),
    "b": ("yaw", 180.0), "[": ("yaw", -15.0), "]": ("yaw", 15.0),
}


def apply_align_action(orientation, action, value, defaults):
    """Manual alignment.  Live changes are temporary until 'save' (Enter),
    which stores them as the calibrated position (state file; survives F9 and
    restarts).  'reset' (Backspace) returns to the start defaults
    (--recenter-yaw-offset / --recenter-pitch-offset) and forgets the saved
    position.  Returns a short German status line."""
    if action == "yaw":
        orientation.set_yaw_offset(orientation.yaw_offset_deg + value)
    elif action == "pitch":
        orientation.set_pitch_offset(orientation.pitch_offset_deg + value)
    elif action == "save":
        orientation.aligned_offsets = (orientation.yaw_offset_deg, orientation.pitch_offset_deg)
        save_state(orientation)
        return (f">>> Ausrichtung gespeichert: Yaw {orientation.yaw_offset_deg:+.0f}°, "
                f"Pitch {orientation.pitch_offset_deg:+.0f}°")
    elif action == "reset":
        orientation.set_yaw_offset(defaults[0])
        orientation.set_pitch_offset(defaults[1])
        orientation.aligned_offsets = None
        save_state(orientation)
        return (f">>> Ausrichtung zurückgesetzt: Yaw {orientation.yaw_offset_deg:+.0f}°, "
                f"Pitch {orientation.pitch_offset_deg:+.0f}°")
    return (f">>> Ausrichtung: Yaw {orientation.yaw_offset_deg:+.0f}°, "
            f"Pitch {orientation.pitch_offset_deg:+.0f}° (Enter = speichern)")


def build_orientation(args):
    return ComplementaryOrientation(
        use_gravity_ref=not args.no_gravity_ref,
        axis_map=args.axis_map,
        invert_yaw=args.invert_yaw,
        invert_pitch=args.invert_pitch,
        yz_tilt_deg=args.yz_tilt,
        rate_smoothing=args.rate_smoothing,
        fusion_mode=args.fusion_mode,
    )


CALIB_STILL_SD = math.radians(1.0)   # per-axis std dev of a still window
CALIB_MAX_BIAS = math.radians(5.0)   # a real MEMS bias is far below this
CALIB_MAX_WINDOWS = 8                # ~4 s at 1 kHz with 500-sample windows


def _median(vals):
    v = sorted(vals)
    n = len(v)
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


def calib_window_stats(gyros):
    """(median bias, max per-axis std dev) of one window of raw gyro samples."""
    med = tuple(_median([g[k] for g in gyros]) for k in range(3))
    sd = 0.0
    for k in range(3):
        m = sum(g[k] for g in gyros) / len(gyros)
        sd = max(sd, math.sqrt(sum((g[k] - m) ** 2 for g in gyros) / len(gyros)))
    return med, sd


def calibrate(frames, calib_samples, max_windows=CALIB_MAX_WINDOWS, verbose=True):
    """Robust start-up gyro bias.

    The old version averaged the first ``calib_samples`` frames no matter what
    the glasses did.  If they were moved/put on during that 0.5 s, the "bias"
    was several deg/s off and the view kept turning by itself.  Now: windows of
    ``calib_samples`` frames, accept the first STILL one (median), retry up to
    ``max_windows`` times, else fall back to zero bias (the ref-mode AHRS
    learns the bias itself as soon as the head is still).

    frames: iterator from frame_stream().  Pass the SAME iterator to
    run_stream afterwards, otherwise the frames already buffered by the
    generator (up to 64 KiB) are silently dropped."""
    if isinstance(frames, socket.socket):
        frames = frame_stream(frames)
    win = []
    tries = 0
    for frame in frames:
        win.append(frame.gyro)
        if len(win) < calib_samples:
            continue
        tries += 1
        med, sd = calib_window_stats(win)
        if sd < CALIB_STILL_SD and max(abs(c) for c in med) < CALIB_MAX_BIAS:
            if verbose:
                print(f"[calib] Brille ruhig (Streuung {math.degrees(sd):.2f} deg/s) – "
                      f"Bias übernommen", flush=True)
            return med
        if verbose:
            print(f"[calib] Bewegung erkannt (Streuung {math.degrees(sd):.2f} deg/s) – "
                  f"Brille bitte still halten ... ({tries}/{max_windows})", flush=True)
        if tries >= max_windows:
            break
        win = []
    if verbose:
        print("[calib] keine Ruhephase gefunden – starte mit Bias 0, "
              "wird gelernt sobald die Brille still ist", flush=True)
    return (0.0, 0.0, 0.0)


def run_stream(frames, args, orientation, bias, flags):
    (recenter_flag, axis_flag, yaw_flag, pitch_flag,
     tilt_up_flag, tilt_down_flag, tilt_reset_flag, *rest) = flags
    flip_flag = rest[0] if rest else threading.Event()
    align_queue = rest[1] if len(rest) > 1 else queue.SimpleQueue()
    align_defaults = rest[2] if len(rest) > 2 else (orientation.yaw_offset_deg,
                                                    orientation.pitch_offset_deg)

    def align(token):
        action, value = ALIGN_KEYS[token]
        print(apply_align_action(orientation, action, value, align_defaults))

    udp = None
    sender = None
    if not args.dry_run:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if getattr(args, "sender", "inline") == "thread":
            sender = PoseSender(udp, (args.udp_ip, args.udp_port), args.max_rate)
            sender.start()
    smoother = QuatOneEuro(getattr(args, "smooth", 0.0), getattr(args, "smooth_beta", 0.3))

    def cycle_axis():
        maps = list(AXIS_MAPS)
        idx = maps.index(orientation.axis_map)
        orientation.set_axis_map(maps[(idx + 1) % len(maps)])
        orientation.recenter()
        save_state(orientation)
        print(
            f">>> Achsen-Mapping = {orientation.axis_map} "
            f"(pitch/yaw/roll <- {AXIS_MAPS[orientation.axis_map]}) – recenter"
        )

    def toggle_yaw():
        orientation.set_invert_yaw(not orientation.invert_yaw)
        orientation.recenter()
        save_state(orientation)
        print(f">>> Yaw-Vorzeichen = {'invertiert' if orientation.invert_yaw else 'normal'} – recenter")

    def toggle_pitch():
        orientation.set_invert_pitch(not orientation.invert_pitch)
        orientation.recenter()
        save_state(orientation)
        print(f">>> Pitch-Vorzeichen = {'invertiert' if orientation.invert_pitch else 'normal'} – recenter")

    def adjust_tilt(delta):
        if orientation.axis_map != "default":
            print(">>> Tilt nur bei axis_map=default sinnvoll (erst a drücken)")
            return
        orientation.set_yz_tilt(orientation.yz_tilt_deg + delta)
        save_state(orientation)
        print(f">>> YZ-Tilt = {orientation.yz_tilt_deg:+.1f}°")

    def cycle_fusion_mode():
        modes = list(ComplementaryOrientation.FUSION_MODES)
        idx = modes.index(orientation.fusion_mode)
        orientation.set_fusion_mode(modes[(idx + 1) % len(modes)])
        orientation.recenter()
        save_state(orientation)
        print(f">>> Fusion-Modus = {orientation.fusion_mode} – recenter")

    edit_param = None
    diagnose = False
    vr_cfg = load_vrto3d_config(args.vrto3d_config)
    if vr_cfg is None:
        print(f"(Hinweis: VRto3D-Config nicht gefunden unter {args.vrto3d_config} – Bild-Param-Tasten inaktiv)")

    last = time.monotonic()
    last_ts = 0
    last_packet = last
    count = 0
    t_start = last
    q_state = (0, (0.0, 0.0, 0.0))
    quiet_calib = not args.disable_quiet_calib and orientation.fusion_mode != "ref"

    if isinstance(frames, socket.socket):
        frames = frame_stream(frames)
    try:
        for frame in frames:
            now = time.monotonic()
            dt = frame_dt(last_ts, frame.timestamp_ns, now - last)
            last = now
            last_ts = frame.timestamp_ns
            if quiet_calib:
                bias, q_state, updated = quiet_bias_step(bias, frame.gyro, q_state)
                if updated:
                    print(
                        f"[calib] Gyro-Bias während Stillstand aktualisiert: "
                        f"{bias[0]:+.5f}, {bias[1]:+.5f}, {bias[2]:+.5f} rad/s",
                        flush=True,
                    )
            orientation.update(dt, frame.gyro, frame.accel, bias)
            count += 1

            if diagnose and count % 30 == 0:
                raw = (
                    frame.gyro[0] - bias[0],
                    frame.gyro[1] - bias[1],
                    frame.gyro[2] - bias[2],
                )
                print(
                    f"[diagnose] gyro deg/s  X={math.degrees(raw[0]):+8.2f}  "
                    f"Y={math.degrees(raw[1]):+8.2f}  Z={math.degrees(raw[2]):+8.2f} | "
                    f"accel X={frame.accel[0]:+6.2f} Y={frame.accel[1]:+6.2f} "
                    f"Z={frame.accel[2]:+6.2f} | out yaw={orientation.yaw_deg:+7.1f} "
                    f"pitch={orientation.pitch_deg:+7.1f} roll={orientation.roll_deg:+7.1f}",
                    flush=True,
                )

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
            if tilt_up_flag.is_set():
                tilt_up_flag.clear()
                adjust_tilt(1.0)
            if tilt_down_flag.is_set():
                tilt_down_flag.clear()
                adjust_tilt(-1.0)
            if flip_flag.is_set():
                flip_flag.clear()
                align("b")
            while True:
                try:
                    align(align_queue.get_nowait())
                except queue.Empty:
                    break
            if tilt_reset_flag.is_set():
                tilt_reset_flag.clear()
                orientation.set_yz_tilt(0.0)
                save_state(orientation)
                print(">>> YZ-Tilt auf 0 zurückgesetzt")

            for ch in poll_keys():
                if ch == "r":
                    orientation.recenter()
                    print(">>> Recenter: geradeaus ausgerichtet")
                elif ch == "R":
                    orientation.recenter("yaw")
                    print(">>> Recenter: nur Blickrichtung (Yaw)")
                elif ch == "q":
                    print("Beende auf Wunsch")
                    return False
                elif ch == "h":
                    print_help()
                elif ch == "s":
                    diagnose = not diagnose
                    print(f">>> Diagnose {'an' if diagnose else 'aus'} (zeigt Roh-Gyro in Grad/s)")
                elif ch == "+" or ch == "=":
                    if edit_param:
                        # re-read: VRto3D OSD / other tools may have changed the file
                        vr_cfg = load_vrto3d_config(args.vrto3d_config) or vr_cfg
                    if edit_param and vr_cfg is not None:
                        lo, hi, step = PARAM_RANGES[edit_param]
                        vr_cfg[edit_param] = round(min(hi, max(lo, vr_cfg.get(edit_param, lo) + step)), 2)
                        if save_vrto3d_config(args.vrto3d_config, vr_cfg):
                            print(f">>> {edit_param} = {vr_cfg[edit_param]} (VRto3D-Config geschrieben; jetzt im Spiel/VR-Fenster Ctrl+Shift+F10 drücken = Neuladen, Piepton)")
                        else:
                            print(">>> Fehler beim Schreiben der VRto3D-Config")
                    else:
                        orientation.set_gain(orientation.gain + 0.1)
                        print(f">>> Empfindlichkeit = {orientation.gain:.1f}")
                elif ch == "-":
                    if edit_param:
                        vr_cfg = load_vrto3d_config(args.vrto3d_config) or vr_cfg
                    if edit_param and vr_cfg is not None:
                        lo, hi, step = PARAM_RANGES[edit_param]
                        vr_cfg[edit_param] = round(min(hi, max(lo, vr_cfg.get(edit_param, hi) - step)), 2)
                        if save_vrto3d_config(args.vrto3d_config, vr_cfg):
                            print(f">>> {edit_param} = {vr_cfg[edit_param]} (VRto3D-Config geschrieben; jetzt im Spiel/VR-Fenster Ctrl+Shift+F10 drücken = Neuladen, Piepton)")
                        else:
                            print(">>> Fehler beim Schreiben der VRto3D-Config")
                    else:
                        orientation.set_gain(orientation.gain - 0.1)
                        print(f">>> Empfindlichkeit = {orientation.gain:.1f}")
                elif ch in ("1", "2", "3"):
                    edit_param = ("depth", "convergence", "fov")[int(ch) - 1]
                    vr_cfg = load_vrto3d_config(args.vrto3d_config) or vr_cfg
                    if vr_cfg is not None:
                        hint = " (+ = rauszoomen, - = reinzoomen)" if edit_param == "fov" else ""
                        print(f">>> Bild-Param: {edit_param} = {vr_cfg.get(edit_param)}  (+/- ändern, 0 beenden){hint}")
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
                elif ch == "t":
                    adjust_tilt(1.0)
                elif ch == "T":
                    adjust_tilt(5.0)
                elif ch == "u":
                    adjust_tilt(-1.0)
                elif ch == "U":
                    adjust_tilt(-5.0)
                elif ch == "f":
                    cycle_fusion_mode()
                elif ch in ALIGN_KEYS:
                    align(ch)

            if args.dry_run:
                if count == 1 or count % 100 == 0:
                    print(
                        f"yaw={orientation.yaw_deg:8.2f} pitch={orientation.pitch_deg:8.2f} "
                        f"roll={orientation.roll_deg:8.2f} deg gain={orientation.gain:.1f}"
                    )
            else:
                out = smoother.filter_euler(*orientation.output_euler(), dt)
                if sender is not None:
                    sender.update(*out)
                elif now - last_packet >= 1.0 / max(1, args.max_rate):
                    packet = pack_opentrack(0.0, 0.0, 0.0, *out)
                    udp.sendto(packet, (args.udp_ip, args.udp_port))
                    last_packet = now

            if count % 1000 == 0:
                elapsed = now - t_start
                print(
                    f"[status] frames={count} rate={count / elapsed:.0f} Hz | "
                    f"map={orientation.axis_map} tilt={orientation.yz_tilt_deg:+.1f}° | "
                    f"bias=({bias[0]:+.4f},{bias[1]:+.4f},{bias[2]:+.4f}) | "
                    f"yaw={orientation.yaw_deg:7.1f} pitch={orientation.pitch_deg:7.1f} "
                    f"roll={orientation.roll_deg:7.1f}",
                    flush=True,
                )

            if args.duration and now - t_start >= args.duration:
                break

        return count
    finally:
        if sender is not None:
            sender.stop()
        if udp is not None:
            udp.close()


def main(argv=None):
    args = parse_args(argv)

    saved = load_state()
    if saved is not None and "yz_tilt_deg" in saved:
        args.yz_tilt = float(saved["yz_tilt_deg"])
    if args.recenter_yaw_offset is None:
        args.recenter_yaw_offset = float((saved or {}).get("yaw_offset_deg", 0.0))
    align_defaults = (args.recenter_yaw_offset, args.recenter_pitch_offset)
    if args.fusion_mode is None:
        args.fusion_mode = "ref"
        if saved is not None and saved.get("fusion_mode") in ComplementaryOrientation.FUSION_MODES:
            args.fusion_mode = saved["fusion_mode"]
            print(f"(Fusion-Modus '{args.fusion_mode}' aus {state_path()} übernommen; "
                  f"überschreiben mit --fusion-mode ref)")
    print(f"Fusion-Modus: {args.fusion_mode}")
    print(f"Ausgabe: {args.max_rate} Pakete/s ({args.sender}), Glättung: "
          + (f"One-Euro {args.smooth:g} Hz / beta {args.smooth_beta:g}" if args.smooth > 0 else "aus"))
    if args.fusion_mode != "ref":
        print("WARNUNG: Modus '%s' integriert Euler-Winkel getrennt – nach starkem Hoch/Runter-"
              "Schauen bleibt die Welt schief. Empfohlen: --fusion-mode ref" % args.fusion_mode)
    elif args.no_gravity_ref:
        print("Hinweis: --no-gravity-ref schaltet im ref-Modus die Schwerkraft-Korrektur ab "
              "(Neigung kann driften). Für ref-Modus weglassen.")

    orientation = build_orientation(args)
    orientation.set_yaw_offset(args.recenter_yaw_offset)
    orientation.set_pitch_offset(args.recenter_pitch_offset)
    orientation.aligned_offsets = None
    if saved and "aligned_yaw_offset_deg" in saved:
        orientation.aligned_offsets = (float(saved["aligned_yaw_offset_deg"]),
                                       float(saved.get("aligned_pitch_offset_deg", 0.0)))
        orientation.set_yaw_offset(orientation.aligned_offsets[0])
        orientation.set_pitch_offset(orientation.aligned_offsets[1])
        print("Gespeicherte Ausrichtung geladen (Backspace = zurück auf Standard)")
    print(f"Ausrichtung: Yaw {orientation.yaw_offset_deg:+.0f}°, Pitch {orientation.pitch_offset_deg:+.0f}° "
          f"| Pfeile = ausrichten, Enter = speichern, F8/b = 180°")
    if not args.no_auto_recenter:
        orientation.recenter("auto")

    recenter_flag = threading.Event()
    axis_flag = threading.Event()
    yaw_flag = threading.Event()
    pitch_flag = threading.Event()
    tilt_up_flag = threading.Event()
    tilt_down_flag = threading.Event()
    tilt_reset_flag = threading.Event()
    flip_flag = threading.Event()
    align_queue = queue.SimpleQueue()

    hotkey_names = [
        args.recenter_hotkey,
        args.axis_hotkey,
        args.invert_yaw_hotkey,
        args.invert_pitch_hotkey,
        args.tilt_up_hotkey,
        args.tilt_down_hotkey,
        args.tilt_reset_hotkey,
        args.flip_hotkey,
    ]
    bindings = [
        (*parse_hotkey_ex(hotkey_names[0]), lambda: recenter_flag.set()),
        (*parse_hotkey_ex(hotkey_names[1]), lambda: axis_flag.set()),
        (*parse_hotkey_ex(hotkey_names[2]), lambda: yaw_flag.set()),
        (*parse_hotkey_ex(hotkey_names[3]), lambda: pitch_flag.set()),
        (*parse_hotkey_ex(hotkey_names[4]), lambda: tilt_up_flag.set()),
        (*parse_hotkey_ex(hotkey_names[5]), lambda: tilt_down_flag.set()),
        (*parse_hotkey_ex(hotkey_names[6]), lambda: tilt_reset_flag.set()),
        (*parse_hotkey_ex(hotkey_names[7]), lambda: flip_flag.set()),
    ]
    if args.align_modifier:
        for key in ("LEFT", "RIGHT", "UP", "DOWN", "ENTER", "BACKSPACE"):
            for shift in ((False, True) if key in _CONSOLE_ARROWS.values() else (False,)):
                hk = args.align_modifier + ("+Shift" if shift else "") + "+" + key
                token = ("S-" if shift else "") + key
                hotkey_names.append(hk)
                bindings.append((*parse_hotkey_ex(hk),
                                 lambda t=token: align_queue.put(t)))
    hotkey = None
    if os.name == "nt":
        hotkey = HotkeyManager(bindings)
        hotkey.start()
        time.sleep(0.1)
        if hotkey.registered:
            active = [n for n, (vk, _mod, _cb) in zip(hotkey_names, bindings) if vk]
            print(f"Globale Hotkeys aktiv: {', '.join(active)}")
        else:
            hotkey = None
            print("(Hinweis: Keine Hotkeys konnten registriert werden)")

    print_help()

    flags = (recenter_flag, axis_flag, yaw_flag, pitch_flag,
             tilt_up_flag, tilt_down_flag, tilt_reset_flag, flip_flag, align_queue,
             align_defaults)

    while True:
        try:
            print(f"connecting {args.host}:{args.imu_port} ...")
            sock = socket.create_connection((args.host, args.imu_port), timeout=5.0)
            sock.settimeout(10.0)
            print("connected")

            frames = frame_stream(sock)
            bias = calibrate(frames, args.calib_samples)
            print(f"gyro bias (rad/s): {bias[0]:+.5f}, {bias[1]:+.5f}, {bias[2]:+.5f}")

            if not args.no_auto_recenter:
                orientation.recenter("auto")
                if orientation.fusion_mode == "ref":
                    print("Recenter: automatisch, sobald die Brille aufrecht und still ist "
                          "(auf dem Kopf geradeaus schauen; jederzeit F9 = neu ausrichten)")
                print(
                    f"Recenter (geradeaus): Initial ausgerichtet nach Kalibrierung "
                    f"[axis_map={orientation.axis_map} yaw_sign={'I' if orientation.invert_yaw else '+'} "
                    f"pitch_sign={'I' if orientation.invert_pitch else '+'} "
                    f"tilt={orientation.yz_tilt_deg:+.1f}deg]"
                )

            result = run_stream(frames, args, orientation, bias, flags)
            sock.close()
            if result is False:
                return
            print(f"done: {result} frames processed")
            return
        except (ConnectionResetError, ConnectionAbortedError, OSError) as exc:
            print(f"Verbindung verloren ({exc}) – Reconnect in 2 s ...")
            try:
                sock.close()
            except (NameError, OSError):
                pass
            time.sleep(2)
            continue


if __name__ == "__main__":
    main()
