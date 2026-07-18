# -*- coding: utf-8 -*-
"""Internal helper."""
import io
import json
import hashlib
import atexit
import logging
import os
import uuid
import shutil
import secrets
import threading
import subprocess
import anyio
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse, Response

import proof_model as M
import ingest
import engines
import safefs
import recognize_ppocrv6
import ocr_job_manager
import windows_process
import ocr_atomic
import recognize_ppocrv6_onnx
import ocr_rescue
import ocr_quality
from document_repository import DocumentConflictError, DocumentError, DocumentNotFoundError, repository_for_proof
from document_task_manager import TASK_MANAGER
import subprocess_env
from settings_store import load_settings
from userctx import Ctx, ctx_dep

router = APIRouter()

_WORKER_CIRCUIT_OPEN = False
_LOG = logging.getLogger("glowfish.ocr")
# comment
_WORKER_IDLE_TIMER = None
# comment
_WORKER = None
_WORKER_LOCK = threading.Lock()
_CUR_ENGINE = {"name": None}
_OCR_ENGINE_RUNNER = None


def configure_ocr_engine_runner(runner=None):
    """Install an optional single-engine runner and return the previous runner.

    Returning ``False`` or raising delegates the same engine attempt to the
    preserved legacy implementation.
    """
    global _OCR_ENGINE_RUNNER
    if runner is not None and not callable(runner):
        raise TypeError("OCR engine runner must be callable or None")
    previous, _OCR_ENGINE_RUNNER = _OCR_ENGINE_RUNNER, runner
    return previous

_UP_EXT = (".jpg", ".jpeg", ".png", ".pdf")     # 娑撳﹣绱堕惂钘夋倳閸?


def _clean_env():
    return subprocess_env.clean_subprocess_env()


# 常驻 worker 的引擎：满血 ONNX + 轻量 ONNX（同一进程换 config 即可）+ Paddle 官方档。
_RESIDENT_ENGINES = {engines.ONNX_HIGH_ENGINE, engines.OFFICIAL_ENGINE, engines.LIGHTWEIGHT_ENGINE}
_ONNX_ENGINES = {engines.ONNX_HIGH_ENGINE, engines.LIGHTWEIGHT_ENGINE}


def _worker_for(eng, prefix, params):
    """Internal helper."""
    global _WORKER, _WORKER_CIRCUIT_OPEN, _WORKER_IDLE_TIMER
    if eng not in _RESIDENT_ENGINES:
        return None
    if _WORKER_CIRCUIT_OPEN:
        return None
    params = dict(params or {})
    model_type = params.get("model_type", eng)
    config_key = json.dumps(params, ensure_ascii=False, sort_keys=True)
    with _WORKER_LOCK:
        if _WORKER_IDLE_TIMER is not None:
            _WORKER_IDLE_TIMER.cancel()
            _WORKER_IDLE_TIMER = None
        if (_WORKER is not None and _WORKER.alive()
                and getattr(_WORKER, "eng", None) == eng
                and _WORKER.model_type == model_type
                and getattr(_WORKER, "config_key", None) == config_key):
            return _WORKER
        if _WORKER is not None:                  # 瀵洘鎼?濡€崇€峰锝呭綁娴滃棙鍨ㄥ鍙夘劥 閳?閺€鑸靛竴闁插秷鎹?
            _WORKER.close()
            _WORKER = None
        worker_cls = (recognize_ppocrv6_onnx.OcrWorker if eng in _ONNX_ENGINES
                      else recognize_ppocrv6.OcrWorker)
        for attempt in range(2):
            w = None
            try:
                w = worker_cls(prefix, env=_clean_env(), model_type=model_type, config=params)
                w.eng = eng
                w.config_key = config_key
                w.start()
                _WORKER = w
                _LOG.info("Worker ready engine=%s pid=%s attempt=%s", eng, getattr(w, "pid", None), attempt + 1)
                return _WORKER
            except Exception:
                _LOG.exception("Worker startup failed engine=%s attempt=%s", eng, attempt + 1)
                if w is not None:
                    w.close()
        _WORKER_CIRCUIT_OPEN = True
        return None


def prewarm(engine: str = None):
    eng = engines.engine_name(engine)
    runner = _OCR_ENGINE_RUNNER
    if runner is not None and hasattr(runner, "prewarm"):
        try:
            if runner.prewarm(eng):
                _CUR_ENGINE["name"] = eng
                return True
        except Exception:
            _LOG.exception("Configured OCR runner prewarm failed engine=%s; using legacy runtime", eng)
    try:
        eng2, prefix, params = engines.resolve_engine(engine)
    except Exception:
        return False
    _CUR_ENGINE["name"] = eng2
    return _worker_for(eng2, prefix, params) is not None


def _schedule_worker_idle_close(worker):
    global _WORKER, _WORKER_IDLE_TIMER
    try:
        ttl = float(os.environ.get("SHUPAI_OCR_IDLE_TTL", "180"))
    except ValueError:
        ttl = 180.0
    if ttl <= 0:
        return

    def close_if_idle():
        global _WORKER, _WORKER_IDLE_TIMER
        with _WORKER_LOCK:
            if _WORKER is worker:
                worker.close()
                _WORKER = None
                _LOG.info("OCR worker released after %.1fs idle", ttl)
            _WORKER_IDLE_TIMER = None

    _WORKER_IDLE_TIMER = threading.Timer(ttl, close_if_idle)
    _WORKER_IDLE_TIMER.daemon = True
    _WORKER_IDLE_TIMER.start()


@atexit.register
def _close_worker():
    global _WORKER, _WORKER_IDLE_TIMER
    if _WORKER is not None:
        try:
            _WORKER.close()
        except Exception:
            pass
        _WORKER = None
    if _WORKER_IDLE_TIMER is not None:
        _WORKER_IDLE_TIMER.cancel()
        _WORKER_IDLE_TIMER = None


def shutdown_ocr():
    """Stop accepting OCR and remove every registered child process."""
    ocr_job_manager.JOB_MANAGER.cancel_all()
    _close_worker()
    windows_process.shutdown_all()


def _run_engine_one_shot(ctx: Ctx, image_dir: Path, recog_path: Path, engine: str, job=None):
    """Start exactly one short-lived OCR process; never create another resident worker."""
    eng2, prefix, params = engines.resolve_engine(engine)
    _CUR_ENGINE["name"] = eng2
    progress_path = job.progress_path if job is not None else ctx.progress_path
    job_id = job.job_id if job is not None else None
    if job is not None:
        job.check_cancelled()
    cmd = prefix + ["--images", str(image_dir), "--out", str(recog_path),
                    "--progress", str(progress_path)]
    if params:
        cmd += ["--config", json.dumps(params, ensure_ascii=False)]
    _LOG.warning("One-shot fallback started engine=%s job_id=%s", eng2, job_id)
    result = windows_process.run(
        cmd, purpose="fallback", job_id=job_id, env=_clean_env(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0 or not recog_path.exists():
        raise RuntimeError(
            f"Recognition failed (engine {eng2}):\n{result.stdout}\n{result.stderr}"
        )
    _stamp_recog_meta(recog_path, eng2)


def _run_engine_legacy(ctx: Ctx, image_dir: Path, recog_path: Path, engine: str, job=None):
    """Explicit rollback runtime: one legacy resident attempt, then one one-shot."""
    eng2, prefix, params = engines.resolve_engine(engine)
    _CUR_ENGINE["name"] = eng2
    progress_path = job.progress_path if job is not None else ctx.progress_path
    job_id = job.job_id if job is not None else None
    if job is not None:
        job.check_cancelled()
    worker = _worker_for(eng2, prefix, params)
    if worker is not None:
        try:
            try:
                worker.submit(image_dir, recog_path, progress_path, params, job_id=job_id)
            except TypeError:
                worker.submit(image_dir, recog_path, progress_path, params)
            if recog_path.exists():
                _stamp_recog_meta(recog_path, eng2)
                _schedule_worker_idle_close(worker)
                return
        except Exception:
            _LOG.exception("Resident worker failed engine=%s job_id=%s", eng2, job_id)
    return _run_engine_one_shot(ctx, image_dir, recog_path, engine, job=job)

def _record_runner_fallback(runner, *, engine, success, error=None):
    observer = getattr(runner, "record_fallback", None)
    if callable(observer):
        observer(engine=engine, success=success, error=error)


def _run_engine(ctx: Ctx, image_dir: Path, recog_path: Path, engine: str, job=None):
    """Run one engine attempt through an injected port with legacy fallback."""
    runner = _OCR_ENGINE_RUNNER
    fallback_reason = None
    if runner is not None:
        try:
            handled = runner(
                ctx=ctx,
                image_dir=image_dir,
                recog_path=recog_path,
                engine=engine,
                job=job,
            )
            if handled is not False:
                if not recog_path.exists():
                    raise RuntimeError("configured OCR runner produced no output")
                return
            _LOG.info("Configured OCR runner declined engine=%s; using legacy runtime", engine)
            fallback_reason = RuntimeError("configured OCR runner declined")
        except Exception as exc:
            if getattr(exc, "error_type", None) == "ocr_input_unavailable":
                _LOG.warning("OCR input unavailable engine=%s; fallback suppressed", engine)
                raise
            fallback_reason = exc
            _LOG.exception("Configured OCR runner failed engine=%s; using one-shot fallback", engine)
        try:
            recog_path.unlink(missing_ok=True)
        except OSError:
            _LOG.warning("Could not discard injected OCR output before legacy fallback: %s", recog_path)
    try:
        result = _run_engine_one_shot(ctx, image_dir, recog_path, engine, job=job)
    except Exception as exc:
        if runner is not None and fallback_reason is not None:
            _record_runner_fallback(runner, engine=engine, success=False, error=exc)
        raise
    if runner is not None and fallback_reason is not None:
        _record_runner_fallback(runner, engine=engine, success=True, error=fallback_reason)
    return result



def _engine_config(eng: str):
    name = engines.engine_name(eng)
    params = dict((engines.ENGINES.get(name) or {}).get("params") or {})
    return name, params


def _engine_config_hash(eng: str):
    name, params = _engine_config(eng)
    payload = {"engine": name, "params": params}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stamp_recog_meta(recog_path: Path, eng: str):
    data = _load_recog_json(recog_path)
    if not isinstance(data, dict):
        return
    data["_meta"] = {"engine": engines.engine_name(eng), "engine_config_hash": _engine_config_hash(eng)}
    Path(recog_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _recog_cache_valid(recog_path: Path, eng: str):
    if not recog_path.exists():
        return False
    data = _load_recog_json(recog_path)
    if not isinstance(data, dict):
        return False
    meta = data.get("_meta") or {}
    # 必须有指纹且对得上。以前这里放行「非默认档 + 无指纹」的老缓存，本意是省一次重跑；
    # 但 DEFAULT_ENGINE 从 ppocrv6_high 改成 ppocrv6_onnx_high 之后语义翻转了——用户升级后
    # 选轻量档打开旧批次，会直接复用由**已被删除的 Paddle 满血档**产出的结果
    # （其 ocr_meta.backend 还是 paddle_static），且永不重跑。宁可让老批次重识一次。
    return bool(meta.get("engine_config_hash")) and meta["engine_config_hash"] == _engine_config_hash(eng)

def _load_recog_json(recog_path: Path):
    try:
        return json.loads(Path(recog_path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _recog_quality(recog_path: Path):
    data = _load_recog_json(recog_path)
    if data is None:
        return {
            "lines": 0,
            "chars": 0,
            "main_chars": 0,
            "low_pages": 999,
            "noise_chars": 0,
            "suspect_garbage_chars": 999,
            "usable_chars": 0,
            "avg_score": 0.0,
        }
    return ocr_quality.summarize_recog(data)


def _is_better_recog(candidate: Path, current: Path):
    cand = _load_recog_json(candidate)
    cur = _load_recog_json(current)
    if cand is None or cur is None:
        return False
    return ocr_quality.is_better(cand, cur)


def _ppocrv6_fallback_reason(quality):
    if quality.get("low_pages", 0) > 0:
        return "native_ppocrv6_low_recall"
    if quality.get("suspect_garbage_chars", 0) >= 24:
        return "native_ppocrv6_garbage_columns"
    return None


def _maybe_low_recall_lightweight_fallback(ctx: Ctx, image_dir: Path, recog_path: Path, eng: str):
    # 只对 Paddle 后端做「质量太差就改投轻量 ONNX」的兜底。满血 ONNX 降到轻量 ONNX 是同一批
    # 模型、更少后处理，不可能更好，那趟往返纯属浪费。
    if eng != engines.OFFICIAL_ENGINE or not recog_path.exists():
        return eng
    quality = _recog_quality(recog_path)
    reason = _ppocrv6_fallback_reason(quality)
    if not reason:
        return eng
    alt = recog_path.with_name("_recog_lightweight_fallback.json")
    try:
        _run_engine(ctx, image_dir, alt, engines.LIGHTWEIGHT_ENGINE)
        if alt.exists() and _is_better_recog(alt, recog_path):
            shutil.copyfile(alt, recog_path)
            _stamp_recog_meta(recog_path, engines.LIGHTWEIGHT_ENGINE)
            _mark_fallback(ctx, eng, RuntimeError(reason))
            return engines.LIGHTWEIGHT_ENGINE
    except Exception:
        pass
    finally:
        try:
            if alt.exists():
                alt.unlink()
        except Exception:
            pass
    _CUR_ENGINE["name"] = eng
    return eng
def _mark_fallback(ctx: Ctx, frm: str, err: Exception, to: str = None):
    """Internal helper."""
    try:
        with open(ctx.progress_path, "w", encoding="utf-8") as f:
            json.dump({"phase": "done", "fallback": {"from": frm, "to": to or engines.LIGHTWEIGHT_ENGINE,
                       "reason": str(err)[:300]}}, f, ensure_ascii=False)
    except Exception:
        pass


def _finish_progress(ctx: Ctx):
    """Internal helper."""
    payload = {"phase": "done", "done": 1, "total": 1}
    try:
        old = ctx.read_progress()
        if isinstance(old, dict) and old.get("fallback"):
            payload["fallback"] = old["fallback"]
    except Exception:
        pass
    ctx.write_progress(payload)


def _ensure_recog_direct(ctx: Ctx, image_dir: Path, recog_path: Path, engine: str = None, job=None):
    """Internal helper."""
    eng = engines.engine_name(engine)
    if _recog_cache_valid(recog_path, eng):
        return eng
    if recog_path.exists():
        try:
            recog_path.unlink()
        except Exception:
            pass
    recog_path.parent.mkdir(parents=True, exist_ok=True)
    if eng == engines.ONNX_HIGH_ENGINE:
        # 打包版里只有 ONNX 两档；Paddle 档要额外解释器，不能进打包版的回退链。
        chain = [engines.ONNX_HIGH_ENGINE, engines.LIGHTWEIGHT_ENGINE]
    elif eng == engines.LIGHTWEIGHT_ENGINE:
        chain = [eng]
    else:
        chain = [eng, engines.LIGHTWEIGHT_ENGINE]
    first_error = None
    for idx, candidate in enumerate(chain):
        try:
            if job is None:
                _run_engine(ctx, image_dir, recog_path, candidate)
            else:
                try:
                    _run_engine(ctx, image_dir, recog_path, candidate, job=job)
                except TypeError as exc:
                    if "unexpected keyword argument 'job'" not in str(exc):
                        raise
                    _run_engine(ctx, image_dir, recog_path, candidate)
            if recog_path.exists():
                _stamp_recog_meta(recog_path, candidate)
            actual = _maybe_low_recall_lightweight_fallback(ctx, image_dir, recog_path, candidate)
            if idx > 0:
                _mark_fallback(ctx, eng, first_error or RuntimeError(f"fallback_to_{actual}"), to=actual)
            elif actual != candidate:
                try:
                    old = ctx.read_progress()
                except Exception:
                    old = None
                if not (isinstance(old, dict) and old.get("fallback")):
                    _mark_fallback(ctx, eng, RuntimeError(f"fallback_to_{actual}"), to=actual)
            return actual
        except Exception as e:
            if first_error is None:
                first_error = e
            try:
                if recog_path.exists():
                    recog_path.unlink()
            except Exception:
                pass
    if eng == engines.LIGHTWEIGHT_ENGINE:
        raise HTTPException(500, f"Recognition failed (engine {eng}): {first_error}")
    raise HTTPException(500, f"Recognition failed (engine {eng}; fallback failed): {first_error}")

def _ensure_recog(ctx: Ctx, image_dir: Path, recog_path: Path, engine: str = None,
                  request_id: str = None):
    eng = engines.engine_name(engine)
    if ocr_job_manager.JOB_MANAGER.is_stopping() or windows_process.is_stopping():
        raise HTTPException(503, "application_stopping")
    if _recog_cache_valid(recog_path, eng):
        return eng
    return ocr_atomic.run_atomic(
        ocr_job_manager.JOB_MANAGER, ctx=ctx, image_dir=image_dir,
        output_path=recog_path, engine=eng, config_hash=_engine_config_hash(eng),
        request_id=request_id, direct_runner=_ensure_recog_direct,
        expected_pages=_count_ocr_images(image_dir))


def _ensure_region_recog(ctx: Ctx, image_dir: Path, recog_path: Path, engine: str = None):
    eng = engines.engine_name(engine)
    try:
        _run_engine(ctx, image_dir, recog_path, eng)
        return eng
    except Exception as e:
        if eng != engines.LIGHTWEIGHT_ENGINE:
            try:
                if recog_path.exists():
                    recog_path.unlink()
            except Exception:
                pass
            try:
                _run_engine(ctx, image_dir, recog_path, engines.LIGHTWEIGHT_ENGINE)
                _mark_fallback(ctx, eng, e)
                return engines.LIGHTWEIGHT_ENGINE
            except Exception as e2:
                raise HTTPException(500, f"Region recognition failed (engine {eng}; fallback failed): {e2}")
        raise HTTPException(500, f"Region recognition failed (engine {eng}): {e}")


def _count_ocr_images(image_dir: Path):
    try:
        return len([p for p in Path(image_dir).iterdir()
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")])
    except Exception:
        return 0


def _begin_ocr_progress(ctx: Ctx, image_dir: Path, engine: str):
    total = _count_ocr_images(image_dir) or 1
    payload = {"phase": "ocr", "done": 0, "total": total, "engine": engines.engine_name(engine)}
    try:
        old = ctx.read_progress()
        if isinstance(old, dict) and old.get("fallback"):
            payload["fallback"] = old["fallback"]
    except Exception:
        pass
    ctx.write_progress(payload)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


def _unique_paths(paths):
    out, seen = [], set()
    for p in paths:
        try:
            rp = Path(p).resolve()
        except Exception:
            continue
        key = str(rp).lower()
        if key not in seen:
            seen.add(key)
            out.append(rp)
    return out


def _batch_image_dirs(reg, proof_path):
    bdir = Path(proof_path).parent
    return _unique_paths([reg.get("image_dir") or bdir / "_src", bdir / "_src", bdir / "_img"])


def _rel_image_value(fp, reg, proof_path):
    fp = Path(fp).resolve()
    image_dir = Path(reg.get("image_dir") or Path(proof_path).parent / "_src").resolve()
    bdir = Path(proof_path).parent.resolve()
    for base in (image_dir, bdir):
        try:
            return str(fp.relative_to(base)).replace("\\", "/")
        except ValueError:
            pass
    return fp.name


def _local_image_candidates(page, reg, proof_path):
    raw = str(page.get("image") or "")
    names = []
    if raw:
        names.append(Path(raw).name)
    page_id = str(page.get("page_id") or "")
    if page_id:
        names.append(Path(page_id).name)
    stems = []
    for name in names:
        stem = Path(name).stem if name else ""
        if stem:
            stems.append(stem)
    for folder in _batch_image_dirs(reg, proof_path):
        if not folder.is_dir():
            continue
        for name in names:
            if name:
                yield folder / name
        for stem in stems:
            for ext in _IMAGE_EXTS:
                yield folder / f"{stem}{ext}"
            try:
                yield from folder.glob(stem + ".*")
            except Exception:
                pass


def _normalize_page_image_ref(page, reg, proof_path):
    raw = str(page.get("image") or "")
    if not raw:
        return False
    src = Path(raw)
    if not src.is_absolute():
        return False
    image_dir = Path(reg.get("image_dir") or Path(proof_path).parent / "_src")
    try:
        src.resolve().relative_to(image_dir.resolve())
    except (ValueError, OSError):
        return False
    page["image"] = _rel_image_value(src, reg, proof_path)
    return True

def _resolve_page_image(page, reg, proof_path, repair=False):
    raw = str(page.get("image") or "")
    image_dir = Path(reg.get("image_dir") or Path(proof_path).parent / "_src")
    bdir = Path(proof_path).parent
    if raw:
        src = Path(raw)
        checks = [src] if src.is_absolute() else [image_dir / raw, bdir / raw]
        for fp in checks:
            if fp.exists() and safefs.within_work(fp):
                if repair:
                    page["image"] = _rel_image_value(fp, reg, proof_path)
                return fp
    for fp in _local_image_candidates(page, reg, proof_path):
        if fp.exists() and safefs.within_work(fp):
            if repair:
                page["image"] = _rel_image_value(fp, reg, proof_path)
            return fp
    return None


def _repair_proof_image_refs(proof, reg, proof_path, persist=True):
    changed = False
    image_dir = Path(reg.get("image_dir") or Path(proof_path).parent / "_src")
    if proof.get("image_dir") != str(image_dir):
        proof["image_dir"] = str(image_dir)
        changed = True
    for page in proof.get("pages", []):
        before = page.get("image")
        if _resolve_page_image(page, reg, proof_path, repair=True) and page.get("image") != before:
            changed = True
    if changed and persist:
        M.save_proof(proof, proof_path)
    return changed
def _load_proof(ctx: Ctx, batch, image_dir, source_label, engine=None, request_id=None):
    """Internal helper."""
    bdir = ctx.work / batch
    recog_path = bdir / "_recog.json"
    proof_path = bdir / "proof.json"
    eng = engines.engine_name(engine)
    _begin_ocr_progress(ctx, Path(image_dir), eng)
    actual_eng = _ensure_recog(ctx, Path(image_dir), recog_path, eng, request_id=request_id)
    proof = M.load_or_build(proof_path, recog_path, batch, engine=actual_eng)
    proof["image_dir"] = str(image_dir)
    proof["source"] = source_label
    proof["engine"] = actual_eng
    reg = {"image_dir": str(image_dir), "proof_path": str(proof_path)}
    for page in proof.get("pages", []):
        if _normalize_page_image_ref(page, reg, proof_path):
            continue
        fp = _resolve_page_image(page, reg, proof_path, repair=False)
        if fp:
            page["image"] = _rel_image_value(fp, reg, proof_path)
    M.save_proof(proof, proof_path)
    return proof

def _ai_punctuate(proof, backend="local"):
    """Internal helper."""
    if backend != "local":
        return
    try:
        from punctuate_local import local_punctuate as _punc, available
        if not available():
            return
    except Exception:
        return
    for pg in proof["pages"]:
        lmap = {l["id"]: l for l in pg["lines"]}
        lines = [lmap[i] for i in pg.get("order", []) if i in lmap]
        try:
            out = _punc([l["text"] for l in lines])
        except Exception:
            return
        for l, t in zip(lines, out):
            l["text"] = t
            l["text_draft"] = t


def _resolve_punct_backend(body, settings):
    """Internal helper."""
    backend = body.get("punct_backend", settings.get("punct_backend", "local"))
    return backend if backend in {"local", "off"} else "local"
# comment
@router.post("/api/upload")
async def upload(request: Request, ctx: Ctx = Depends(ctx_dep)):
    form = await request.form()
    files = form.getlist("files")
    if not files:
        raise HTTPException(400, "No files selected")
    try:
        mtimes = json.loads(form.get("mtimes") or "[]")    # File.lastModified(ms) 閹稿绨€靛綊缍?
    except Exception:
        mtimes = []
    token = secrets.token_hex(8)
    items = []
    for i, f in enumerate(files):
        rel = safefs.safe_rel(getattr(f, "filename", None) or "file")
        if Path(rel).suffix.lower() not in _UP_EXT:
            continue
        dst = safefs.safe_join("users", ctx.uid, "_uploads", token, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as out:                       # 濞翠礁绱￠拃鐣屾磸閿涘苯銇囬弬鍥︽娑撳秶鍨庨崘鍛摠
            shutil.copyfileobj(f.file, out)
        try:
            mt = float(mtimes[i]) / 1000.0 if i < len(mtimes) else 0
        except Exception:
            mt = 0
        m = {"rel": rel, "name": Path(rel).name, "mtime": mt,
             "type": "pdf" if rel.lower().endswith(".pdf") else "image"}
        if m["type"] == "pdf":
            try:
                import fitz
                doc = fitz.open(str(dst)); m["pages"] = len(doc); doc.close()
            except Exception:
                m["pages"] = 1
        items.append(m)
    if not items:
        raise HTTPException(400, "No supported image or PDF files found (jpg/png/pdf only)")
    return {"token": token, "items": items}


@router.get("/api/thumb")
def thumb(token: str, rel: str, page: int = 0, ctx: Ctx = Depends(ctx_dep)):
    """Internal helper."""
    fp = safefs.safe_join("users", ctx.uid, "_uploads", safefs.safe_rel(token),
                          safefs.safe_rel(rel))
    if not fp.is_file():
        raise HTTPException(404, "File not found")
    from PIL import Image, ImageOps
    try:
        if fp.suffix.lower() == ".pdf":
            import fitz
            doc = fitz.open(str(fp))
            pno = min(max(0, (page or 1) - 1), len(doc) - 1)
            pix = doc[pno].get_pixmap(dpi=36)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()
        else:
            img = ImageOps.exif_transpose(Image.open(fp)).convert("RGB")
        img.thumbnail((120, 120))
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=80)
        return Response(buf.getvalue(), media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(500, f"Thumbnail failed: {e}")


@router.get("/api/import_progress")
def import_progress(ctx: Ctx = Depends(ctx_dep)):
    active = ocr_job_manager.JOB_MANAGER.status(ctx.uid, active_only=True)
    if active:
        return active
    p = ctx.read_progress()
    if isinstance(p, dict) and _CUR_ENGINE["name"]:
        p.setdefault("engine", _CUR_ENGINE["name"])   # 閸撳秶顏弰鍓с仛瑜版挸澧犲鏇熸惛閿涘牓鐝划缍盠/韫囶偊鈧噦绱?
    return p


def _derive_batch(items):
    """Internal helper."""
    first_rel = safefs.safe_rel(items[0].get("rel", "file"))
    segs = first_rel.split("/")
    base = segs[0] if len(segs) > 1 else Path(first_rel).stem    # 閺傚洣娆㈡径閫涚瑐娴肩姴褰囨い璺虹湴婢剁懓鎮?
    n = len(items)
    if n > 1 or len(segs) > 1:
        batch = safefs.coerce_batch(base)
        label = f"{base} ({n} items)"
    else:
        batch = safefs.coerce_batch(Path(first_rel).stem)
        label = Path(first_rel).name
    return batch, label


@router.post("/api/open")
async def open_sources(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """Internal helper."""
    body = await req.json()
    token = safefs.safe_rel(body.get("token", ""))
    items = body.get("items") or []
    if not token or not items:
        raise HTTPException(400, "No source items selected")
    ctx.write_progress({"phase": "import", "done": 0, "total": len(items)})
    abs_items = []
    for it in items:
        ap = safefs.safe_join("users", ctx.uid, "_uploads", token,
                              safefs.safe_rel(it.get("rel", "")))
        m = {"path": str(ap), "type": it.get("type", "image")}
        if it.get("page"):
            m["page"] = it["page"]
        abs_items.append(m)
    name = (body.get("name") or "").strip()
    if name:
        batch, label, split = safefs.coerce_batch(name), name, True
    else:
        (batch, label), split = _derive_batch(items), False
    bdir = ctx.work / batch
    if bdir.exists():
        # comment
        pf = bdir / "proof.json"
        same = False
        if pf.exists() and not split:
            try:
                same = json.loads(pf.read_text(encoding="utf-8")).get("source") == label
            except Exception:
                same = False
        if same:
            shutil.rmtree(bdir, ignore_errors=True)
        else:
            base_b, i = batch, 2
            while (ctx.work / batch).exists():
                batch = safefs.coerce_batch(f"{base_b}{i}"); i += 1
            bdir = ctx.work / batch
    src_dir = bdir / "_src"
    try:
        def import_progress(done, src, page=None, pages=None):
            name = Path(src).name
            label = f"{name} page {page}" if page and pages and pages > 1 else name
            ctx.write_progress({"phase": "import", "done": done, "total": 0,
                                "current": name, "label": label})

        ctx.write_progress({"phase": "import", "done": 0, "total": 0})
        files = ingest.explode_ordered(abs_items, src_dir, progress=import_progress)
        ctx.write_progress({"phase": "import", "done": len(files), "total": len(files)})
    except Exception as e:
        raise HTTPException(500, f"Import/PDF render failed: {e}")
    if not files:
        raise HTTPException(400, "No supported image or PDF files found")
    st = load_settings(ctx)
    proof = await anyio.to_thread.run_sync(lambda: _load_proof(ctx, batch, src_dir, label, request_id=body.get("request_id"),
                        engine=st.get("engine_pref") or None)   # 閻劍鍩涘鏇熸惛閸嬪繐銈介敍鍫⑩敄=姒涙顓绘妯肩翱閿?
    )
    _pb = _resolve_punct_backend(body, st)       # 閼奉亜濮╅弬顓炲綖閿涙ocal 閺堫剙婀存妯款吇瀵偓 / off 閸?
    if _pb != "off":
        _ai_punctuate(proof, _pb)
    if st.get("default_script") == "t" and proof.get("script") != "t":
        M.convert_proof(proof, "t")
    M.save_proof(proof, str(bdir / "proof.json"))
    _finish_progress(ctx)
    meta = repository_for_proof(bdir / "proof.json").load_meta()
    return JSONResponse({"batch": proof["batch"], "document_meta": meta,
                         "low_conf": M.LOW_CONF, "source": label,
                         "page_count": len(meta.get("pages", [])),
                         "paged": True})


def _document_repo(ctx, batch):
    reg = ctx.reg(safefs.safe_batch(batch))
    if not reg:
        raise HTTPException(404, "Document not found")
    return reg, repository_for_proof(reg["proof_path"])


@router.get("/api/document_meta")
def document_meta(batch: str, ctx: Ctx = Depends(ctx_dep)):
    _, repo = _document_repo(ctx, batch)
    try:
        return repo.load_meta()
    except DocumentNotFoundError:
        raise HTTPException(404, "Document not found")


@router.get("/api/document_page")
def document_page(batch: str, page_id: str, ctx: Ctx = Depends(ctx_dep)):
    _, repo = _document_repo(ctx, batch)
    try:
        return repo.load_page(page_id)
    except DocumentNotFoundError:
        raise HTTPException(404, "Page not found")


@router.post("/api/save_page")
async def save_page(req: Request, ctx: Ctx = Depends(ctx_dep)):
    body = await req.json()
    batch = body.get("batch", "")
    page_id = str(body.get("page_id", ""))
    if not page_id or not isinstance(body.get("page"), dict):
        raise HTTPException(400, "page_id and page are required")
    _, repo = _document_repo(ctx, batch)
    try:
        result = await anyio.to_thread.run_sync(lambda: repo.save_page(page_id, body["page"], body.get("base_revision", -1)))
    except DocumentConflictError as exc:
        raise HTTPException(409, {"error": "revision_conflict", "current_revision": exc.current_revision})
    return result


@router.post("/api/save_document_meta")
async def save_document_meta(req: Request, ctx: Ctx = Depends(ctx_dep)):
    body = await req.json()
    batch = body.get("batch", "")
    changes = body.get("changes", {})
    if not isinstance(changes, dict):
        raise HTTPException(400, "changes must be an object")
    _, repo = _document_repo(ctx, batch)
    try:
        result = await anyio.to_thread.run_sync(lambda: repo.save_meta(changes, body.get("base_revision")))
    except DocumentConflictError as exc:
        raise HTTPException(409, {"error": "revision_conflict", "current_revision": exc.current_revision})
    return result


@router.post("/api/document_checkpoint")
async def document_checkpoint(req: Request, ctx: Ctx = Depends(ctx_dep)):
    body = await req.json()
    batch = safefs.safe_batch(body.get("batch", ""))
    _, repo = _document_repo(ctx, batch)

    total = len(repo.load_meta().get("pages", []))

    def build_checkpoint(task):
        repo.checkpoint(
            progress=lambda done, page_total: task.progress(done=done, total=page_total),
            check_cancelled=task.check_cancelled,
        )
        return None

    task = TASK_MANAGER.submit(ctx.uid, ctx.work, "checkpoint", [batch], total, build_checkpoint)
    return {"job_id": task.task_id, "state": task.state, "kind": task.kind}

@router.get("/api/load")
def load_existing(batch: str, ctx: Ctx = Depends(ctx_dep)):
    """Pure read: load proof.json without triggering OCR or modifying any file.

    OCR engine switching only affects new imports. To re-recognize an existing
    document, use the explicit /api/reocr_batch endpoint.
    """
    reg = ctx.reg(safefs.safe_batch(batch))
    if not reg:
        raise HTTPException(404, "Document not found")
    proof_path = Path(reg["proof_path"])
    if not proof_path.exists():
        raise HTTPException(404, "Proof file not found")
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(500, "Proof file corrupted, cannot load")
    # Normalize paths in the response only. Opening/search-result navigation is
    # a read operation and must not rewrite a proof merely because paths moved.
    _repair_proof_image_refs(proof, reg, proof_path, persist=False)
    return JSONResponse({"proof": proof, "low_conf": M.LOW_CONF,
                         "source": proof.get("source", batch), "deprecated": True,
                         "replacement": ["/api/document_meta", "/api/document_page"]})

@router.post("/api/reocr_batch")
async def reocr_batch(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """Explicit re-recognition: re-run OCR on an existing batch.

    This may overwrite manual proofreading changes. The caller must confirm intent.
    Not triggered automatically by search or /api/load.
    """
    body = await req.json()
    batch = safefs.safe_batch(body.get("batch", ""))
    reg = ctx.reg(batch)
    if not reg:
        raise HTTPException(404, "Document not found")
    proof_path = Path(reg["proof_path"])
    bdir = proof_path.parent
    recog_path = bdir / "_recog.json"
    image_dir = Path(reg.get("image_dir") or bdir / "_src")
    st = load_settings(ctx)
    eng = engines.engine_name(st.get("engine_pref") or None)
    _begin_ocr_progress(ctx, image_dir, eng)
    actual = await anyio.to_thread.run_sync(lambda: _ensure_recog(
        ctx, image_dir, recog_path, eng,
        request_id=body.get("request_id")))
    proof = M.load_or_build(proof_path, recog_path, batch, engine=actual)
    proof["image_dir"] = str(image_dir)
    proof["engine"] = actual
    proof["source"] = proof.get("source", batch)
    _repair_proof_image_refs(proof, reg, proof_path)
    M.save_proof(proof, proof_path)
    _finish_progress(ctx)
    meta = repository_for_proof(proof_path).load_meta()
    return JSONResponse({"batch": batch, "document_meta": meta,
                         "low_conf": M.LOW_CONF, "source": proof.get("source", batch),
                         "page_count": len(meta.get("pages", [])), "paged": True})

@router.get("/img/{batch}/{page_id}")
def get_image(batch: str, page_id: str, ctx: Ctx = Depends(ctx_dep)):
    reg = ctx.reg(safefs.safe_batch(batch))
    if not reg:
        raise HTTPException(404, "Batch not loaded")
    proof_path = Path(reg["proof_path"])
    try:
        page = repository_for_proof(proof_path).load_page(page_id)["page"]
    except DocumentNotFoundError:
        raise HTTPException(404, "Page not found")
    fp = _resolve_page_image(page, reg, proof_path, repair=True)
    if not fp:
        raise HTTPException(404, "Image missing")

    if fp.suffix.lower() in (".tif", ".tiff", ".bmp", ".webp"):
        from PIL import Image
        buf = io.BytesIO()
        Image.open(fp).convert("RGB").save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png")
    return FileResponse(str(fp))

@router.post("/api/save")
async def save(req: Request, ctx: Ctx = Depends(ctx_dep)):
    body = await req.json()
    proof = body["proof"]
    reg = ctx.reg(safefs.safe_batch(proof.get("batch", "")))
    if not reg:
        raise HTTPException(404, "Batch not loaded")
    M.save_proof(proof, reg["proof_path"])
    return {"ok": True, "stats": M.edit_stats(proof)}



@router.post("/api/reocr_region")
async def reocr_region(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """Internal helper."""
    body = await req.json()
    batch = safefs.safe_batch(body.get("batch", ""))
    page_id = str(body.get("page_id", ""))
    box = body.get("box") or []
    if len(box) != 4:
        raise HTTPException(400, "No text provided")
    reg = ctx.reg(batch)
    if not reg:
        raise HTTPException(404, "Batch not found")
    proof_path = Path(reg["proof_path"])
    try:
        page = repository_for_proof(proof_path).load_page(page_id)["page"]
    except DocumentNotFoundError:
        raise HTTPException(404, "Page not found")
    img_path = _resolve_page_image(page, reg, proof_path, repair=True)
    if not img_path:
        raise HTTPException(404, "Line not found")
    from PIL import Image
    x1, y1, x2, y2 = [int(round(float(v))) for v in box]
    x1, x2 = sorted((max(0, x1), max(0, x2)))
    y1, y2 = sorted((max(0, y1), max(0, y2)))
    with Image.open(img_path).convert("RGB") as img:
        x2 = min(img.width, x2); y2 = min(img.height, y2)
        if x2 - x1 < 8 or y2 - y1 < 8:
            raise HTTPException(400, "No text provided")
        tmp = proof_path.parent / "_region_ocr"
        src = tmp / "_src"
        shutil.rmtree(tmp, ignore_errors=True)
        src.mkdir(parents=True, exist_ok=True)
        crop_path = src / "region.png"
        img.crop((x1, y1, x2, y2)).save(crop_path)
    out = tmp / "_recog.json"
    st = load_settings(ctx)
    actual_eng = _ensure_region_recog(ctx, src, out, st.get("engine_pref") or None)
    data = json.loads(out.read_text(encoding="utf-8"))
    first = next(iter(data.values()), {}) if isinstance(data, dict) else {}
    mapped = []
    source = "manual_region_lightweight" if actual_eng == engines.LIGHTWEIGHT_ENGINE else "manual_region"
    for line in first.get("lines", []):
        mapped.append(ocr_rescue.map_crop_line(line, (x1, y1, x2, y2), source))
    shutil.rmtree(tmp, ignore_errors=True)
    return {"lines": mapped, "engine": actual_eng}


def _convert_document_pages(repo, to: str) -> dict:
    if to not in {"s", "t"}:
        raise ValueError("script must be s or t")
    meta = repo.load_meta()

    def convert_page(page, _index):
        M.convert_proof({"script": meta.get("script", "s"), "pages": [page]}, to)
        return True

    return repo.transform_pages(convert_page, meta_changes={"script": to})

@router.post("/api/convert")
async def convert(req: Request, ctx: Ctx = Depends(ctx_dep)):
    """Convert a persisted document page by page; legacy proof payloads are ignored."""
    body = await req.json()
    legacy = body.get("proof") if isinstance(body.get("proof"), dict) else {}
    batch = body.get("batch") or legacy.get("batch", "")
    _, repo = _document_repo(ctx, batch)
    try:
        meta = await anyio.to_thread.run_sync(lambda: _convert_document_pages(repo, body.get("to", "s")))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"batch": batch, "document_meta": meta,
            "page_count": len(meta.get("pages", [])), "paged": True}