# -*- coding: utf-8 -*-
"""Versioned, page-granular persistence for proofread documents."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Mapping


SCHEMA_VERSION = 2
_LOCKS_GUARD = threading.Lock()
_BATCH_LOCKS: Dict[str, threading.RLock] = {}


class DocumentError(RuntimeError):
    pass


class DocumentNotFoundError(DocumentError):
    pass


class DocumentConflictError(DocumentError):
    def __init__(self, current_revision: int):
        super().__init__(f"revision conflict; current revision is {current_revision}")
        self.current_revision = current_revision


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve()).casefold()
    with _LOCKS_GUARD:
        return _BATCH_LOCKS.setdefault(key, threading.RLock())


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".j-", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        finally:
            raise


def _page_key(page_id: str) -> str:
    return hashlib.sha256(page_id.encode("utf-8")).hexdigest()[:16]


def _page_summary(page: Mapping) -> dict:
    return {
        "page_id": str(page.get("page_id", "")),
        "image": page.get("image", ""),
        "width": page.get("width", 0),
        "height": page.get("height", 0),
    }


class DocumentRepository:
    """Owns migration and all reads/writes for one batch directory."""

    def __init__(self, batch_dir: Path | str):
        self.batch_dir = Path(batch_dir)
        self.proof_path = self.batch_dir / "proof.json"
        self.meta_path = self.batch_dir / "document.json"
        self.pages_dir = self.batch_dir / "pages"
        self._lock = _lock_for(self.batch_dir)
        self._page_locks: Dict[str, threading.Lock] = {}

    @contextmanager
    def _page_lock(self, page_id: str):
        with self._lock:
            lock = self._page_locks.setdefault(page_id, threading.Lock())
        with lock:
            yield

    def _read_json(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise DocumentNotFoundError(str(path)) from exc

    def ensure_migrated(self) -> dict:
        with self._lock:
            if self.meta_path.exists():
                return self._read_json(self.meta_path)
            if not self.proof_path.exists():
                raise DocumentNotFoundError(str(self.proof_path))
            legacy = self._read_json(self.proof_path)
            pages = legacy.get("pages")
            if not isinstance(pages, list):
                raise DocumentError("legacy proof has no pages array")
            generation = "m" + uuid.uuid4().hex[:8]
            staging = self.batch_dir / f".m-{generation[1:]}"
            generation_dir = staging / "pages" / generation
            try:
                generation_dir.mkdir(parents=True)
                descriptors = []
                expected_lines = 0
                for index, raw_page in enumerate(pages):
                    page = copy.deepcopy(raw_page)
                    page_id = str(page.get("page_id") or f"page-{index + 1}")
                    if any(p.get("page_id") == page_id for p in descriptors):
                        raise DocumentError(f"duplicate page id: {page_id}")
                    page["page_id"] = page_id
                    page["revision"] = int(page.get("revision", 0))
                    filename = f"{_page_key(page_id)}.json"
                    _atomic_json(generation_dir / filename, page)
                    expected_lines += len(page.get("lines", []))
                    descriptor = _page_summary(page)
                    descriptor.update({"revision": page["revision"], "file": f"pages/{generation}/{filename}"})
                    descriptors.append(descriptor)
                meta = {k: copy.deepcopy(v) for k, v in legacy.items() if k != "pages"}
                meta.update({
                    "schema_version": SCHEMA_VERSION,
                    "revision": int(legacy.get("revision", 0)),
                    "pages": descriptors,
                })
                _atomic_json(staging / "document.json", meta)
                # Validate the staged representation before it can become active.
                staged_meta = self._read_json(staging / "document.json")
                actual_lines = sum(len(self._read_json(staging / p["file"]).get("lines", [])) for p in staged_meta["pages"])
                if len(staged_meta["pages"]) != len(pages) or actual_lines != expected_lines:
                    raise DocumentError("migration consistency check failed")
                self.pages_dir.mkdir(parents=True, exist_ok=True)
                os.replace(generation_dir, self.pages_dir / generation)
                _fsync_dir(self.pages_dir)
                _atomic_json(self.meta_path, meta)  # activation point
                return meta
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    def _meta(self) -> dict:
        return self.ensure_migrated()

    def load_meta(self) -> dict:
        meta = copy.deepcopy(self._meta())
        for page in meta.get("pages", []):
            page.pop("file", None)
        return meta

    def _descriptor(self, meta: Mapping, page_id: str) -> dict:
        descriptor = next((p for p in meta.get("pages", []) if str(p.get("page_id")) == page_id), None)
        if descriptor is None:
            raise DocumentNotFoundError(f"page not found: {page_id}")
        return descriptor

    def load_page(self, page_id: str) -> dict:
        with self._lock:
            meta = self._meta()
            descriptor = self._descriptor(meta, page_id)
            page = self._read_json(self.batch_dir / descriptor["file"])
            return {"page": page, "revision": int(descriptor.get("revision", 0)),
                    "document_revision": int(meta.get("revision", 0))}

    def iter_pages(self) -> Iterator[dict]:
        with self._lock:
            meta = copy.deepcopy(self._meta())
        for descriptor in meta.get("pages", []):
            yield self._read_json(self.batch_dir / descriptor["file"])

    def load_full(self) -> dict:
        with self._lock:
            meta = copy.deepcopy(self._meta())
            pages = [self._read_json(self.batch_dir / p["file"]) for p in meta.get("pages", [])]
        for descriptor in meta.get("pages", []):
            descriptor.pop("file", None)
        meta["pages"] = pages
        meta.pop("schema_version", None)
        return meta

    def save_page(self, page_id: str, page: Mapping, base_revision: int) -> dict:
        page_id = str(page_id)
        with self._page_lock(page_id), self._lock:
            meta = copy.deepcopy(self._meta())
            descriptor = self._descriptor(meta, page_id)
            current = int(descriptor.get("revision", 0))
            if int(base_revision) != current:
                raise DocumentConflictError(current)
            new_revision = current + 1
            document_revision = int(meta.get("revision", 0)) + 1
            stored = copy.deepcopy(dict(page))
            stored["page_id"] = page_id
            stored["revision"] = new_revision
            generation = f"r{new_revision}-{uuid.uuid4().hex[:8]}"
            relative = f"pages/{generation}/{_page_key(page_id)}.json"
            _atomic_json(self.batch_dir / relative, stored)
            descriptor.update(_page_summary(stored))
            descriptor.update({"revision": new_revision, "file": relative})
            meta["revision"] = document_revision
            _atomic_json(self.meta_path, meta)
            return {"ok": True, "revision": new_revision, "document_revision": document_revision}

    def save_meta(self, changes: Mapping, base_revision: int | None = None) -> dict:
        forbidden = {"pages", "schema_version"}
        with self._lock:
            meta = copy.deepcopy(self._meta())
            current = int(meta.get("revision", 0))
            if base_revision is not None and int(base_revision) != current:
                raise DocumentConflictError(current)
            for key, value in changes.items():
                if key not in forbidden:
                    meta[key] = copy.deepcopy(value)
            meta["revision"] = current + 1
            _atomic_json(self.meta_path, meta)
            return {"ok": True, "revision": meta["revision"]}

    def replace_full(self, proof: Mapping, checkpoint: bool = False) -> dict:
        """Compatibility/import path. New UI code must use save_page/save_meta."""
        with self._lock:
            pages = copy.deepcopy(list(proof.get("pages", [])))
            generation = "g" + uuid.uuid4().hex[:8]
            descriptors = []
            for index, page in enumerate(pages):
                page_id = str(page.get("page_id") or f"page-{index + 1}")
                page["page_id"] = page_id
                page["revision"] = int(page.get("revision", 0))
                relative = f"pages/{generation}/{_page_key(page_id)}.json"
                _atomic_json(self.batch_dir / relative, page)
                descriptor = _page_summary(page)
                descriptor.update({"revision": page["revision"], "file": relative})
                descriptors.append(descriptor)
            old_revision = int(self._meta().get("revision", 0)) if self.meta_path.exists() or self.proof_path.exists() else 0
            meta = {k: copy.deepcopy(v) for k, v in proof.items() if k != "pages"}
            meta.update({"schema_version": SCHEMA_VERSION, "revision": old_revision + 1, "pages": descriptors})
            _atomic_json(self.meta_path, meta)
            if checkpoint:
                _atomic_json(self.proof_path, self.load_full())
            return self.load_meta()

    def checkpoint(self) -> dict:
        with self._lock:
            proof = self.load_full()
            _atomic_json(self.proof_path, proof)
            return {"ok": True, "revision": int(self._meta().get("revision", 0))}


def repository_for_proof(proof_path: Path | str) -> DocumentRepository:
    return DocumentRepository(Path(proof_path).parent)
