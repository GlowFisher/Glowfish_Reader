"""Durable page-level checkpoints for long-running OCR jobs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1


class CheckpointMismatch(RuntimeError):
    """The checkpoint belongs to a different input or OCR configuration."""


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def source_fingerprint(images: Iterable[Path]) -> list[dict[str, Any]]:
    result = []
    for image in images:
        stat = image.stat()
        result.append(
            {
                "name": image.name,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return result


def config_fingerprint(config: Mapping[str, Any] | None) -> str:
    encoded = json.dumps(dict(config or {}), ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class OcrCheckpoint:
    def __init__(
        self,
        root: Path,
        images: Iterable[Path],
        *,
        requested_engine: str,
        config: Mapping[str, Any] | None = None,
        job_id: str | None = None,
        attempt: int = 1,
    ):
        self.root = Path(root).resolve()
        self.pages_dir = self.root / "pages"
        self.images_dir = self.root / "images"
        self.manifest_path = self.root / "manifest.json"
        self.images = [Path(image).resolve() for image in images]
        self.page_order = [image.stem for image in self.images]
        self._source = source_fingerprint(self.images)
        self.requested_engine = str(requested_engine)
        self.config_hash = config_fingerprint(config)
        self.job_id = str(job_id or "")
        self.attempt = max(1, int(attempt or 1))
        self._manifest = self._open_manifest()
        self._pages_cache = self._scan_pages()
        self._last_checkpoint_at = float(self._manifest.get("updated_at") or time.time())

    def _new_manifest(self) -> dict[str, Any]:
        now = time.time()
        return {
            "schema_version": SCHEMA_VERSION,
            "job_id": self.job_id,
            "requested_engine": self.requested_engine,
            "config_hash": self.config_hash,
            "source_fingerprint": self._source,
            "page_order": self.page_order,
            "status": "running",
            "attempt": self.attempt,
            "created_at": now,
            "updated_at": now,
            "failed_pages": {},
        }

    def _open_manifest(self) -> dict[str, Any]:
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.is_file():
            manifest = self._new_manifest()
            _atomic_json(self.manifest_path, manifest)
            return manifest
        manifest = _read_json(self.manifest_path)
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise CheckpointMismatch("unsupported OCR checkpoint schema")
        if manifest.get("source_fingerprint") != self._source:
            raise CheckpointMismatch("OCR checkpoint source fingerprint mismatch")
        if manifest.get("page_order") != self.page_order:
            raise CheckpointMismatch("OCR checkpoint page order mismatch")
        manifest["job_id"] = self.job_id or manifest.get("job_id", "")
        manifest["attempt"] = max(self.attempt, int(manifest.get("attempt") or 1))
        manifest["status"] = "running"
        manifest["updated_at"] = time.time()
        _atomic_json(self.manifest_path, manifest)
        return manifest

    def _page_path(self, page_id: str) -> Path:
        if page_id not in self.page_order:
            raise CheckpointMismatch(f"unknown checkpoint page: {page_id}")
        return self.pages_dir / f"{page_id}.json"

    def _scan_pages(self) -> dict[str, dict[str, Any]]:
        pages: dict[str, dict[str, Any]] = {}
        for page_id in self.page_order:
            path = self._page_path(page_id)
            if not path.is_file():
                continue
            try:
                page = _read_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(page, dict) and not page.get("failed"):
                pages[page_id] = page
        return pages

    def load_pages(self) -> dict[str, dict[str, Any]]:
        return dict(self._pages_cache)

    def record_success(
        self,
        page_id: str,
        page: Mapping[str, Any],
        *,
        engine: str,
        attempt: int,
    ) -> None:
        payload = dict(page)
        meta = dict(payload.get("ocr_meta") or {})
        meta.update(engine=str(engine), attempt=max(1, int(attempt or 1)))
        payload["ocr_meta"] = meta
        _atomic_json(self._page_path(page_id), payload)
        self._pages_cache[page_id] = payload
        failures = self._manifest.setdefault("failed_pages", {})
        had_failure = page_id in failures
        failures.pop(page_id, None)
        self._last_checkpoint_at = time.time()
        self._manifest.update(status="running", updated_at=self._last_checkpoint_at)
        if had_failure:
            _atomic_json(self.manifest_path, self._manifest)

    def record_failure(self, page_id: str, error: BaseException, *, engine: str, attempt: int) -> None:
        failures = self._manifest.setdefault("failed_pages", {})
        history = list(failures.get(page_id) or [])
        history.append(
            {
                "engine": str(engine),
                "attempt": max(1, int(attempt or 1)),
                "error": f"{type(error).__name__}: {error}"[:500],
                "at": time.time(),
            }
        )
        failures[page_id] = history
        self._manifest.update(status="running", updated_at=time.time())
        self._last_checkpoint_at = self._manifest["updated_at"]
        _atomic_json(self.manifest_path, self._manifest)

    def progress(self) -> dict[str, Any]:
        pages = self.load_pages()
        engines = Counter(
            str((page.get("ocr_meta") or {}).get("engine") or "unknown")
            for page in pages.values()
        )
        return {
            "done": len(pages),
            "total": len(self.page_order),
            "failed": sorted(self._manifest.get("failed_pages", {})),
            "last_checkpoint_at": self._last_checkpoint_at,
            "completed_by_engine": dict(engines),
        }

    def materialize(self, output_path: Path) -> dict[str, dict[str, Any]]:
        pages = self.load_pages()
        missing = [page_id for page_id in self.page_order if page_id not in pages]
        if missing:
            raise RuntimeError(f"OCR checkpoint is incomplete: {len(missing)} page(s) missing")
        output_path = Path(output_path).resolve()
        final_images = output_path.parent / "_img"
        final_images.mkdir(parents=True, exist_ok=True)
        ordered: dict[str, dict[str, Any]] = {}
        for page_id in self.page_order:
            page = dict(pages[page_id])
            image = page.get("image")
            if image:
                source = Path(image)
                if source.is_file():
                    target = final_images / source.name
                    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
                    shutil.copy2(source, temporary)
                    os.replace(temporary, target)
                    page["image"] = str(target)
            ordered[page_id] = page
        _atomic_json(output_path, ordered)
        self._manifest.update(status="complete", updated_at=time.time())
        _atomic_json(self.manifest_path, self._manifest)
        self._last_checkpoint_at = self._manifest["updated_at"]
        return ordered
