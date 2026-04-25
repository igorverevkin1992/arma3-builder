"""Generate KB topic (`sentences.bikb`) + CfgSentences entries for dialogue.

Arma's KB (knowledge base) system is what enables NPC → player radio / speech
with lipsync. The minimal producible unit is:

  * ``sentences.bikb``  – KB topic + sentence bank
  * ``CfgSentences``    – registers the topic class (must be `#include`-d
                          from ``description.ext`` — Config Master does this).
  * SQF: ``unit kbAddTopic [topicName, "sentences.bikb", "CfgSentences\\<topicName>"]``
         ``unit kbTell    [target, topicName, sentenceId]``

For designers we keep it simple: one topic per mission. The driver SQF must
run AFTER ``A3B_fnc_initFsm`` has populated ``A3B_stateMachine``, so we wait
for the namespace variable before binding sentences to FSM transitions.
"""
from __future__ import annotations

from ..protocols import MissionBlueprint


def _topic_name(blueprint: MissionBlueprint) -> str:
    return f"A3B_topic_{blueprint.mission_id or 'mission'}"


def generate_sentences_bikb(
    blueprint: MissionBlueprint,
    *,
    audio_paths: dict[str, str] | None = None,
) -> str:
    """Return the contents of ``sentences.bikb``.

    Arma's KB parser expects raw `class <topic>` blocks at the top of the
    file (no outer wrapper). Each sentence carries `text`, a `speech[]`
    array pointing at the OGG TTS rendered for that line (or empty array
    if no audio was synthesised), and an empty `Arguments` block — the
    minimum schema the engine accepts.
    """
    if not blueprint.dialogue:
        return "// No dialogue lines for this mission.\n"
    topic = _topic_name(blueprint)
    audio_paths = audio_paths or {}
    lines: list[str] = [
        f"class {topic}",
        "{",
        f"    // Auto-generated from blueprint.dialogue ({len(blueprint.dialogue)} lines).",
    ]
    for d in blueprint.dialogue:
        text = d.text.replace('"', '""')
        sound = audio_paths.get(d.id, "")
        speech_arr = f'{{"{sound}"}}' if sound else "{}"
        lines.append(
            f'    class {d.id} {{\n'
            f'        text = "{text}";\n'
            f'        speech[] = {speech_arr};\n'
            f'        class Arguments {{}};\n'
            f'    }};'
        )
    lines.append("};")
    return "\n".join(lines) + "\n"


def generate_cfg_sentences(blueprint: MissionBlueprint) -> str:
    """Return the ``CfgSentences`` fragment that description.ext includes.

    We declare the topic *class header* and forward-declare each sentence.
    The actual bodies live in ``sentences.bikb`` — Arma resolves them by
    name when ``kbAddTopic`` is called.
    """
    if not blueprint.dialogue:
        return "class CfgSentences {};\n"
    topic = _topic_name(blueprint)
    return (
        "class CfgSentences\n"
        "{\n"
        f"    class {topic}\n"
        "    {\n"
        + "\n".join(f'        class {d.id};' for d in blueprint.dialogue)
        + "\n    };\n"
          "};\n"
    )


def generate_dialog_driver_sqf(blueprint: MissionBlueprint) -> str:
    """Bind dialogue lines to FSM state transitions.

    The driver:
      1. Waits for ``A3B_stateMachine`` (set by ``fn_initFsm``) — without
         this guard, the addStateScript calls would target objNull.
      2. Calls ``kbAddTopic`` with the *fully-qualified* CfgSentences path
         (``"CfgSentences\\<topic>"``) — passing only ``"CfgSentences"``
         silently fails because the engine cannot resolve the class.
      3. Registers each line as an `enter` script-hook of its trigger state,
         or fires it immediately if no trigger is set.
    """
    if not blueprint.dialogue:
        return "// No dialogue configured.\n"
    topic = _topic_name(blueprint)
    out: list[str] = [
        "// fn_playDialog.sqf — binds radio lines to FSM state transitions.",
        "params [[\"_speaker\", objNull, [objNull]]];",
        "if (isNull _speaker) exitWith {};",
        "",
        "// Wait for the FSM to be ready (set by A3B_fnc_initFsm).",
        "waitUntil { !isNil { missionNamespace getVariable \"A3B_stateMachine\" } };",
        "private _sm = missionNamespace getVariable \"A3B_stateMachine\";",
        "",
        "// Register the KB topic on the speaker. Fully-qualified config path.",
        f'_speaker kbAddTopic ["{topic}", "sentences.bikb", "CfgSentences\\\\{topic}", ""];',
        "",
    ]
    for d in blueprint.dialogue:
        if d.trigger_state:
            out.append(
                f'[_sm, "{d.trigger_state}", '
                f'{{ _speaker kbTell [player, "{topic}", "{d.id}"] }}, '
                f'"enter"] call CBA_statemachine_fnc_addStateScript;'
            )
        else:
            out.append(f'_speaker kbTell [player, "{topic}", "{d.id}"];')
    return "\n".join(out) + "\n"
