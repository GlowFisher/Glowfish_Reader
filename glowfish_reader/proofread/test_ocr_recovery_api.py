import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import content_api
import ocr_recovery
from document_repository import repository_for_proof
from userctx import Ctx

def _ctx(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    ctx = SimpleNamespace(uid="local", work=work)
    ctx.reg = Ctx.reg.__get__(ctx, type(ctx))
    return ctx



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


def _checkpoint_page(batch_dir, page_id="p001", text="page text", image_value=None):
    image = batch_dir / "_ocr_checkpoint" / "images" / f"{page_id}.jpg"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"normalized image")
    pages = batch_dir / "_ocr_checkpoint" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    (pages / f"{page_id}.json").write_text(
        json.dumps(
            {
                "image": image_value or str(image),
                "width": 80,
                "height": 60,
                "lines": [{"text": text, "box": [0, 0, 10, 20], "score": 0.99}],
                "ocr_meta": {"engine": "ppocrv6_onnx_high"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = batch_dir / "_ocr_checkpoint" / "manifest.json"
    manifest.write_text(
        json.dumps({"page_order": [page_id], "failed_pages": {}, "updated_at": 1}),
        encoding="utf-8",
    )


def test_recoverable_route_returns_sanitized_jobs(tmp_path):
    ctx = _ctx(tmp_path)
    _, record = _record(ctx, tmp_path)

    response = content_api.recoverable_import_jobs(ctx=ctx)

    assert response["jobs"][0]["job_id"] == record["job_id"]
    assert "path" not in response["jobs"][0]


def test_publish_checkpoint_page_creates_partial_document_without_proof_json(tmp_path):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    _checkpoint_page(batch_dir)

    result = content_api._publish_checkpoint_pages(ctx, batch_dir, record)

    assert result["published"] == 1
    assert (batch_dir / "document.json").is_file()
    assert not (batch_dir / "proof.json").exists()
    assert result["document_meta"]["pages"][0]["page_id"] == "p001"
    assert (batch_dir / "_img" / "p001.jpg").is_file()


def test_partial_document_opens_through_paged_api_without_proof_json(tmp_path):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    _checkpoint_page(batch_dir, text="visible page")
    content_api._publish_checkpoint_pages(ctx, batch_dir, record)

    meta = content_api.document_meta(batch_dir.name, ctx=ctx)
    page = content_api.document_page(batch_dir.name, "p001", ctx=ctx)

    assert not (batch_dir / "proof.json").exists()
    assert meta["pages"][0]["page_id"] == "p001"
    assert page["page"]["lines"][0]["text"] == "visible page"

def test_publish_checkpoint_page_copies_relative_checkpoint_image(tmp_path):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    _checkpoint_page(batch_dir, image_value="images/p001.jpg")

    result = content_api._publish_checkpoint_pages(ctx, batch_dir, record)

    assert result["published"] == 1
    assert (batch_dir / "_img" / "p001.jpg").read_bytes() == b"normalized image"

def test_publish_checkpoint_pages_is_idempotent_and_preserves_edited_page(tmp_path):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    _checkpoint_page(batch_dir, text="first text")
    first = content_api._publish_checkpoint_pages(ctx, batch_dir, record)
    repo = repository_for_proof(batch_dir / "proof.json")
    page_id = first["document_meta"]["pages"][0]["page_id"]
    page = repo.load_page(page_id)["page"]
    page["lines"][0]["text"] = "edited text"
    repo.save_page(page_id, page, page["revision"])

    _checkpoint_page(batch_dir, text="new OCR text")
    second = content_api._publish_checkpoint_pages(ctx, batch_dir, record)

    assert second["published"] == 1
    saved = repo.load_page(page_id)["page"]
    assert saved["lines"][0]["text"] == "edited text"


def test_import_progress_publishes_completed_checkpoint_pages(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    batch_dir, _record_value = _record(ctx, tmp_path)
    _checkpoint_page(batch_dir)
    monkeypatch.setattr(
        content_api.ocr_job_manager.JOB_MANAGER,
        "status",
        lambda *_args, **_kwargs: {"batch": batch_dir.name, "phase": "ocr", "done": 1, "total": 1},
    )

    response = content_api.import_progress(ctx=ctx)

    assert response["published"] == 1
    assert response["document_meta"]["batch"] == batch_dir.name
    assert response["document_meta"]["pages"][0]["page_id"] == "p001"


def test_recoverable_jobs_include_partial_document_meta(tmp_path):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    _checkpoint_page(batch_dir)
    content_api._publish_checkpoint_pages(ctx, batch_dir, record)

    response = content_api.recoverable_import_jobs(ctx=ctx)

    assert response["jobs"][0]["published"] == 1
    assert response["jobs"][0]["document_meta"]["batch"] == batch_dir.name


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


def test_load_proof_finalizes_checkpoint_without_overwriting_edited_page(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    _checkpoint_page(batch_dir, text="first text")
    content_api._publish_checkpoint_pages(ctx, batch_dir, record)
    repo = repository_for_proof(batch_dir / "proof.json")
    page = repo.load_page("p001")["page"]
    page["lines"][0]["text"] = "edited text"
    repo.save_page("p001", page, page["revision"])

    _checkpoint_page(batch_dir, text="new OCR text")
    monkeypatch.setattr(content_api, "_begin_ocr_progress", lambda *_args, **_kwargs: None)

    def ensure_recog(_ctx, _image_dir, recog_path, _engine, request_id=None):
        recog_path.write_text("{}", encoding="utf-8")
        return "ppocrv6_onnx_high"

    monkeypatch.setattr(content_api, "_ensure_recog", ensure_recog)

    content_api._load_proof(
        ctx,
        batch_dir.name,
        batch_dir / "_src",
        "Book",
        engine="ppocrv6_onnx_high",
    )

    assert (batch_dir / "proof.json").is_file()
    assert repo.load_meta()["ocr_status"] == "complete"
    saved = repo.load_page("p001")["page"]
    assert saved["lines"][0]["text"] == "edited text"
    proof = json.loads((batch_dir / "proof.json").read_text(encoding="utf-8"))
    assert proof["pages"][0]["lines"][0]["text"] == "edited text"

def test_discard_removes_only_the_selected_incomplete_batch(tmp_path):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    other = ctx.work / "other"
    other.mkdir()

    response = content_api.discard_import_job(record["job_id"], ctx=ctx)

    assert response["ok"]
    assert not batch_dir.exists()
    assert other.is_dir()


def test_discard_recovery_keeps_published_partial_document(tmp_path):
    ctx = _ctx(tmp_path)
    batch_dir, record = _record(ctx, tmp_path)
    _checkpoint_page(batch_dir)
    content_api._publish_checkpoint_pages(ctx, batch_dir, record)

    response = content_api.discard_import_job(record["job_id"], ctx=ctx)

    assert response["ok"]
    assert response["kept_document"] is True
    assert batch_dir.is_dir()
    assert not ocr_recovery.checkpoint_dir(batch_dir).exists()
    assert (batch_dir / "proof.json").is_file()
    proof = json.loads((batch_dir / "proof.json").read_text(encoding="utf-8"))
    assert proof["ocr_status"] == "stopped"
    assert repository_for_proof(batch_dir / "proof.json").load_meta()["ocr_status"] == "stopped"


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
