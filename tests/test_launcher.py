from pathlib import Path

from arma3_builder.arma.launcher import (
    arma3_editor_command,
    build_launch_payload,
    steam_launch_command,
)


def test_editor_cmd_contains_world_and_path():
    cmd = arma3_editor_command(Path("/tmp/x"), world="Tanoa", mods=["rhsusf", "cba_main"])
    assert "-world=Tanoa" in cmd
    assert "-mod=rhsusf;cba_main" in cmd
    assert "playMission" in cmd


def test_steam_uri_format():
    uri = steam_launch_command("my_camp")
    assert uri.startswith("steam://rungameid/107410")
    assert "-campaign=my_camp" in uri


def test_launch_payload_shape():
    p = build_launch_payload(Path("/tmp/out"), world="Altis", slug="s", mods=[])
    assert "editor_cmd" in p
    assert "steam_uri" in p
    assert "copy_paths" in p
