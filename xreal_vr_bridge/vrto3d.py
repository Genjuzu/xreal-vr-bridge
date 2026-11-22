"""VRto3D display order and the recommended config for the XREAL glasses.

VRto3D on Windows (platform::EnumerateMonitors) lists monitors and then swaps
the primary monitor to position 1. ``display_index`` is that 1-based position.
0, or a number past the end of the list, means "the primary monitor".

The reference One Pro reports a monitor hardware id containing ``MRG4100``.
With the laptop as the primary display that glasses panel was index 2.
"""

import json
import os
import sys
import tempfile
import time

# Keys the reference setup actually used. Other keys in an existing
# default_config.json are left alone.
RECOMMENDED_SETTINGS = {
    "output_mode": "SbS",
    "render_width": 1920,
    "render_height": 1080,
    "aspect_ratio": 1.77778,
    "fov": 61.0,
    "use_open_track": True,
    "open_track_port": 4242,
}

# Hardware id substring seen on the reference XREAL One Pro.
XREAL_HW_ID = "MRG4100"


def order_displays(displays):
    """Move the primary monitor to index 0.

    ``displays`` is a sequence of ``(name, device_id, is_primary)``.
    The returned list is the order VRto3D numbers from 1.
    """
    out = list(displays)
    for i, item in enumerate(out):
        if item[2] and i != 0:
            out[0], out[i] = out[i], out[0]
            break
    return out


def xreal_display_index(displays):
    """1-based VRto3D index of the first monitor whose id contains MRG4100."""
    for index, (_name, device_id, _primary) in enumerate(order_displays(displays), start=1):
        if device_id and XREAL_HW_ID in device_id:
            return index
    return None


def merge_config(cfg, display_index=None):
    """Copy ``cfg`` and overlay the recommended keys.

    ``display_index`` is written only when it is not None, so a run that
    could not see the glasses does not clobber a value the user already set.
    """
    merged = dict(cfg or {})
    merged.update(RECOMMENDED_SETTINGS)
    if display_index is not None:
        merged["display_index"] = int(display_index)
    return merged


def _same(current, wanted):
    if isinstance(wanted, float) and isinstance(current, (int, float)):
        return float(current) == float(wanted)
    if isinstance(wanted, bool) or isinstance(current, bool):
        return current is wanted or current == wanted
    return current == wanted


def config_changes(cfg, display_index=None):
    """Keys that ``merge_config`` would change. Empty when already applied."""
    merged = merge_config(cfg, display_index)
    changed = {}
    for key, wanted in merged.items():
        if key not in (cfg or {}) or not _same(cfg.get(key), wanted):
            if key in RECOMMENDED_SETTINGS or key == "display_index":
                changed[key] = wanted
    return changed


def backup_path_for(path, now=None):
    """A new backup filename. Never returns a path that already exists."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    candidate = f"{path}.bak-{stamp}"
    n = 1
    while os.path.exists(candidate):
        n += 1
        candidate = f"{path}.bak-{stamp}-{n}"
    return candidate


def apply_config(path, display_index=None):
    """Back up ``path`` and write the recommended settings into it.

    Does nothing when the file is already in the recommended state.
    Does not create a config that VRto3D has not generated yet.
    Does not delete anything. Returns a dict with ``status`` of
    ``missing``, ``unchanged``, or ``updated``.
    """
    if not path or not os.path.isfile(path):
        return {"status": "missing", "path": path}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            cfg = json.load(handle)
    except (OSError, ValueError) as exc:
        return {"status": "error", "path": path, "error": str(exc)}
    if not isinstance(cfg, dict):
        return {"status": "error", "path": path, "error": "config is not a JSON object"}
    changes = config_changes(cfg, display_index)
    if not changes:
        return {"status": "unchanged", "path": path}
    backup = backup_path_for(path)
    merged = merge_config(cfg, display_index)
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2)
            handle.write("\n")
        # Copy the original aside only after the new file is ready to swap in.
        with open(path, "rb") as src, open(backup, "wb") as dst:
            dst.write(src.read())
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return {"status": "error", "path": path, "error": str(exc)}
    return {"status": "updated", "path": path, "backup": backup, "changes": changes}


def active_displays():
    """Active Windows displays as ``(name, device_id, is_primary)``.

    Uses EnumDisplayDevices, which is what the reference machine's helper
    used. VRto3D itself walks EnumDisplayMonitors and then does the same
    primary-to-front swap. The two lists usually match; if the picture lands
    on the wrong screen, set ``display_index`` by hand.
    """
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    class DISPLAY_DEVICE(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]

    user32 = ctypes.windll.user32
    out = []
    index = 0
    while True:
        device = DISPLAY_DEVICE()
        device.cb = ctypes.sizeof(DISPLAY_DEVICE)
        if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            break
        if device.StateFlags & 1:  # DISPLAY_DEVICE_ACTIVE
            monitor = DISPLAY_DEVICE()
            monitor.cb = ctypes.sizeof(DISPLAY_DEVICE)
            device_id = ""
            if user32.EnumDisplayDevicesW(device.DeviceName, 0, ctypes.byref(monitor), 0):
                device_id = monitor.DeviceID
            out.append((device.DeviceName, device_id, bool(device.StateFlags & 4)))
        index += 1
    return out


def report():
    """JSON-serialisable view of the displays and the suggested index."""
    if os.name != "nt":
        return {"displays": [], "xreal_index": None, "error": "not-windows"}
    displays = order_displays(active_displays())
    rows = []
    for index, (name, device_id, primary) in enumerate(displays, start=1):
        rows.append({
            "index": index,
            "name": name,
            "id": device_id,
            "primary": primary,
            "xreal": bool(device_id and XREAL_HW_ID in device_id),
        })
    return {"displays": rows, "xreal_index": xreal_display_index(displays)}


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m xreal_vr_bridge.vrto3d",
        description="List displays in VRto3D order, or write the recommended config.",
    )
    parser.add_argument("--report", action="store_true",
                        help="print one JSON object (for the installer)")
    parser.add_argument("--apply", action="store_true",
                        help="write recommended settings into --config")
    parser.add_argument("--config", help="path to default_config.json")
    parser.add_argument("--display-index", type=int, default=None)
    args = parser.parse_args(argv)

    if args.apply:
        if not args.config:
            print("error: --apply needs --config", file=sys.stderr)
            return 1
        result = apply_config(args.config, args.display_index)
        print(json.dumps(result))
        if result["status"] == "error":
            return 1
        if result["status"] == "missing":
            return 2
        return 0

    info = report()
    if args.report or not sys.stdout.isatty():
        print(json.dumps(info))
        return 0 if not info.get("error") else 0
    if info.get("error"):
        print(info["error"])
        return 0
    if not info["displays"]:
        print("No active displays found.")
        return 1
    for row in info["displays"]:
        flags = []
        if row["primary"]:
            flags.append("primary")
        if row["xreal"]:
            flags.append("XREAL")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        print(f"{row['index']}: {row['name']} | {row['id']}{suffix}")
    if info["xreal_index"] is None:
        print("No MRG4100 display found. Set display_index yourself.")
    else:
        print(f"Suggested display_index: {info['xreal_index']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
