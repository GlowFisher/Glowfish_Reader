# -*- coding: utf-8 -*-
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import notice_api


def test_notice_url_uses_explicit_override(monkeypatch):
    monkeypatch.setenv("SHUPAI_NOTICE_URL", "https://example.test/custom.json")
    monkeypatch.setenv("SHUPAI_LICENSE_SERVER", "https://license.example.test")

    assert notice_api.notice_url() == "https://example.test/custom.json"


def test_notice_url_derives_from_license_server(monkeypatch):
    monkeypatch.delenv("SHUPAI_NOTICE_URL", raising=False)
    monkeypatch.setenv("SHUPAI_LICENSE_SERVER", "https://license.example.test/")

    assert notice_api.notice_url() == "https://license.example.test/notices.json"


def test_normalize_notice_accepts_minimal_notice():
    notice = notice_api.normalize_notice({
        "id": "n1",
        "title": "维护通知",
        "body": "今晚维护。",
    })

    assert notice == {
        "id": "n1",
        "title": "维护通知",
        "body": "今晚维护。",
        "level": "info",
        "starts_at": "",
        "ends_at": "",
        "published_at": "",
        "force_popup": False,
        "link_text": "",
        "link_url": "",
    }


def test_filter_notices_hides_future_and_expired_notices():
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

    notices = notice_api.filter_notices([
        {"id": "active", "title": "A", "body": "ok", "starts_at": "2026-07-06T00:00:00Z", "ends_at": "2026-07-07T00:00:00Z"},
        {"id": "future", "title": "F", "body": "no", "starts_at": "2026-07-07T00:00:00Z"},
        {"id": "expired", "title": "E", "body": "no", "ends_at": "2026-07-06T00:00:00Z"},
    ], current_version="1.0.4", now=now)

    assert [n["id"] for n in notices] == ["active"]


def test_filter_notices_respects_version_bounds():
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

    notices = notice_api.filter_notices([
        {"id": "visible", "title": "A", "body": "ok", "min_version": "1.0.0", "max_version": "1.0.4"},
        {"id": "too-new", "title": "B", "body": "no", "min_version": "1.0.5"},
        {"id": "too-old", "title": "C", "body": "no", "max_version": "1.0.3"},
    ], current_version="1.0.4", now=now)

    assert [n["id"] for n in notices] == ["visible"]


def test_filter_notices_skips_bad_entries_but_keeps_valid_ones():
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

    notices = notice_api.filter_notices([
        {"id": "valid", "title": "A", "body": "ok"},
        {"id": "missing-body", "title": "B"},
        {"id": "bad-date", "title": "C", "body": "no", "starts_at": "not-a-date"},
        "not an object",
    ], current_version="1.0.4", now=now)

    assert [n["id"] for n in notices] == ["valid"]


def test_get_notices_soft_fails_on_fetch_error(monkeypatch):
    monkeypatch.setattr(notice_api.updater, "current_version", lambda: "1.0.4")
    monkeypatch.setattr(notice_api, "fetch_remote_notices", lambda: None)
    notice_api.clear_cache()

    assert notice_api.get_notices(use_cache=False) == {
        "ok": False,
        "current": "1.0.4",
        "notices": [],
    }


def test_get_notices_filters_remote_document(monkeypatch):
    monkeypatch.setattr(notice_api.updater, "current_version", lambda: "1.0.4")
    monkeypatch.setattr(notice_api, "fetch_remote_notices", lambda: {
        "schema": 1,
        "notices": [
            {"id": "visible", "title": "A", "body": "ok"},
            {"id": "future", "title": "F", "body": "no", "starts_at": "2999-01-01T00:00:00Z"},
        ],
    })
    notice_api.clear_cache()

    result = notice_api.get_notices(use_cache=False)

    assert result["ok"] is True
    assert result["current"] == "1.0.4"
    assert [n["id"] for n in result["notices"]] == ["visible"]
