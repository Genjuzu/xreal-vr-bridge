import json

from xreal_vr_bridge.vrto3d import (
    RECOMMENDED_SETTINGS,
    apply_config,
    config_changes,
    order_displays,
    xreal_display_index,
)


def test_primary_monitor_moves_to_index_1():
    displays = [
        ("\\\\.\\DISPLAY2", r"MONITOR\MRG4100\{abc}", False),
        ("\\\\.\\DISPLAY1", r"MONITOR\LNX\{laptop}", True),
        ("\\\\.\\DISPLAY3", r"MONITOR\OTHER\{x}", False),
    ]
    ordered = order_displays(displays)
    assert ordered[0][2] is True
    assert xreal_display_index(displays) == 2


def test_glasses_as_primary_are_index_1():
    displays = [
        ("\\\\.\\DISPLAY1", r"MONITOR\LNX", False),
        ("\\\\.\\DISPLAY2", r"MONITOR\MRG4100", True),
    ]
    assert xreal_display_index(displays) == 1


def test_missing_glasses_have_no_index():
    assert xreal_display_index([("\\\\.\\DISPLAY1", r"MONITOR\LNX", True)]) is None


def test_recommended_settings_match_the_reference_setup():
    assert RECOMMENDED_SETTINGS["fov"] == 61.0
    assert RECOMMENDED_SETTINGS["use_open_track"] is True
    assert RECOMMENDED_SETTINGS["open_track_port"] == 4242
    assert RECOMMENDED_SETTINGS["output_mode"] == "SbS"
    assert RECOMMENDED_SETTINGS["render_width"] == 1920
    assert RECOMMENDED_SETTINGS["render_height"] == 1080


def test_apply_config_backs_up_once_and_preserves_other_keys(tmp_path):
    path = tmp_path / "default_config.json"
    path.write_text(json.dumps({
        "fov": 70,
        "display_index": 0,
        "user_preset": "keep-me",
        "use_open_track": False,
    }), encoding="utf-8")

    first = apply_config(str(path), display_index=2)
    assert first["status"] == "updated"
    assert first["backup"]
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["fov"] == 61.0
    assert written["display_index"] == 2
    assert written["user_preset"] == "keep-me"
    assert written["use_open_track"] is True
    assert written["open_track_port"] == 4242
    backup = json.loads(open(first["backup"], encoding="utf-8").read())
    assert backup["fov"] == 70
    assert backup["user_preset"] == "keep-me"

    second = apply_config(str(path), display_index=2)
    assert second["status"] == "unchanged"
    assert list(tmp_path.glob("*.bak-*")) == [tmp_path / __import__("os").path.basename(first["backup"])]


def test_apply_leaves_display_index_when_not_given(tmp_path):
    path = tmp_path / "default_config.json"
    original = dict(RECOMMENDED_SETTINGS)
    original["display_index"] = 4
    original["custom"] = 1
    path.write_text(json.dumps(original), encoding="utf-8")
    assert config_changes(original, None) == {}
    result = apply_config(str(path), None)
    assert result["status"] == "unchanged"
    assert json.loads(path.read_text(encoding="utf-8"))["display_index"] == 4


def test_apply_does_not_create_a_missing_config(tmp_path):
    path = tmp_path / "missing.json"
    result = apply_config(str(path), 2)
    assert result["status"] == "missing"
    assert not path.exists()
