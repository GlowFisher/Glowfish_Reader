# -*- coding: utf-8 -*-
"""导出记忆上次目录：export_last_dir 须在默认设置白名单内，才能随 /api/settings 持久化。"""
import settings_store


def test_export_last_dir_in_defaults():
    assert "export_last_dir" in settings_store.DEFAULT_SETTINGS
    assert settings_store.DEFAULT_SETTINGS["export_last_dir"] == ""
