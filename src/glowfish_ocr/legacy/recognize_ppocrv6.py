# -*- coding: utf-8 -*-
"""Official PaddleOCR PP-OCRv6 engine.

Runs in a PaddleOCR environment and writes the same _recog.json contract as the
existing OCR engines:
  { "<page_id>": {"image", "width", "height",
                  "lines": [{"text", "box", "score"}]} }
"""
import argparse
import atexit
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import ocr_filter
import ocr_rescue

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
_SUBST_DRIVE = None


def _is_ascii_path(path):
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _ensure_paddlex_env():
    """Set stable local defaults before PaddleOCR/PaddleX is imported."""
    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "huggingface")
    os.environ.setdefault("PADDLE_PDX_HUGGING_FACE_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")
    os.environ.setdefault("FLAGS_use_mkldnn", "false")
    if os.environ.get("PADDLE_PDX_CACHE_HOME"):
        return
    root = Path(__file__).resolve().parents[1]
    cache_rel = Path("proofread") / "_work" / "paddlex_cache"
    if _is_ascii_path(root):
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(root / cache_rel)
        return
    if os.name != "nt":
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(root / cache_rel)
        return
    global _SUBST_DRIVE
    for letter in "ZYXWVUTSRQPONMLKJIH":
        drive = f"{letter}:"
        if Path(drive + "\\").exists():
            continue
        try:
            subprocess.run(["subst", drive, str(root)], check=True,
                           capture_output=True, text=True)
            _SUBST_DRIVE = drive
            os.environ["PADDLE_PDX_CACHE_HOME"] = str(Path(drive + "\\") / cache_rel)
            atexit.register(lambda d=drive: subprocess.run(
                ["subst", d, "/D"], capture_output=True, text=True))
            return
        except Exception:
            continue
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(root / cache_rel)


def to_bbox(poly):
    """Convert a 4-point polygon or xyxy box to [xmin, ymin, xmax, ymax]."""
    try:
        flat = list(poly)
        if flat and hasattr(flat[0], "__len__"):
            xs = [float(p[0]) for p in flat]
            ys = [float(p[1]) for p in flat]
            return [min(xs), min(ys), max(xs), max(ys)]
        if len(flat) == 4:
            x1, y1, x2, y2 = map(float, flat)
            return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
    except Exception:
        pass
    return [0.0, 0.0, 0.0, 0.0]


def extract(result):
    """Extract texts, scores, and boxes from PaddleOCR 3.x prediction output."""
    try:
        data = result.json
    except Exception:
        data = result if isinstance(result, dict) else {}
    inner = data.get("res", data) if isinstance(data, dict) else {}
    texts = inner.get("rec_texts") or []
    scores = inner.get("rec_scores") or [1.0] * len(texts)
    polys = (inner.get("rec_polys") or inner.get("dt_polys")
             or inner.get("rec_boxes") or inner.get("boxes"))
    return list(texts), list(scores), polys


def _list_images(img_dir):
    return sorted(p for p in Path(img_dir).iterdir() if p.suffix.lower() in IMG_EXT)


def _resolve_device():
    """SHUPAI_OCR_DEVICE: auto(默认,装了 GPU 版 paddle 就用 gpu:0) / cpu / gpu[:N] / 空=不传。

    返回 None 表示不显式传 device，交给 PaddleOCR 自己决定（CPU 版 paddle 的既有行为）。
    """
    want = (os.environ.get("SHUPAI_OCR_DEVICE") or "auto").strip().lower()
    if want in ("", "none"):
        return None
    if want == "cpu":
        return "cpu"
    if want.startswith("gpu"):
        return want if ":" in want else "gpu:0"
    # auto：只有 paddle 真编译了 CUDA 才上 GPU，否则老老实实 CPU（不传，保持旧行为）。
    try:
        import paddle
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            return "gpu:0"
    except Exception:
        pass
    return None


ACTIVE_DEVICE = None      # 实际生效的设备（"gpu:0" / "cpu" / None=引擎自选），供 ocr_meta 回显
def _construct(PaddleOCR, kwargs):
    try:
        return PaddleOCR(**kwargs)
    except TypeError:
        kwargs.pop("use_doc_orientation_classify", None)
        kwargs.pop("use_doc_unwarping", None)
        return PaddleOCR(**kwargs)


def _build_engine(config=None):
    """Build the official local PaddleOCR PP-OCRv6 predictor.

    CPU 版与 GPU 版 paddle 都能跑：装了 GPU 版就自动用显卡，装的是 CPU 版（或有 GPU 版
    但显卡/驱动/显存起不来）就回落 CPU。用户可用 SHUPAI_OCR_DEVICE=cpu 强制关掉 GPU。
    """
    global ACTIVE_DEVICE
    _ensure_paddlex_env()
    from paddleocr import PaddleOCR

    cfg = dict(config or {})
    ocr_version = cfg.pop("ocr_version", "PP-OCRv6")
    lang = cfg.pop("lang", "chinese_cht")
    # ⚠ 新增「识别流程开关」（非 PaddleOCR 构造参数）一律要在这里 pop，漏 pop 会 ValueError。
    cfg.pop("column_rescue", None)
    cfg.pop("profile", None)
    cfg.pop("degraded_preproc", None)
    # 余下的 text_det_* 是真·PaddleOCR 构造参数，经 kwargs.update(cfg) 直通（bench --profile-config
    # 靠它做 det A/B）。只有显式定死「尺度」才关掉按页自适应——box_thresh / unclip 等与尺度正交，
    # 必须能和自适应组合，否则调阈值就把尺度修复一起关掉了。
    kwargs = {
        "ocr_version": ocr_version,
        "lang": lang,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    device = _resolve_device()
    if device:
        kwargs["device"] = device
    kwargs.update(cfg)

    try:
        engine = _construct(PaddleOCR, dict(kwargs))
        ACTIVE_DEVICE = kwargs.get("device")
        return engine
    except Exception as exc:
        if not str(device or "").startswith("gpu"):
            raise
        # GPU 起不来（缺驱动/CUDA DLL/显存不足）→ 回落 CPU，别让没显卡的用户直接崩。
        print(f"WARN: GPU OCR unavailable ({exc!r}); falling back to CPU", file=sys.stderr)
        kwargs["device"] = "cpu"
        engine = _construct(PaddleOCR, dict(kwargs))
        ACTIVE_DEVICE = "cpu"
        return engine


def _predict_path(engine, image_path, det=None):
    """det: 逐调用的 det 覆盖（text_det_limit_side_len / _limit_type 等），None=用引擎构造时的档位。"""
    lines = []
    for result in engine.predict(str(image_path), **(det or {})):
        texts, scores, polys = extract(result)
        polys = list(polys) if polys is not None else [None] * len(texts)
        for idx, text in enumerate(texts):
            if not str(text).strip():
                continue
            score = scores[idx] if idx < len(scores) else 1.0
            poly = polys[idx] if idx < len(polys) else None
            lines.append({
                "text": str(text),
                "box": to_bbox(poly) if poly is not None else [0.0, 0.0, 0.0, 0.0],
                "score": round(float(score), 4),
            })
    return lines


def _column_rescue(engine, oriented, pid, norm_dir, columns=None):
    rescued = []
    for idx, box in enumerate(columns or ocr_rescue.find_vertical_text_columns(oriented)):
        x1, y1, x2, y2 = box
        crop = ocr_rescue.enhance_for_ocr(oriented.crop((x1, y1, x2, y2)))
        crop_path = Path(norm_dir) / f"{pid}_col_{idx:03d}.jpg"
        crop.save(crop_path, "JPEG", quality=92)
        for line in _predict_path(engine, crop_path):
            rescued.append(ocr_rescue.map_crop_line(line, box, "column_rescue"))
    return rescued


def recognize_one(engine, img_path, norm_dir, column_rescue=True):
    """Recognize one image after EXIF normalization, returning one page dict.

    这是 dev/诊断用的官方 PaddleOCR 对照路径。满血档已迁到 recognize_ppocrv6_onnx.py
    的 profile='high_accuracy'（见 docs/OCR_满血版设计.md）。
    """
    from PIL import Image, ImageOps

    pid = Path(img_path).stem
    norm_path = Path(norm_dir) / f"{pid}.jpg"
    ocr_path = Path(norm_dir) / f"{pid}_ocr.jpg"
    oriented = ImageOps.exif_transpose(Image.open(img_path)).convert("RGB")
    width, height = oriented.size
    oriented.save(norm_path, "JPEG", quality=92)
    ocr_rescue.enhance_for_ocr(oriented).save(ocr_path, "JPEG", quality=92)

    lines = _predict_path(engine, ocr_path)
    for line in lines:
        line.setdefault("source", "full_page")
    low_recall = ocr_rescue.is_low_recall(lines, width, height)
    columns = ocr_rescue.find_vertical_text_columns(oriented) if column_rescue else []
    rescue_columns = (columns if low_recall else ocr_rescue.uncovered_columns(columns, lines)) if column_rescue else []
    if rescue_columns:
        lines = list(lines) + _column_rescue(engine, oriented, pid, norm_dir, rescue_columns)
    lines = ocr_rescue.dedupe_lines(lines)
    lines = ocr_filter.annotate_page_lines(lines, width, height, image_path=norm_path)
    return {"image": str(norm_path), "width": width, "height": height, "lines": lines,
            "ocr_meta": {"body_region": list(ocr_rescue.find_body_region(oriented)),
                         "low_recall": low_recall, "columns": len(columns),
                         "rescued_columns": len(rescue_columns),
                         "device": ACTIVE_DEVICE or "cpu",
                         "backend": "ppocrv6", "runtime": "paddle_static",
                         "det_model": "PP-OCRv6_medium_det",
                         "rec_model": "PP-OCRv6_medium_rec"}}



def run_job(engine, images, out, progress=None, log=print, config=None):
    imgs = _list_images(images)
    if not imgs:
        raise FileNotFoundError(f"No images found: {images}")
    failed = []
    cfg = dict(config or {})
    column_rescue = bool(cfg.get("column_rescue", True))
    # 这条 Paddle 路径不再实现 high_accuracy / 退化预处理。以前它默默收下这两个 config 键
    # 却什么都不做，`run_bench --engine ppocrv6 --profile-config '{"profile":"high_accuracy"}'`
    # 会得出「profile 无效」的假结论。现在出声。
    for dead_key in ("profile", "degraded_preproc"):
        if cfg.get(dead_key):
            print(f"WARN: engine 'ppocrv6' 不支持 config['{dead_key}']={cfg[dead_key]!r}，已忽略。"
                  f"满血档请用 ppocrv6_onnx_high。", file=sys.stderr)

    def wp(phase, done, total, current=None):
        if not progress:
            return
        try:
            payload = {"phase": phase, "done": done, "total": total, "failed": failed}
            if current:
                payload["current"] = current
            with open(progress, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception:
            pass

    wp("load", 0, len(imgs))
    norm_dir = Path(out).resolve().parent / "_img"
    norm_dir.mkdir(parents=True, exist_ok=True)
    recog = {}
    for idx, img in enumerate(imgs):
        pid = img.stem
        wp("ocr", idx, len(imgs), img.name)
        t_page = time.perf_counter()
        try:
            recog[pid] = recognize_one(engine, img, norm_dir, column_rescue=column_rescue)
            elapsed = time.perf_counter() - t_page
            recog[pid].setdefault("ocr_meta", {})["page_seconds"] = round(elapsed, 2)
            passes = len(recog[pid].get("ocr_meta", {}).get("candidate_sources") or []) or 1
            log(f"  {pid}: {len(recog[pid]['lines'])} lines "
                f"({recog[pid]['width']}x{recog[pid]['height']})")
            log(f"@@PAGE_SECONDS={pid}:{elapsed:.2f}:passes={passes}@@")
        except Exception as exc:
            log(f"  FAIL {pid}: {exc!r}")
            failed.append({"name": img.name, "idx": idx + 1})
            norm_path = norm_dir / f"{pid}.jpg"
            recog[pid] = {"image": str(norm_path) if norm_path.exists() else str(img),
                          "width": 0, "height": 0, "lines": [], "failed": True}
        wp("ocr", idx + 1, len(imgs), img.name)

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(recog, f, ensure_ascii=False, indent=2)
    wp("done", len(imgs), len(imgs))
    return len(recog), len(failed)

# Worker protocol for resident OCR jobs.
SENTINEL = "@@OCR@@"


def _emit(obj):
    sys.stdout.write(SENTINEL + json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve_worker(config=None):
    config = dict(config or {})
    try:
        engine = _build_engine(config)
    except Exception as exc:
        _emit({"event": "ready", "ok": False, "error_type": "ocr_worker_start_failed",
               "stage": "initialization", "reason": str(exc)[:500], "error": repr(exc)})
        return 1
    _emit({"event": "ready", "ok": True, "model_type": "ppocrv6"})

    def log(*args):
        try:
            print(*args, file=sys.stderr)
            sys.stderr.flush()
        except Exception:
            pass

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        job_id = None
        try:
            job = json.loads(line)
            job_id = job.get("job_id")
            cfg = job.get("config") or {}
            if cfg != config:
                engine = _build_engine(cfg)
                config = dict(cfg)
            pages, nfail = run_job(
                engine, job["images"], job["out"], job.get("progress"), log=log, config=cfg
            )
            _emit({"event": "result", "ok": True, "job_id": job_id,
                   "out": job["out"], "pages": pages, "failed": nfail})
        except Exception as exc:
            _emit({"event": "result", "ok": False, "job_id": job_id,
                   "error_type": "ocr_worker_job_failed", "stage": "recognition",
                   "reason": str(exc)[:500], "error": repr(exc)})
    return 0


class OcrWorker:
    def __init__(self, argv_prefix, env=None, model_type="ppocrv6", config=None):
        import threading
        self.argv = list(argv_prefix) + ["--serve-worker"]
        if config:
            self.argv += ["--worker-config", json.dumps(config, ensure_ascii=True)]
        self.env = env
        self.model_type = model_type
        self._lock = threading.Lock()
        self._p = None

    def start(self):
        import subprocess
        self._p = subprocess.Popen(
            self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=self.env, text=True,
            encoding="utf-8", errors="replace", bufsize=1)
        msg = self._read_event()
        if not (msg and msg.get("event") == "ready" and msg.get("ok")):
            self.close()
            raise RuntimeError(f"worker not ready: {msg}")
        return self

    def alive(self):
        return self._p is not None and self._p.poll() is None

    def _read_event(self):
        p = self._p
        if p is None or p.stdout is None:
            return None
        for line in p.stdout:
            line = line.rstrip("\n")
            if line.startswith(SENTINEL):
                try:
                    return json.loads(line[len(SENTINEL):])
                except Exception:
                    return None
        return None

    def submit(self, images, out, progress=None, config=None):
        with self._lock:
            if not self.alive():
                raise RuntimeError("worker is not running")
            job = {"images": str(images), "out": str(out),
                   "progress": str(progress) if progress else None,
                   "config": config or {}}
            self._p.stdin.write(json.dumps(job, ensure_ascii=True) + "\n")
            self._p.stdin.flush()
            msg = self._read_event()
            if not msg or msg.get("event") != "result":
                raise RuntimeError(f"worker protocol error: {msg}")
            if not msg.get("ok"):
                raise RuntimeError(f"worker OCR failed: {msg.get('error')}")
            return msg

    def close(self):
        p, self._p = self._p, None
        if p is None:
            return
        try:
            if p.stdin:
                p.stdin.close()
        except Exception:
            pass
        try:
            p.terminate()
        except Exception:
            pass

def main():
    if "--serve-worker" in sys.argv:
        config = {}
        if "--worker-config" in sys.argv:
            try:
                config = json.loads(sys.argv[sys.argv.index("--worker-config") + 1])
            except Exception:
                config = {}
        sys.exit(serve_worker(config))
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--progress", default=None)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    config = {}
    if args.config:
        try:
            config = json.loads(args.config)
        except Exception:
            config = {}
    imgs = _list_images(args.images)
    if not imgs:
        sys.exit(f"No images found: {args.images}")
    print(f"Loading official PaddleOCR PP-OCRv6 ... {len(imgs)} images")
    engine = _build_engine(config)
    run_job(engine, args.images, args.out, args.progress, log=print, config=config)
    print("Wrote", args.out)


if __name__ == "__main__":
    main()
