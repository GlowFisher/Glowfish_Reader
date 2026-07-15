# -*- coding: utf-8 -*-
"""Atomic staging and commit helpers used by the OCR single-flight manager."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path


def _load_valid(path, expected_pages):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("OCR output must be a JSON object")
    pages = [key for key in data if key != "_meta"]
    if expected_pages and len(pages) != expected_pages:
        raise ValueError(f"OCR page count mismatch: expected {expected_pages}, got {len(pages)}")
    return data


def _commit_images(job, data):
    staged_images = job.directory / "_img"
    final_images = job.output_path.parent / "_img"
    if not staged_images.is_dir():
        return
    final_images.mkdir(parents=True, exist_ok=True)
    for source in staged_images.iterdir():
        if not source.is_file():
            continue
        target = final_images / source.name
        temporary = target.with_name(f".{target.name}.{job.job_id}.tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    for page_id, page in data.items():
        if page_id == "_meta" or not isinstance(page, dict):
            continue
        image = page.get("image")
        if image:
            page["image"] = str(final_images / Path(image).name)


def _write_fsynced(path, data):
    temporary = Path(path).with_name(f".{Path(path).name}.{uuid.uuid4().hex}.tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def run_atomic(manager, *, ctx, image_dir, output_path, engine, config_hash,
               request_id, direct_runner, expected_pages):
    output_path = Path(output_path).resolve()

    def execute(job):
        job.progress("loading_model", percent=3)
        actual_engine = direct_runner(
            ctx, Path(image_dir), job.staged_output, engine, job=job)
        job.check_cancelled()
        data = _load_valid(job.staged_output, expected_pages)
        job.progress("committing", percent=95)
        _commit_images(job, data)
        _write_fsynced(job.staged_output, data)
        job.check_cancelled()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(job.staged_output, output_path)
        return actual_engine

    return manager.run(
        getattr(ctx, "uid", "local"), output_path, engine, config_hash,
        request_id or uuid.uuid4().hex, execute)
