"""Music cue generation.

Two surfaces:
  1. ``CfgMusic`` block for description.ext — registers each unique track
     with a `sound[]` path (`music/<track>.ogg` placeholder; the designer
     drops the real OGG into that directory post-hoc).
  2. SQF wiring that calls ``playMusic`` on FSM state entry.
"""
from __future__ import annotations

from ..protocols import MissionBlueprint, MusicCue


def generate_cfg_music_block(blueprint: MissionBlueprint) -> str:
    """CfgMusic fragment for description.ext.

    Only tracks whose name starts with `A3B_` are treated as custom; vanilla
    tracks (`LeadTrack01a_F_EPA`, etc.) are passed through to `playMusic`
    without a CfgMusic entry.
    """
    custom = {c.track for c in blueprint.music_cues if c.track.startswith("A3B_")}
    if not custom:
        return "// No custom music tracks.\nclass CfgMusic {};"

    entries = []
    for t in sorted(custom):
        entries.append(
            f'    class {t}\n'
            f'    {{\n'
            f'        name    = "{t}";\n'
            f'        sound[] = {{"music\\{t}.ogg", db+0, 1.0}};\n'
            f'    }};'
        )
    return "class CfgMusic\n{\n" + "\n".join(entries) + "\n};"


def wire_music_into_fsm(blueprint: MissionBlueprint) -> None:
    """Inline `playMusic` calls on each cue's trigger state entry."""
    by_id = {s.id: s for s in blueprint.fsm.states}
    for cue in blueprint.music_cues:
        state = by_id.get(cue.trigger_state)
        if state is None:
            continue
        # Cross-fade via fadeMusic. playMusic starts the track from 0s
        # on every client (it broadcasts automatically).
        state.on_enter.append(
            f'{cue.fade_seconds} fadeMusic {cue.volume}; '
            f'playMusic "{cue.track}"'
        )


def music_tracks_manifest(blueprint: MissionBlueprint) -> list[MusicCue]:
    return list(blueprint.music_cues)
