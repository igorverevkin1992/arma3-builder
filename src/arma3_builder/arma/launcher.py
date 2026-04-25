"""One-click launch helpers for Arma 3.

These generate platform-specific commands to launch the currently-generated
campaign in Eden Editor or as a direct playable mission. The UI surfaces them
as `Copy to clipboard` since we can't fork processes on the user's machine.
"""
from __future__ import annotations

import shlex
from pathlib import Path


def arma3_editor_command(
    mission_path: Path,
    *,
    world: str,
    arma3_exe: str = "Arma3.exe",
    mods: list[str] | None = None,
) -> str:
    mods = mods or []
    parts = [arma3_exe, "-noSplash", f"-world={world}"]
    if mods:
        parts.append("-mod=" + ";".join(mods))
    parts.append(f'-init=playMission [{{""}}, {shlex.quote(str(mission_path))}]')
    return " ".join(parts)


def steam_launch_command(campaign_slug: str) -> str:
    """Steam URL that launches Arma 3 with a campaign pre-selected.

    The user must have installed the campaign under ``Arma 3/Campaigns/``.
    """
    return f"steam://rungameid/107410 -autoPlay=1 -campaign={campaign_slug}"


def build_launch_payload(output_path: Path, world: str, slug: str, mods: list[str]) -> dict:
    return {
        "editor_cmd": arma3_editor_command(output_path, world=world, mods=mods),
        "steam_uri": steam_launch_command(slug),
        "copy_paths": {
            "singleplayer_missions_hint":
                "Copy this folder into:  Documents/Arma 3 - Other Profiles/<profile>/missions/",
            "campaign_hint":
                "Copy this folder into:  Arma 3/Campaigns/  (or PBO-pack with addonBuilder)",
        },
    }
