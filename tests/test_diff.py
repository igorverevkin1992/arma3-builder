from arma3_builder.pipeline.diff import diff_artifacts
from arma3_builder.protocols import GeneratedArtifact


def test_diff_detects_modification():
    a = [GeneratedArtifact(relative_path="f.sqf", content="hint 'a'\n", kind="sqf")]
    b = [GeneratedArtifact(relative_path="f.sqf", content="hint 'b'\n", kind="sqf")]
    diffs = diff_artifacts(a, b)
    assert len(diffs) == 1
    assert diffs[0].change == "modified"
    assert "hint 'a'" in diffs[0].unified
    assert "hint 'b'" in diffs[0].unified


def test_diff_detects_add_remove():
    a = [GeneratedArtifact(relative_path="one.sqf", content="x", kind="sqf")]
    b = [GeneratedArtifact(relative_path="two.sqf", content="y", kind="sqf")]
    diffs = diff_artifacts(a, b)
    changes = {d.path: d.change for d in diffs}
    assert changes["one.sqf"] == "removed"
    assert changes["two.sqf"] == "added"
