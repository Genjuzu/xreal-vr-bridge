"""The flags a shortcut does not pass must already be the known-good setup."""

from xreal_vr_bridge.cli import parse_args


def test_known_good_cli_defaults():
    args = parse_args([])
    assert args.host == "169.254.2.1"
    assert args.imu_port == 52998
    assert args.udp_ip == "127.0.0.1"
    assert args.udp_port == 4242
    assert args.fusion_mode == "ref"
    assert args.sender == "thread"
    assert args.max_rate == 250
    assert args.no_gravity_ref is False
    assert args.recenter_yaw_offset == 0.0
    assert args.recenter_pitch_offset == 0.0
    assert args.smooth == 0.0
    assert args.disable_quiet_calib is False


def test_shortcuts_only_need_the_yaw_offset():
    steamvr = parse_args(["--recenter-yaw-offset", "180"])
    uevr = parse_args(["--recenter-yaw-offset", "0"])
    assert steamvr.recenter_yaw_offset == 180.0
    assert uevr.recenter_yaw_offset == 0.0
    assert steamvr.fusion_mode == uevr.fusion_mode == "ref"
    assert steamvr.max_rate == uevr.max_rate == 250
