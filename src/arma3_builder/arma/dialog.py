"""Generate KB topic (`sentences.bikb`) + CfgSentences entries for dialogue.

Arma's KB (knowledge base) system is what enables NPC → player radio / speech
with lipsync. The minimal producible unit is:

  * ``sentences.bikb`` – per-topic sentence bank
  * ``CfgSentences`` – registers the topic and its sentences
  * SQF: ``unit kbAddTopic ["topicName","sentences.bikb","CfgSentences"]``
         ``unit kbTell [player, "topicName", "sentenceId"]``

For designers we keep it simple: one topic per mission.
"""
from __future__ import annotations

from ..protocols import MissionBlueprint


def generate_sentences_bikb(blueprint: MissionBlueprint) -> str:
    if not blueprint.dialogue:
        return "// No dialogue lines for this mission.\n"
    topic_name = f"A3B_topic_{blueprint.mission_id or 'mission'}"
    lines: list[str] = [
        f"class {topic_name}",
        "{",
        f"    // Auto-generated from blueprint.dialogue ({len(blueprint.dialogue)} lines).",
    ]
    for d in blueprint.dialogue:
        text = d.text.replace('"', '""')
        lines.append(
            f'    class {d.id} {{\n'
            f'        text = "{text}";\n'
            f'        speech[] = {{}};\n'
            f'        class Arguments {{}};\n'
            f'    }};'
        )
    lines.append("};")
    return "\n".join(lines) + "\n"


def generate_cfg_sentences(blueprint: MissionBlueprint) -> str:
    if not blueprint.dialogue:
        return "class CfgSentences {};\n"
    topic_name = f"A3B_topic_{blueprint.mission_id or 'mission'}"
    return (
        "class CfgSentences\n"
        "{\n"
        f"    class {topic_name}\n"
        "    {\n"
        + "\n".join(
            f'        class {d.id};' for d in blueprint.dialogue
        )
        + "\n    };\n"
          "};\n"
    )


def generate_dialog_driver_sqf(blueprint: MissionBlueprint) -> str:
    """Register the topic on the speaker unit and bind it to FSM states."""
    if not blueprint.dialogue:
        return "// No dialogue configured.\n"
    topic_name = f"A3B_topic_{blueprint.mission_id or 'mission'}"
    out: list[str] = [
        "// fn_playDialog.sqf — binds radio lines to FSM state transitions.",
        "params [[\"_speaker\", objNull, [objNull]]];",
        "if (isNull _speaker) exitWith {};",
        f'_speaker kbAddTopic ["{topic_name}", "sentences.bikb", "CfgSentences", ""];',
        "",
    ]
    for d in blueprint.dialogue:
        if d.trigger_state:
            out.append(
                f'[missionNamespace getVariable ["A3B_stateMachine", objNull], '
                f'"{d.trigger_state}", {{ '
                f'_speaker kbTell [player, "{topic_name}", "{d.id}"] '
                f'}}, "enter"] call CBA_statemachine_fnc_addStateScript;'
            )
        else:
            out.append(f'_speaker kbTell [player, "{topic_name}", "{d.id}"];')
    return "\n".join(out) + "\n"
