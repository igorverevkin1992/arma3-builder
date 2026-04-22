from arma3_builder.arma.description_ext import generate_mission_description_ext


def test_description_ext_has_required_keys(mission_blueprint):
    text = generate_mission_description_ext(mission_blueprint)
    assert 'briefingName = "Test Mission"' in text
    assert 'skipLobby = 1' in text
    assert 'respawn = "BASE"' in text
    assert "class CfgFunctions" in text
    assert "class CfgDebriefing" in text
    # The terminal end1 state must produce a debriefing class.
    assert "class end1" in text


def test_description_ext_balanced_braces(mission_blueprint):
    text = generate_mission_description_ext(mission_blueprint)
    assert text.count("{") == text.count("}")
