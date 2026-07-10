# -*- coding: utf-8 -*-
"""Announcement feed API for the local GlowFish backend.

The remote source is a hosted notices.json file. Failures are intentionally soft:
announcements must never block reading, login, activation, or updates.
"""
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import APIRouter

import updater

router = APIRouter()

_DEFAULT_SERVER = "https://license.glowfishreader.com"
_TIMEOUT = 6
_CACHE_SECONDS = 600
_LEVELS = {"info", "warning", "critical"}
_cache: dict[str, Any] = {"expires_at": 0.0, "result": None}


def clear_cache():
    _cache["expires_at"] = 0.0
    _cache["result"] = None


def notice_url() -> str:
    url = os.environ.get("SHUPAI_NOTICE_URL")
    if url:
        return url
    base = os.environ.get("SHUPAI_LICENSE_SERVER") or _DEFAULT_SERVER
    return base.rstrip("/") + "/notices.json"


def _string(value: Any) -> str:
    return str(value or "").strip()


def normalize_notice(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    notice_id = _string(raw.get("id"))
    title = _string(raw.get("title"))
    body = _string(raw.get("body"))
    if not notice_id or not title or not body:
        return None
    level = _string(raw.get("level") or "info").lower()
    if level not in _LEVELS:
        level = "info"
    return {
        "id": notice_id,
        "title": title,
        "body": body,
        "level": level,
        "starts_at": _string(raw.get("starts_at")),
        "ends_at": _string(raw.get("ends_at")),
        "published_at": _string(raw.get("published_at")),
        "force_popup": bool(raw.get("force_popup")),
        "link_text": _string(raw.get("link_text")),
        "link_url": _string(raw.get("link_url")),
    }


def _parse_dt(value: str) -> datetime | None:
    value = _string(value)
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _version_visible(notice: dict[str, Any], current_version: str) -> bool:
    cur = updater.parse_version(current_version)
    min_version = _string(notice.get("min_version"))
    max_version = _string(notice.get("max_version"))
    if min_version and cur < updater.parse_version(min_version):
        return False
    if max_version and cur > updater.parse_version(max_version):
        return False
    return True


def filter_notices(raw_notices: Any, current_version: str, now: datetime | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw_notices, list):
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    visible = []
    for raw in raw_notices:
        notice = normalize_notice(raw)
        if not notice:
            continue
        notice["min_version"] = _string(raw.get("min_version")) if isinstance(raw, dict) else ""
        notice["max_version"] = _string(raw.get("max_version")) if isinstance(raw, dict) else ""
        try:
            starts_at = _parse_dt(notice.get("starts_at", ""))
            ends_at = _parse_dt(notice.get("ends_at", ""))
            published_at = _parse_dt(notice.get("published_at", ""))
        except (TypeError, ValueError):
            continue
        if starts_at and starts_at > now:
            continue
        if ends_at and ends_at <= now:
            continue
        if not _version_visible(notice, current_version):
            continue
        notice["_sort_at"] = published_at or starts_at or datetime.min.replace(tzinfo=timezone.utc)
        visible.append(notice)

    visible.sort(key=lambda item: item["_sort_at"], reverse=True)
    for notice in visible:
        notice.pop("_sort_at", None)
        notice.pop("min_version", None)
        notice.pop("max_version", None)
    return visible


def fetch_remote_notices() -> dict[str, Any] | None:
    try:
        response = requests.get(notice_url(), timeout=_TIMEOUT)
        if response.status_code != 200:
            return None
        data = response.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def get_notices(use_cache: bool = True) -> dict[str, Any]:
    now_ts = time.time()
    if use_cache and _cache["result"] is not None and now_ts < float(_cache["expires_at"]):
        return dict(_cache["result"])

    current = updater.current_version()
    remote = fetch_remote_notices()
    if not isinstance(remote, dict):
        result = {"ok": False, "current": current, "notices": []}
    else:
        result = {
            "ok": True,
            "current": current,
            "notices": filter_notices(remote.get("notices"), current),
        }
    _cache["result"] = result
    _cache["expires_at"] = now_ts + _CACHE_SECONDS
    return dict(result)


@router.get("/api/notices")
def api_notices():
    return get_notices()
