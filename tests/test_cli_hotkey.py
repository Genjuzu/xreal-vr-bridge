import pytest

from xreal_vr_bridge.cli import HotkeyManager, parse_hotkey, parse_hotkey_ex
from xreal_vr_bridge.fusion import AXIS_MAPS as FUSION_AXIS_MAPS


def test_cli_imports_axis_maps():
    from xreal_vr_bridge import cli

    assert hasattr(cli, "AXIS_MAPS")
    assert cli.AXIS_MAPS is FUSION_AXIS_MAPS


def test_parse_hotkey_names():
    assert parse_hotkey("F9") == 0x78
    assert parse_hotkey("F12") == 0x7B
    assert parse_hotkey("nope") == 0
    assert parse_hotkey("") == 0
    assert parse_hotkey(None) == 0


def test_hotkey_manager_required_args():
    with pytest.raises(TypeError):
        HotkeyManager()


def test_parse_hotkey_ex_plain():
    assert parse_hotkey_ex("F9") == (0x78, 0)
    assert parse_hotkey_ex("F12") == (0x7B, 0)
    assert parse_hotkey_ex("nope") == (0, 0)


def test_parse_hotkey_ex_with_modifier():
    assert parse_hotkey_ex("Ctrl+F11") == (0x7A, 0x0002)
    assert parse_hotkey_ex("CTRL+F10") == (0x79, 0x0002)
    assert parse_hotkey_ex("Ctrl+F12") == (0x7B, 0x0002)
    assert parse_hotkey_ex("Shift+F9")[1] == 0x0004
