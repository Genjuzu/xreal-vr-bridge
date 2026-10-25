import pytest

from xreal_vr_bridge.cli import HotkeyManager, parse_hotkey


def test_parse_hotkey_names():
    assert parse_hotkey("F9") == 0x78
    assert parse_hotkey("F12") == 0x7B
    assert parse_hotkey("nope") == 0
    assert parse_hotkey("") == 0
    assert parse_hotkey(None) == 0


def test_hotkey_manager_required_args():
    with pytest.raises(TypeError):
        HotkeyManager()
