"""The Windows scripts must not retarget OpenXR or SteamVR for every app."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = list(ROOT.glob("*.ps1")) + list(ROOT.glob("*.bat")) + list((ROOT / "tools").glob("*.ps1")) + list((ROOT / "tools").glob("*.bat"))

# Strings that would mean the scripts write the machine-wide runtime or
# SteamVR's forced headset. Mentioning them in the README is fine.
FORBIDDEN = (
    "ActiveRuntime",
    "forcedDriver",
    "Khronos",
    "Set-ItemProperty",
    "New-ItemProperty",
    "Remove-ItemProperty",
    "reg add",
    "reg.exe",
)


def test_scripts_exist():
    names = {path.name for path in SCRIPTS}
    assert "install.ps1" in names
    assert "install.bat" in names
    assert "uninstall.ps1" in names
    assert "uninstall.bat" in names
    assert "launch-openxr-steamvr.ps1" in names


def test_scripts_do_not_change_the_system_openxr_runtime():
    offenders = []
    for path in SCRIPTS:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            if token in text:
                offenders.append(f"{path.name}: {token}")
    assert offenders == []


def test_installer_and_launcher_state_the_boundary():
    install = (ROOT / "install.ps1").read_text(encoding="utf-8")
    launch = (ROOT / "tools" / "launch-openxr-steamvr.ps1").read_text(encoding="utf-8")
    uninstall = (ROOT / "uninstall.ps1").read_text(encoding="utf-8")
    assert "does not change the system OpenXR runtime" in install
    assert "does not edit steamvr.vrsettings" in install
    assert "XR_RUNTIME_JSON" in launch
    assert "UseShellExecute = $false" in launch
    assert "system OpenXR runtime" in uninstall
