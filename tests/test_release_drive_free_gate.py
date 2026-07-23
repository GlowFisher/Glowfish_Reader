from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "glowfish_reader"
    / "proofread"
    / "release.ps1"
)


def test_release_blocks_runtime_subst_invocations():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "enforcing drive-free OCR runtime" in text
    assert "$driveAliasRuntimeFiles" in text
    assert "forbidden subst invocation in runtime" in text


def test_frozen_gate_uses_unicode_data_and_rejects_new_drive_aliases():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "$unicodeGateLeaf" in text
    assert "FromBase64String" in text
    assert "$driveAliasesBefore" in text
    assert "$driveAliasesAfter" in text
    assert "created a temporary drive alias" in text
