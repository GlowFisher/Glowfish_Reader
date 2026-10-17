"""Persistence and discovery for interrupted OCR imports."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


CHECKPOINT_DIR = "_ocr_checkpoint"
IMPORT_RECORD = "import.json"
MANIFEST = "manifest.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def source_fingerprint(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        path = Path(item["path"])
        stat = path.stat()
        result.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "type": str(item.get("type") or "image"),
                "page": int(item.get("page") or 0),
            }
        )
    return result


def checkpoint_dir(batch_dir: Path) -> Path:
    return Path(batch_dir) / CHECKPOINT_DIR


def create_record(
    batch_dir: Path,
    *,
    batch: str,
    source: str,
    engine: str,
    request_id: str,
    source_items: Iterable[dict[str, Any]],
    total: int,
    punct_backend: str = "local",
    default_script: str = "s",
) -> dict[str, Any]:
    directory = checkpoint_dir(batch_dir)
    existing = _read_json(directory / IMPORT_RECORD) or {}
    now = time.time()
    record = {
        "schema_version": 1,
        "job_id": existing.get("job_id") or uuid.uuid4().hex,
        "batch": str(batch),
        "source": str(source),
        "engine": str(engine),
        "request_id": str(request_id),
        "source_fingerprint": source_fingerprint(source_items),
        "total": max(0, int(total)),
        "punct_backend": str(punct_backend or "off"),
        "default_script": str(default_script or "s"),
        "status": "recoverable",
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }
    _atomic_json(directory / IMPORT_RECORD, record)
    return record


def load_record(batch_dir: Path) -> dict[str, Any] | None:
    return _read_json(checkpoint_dir(batch_dir) / IMPORT_RECORD)


def mark_status(batch_dir: Path, status: str, **extra) -> dict[str, Any] | None:
    path = checkpoint_dir(batch_dir) / IMPORT_RECORD
    record = _read_json(path)
    if record is None:
        return None
    record.update(status=str(status), updated_at=time.time())
    record.update(extra)
    _atomic_json(path, record)
    return record


def _checkpoint_stats(directory: Path) -> tuple[int, list[str], dict[str, int], float]:
    pages_dir = directory / "pages"
    completed = 0
    engines: Counter[str] = Counter()
    updated_at = directory.stat().st_mtime if directory.exists() else 0.0
    if pages_dir.is_dir():
        for path in pages_dir.glob("*.json"):
            page = _read_json(path)
            if page is None or page.get("failed"):
                continue
            completed += 1
            engine = str((page.get("ocr_meta") or {}).get("engine") or "unknown")
            engines[engine] += 1
            updated_at = max(updated_at, path.stat().st_mtime)
    manifest = _read_json(directory / MANIFEST) or {}
    failed_pages = sorted((manifest.get("failed_pages") or {}).keys())
    updated_at = max(updated_at, float(manifest.get("updated_at") or 0))
    return completed, failed_pages, dict(engines), updated_at


def summarize(batch_dir: Path, record: dict[str, Any] | None = None) -> dict[str, Any] | None:
    batch_dir = Path(batch_dir)
    record = record or load_record(batch_dir)
    if record is None or (batch_dir / "proof.json").is_file():
        return None
    completed, failed_pages, engines, checkpoint_updated = _checkpoint_stats(
        checkpoint_dir(batch_dir)
    )
    return {
        "job_id": str(record.get("job_id") or ""),
        "batch": batch_dir.name,
        "source": str(record.get("source") or batch_dir.name),
        "completed": completed,
        "total": max(completed, int(record.get("total") or 0)),
        "engine": str(record.get("engine") or ""),
        "updated_at": max(float(record.get("updated_at") or 0), checkpoint_updated),
        "failed_pages": failed_pages,
        "completed_by_engine": engines,
        "status": str(record.get("status") or "recoverable"),
    }


def discover(work: Path) -> list[dict[str, Any]]:
    work = Path(work)
    result = []
    if not work.is_dir():
        return result
    for batch_dir in work.iterdir():
        if not batch_dir.is_dir() or batch_dir.name.startswith(("_", ".")):
            continue
        summary = summarize(batch_dir)
        if summary and summary["job_id"]:
            result.append(summary)
    result.sort(key=lambda item: item["updated_at"], reverse=True)
    return result


def find(work: Path, job_id: str) -> tuple[Path, dict[str, Any]] | None:
    wanted = str(job_id)
    for summary in discover(work):
        if summary["job_id"] != wanted:
            continue
        batch_dir = Path(work) / summary["batch"]
        record = load_record(batch_dir)
        if record is not None:
            return batch_dir, record
    return None
