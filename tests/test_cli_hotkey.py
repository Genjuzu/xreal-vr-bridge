import math

import pytest

from xreal_vr_bridge.cli import (
    HotkeyManager,
    load_state,
    parse_hotkey,
    parse_hotkey_ex,
    quiet_bias_step,
    save_state,
)
from xreal_vr_bridge.fusion import AXIS_MAPS as FUSION_AXIS_MAPS, ComplementaryOrientation


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


def test_save_load_state_roundtrip():
    o = ComplementaryOrientation(yz_tilt_deg=32.0)
    o.set_axis_map("default")
    save_state(o)
    state = load_state()
    assert state is not None
    assert state["yz_tilt_deg"] == 32.0
    assert state["axis_map"] == "default"


def test_quiet_bias_step_updates_after_still_window():
    offset = 0.001  # rad/s, below the quiet threshold
    bias = (0.0, 0.0, 0.0)
    q_state = (0, (0.0, 0.0, 0.0))
    for _ in range(1000):
        bias, q_state, updated = quiet_bias_step(bias, (offset, 0.0, 0.0), q_state)
    assert updated
    assert abs(bias[0] - offset) < 1e-9


def test_quiet_bias_step_resets_on_motion():
    offset = 0.1
    bias = (0.0, 0.0, 0.0)
    q_state = (0, (0.0, 0.0, 0.0))
    for _ in range(500):
        bias, q_state, _ = quiet_bias_step(bias, (offset, 0.0, 0.0), q_state)
    bias, q_state, updated = quiet_bias_step(
        bias, (math.radians(30.0), 0.0, 0.0), q_state
    )
    assert not updated
    assert q_state[0] == 0


def test_quiet_bias_step_uses_threshold():
    bias = (0.0, 0.0, 0.0)
    q_state = (0, (0.0, 0.0, 0.0))
    for _ in range(50):
        bias, q_state, updated = quiet_bias_step(bias, (0.0001, 0.0, 0.0), q_state)
    assert not updated
    assert q_state[0] == 50
