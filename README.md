# XREAL VR Bridge

Head-tracked VR for the **XREAL One Pro** (and, by the same protocol, likely the **XREAL One**) on Windows. The bridge reads the glasses' IMU over the USB-C network, fuses it with a quaternion AHRS, and sends [OpenTrack](https://github.com/opentrack/opentrack) UDP to [VRto3D](https://github.com/oneup03/VRto3D). SteamVR home, Unity apps, and [UEVR](https://github.com/praydog/UEVR) games can then use the glasses as a 3DoF headset.

One installer. Two shortcuts. The only choice is which way is "forward".

This project does **not** change the Windows OpenXR runtime. A Quest via Virtual Desktop or the Oculus app keeps working. OpenXR apps that should use the glasses are started one at a time with a launcher that sets the runtime for that process only.

## Quick start

1. Plug the glasses into USB-C so Windows sees both the display and a network adapter.
2. On the glasses: **Follow mode**, **stabilizer off**, and **3840x1080 side-by-side** where the glasses offer it.
3. Clone this repository and double-click `install.bat`.
4. Press Enter to install to `D:\VR\xreal-vr-bridge` when `D:` exists, otherwise `%USERPROFILE%\xreal-vr-bridge`. Type `.` to set the clone up where it already is. Type any other folder to use that instead.
5. Put the glasses on and hold still for a few seconds while the window says it is calibrating.
6. Start **XREAL Bridge (SteamVR and Apps, offset 180)**, then start SteamVR.
7. For a UEVR game, quit that shortcut and start **XREAL Bridge (Games and UEVR, offset 0)** instead. In UEVR, inject with **OpenVR**, not OpenXR.

The bridge window should say `Fusion mode: ref` and `Glasses are still`.

## Requirements

| Piece | What you need |
|---|---|
| Glasses | XREAL One Pro. The One uses the same IMU frame format; it has not been re-checked on hardware for this release. |
| OS | Windows 10 or 11 |
| Python | **3.11 or newer** on Windows (the installer fetches 3.12 with winget if it has to). Older Windows Python sleeps in ~15 ms steps, so the 250 Hz sender cannot keep an even pace. The library imports on 3.8+. |
| Steam | Steam, plus SteamVR |
| VRto3D | The OpenVR driver that draws side-by-side 3D. The installer can copy the official zip into SteamVR. |
| UEVR | Optional. Use a **nightly** build for Unreal Engine games. |

No compiler, no vendor SDK, and no extra Python packages at runtime.

## Install

`install.bat` runs `install.ps1`. It is safe to run again.

It will:

- Find Python 3.11+, or install Python 3.12 for the current user with winget.
- Create `.venv` in the install folder and install this project into it. An existing environment is reused. A broken one is renamed, not deleted.
- Find Steam from its registry entry and `libraryfolders.vdf`, then find SteamVR.
- If `SteamVR\drivers\vrto3d` is missing, offer to download [the official driver zip](https://github.com/oneup03/VRto3D/releases/latest/download/vrto3d.zip) and copy the `vrto3d` folder in. It does not run `VRto3D-Installer.exe`.
- If `Steam\config\vrto3d\default_config.json` already exists, copy it to a new `default_config.json.bak-<timestamp>` file and then set the keys below. Other keys are left as they are. A second run that finds the same values does not write another backup. If the file does not exist yet, start SteamVR once so VRto3D can create it, then run the installer again.
- Ask which monitor the glasses are, after printing the list it detected.
- Create Desktop and Start Menu shortcuts.

It will **not**:

- Write the Windows OpenXR active runtime (`ActiveRuntime` under `HKLM\SOFTWARE\Khronos\OpenXR\1`, including the 32-bit `WOW6432Node` view).
- Edit `steamvr.vrsettings` or set a forced SteamVR driver.
- Delete files that are already in the install folder. Copying uses robocopy without a mirror.

```text
install.bat
install.bat -InstallDir D:\VR\xreal-vr-bridge -DisplayIndex 2
install.bat -NonInteractive
install.bat -SkipVRto3D
```

`-NonInteractive` uses the suggested folder, downloads the VRto3D zip when the driver is missing, and keeps a detected display index. It does not prompt.

Uninstall with `uninstall.bat`. That removes the shortcuts this installer created. The project folder stays. The virtual environment is removed only if you say so. A VRto3D backup is restored only if you say so, and the current config is copied aside first.

### Settings the installer writes

| Key | Value | Why |
|---|---|---|
| `output_mode` | `SbS` | Full side-by-side for the glasses |
| `render_width` / `render_height` | 1920 / 1080 | One eye, so the panel is 3840x1080 |
| `aspect_ratio` | 1.77778 | 16:9 |
| `fov` | **61** | Comfortable on the reference One Pro. 70 felt too fast and caused nausea. 57 felt too zoomed in. |
| `use_open_track` | true | Listen for this bridge |
| `open_track_port` | 4242 | Where the bridge sends UDP |
| `display_index` | detected, or what you type | Which monitor the headset window uses |

### Manual install

If you would rather not run the installer:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe -m xreal_vr_bridge.cli --recenter-yaw-offset 180
```

Download VRto3D from its [latest release](https://github.com/oneup03/VRto3D/releases/latest) and copy the `vrto3d` folder into `SteamVR\drivers\`. Start SteamVR once, then edit `Steam\config\vrto3d\default_config.json` with the table above. `tools\start_bridge.bat` and `tools\start_bridge_uevr.bat` are the same two shortcuts without the Start Menu entries.

## Usage

| Shortcut | Command | Use it for |
|---|---|---|
| XREAL Bridge (SteamVR and Apps, offset 180) | `--recenter-yaw-offset 180` | SteamVR home and Unity apps. Without the half-turn, the SteamVR menu sits behind you. |
| XREAL Bridge (Games and UEVR, offset 0) | `--recenter-yaw-offset 0` | UEVR and other games, where forward should stay forward. |

`180` and `-180` are the same half-turn. The status line prints angles from -180 to 180, so the SteamVR shortcut shows `yaw -180 deg`. That is the offset you asked for.

Hold the glasses still when the window says `[calib]`. It accepts the first still window (about half a second) and gives up after about four seconds, then starts with zero bias and learns it as soon as the glasses are still. In the default mode it also waits until the glasses are upright and still, then recenters. Look straight ahead while wearing them. **F9** does that again at any time.

Both shortcuts share one saved pose in `%TEMP%\xreal_bridge_state.json`. **Enter** stores the current alignment and the next start uses it, for either shortcut, until **Backspace**. Backspace returns to the offset of the shortcut you launched (180 or 0) and forgets the saved pose.

A mode you pick with the `f` key lasts until you quit. The next start is `ref` again unless you pass `--fusion-mode`.

### UEVR

- Install a **nightly** UEVR build.
- Inject the game with the **OpenVR** runtime, not OpenXR. Leave the system OpenXR runtime alone.
- On the reference setup, `UI_FollowView=true` kept the game UI with the head, and `VR_MovementOrientation=0` stopped the character walking sideways.
- Use the **offset 0** shortcut. Offset 180 turns the whole view around, which makes "forward" on the stick walk backward.

### OpenXR, one app at a time

Some apps speak OpenXR only. SteamVR's runtime file is `steamxr_win64.json` inside the SteamVR folder. The OpenXR loader uses that file when `XR_RUNTIME_JSON` is set, and it does not look at the registry value while the variable is set.

**XREAL OpenXR via SteamVR (this app only)** runs `tools\launch-openxr-steamvr.ps1`. It asks for an `.exe`, sets `XR_RUNTIME_JSON` on that process, and starts it. Child processes inherit the variable. Nothing else on the PC changes. `tools\launch-openxr-steamvr.bat` is a template: copy it, set `APP`, and double-click.

```bat
powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools\launch-openxr-steamvr.ps1 -Exe "D:\Games\SomeOpenXrApp.exe"
```

Do not point UEVR at OpenXR to get this. UEVR should keep using OpenVR injection.

## Hotkeys

Keys in the bridge window need that window focused. The global keys work while a game is focused. They are Windows hotkeys, so another tool cannot use the same chord while the bridge is running.

### Bridge window

| Key | What it does |
|---|---|
| `r` | Recenter. In the default `ref` mode, look straight ahead **and level** first. That also learns the IMU's mount tilt (about 30° on the One Pro). |
| `R` | Recenter yaw only. The level reference stays. |
| `h` | Print this list |
| `q` | Quit |
| `s` | Toggle the diagnostic line: raw gyro in deg/s, accelerometer, and the angles being sent |
| `+` / `=` | Sensitivity +0.1 (default 1.0, minimum 0.1). While `1`/`2`/`3` is active, increase that VRto3D value instead. |
| `-` | Sensitivity −0.1, or decrease the selected VRto3D value |
| `1` `2` `3` | Edit VRto3D `depth`, `convergence`, or `fov` in `default_config.json` |
| `0` | Leave that editor |
| `a` | Cycle the gyro axis map (`default`, `swap_yz`, `swap_xy`, `rotate`) and recenter |
| `y` | Toggle the yaw sign and recenter |
| `p` | Toggle the pitch sign and recenter |
| `f` | Cycle fusion mode for **this session** (`legacy` → `quat_old` → `quat_new` → `ref`) and recenter |
| `t` / `T` | YZ mount tilt +1° / +5°. Not used by `ref`. |
| `u` / `U` | YZ mount tilt −1° / −5° |
| Left / Right | Yaw offset −5° / +5°. Hold Shift for 1°. |
| Up / Down | Pitch offset +5° / −5° (up looks higher). Hold Shift for 1°. |
| Enter | Save the alignment. It survives F9 and a restart. |
| Backspace | Restore this launch's `--recenter-yaw-offset` and `--recenter-pitch-offset`, and forget the saved pose |
| `b` | Add 180° to the yaw offset |
| `[` / `]` | Yaw offset −15° / +15° |

`depth` steps by 0.01 between 0 and 0.5, `convergence` by 0.25 between 0.1 and 10, `fov` by 1° between 40 and 110. For FOV, `+` zooms out and `-` zooms in. After a change, press **Ctrl+Shift+F10** in the VR window so VRto3D reloads the file (it beeps).

The arrow keys and `b` / `[` / `]` change the live view immediately and are forgotten on the next start until you press Enter.

### Global keys

| Key | Same as |
|---|---|
| F8 | `b` (add 180°) |
| F9 | `r` (recenter) |
| F10 | `a` (cycle axis map) |
| F11 | `y` (yaw sign) |
| F12 | `p` (pitch sign) |
| Ctrl+F10 | YZ tilt −1° |
| Ctrl+F11 | YZ tilt +1° |
| Ctrl+F12 | YZ tilt reset to 0 |
| Ctrl+Alt+arrows | The arrow keys above (5°) |
| Ctrl+Alt+Shift+arrows | 1° steps |
| Ctrl+Alt+Enter | Enter (save) |
| Ctrl+Alt+Backspace | Backspace (restore the launch offset) |

`--align-modifier` changes the Ctrl+Alt prefix. An empty string turns those global alignment keys off. Some Intel graphics drivers use Ctrl+Alt+arrows to rotate the desktop; if the picture rotates, use `--align-modifier Ctrl+Shift` or turn the hotkeys off.

While the bridge is running it owns **Ctrl+F10**, **Ctrl+F11**, and **Ctrl+F12**. VRto3D also uses those chords (reload the game profile, toggle auto-depth, screenshot). They belong to the bridge until you quit it. **Ctrl+Shift+F10** is not one of the bridge's keys.

### VRto3D's own keys

These belong to VRto3D, not to this program. They match [VRto3D's current README](https://github.com/oneup03/VRto3D).

| Key | What it does |
|---|---|
| Ctrl+Home | Open or close the on-screen menu |
| Ctrl+Shift+F10 | Reload `default_config.json` (a beep means it worked) |
| Ctrl+F10 | Reload the running game's profile (unavailable while the bridge is running) |
| Ctrl+F8 | Bring the headset window forward and focus the game |
| Ctrl+F7 | Save depth, convergence, and FOV into the game's profile |

`display_index`, output mode, and the OpenTrack port are read when SteamVR starts. Restart SteamVR after changing them. FOV reloads with Ctrl+Shift+F10.

## Tuning

### FOV

61 was the comfortable horizontal FOV on the reference One Pro. Raise it with `3` then `+` if the world feels zoomed in. Lower it if the world slides when you turn (that mismatch is what made 70 nauseating). Reload with Ctrl+Shift+F10. A value saved into a game profile with Ctrl+F7 overrides the default for that game only.

### Display index

VRto3D lists monitors, moves the **primary** monitor to position 1, and then counts from 1. `display_index` 0 also means "the primary". On the reference laptop the laptop panel was primary, so it was index 1 and the glasses were **index 2**.

The installer (and `python -m xreal_vr_bridge.vrto3d`) uses the same primary-to-front swap and looks for the monitor hardware id `MRG4100`, which is what the reference One Pro reports. Windows' Identify numbers in Settings are a different order. If the headset window opens on the wrong screen:

1. Run `python -m xreal_vr_bridge.vrto3d` and read the numbered list, or set `display_index` in `Steam\config\vrto3d\default_config.json`.
2. Restart SteamVR.
3. Ctrl+F8 brings the VRto3D window forward if it opened behind something else.

### Offsets

Yaw offset turns the whole view about vertical. Pitch offset looks up or down about the head's own right axis, and it stays "up" when you have also turned. F9 recenters tracking and then applies the offset again, which is why SteamVR home can stay in front of you after a recenter.

Use 180 for SteamVR home and for Unity apps whose menu is born behind you. Use 0 for UEVR. If a game is almost right but a few degrees off, nudge with the arrows and press Enter.

### If you also use a Quest

Leave the Windows OpenXR runtime on Virtual Desktop or Oculus. This installer will not switch it. SteamVR's own `steamvr.vrsettings` is also left alone, because `forcedDriver` would make every SteamVR session use VRto3D.

If SteamVR starts a different headset anyway, use VRto3D's SteamVR Config Manager (shipped with their installer, or `steamvr_cfg_mgr.zip` on their release page) and keep a profile per headset. To force it by hand, back up `Steam\config\steamvr.vrsettings` and set `"forcedDriver": "vrto3d"` inside the `steamvr` object. Restore the backup to undo it. That key is SteamVR's headset choice. It is not the Windows OpenXR runtime.

## Troubleshooting

**The picture is on the wrong screen.** See [Display index](#display-index). Restart SteamVR after the edit. Ctrl+F8 brings the window forward.

**The view spins on its own (drift).** The startup bias was taken while the glasses moved. Quit, start again, and leave them still until you see `Glasses are still` or `bias accepted`. In `ref` mode the bias is also learned during any later half-second of stillness, including when an earlier bias was wrong. Do not pass `--no-gravity-ref`; without gravity, pitch and roll drift.

**The image judders while turning.** Use the default threaded sender (`--sender thread`) and Python 3.11 or newer. The default rate is 250 packets/s, which is enough for VRto3D's sample clock (twice the panel rate; the reference panel was 60 Hz, so VRto3D sampled at 120 Hz). Optional extra smoothing: `--smooth 3` (One-Euro, almost no lag on a fast turn; `--smooth-beta 0.3`). VRto3D has its own filter in the on-screen menu under Tracking.

**The world stays crooked after you look up and back down.** That is the old Euler integrator. The window must say `Fusion mode: ref`. `legacy`, `quat_old`, and `quat_new` still tilt. Press F9 while looking straight ahead and level. Do not pass `--no-gravity-ref`.

**SteamVR's menu is behind you.** Use the offset 180 shortcut, or press F8 / `b` once and Enter if you want to keep it.

**The character walks sideways in a UEVR game.** Set `VR_MovementOrientation=0`. Use the offset 0 shortcut.

**Controls are reversed.** Offset 180 faces the other way, so the stick's forward is backward. Use offset 0 for that game. If only looking left/right is mirrored, press F11 (yaw sign) once. F12 does the same for pitch.

**The bridge cannot connect.** The glasses serve the IMU at `169.254.2.1` port `52998` on the USB-C RNDIS adapter. Windows should show an Ethernet adapter in `169.254.2.x`. Close anything else that already connected to that port. The bridge retries every 2 seconds. `--host` and `--imu-port` override the address.

**No global hotkeys.** Another program already registered that key, or you are not on Windows. The window keys still work when the bridge window is focused.

**Arrow keys rotate the Windows desktop.** That is the graphics driver's Ctrl+Alt+arrow shortcut. Start with `--align-modifier Ctrl+Shift`, or `--align-modifier ""` to disable the global alignment keys.

## Protocol and technical notes

```text
XREAL One / One Pro (X1)
  TCP 169.254.2.1:52998     134-byte little-endian frames
        │
        ▼
  xreal_vr_bridge.protocol  sync on magic 0x28 0x36 or 0x27 0x36, skip NaN frames
        │
        ▼
  xreal_vr_bridge.ahrs      quaternion AHRS (mode "ref"): bias, gravity, mount tilt
        │
        ▼
  xreal_vr_bridge.opentrack 48 bytes, 6 x float64: X, Y, Z, Yaw, Pitch, Roll
        │
        ▼
  UDP 127.0.0.1:4242        VRto3D / OpenTrack. Position is always 0 (3DoF).
```

Defaults, with no flags other than the yaw offset:

| Setting | Default | Flag |
|---|---|---|
| Glasses | `169.254.2.1:52998` | `--host`, `--imu-port` |
| OpenTrack | `127.0.0.1:4242` | `--udp-ip`, `--udp-port` |
| Fusion | `ref` | `--fusion-mode` |
| Gravity correction | on | `--no-gravity-ref` turns it off |
| Sender | `thread` (latest pose on its own clock) | `--sender inline` is the old path |
| Rate | 250 packets/s | `--max-rate` |
| Yaw offset | 0 | `--recenter-yaw-offset` |
| Startup bias | first still window of 500 samples, up to 8 windows | `--calib-samples` |

### Frame

| Field | Offset | Type |
|---|---|---|
| Magic | 0 | `0x28 0x36` or `0x27 0x36` |
| Timestamp | 14 | `u64` nanoseconds, device clock |
| Gyro | 34 | 3 x `f32` rad/s |
| Accelerometer | 46 | 3 x `f32` m/s² |
| Temperature | 70 | `f32` °C |

The frame is 134 bytes. The firmware inserts frames whose gyro or accelerometer is NaN; `frame_stream` drops those. Integration uses the device timestamp when the step is between 10 µs and 50 ms, because frames arrive in TCP bursts and the PC clock cannot see the gaps inside a burst.

### Sensor axes and the `ref` AHRS

Measured on the One / One Pro, and what the tests check:

- Sensor axes: **X right, Y down, Z forward**.
- Gyro **+X** looks up, **+Y** turns right, **+Z** rolls toward the right shoulder.
- Sitting level, the accelerometer reads about `(0, -9.8, 0)`.
- Output yaw is positive to the right, pitch positive looking up, roll positive toward the left shoulder. VRto3D rebuilds yaw-then-pitch-then-roll and negates yaw; the bridge emits the Euler order that matches that rebuild.

`ref` remaps the sensor into SteamVR's frame, subtracts gyro bias, applies a Mahony gravity correction, and integrates a quaternion. There are no Euler angles inside the loop, which is what stops the view going crooked after a look up and down. The IMU sits about 30° tilted in the frame. F9 while you look straight and level learns that tilt from gravity. Yaw has no magnetometer, so a long session can still drift in heading; F9 clears it.

The other fusion modes remain available for comparison. They are not the setup the shortcuts use.

### Axis check

`python -m xreal_vr_bridge.cli --dry-run`, glasses on, look straight, press `r`, press `s`. Move once, slowly, about 45°, then back to center.

| Move | Raw gyro | Output | Should barely move |
|---|---|---|---|
| Turn right | Y positive | yaw positive | pitch, roll |
| Turn left | Y negative | yaw negative | pitch, roll |
| Look up | X positive | pitch positive | yaw, roll |
| Look down | X negative | pitch negative | yaw, roll |
| Left ear toward shoulder | Z negative | roll positive | yaw, pitch |
| Right ear toward shoulder | Z positive | roll negative | yaw, pitch |

If a sign is wrong only inside one VRto3D build, `y` or `p` flips that output without changing the filter.

### Reference machine

Checked on the owner's laptop against a real One Pro. These are observations, not extra code paths: the host adapter was `169.254.2.10/24`, the glasses answered at `169.254.2.1`, the IMU port was 52998, raw frames arrived near 1400 Hz with a large share of NaN placeholders, the panel ran at 60 Hz even at 3840x1080, comfortable FOV was 61, and `display_index` was 2 while the laptop was the primary monitor.

### Development

```sh
python -m pip install -e ".[dev]"
python -m pytest -q

# No glasses: terminal A
python tools/mock_imu_server.py --yaw-rate 30
# Terminal B
python -m xreal_vr_bridge.cli --host 127.0.0.1 --dry-run
```

GitHub Actions runs pytest on Ubuntu and Windows, on Python 3.11 and 3.12.

The bridge is MIT. It implements the publicly documented X1 framing and does not ship or copy code from the GPLv3 projects around this hardware (XRLinuxDriver, decky-XRGaming, Breezy Desktop). VRto3D is a separate MIT program; this repo only writes its JSON config and, if you agree, copies its release zip.

## License

MIT. See [LICENSE](LICENSE).
