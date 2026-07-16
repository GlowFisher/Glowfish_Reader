# -*- coding: utf-8 -*-
from pathlib import Path


INSTALLER = Path(__file__).with_name("installer.iss")


def _source():
    return INSTALLER.read_text(encoding="utf-8")


def test_installer_preserves_stable_per_user_upgrade_identity():
    text = _source()

    assert "AppId={{8F3B2A10-7C4E-4D2A-9B6F-A1B2C3D4E5F6}" in text
    assert "PrivilegesRequired=lowest" in text
    assert "DefaultDirName={localappdata}\\Programs\\{#AppDisplayName}" in text
    assert "CloseApplications=yes" in text
    assert "RestartApplications=no" in text


def test_installer_accepts_external_source_and_output_directories():
    text = _source()

    assert "#ifndef SourceDir" in text
    assert 'Source: "{#SourceDir}\\*"' in text
    assert "#ifndef OutputDir" in text
    assert "OutputDir={#OutputDir}" in text


def test_installer_never_targets_user_data_for_removal():
    text = _source()
    assert "[UninstallDelete]" not in text
