from arma3_builder.arma.dialog import (
    generate_cfg_sentences,
    generate_dialog_driver_sqf,
    generate_sentences_bikb,
)
from arma3_builder.protocols import Dialogue


def test_dialog_artifacts_when_lines_present(mission_blueprint):
    mission_blueprint.dialogue = [
        Dialogue(id="hq1", speaker="HQ", text="Contact front!", trigger_state="start"),
    ]
    bikb = generate_sentences_bikb(mission_blueprint)
    cfg = generate_cfg_sentences(mission_blueprint)
    sqf = generate_dialog_driver_sqf(mission_blueprint)
    assert "class hq1" in bikb
    assert "Contact front!" in bikb
    assert "class hq1;" in cfg
    assert "kbAddTopic" in sqf
    assert "kbTell" in sqf
    assert "start" in sqf  # trigger_state bound to FSM


def test_no_dialog_emits_empty_scaffold(mission_blueprint):
    mission_blueprint.dialogue = []
    assert "No dialogue" in generate_sentences_bikb(mission_blueprint)
    assert "class CfgSentences {}" in generate_cfg_sentences(mission_blueprint)
