import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import content_api
import ocr_recovery


def _ctx(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    return SimpleNamespace(uid="local", work=work)


def _record(ctx, tmp_path, batch="book"):
    upload = tmp_path / f"{batch}.pdf"
    upload.write_bytes(b"pdf")
    batch_dir = ctx.work / batch
    (batch_dir / "_src").mkdir(parents=True)
    (batch_dir / "_src" / "p001.png").write_bytes(b"image")
    record = ocr_recovery.create_record(
        batch_dir,
        batch=batch,
        source="Book",
        engine="ppocrv6_onnx_high",
        request_id="request-1",
        source_items=[{"path": str(upload), "type": "pdf"}],
        total=1,
        punct_backend="off",
    )
    return batch_dir, record


def test_recoverable_route_returns_sanitized_jobs(tmp_path):
    ctx = _ctx(tmp_path)
    _, record = _record(ctx, tmp_path)

    response = content_api.recoverable_import_jobs(ctx=ctx)

    assert response["jobs"][0]["job_id"] == record["job_id"]
    assert "path" not in response["jobs"][0]


def test_resume_runs_in_background_and_cleans_checkpoint_on_success(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    progress = []

    class Task:
        task_id = "task-1"

        def progress(self, **payload):
            progress.append(payload)

    def submit(_uid, _root, _kind, _batches, _total, runner):
        task = Task()
        runner(task)
        return task

    monkeypatch.setattr(content_api.TASK_MANAGER, "submit", submit)
    monkeypatch.setattr(
        content_api,
        "_load_proof",
        lambda *_args, **_kwargs: {"batch": "book", "pages": [], "script": "s"},
    )
    monkeypatch.setattr(content_api, "_finish_progress", lambda _ctx: None)

    def save(proof, path):
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(proof, stream)

    monkeypatch.setattr(content_api.M, "save_proof", save)

    response = content_api.resume_import_job(record["job_id"], ctx=ctx)

    assert response["task_id"] == "task-1"
    assert (batch_dir / "proof.json").is_file()
    assert not ocr_recovery.checkpoint_dir(batch_dir).exists()
    assert progress[-1]["done"] == 1
    assert record["job_id"] not in content_api._RECOVERY_RUNNING


def test_discard_removes_only_the_selected_incomplete_batch(tmp_path):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    other = ctx.work / "other"
    other.mkdir()

    response = content_api.discard_import_job(record["job_id"], ctx=ctx)

    assert response["ok"]
    assert not batch_dir.exists()
    assert other.is_dir()


@pytest.mark.parametrize("action", ["resume", "discard"])
def test_active_batch_cannot_be_resumed_or_discarded(tmp_path, monkeypatch, action):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    monkeypatch.setattr(
        content_api.ocr_job_manager.JOB_MANAGER,
        "status",
        lambda *_args, **_kwargs: {"batch": batch_dir.name, "phase": "ocr"},
    )

    with pytest.raises(HTTPException) as exc_info:
        if action == "resume":
            content_api.resume_import_job(record["job_id"], ctx=ctx)
        else:
            content_api.discard_import_job(record["job_id"], ctx=ctx)

    assert exc_info.value.status_code == 409
    assert batch_dir.is_dir()
