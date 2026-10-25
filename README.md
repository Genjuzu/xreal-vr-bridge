# xreal-vr-bridge

XREAL One / One Pro (X1-Chip) → **OpenTrack-UDP** → **SteamVR / VRto3D** Bridge.

Liest den ~1000-Hz-IMU-Stream der Brille (TCP `169.254.2.1:52998`, 134-Byte-Frames,
Little-Endian), kalibriert den Gyro-Bias (500 Samples) und sendet die Orientierung
als OpenTrack-UDP-Paket (48 Bytes, `6 × float64`: X,Y,Z,Yaw,Pitch,Roll) an z. B.
`127.0.0.1:4242` (VRto3D / OpenTrack / Simulatoren).

## Status

- [x] Repo-Skelett (MIT, pyproject, README, PLAN)
- [x] `protocol.py` – Frame-Sync (Magic 2836/2736), Dekodierung, NaN-Skip
- [x] `fusion.py` – Gyro-Bias-Kalibrierung, Komplementärfilter (96/4), Yaw-Integration
- [x] `opentrack.py` – UDP-Paket-Builder
- [x] `tools/mock_imu_server.py` – simulierte Brille (1000 Hz) ohne Hardware
- [x] `cli.py` – Bridge-CLI + Integrationstest
- [x] Live-Validierung gegen echte XREAL One Pro (siehe unten)

## Nutzung

Echte Brille (angeschlossen via USB-C, Ethernet-Interface auf 169.254.2.x):

```sh
python -m xreal_vr_bridge.cli --dry-run          # Orientierung anzeigen
python -m xreal_vr_bridge.cli                    # UDP an 127.0.0.1:4242
python -m xreal_vr_bridge.cli --udp-port 4242 --max-rate 120
```

Ohne Brille (Mock):

```sh
python tools/mock_imu_server.py --yaw-rate 30 &
python -m xreal_vr_bridge.cli --host 127.0.0.1 --dry-run
```

Wichtige Optionen: `--calib-samples` (Standard 500), `--max-rate` (UDP-Pakete/s,
Standard 120), `--duration` (nach N Sekunden beenden), `--verbose`.

## Live-Validierung (25.10.2026, echte Brille)

- Host-Interface `Ethernet 2` = 169.254.2.10/24; Gerät 169.254.2.1 antwortet (ARP).
- Ports 52995–52999 offen; IMU-Stream auf 52998 bestätigt.
- Frame-Format bestätigt: 134 Bytes, Header-Start `28 36` (Magic 2836), Gyro @ 34
  (rad/s), Accel @ 46 (m/s², Ruhe-Magnitude ≈ 9,8), Temperatur @ 70 (≈ 25,4 °C im
  Test).
- Gemessene Rate: ~1400 Frames/s roh. **Wichtig:** die Firmware interleavt NaN-
  Platzhalter-Frames (~28 %); `frame_stream` überspringt diese.
- Bridge-Lauf: Bias-Kalibrierung liefert endliche Werte; statische Pitch-/Roll-Werte
  konvergieren stabil (Testgerät lag geneigt, pitch ≈ −68°, yaw ≈ 0°).

## SteamVR / VRto3D-Integration (Windows)

Voraussetzungen: SteamVR installiert, XREAL One Pro per USB-C angeschlossen
(Display + Ethernet), Brille im **Follow Mode (0DoF)**, **Stabilizer OFF** und
**3D Mode Full SBS** (OSD: Doppelklick auf „X“).

Installation des Treibers (einmalig):

```powershell
$zip = (Invoke-WebRequest -Uri "https://github.com/oneup03/VRto3D/releases/download/V5.0.0/VRto3D.zip").Content
Expand-Archive -Path $zip -DestinationPath "$env:TEMP\vrto3d" -Force
Copy-Item -Recurse "$env:TEMP\vrto3d\vrto3d" `
  "C:\Program Files (x86)\Steam\steamapps\common\SteamVR\drivers\vrto3d"
```

Danach in `Steam\config\steamvr.vrsettings` unter `steamvr` setzen:
`"forcedDriver": "vrto3d"` (Backup vorher anlegen). Die Datei
`Steam\config\vrto3d\default_config.json` wird beim ersten Start von VRto3D
angelegt; für die XREAL One Pro relevant:

```json
{
  "output_mode": "SbS",
  "render_width": 1920,
  "render_height": 1080,
  "aspect_ratio": 1.77778,
  "fov": 57.0,
  "use_open_track": true,
  "open_track_port": 4242
}
```

Betrieb:

```powershell
# Bridge (IMU -> OpenTrack UDP auf 127.0.0.1:4242) in eigenem Fenster:
# --no-gravity-ref: Gyro-only-Integration (empfohlen für VR, kein Rückzug
#   zur Schwerkraftachse), automatischer Recenter nach Kalibrierung.
Start-Process -FilePath "C:\...\xreal-vr-bridge\.venv\Scripts\python.exe" `
  -ArgumentList "-m","xreal_vr_bridge.cli","--no-gravity-ref"
# SteamVR starten (HMD erscheint als "Stereo3D-1234" / VRto3D)
Start-Process "steam://run/250820"
```

Falls das VR-Fenster auf dem falschen Monitor erscheint: `display_index` in
`default_config.json` anpassen (1 = erster Monitor, 2 = zweiter usw.) und
SteamVR neu starten. `Ctrl + Home` öffnet das VRto3D-OSD (Tracking-Tab →
OpenTrack).

### Interaktives Menü der Bridge (Funktionen)

| Taste | Funktion |
|---|---|
| `r` | **Recenter**: aktuelle Blickrichtung = geradeaus (Yaw/Pitch/Roll = 0) |
| `+` / `-` | Empfindlichkeit der Kopfbewegung (0.1 Schritte; Standard 1.0) |
| `1` / `2` / `3` | Bild-Parameter wählen: **Tiefe** (depth) / **Konvergenz** (convergence) / **FOV** (fov) – Wert wird in die VRto3D-`default_config.json` geschrieben; im Spiel `Ctrl+Shift+F10` zum Neuladen |
| `0` | Bild-Param-Modus verlassen |
| `h` | Hilfe anzeigen |
| `q` | Bridge beenden |

Tipp: Sind die Bilder leicht verschwommen oder zu „nah/fern“, mit `1`/`2`/`3`
die Werte in kleinen Schritten anpassen und mit `Ctrl+Shift+F10` im Spiel neu
laden. Die Anpassung wirkt global (alle Spiele), bis sie im VRto3D-OSD pro
Spiel überschrieben wird.

## Architektur

```
XREAL One Pro (X1)
  └─ TCP 169.254.2.1:52998  ~1000 Hz, 134-Byte-Frames (LE)
       Gyro @34 (rad/s), Accel @46 (m/s²), Temp @70 (°C)
            │
            ▼
  xreal_vr_bridge.protocol   Frame-Sync (Magic 2836/2736), Dekodierung, NaN-Skip
            │
            ▼
  xreal_vr_bridge.fusion     Gyro-Bias-Kalibrierung (500 Samples),
                             Komplementärfilter (96% Gyro / 4% Accel),
                             Yaw = Gyro-Integration (kein Magnetometer → Drift)
            │
            ▼
  xreal_vr_bridge.opentrack  OpenTrack-UDP-Paket (48 B, 6×float64)
            │
            ▼
  VRto3D (SteamVR/OpenXR) / Simulatoren (OpenTrack empfängt UDP)
```

## Lizenz

MIT. Eigener Code auf Basis öffentlich dokumentierter Reverse-Engineering-Fakten;
kein Hersteller-SDK. GPLv3-Komponenten (XRLinuxDriver, decky-XRGaming, Breezy
Desktop) bleiben strikt getrennt – daraus wird kein Code übernommen.
