import ctypes
import json
import sys
from ctypes import wintypes

VRTO3D_CONFIG = r"C:\Program Files (x86)\Steam\config\vrto3d\default_config.json"


class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


def active_displays():
    user32 = ctypes.windll.user32
    out = []
    i = 0
    while True:
        dd = DISPLAY_DEVICE()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICE)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        if dd.StateFlags & 1:
            mon = DISPLAY_DEVICE()
            mon.cb = ctypes.sizeof(DISPLAY_DEVICE)
            mon_id = ""
            if user32.EnumDisplayDevicesW(dd.DeviceName, 0, ctypes.byref(mon), 0):
                mon_id = mon.DeviceID
            out.append((dd.DeviceName, mon_id, bool(dd.StateFlags & 4)))
        i += 1
    return out


def vrto3d_order(displays):
    """VRto3D (platform::EnumerateMonitors) swaps the PRIMARY monitor to
    position 1; display_index counts in that order.  Without the swap the
    XREAL got index 1 = laptop panel when the laptop is primary."""
    out = list(displays)
    for i, d in enumerate(out):
        if d[2] and i != 0:
            out[0], out[i] = out[i], out[0]
            break
    return out


def main():
    displays = vrto3d_order(active_displays())
    if not displays:
        print("keine aktiven Displays gefunden")
        return 1
    for idx, (name, devid, primary) in enumerate(displays, start=1):
        print(f"order {idx}: {name} | {devid}{' [primary]' if primary else ''}")
    xreal = [idx for idx, (name, devid, _p) in enumerate(displays, start=1)
             if "MRG4100" in devid]
    if not xreal:
        print("XREAL-Display (MRG4100) nicht gefunden – nichts geändert")
        return 1
    order = xreal[0]
    print(f"XREAL One Pro ist Display-Order {order}")

    with open(VRTO3D_CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["display_index"] = order
    cfg["dash_enable"] = True
    with open(VRTO3D_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print(f"default_config.json aktualisiert: display_index={order}, dash_enable=true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
