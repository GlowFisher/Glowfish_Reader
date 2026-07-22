from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src"


def test_recoverable_ocr_api_and_startup_prompt_are_wired():
    api = (ROOT / "api" / "ocr-api.js").read_text(encoding="utf-8")
    app = (ROOT / "app.js").read_text(encoding="utf-8")

    assert "/api/import_jobs/recoverable" in api
    assert "/api/import_jobs/" + "$" + "{encodeURIComponent(jobId)}/resume" in api
    assert 'method: "DELETE"' in api
    assert "async function gfCheckRecoverableImports()" in app
    assert "GlowfishApi.ocr.resume(job.job_id)" in app
    assert "GlowfishApi.ocr.discard(job.job_id)" in app
    assert "setTimeout(gfCheckRecoverableImports, 250)" in app


def test_recovery_progress_accepts_page_ids_and_engine_breakdown():
    app = (ROOT / "app.js").read_text(encoding="utf-8")

    assert 'typeof f === "string"' in app
    assert "ppocrv6_onnx_high" in app
    assert "startImportProgress();" in app
    assert "gfWatchDocumentTask(started.task_id)" in app
