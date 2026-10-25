# Plan: XREAL One Pro (X1) → SteamVR / OpenTrack Bridge

Ziel: Die XREAL One / One Pro als PC-VR-Headset (3DoF, Gamepad/Maus) und als
räumliche Workstation nutzbar machen. Dieses Repo implementiert den eigenen,
quelloffenen Teil (MIT): IMU-Lesen → Sensorfusion → OpenTrack-UDP → SteamVR/VRto3D.

## Warum MIT?
- Unser Code ist reine Protokoll-/Integrationslogik auf Basis öffentlich
  dokumentierter Reverse-Engineering-Fakten (kein Hersteller-SDK, keine
  geschützten Binaries).
- Das Ökosystem ist überwiegend permissiv (VRto3D MIT, KyleKreuter/xreal MIT,
  one-xr MIT, opentrack ISC). MIT erlaubt kommerzielle Nutzung und passt dazu.
- Achtung (Lizenz-Grenze): `XRLinuxDriver`/`decky-XRGaming`/`Breezy Desktop`
  sind GPLv3. Aus diesen **keinen Code übernehmen/kopieren** — nur Fakten
  (Protokoll-Offsets), die nicht urheberrechtlich geschützt sind, als
  Referenz verwenden. GPL-Komponenten bleiben strikt getrennt.

## Architektur (Pfad 3 aus der Analyse: Eigenentwicklung)

```
XREAL One Pro (X1)
  └─ TCP 169.254.2.1:52998  ~1000 Hz, 134-Byte-Frames (LE)
       Gyro @34 (rad/s), Accel @46 (m/s²), Temp @70 (°C)
            │
            ▼
  xreal_vr_bridge.protocol   Frame-Sync (Magic 2836/2736), Dekodierung, Counter-Rollover
            │
            ▼
  xreal_vr_bridge.fusion     Gyro-Bias-Kalibrierung (500 Samples),
                             Komplementärfilter (96% Gyro / 4% Accel für Pitch/Roll),
                             Yaw = Gyro-Integration (kein Magnetometer → Drift dokumentiert)
            │
            ▼
  xreal_vr_bridge.opentrack  OpenTrack-UDP-Paket (48 B, 6×float64: X,Y,Z,Yaw,Pitch,Roll)
            │
            ▼
  VRto3D (SteamVR/OpenXR) / Simulatoren (OpenTrack empfängt UDP)
```

## Inkremente
0. ✅ Repo-Skelett (LICENSE MIT, .gitignore, pyproject, README, PLAN)
1. ✅ `protocol.py` — Frame-Dekodierung + Sync + NaN-Platzhalter-Skip (TDD).
    Counter-Rollover entfällt: die Integration nutzt lokale Wanduhr (dt), kein
    Packet-Ordinal → Rollover ist für den Datenpfad irrelevant.
2. ✅ `fusion.py` — Kalibrierung + Komplementärfilter (TDD)
3. ✅ `opentrack.py` — UDP-Paket-Builder (TDD)
4. ✅ `tools/mock_imu_server.py` — simulierte Brille (1000 Hz) für Tests ohne Hardware
5. ✅ `cli.py` — Bridge-CLI (TCP→Kalibrierung→Filter→UDP, Rate-Limit) + Integrationstest
6. ✅ Live-Validierung beim echten Gerät (Offsets, Rate, NaN-Interleaving, Bias,
    stabile statische Orientierung) – Details in README.

## Nächste Schritte (optional)
- Git-Initialisierung/erster Commit + Publikation (GitHub, MIT) auf Wunsch.
- OpenTrack-Test mit VRto3D im SteamVR (Benötigt SteamVR + VRto3D installiert).
- 6DoF-Erweiterung via Webcam (OpenTrack NeuralNet) als separates Inkrement.
- Bluetooth-Controller (Joy-Con) als SteamVR-Controller, später.

## Lieferbare Nutzung
- Echte Brille: `xreal-bridge`
- Ohne Brille (Mock): `python tools/mock_imu_server.py` + `xreal-bridge --host 127.0.0.1`

## Nicht im Scope (Phase 1)
- 6DoF-Kopf-Tracking (XREAL Eye gibt keine Daten nach außen; Webcam-Pfad als
  spätere Erweiterung, z. B. OpenTrack NeuralNet).
- Bluetooth-Controller als SteamVR-Controller (eigenes Inkrement, später).
- Rust/C++-Portierung (später, gleiches Kern-Protokoll).
