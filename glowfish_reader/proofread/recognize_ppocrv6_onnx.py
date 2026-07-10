# -*- coding: utf-8 -*-
"""PaddleOCR PP-OCRv6 ONNX Runtime engine.

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
from pathlib import Path

import det_scale
import ocr_confusion
import ocr_enhance
import ocr_filter
import ocr_rescue

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
_SUBST_DRIVE = None
ACTIVE_DEVICE = None      # 实际生效的设备（"gpu:0" / "cpu"），供 ocr_meta 回显
EXPLICIT_DET_CFG = False  # config 里显式定死 text_det_limit_* → 自适应尺度让位


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


def _cuda_provider_available():
    """onnxruntime 装的是 GPU 轮子（有 CUDAExecutionProvider）才算能上显卡。

    CPU 轮子（打包默认）只有 CPUExecutionProvider；paddlex 的 onnxruntime 引擎会在
    device_type=gpu 时自己查一遍并抛 RuntimeError，我们提前查是为了 auto 档静默选 CPU。
    """
    try:
        import onnxruntime as ort
        return "CUDAExecutionProvider" in set(ort.get_available_providers())
    except Exception:
        return False


def _resolve_device():
    """SHUPAI_OCR_DEVICE：cpu（默认）/ gpu[:N] / auto（有 CUDA provider 才上显卡）。

    ⚠ 默认是 cpu 而不是 auto，与满血档相反，这是**实测**的结论不是保守：
    轻量档 GPU 提速为零。s04（4531×6786，RTX 4060 Laptop，onnxruntime-gpu 1.23.2）
    分阶段计时——神经网络推理只占 41%（2.16s CPU / 2.41s GPU，GPU 反而略慢），
    其余 59% 是读图 0.55s + 图像增强 0.94s + 列检测 1.06s + 正文区域 0.51s，
    全是 PIL/numpy 的 CPU 活。模型太小（det 只喂 974px、rec 只识十来个列条），
    每次 kernel launch 的 CUDA 开销盖过了并行收益。多页摊掉 warmup 后 11.2s/页(GPU)
    对 11.1s/页(CPU)。故 auto 档保留但不做默认——免得装了 GPU 轮子的机器被静默
    切到一条更慢的路上。想提速请去优化上面那 59%，不是换设备。

    满血档（paddle 后端）不同：那边推理占比高，GPU 确有收益，故它默认 auto。
    """
    want = (os.environ.get("SHUPAI_OCR_DEVICE") or "cpu").strip().lower()
    if want.startswith("gpu"):
        return want if ":" in want else "gpu:0"
    if want == "auto":
        return "gpu:0" if _cuda_provider_available() else "cpu"
    return "cpu"


def _construct(PaddleOCR, kwargs):
    try:
        return PaddleOCR(**kwargs)
    except TypeError:
        kwargs.pop("use_doc_orientation_classify", None)
        kwargs.pop("use_doc_unwarping", None)
        return PaddleOCR(**kwargs)


def _build_engine(config=None):
    """Build the official PaddleOCR PP-OCRv6 predictor on ONNX Runtime.

    CPU 轮子与 GPU 轮子（onnxruntime / onnxruntime-gpu）都能跑：装了 GPU 轮子就自动
    用显卡，否则老实 CPU。显卡起不来（缺驱动 / cuDNN 不全 / 显存不足）自动回落 CPU。
    """
    global ACTIVE_DEVICE, EXPLICIT_DET_CFG
    _ensure_paddlex_env()
    from paddleocr import PaddleOCR

    cfg = dict(config or {})
    ocr_version = cfg.pop("ocr_version", "PP-OCRv6")
    lang = cfg.pop("lang", "chinese_cht")
    # 这几个是我们自己流水线的开关，不是 PaddleOCR 构造参数，别透传进去。
    cfg.pop("profile", None)
    cfg.pop("column_rescue", None)
    # 显式定死 det 尺度时让位给调用方；box_thresh/unclip 与尺度正交，可与自适应组合。
    EXPLICIT_DET_CFG = any(key in cfg for key in ("text_det_limit_side_len", "text_det_limit_type"))
    root = Path(__file__).resolve().parent / "models" / "ppocrv6_onnx"
    device = _resolve_device()
    kwargs = {
        "ocr_version": ocr_version,
        "lang": lang,
        "text_detection_model_name": "PP-OCRv6_medium_det",
        "text_detection_model_dir": str(root / "det"),
        "text_recognition_model_name": "PP-OCRv6_medium_rec",
        "text_recognition_model_dir": str(root / "rec"),
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "engine": "onnxruntime",
        "device": device,
    }
    kwargs.update(cfg)                      # config 里显式给 device 仍可覆盖（bench A/B）
    device = kwargs.get("device", device)
    try:
        engine = _construct(PaddleOCR, dict(kwargs))
        ACTIVE_DEVICE = device
        return engine
    except Exception as exc:
        if not str(device or "").startswith("gpu"):
            raise
        print(f"WARN: GPU OCR unavailable ({exc!r}); falling back to CPU", file=sys.stderr)
        kwargs["device"] = "cpu"
        engine = _construct(PaddleOCR, dict(kwargs))
        ACTIVE_DEVICE = "cpu"
        return engine


def _confusion_enabled():
    """形近字后处理（层③）。纯文本变换，两档共用；GF_OCR_CONFUSION=0 关断以做消融。"""
    return (os.environ.get("GF_OCR_CONFUSION") or "1").strip().lower() not in ("0", "false", "off")


def _predict_path(engine, image_path, det=None):
    """det: 逐调用的 det 覆盖（text_det_limit_side_len / _limit_type），None=用引擎构造时的档位。"""
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


def _column_rescue(engine, oriented, pid, norm_dir, columns=None, det_ratio=0.0):
    rescued = []
    for idx, box in enumerate(columns or ocr_rescue.find_vertical_text_columns(oriented)):
        x1, y1, x2, y2 = box
        crop = ocr_rescue.enhance_for_ocr(oriented.crop((x1, y1, x2, y2)))
        crop_path = Path(norm_dir) / f"{pid}_col_{idx:03d}.jpg"
        crop.save(crop_path, "JPEG", quality=92)
        # 裁剪图长边同样会被夹到 4000，不施同一 scale 的话尺度陷阱原样复现。
        det = None if EXPLICIT_DET_CFG else det_scale.det_for_size(crop.size, det_ratio)
        for line in _predict_path(engine, crop_path, det):
            rescued.append(ocr_rescue.map_crop_line(line, box, "column_rescue"))
    return rescued


def recognize_one(engine, img_path, norm_dir, profile=None):
    """Recognize one image after EXIF normalization, returning one page dict.

    Full-page OCR is preserved. If recall is suspiciously low, the page is also
    rescanned as right-to-left vertical columns and recovered lines are merged.

    profile='high_accuracy' 时额外叠加 ocr_enhance 的增强层（手写页低阈值二检 /
    低置信行多预处理投票 / 小字超分重识）。检测尺度自适应两档共用——那是整列漏检的
    根因修复，不属于"增强"。
    """
    from PIL import Image, ImageOps

    high = profile == "high_accuracy"
    pid = Path(img_path).stem
    norm_path = Path(norm_dir) / f"{pid}.jpg"
    ocr_path = Path(norm_dir) / f"{pid}_ocr.jpg"
    oriented = ImageOps.exif_transpose(Image.open(img_path)).convert("RGB")
    width, height = oriented.size
    oriented.save(norm_path, "JPEG", quality=92)
    ocr_rescue.enhance_for_ocr(oriented).save(ocr_path, "JPEG", quality=92)

    # 列检测提前到整页识别之前：大图原尺寸进 DB 检测器会让笔画松散的列置信度塌陷、整列漏检，
    # 得先量出列距才能反推该把 det 输入缩到多大。这一趟本来就要跑（下面 rescue 要用），不额外花钱。
    columns = ocr_rescue.find_vertical_text_columns(oriented)
    det_pitch = det_scale.column_pitch(columns)
    det_ratio = 0.0 if EXPLICIT_DET_CFG else det_scale.scale_for(det_pitch)
    page_det = None if EXPLICIT_DET_CFG else det_scale.det_for_size(oriented.size, det_ratio)

    def predict_crop(path, size):
        det = None if EXPLICIT_DET_CFG else det_scale.det_for_size(size, det_ratio)
        return _predict_path(engine, path, det)

    lines = _predict_path(engine, ocr_path, page_det)
    for line in lines:
        line.setdefault("source", "full_page")

    # 层⑤：稀疏/小字页再用低 box_thresh 检一遍（逐调用覆盖，不重建引擎）。
    low_thresh_used = False
    if high and ocr_enhance.low_thresh_enabled() and ocr_enhance.looks_like_handwriting(lines, width, height):
        try:
            low_lines = _predict_path(engine, ocr_path, ocr_enhance.low_thresh_det(page_det))
            for line in low_lines:
                line.setdefault("source", "full_page_low")
            lines = list(lines) + low_lines
            low_thresh_used = True
        except Exception as exc:
            print(f"WARN: low-threshold pass failed: {exc!r}", file=sys.stderr)

    low_recall = ocr_rescue.is_low_recall(lines, width, height)
    rescue_columns = columns if low_recall else ocr_rescue.uncovered_columns(columns, lines)
    if rescue_columns:
        lines = list(lines) + _column_rescue(engine, oriented, pid, norm_dir, rescue_columns,
                                             det_ratio=det_ratio)

    if high:
        lines = ocr_enhance.prefilter_by_score(lines)
        lines, merge_stats = ocr_rescue.merge_high_accuracy_lines(lines)
    else:
        lines = ocr_rescue.dedupe_lines(lines)
        merge_stats = None

    # ⚠ 增强层必须跑在 annotate_page_lines **之前**。ocr_filter.classify_line 同时依据
    # text 与 score 判 main_text / noise，而这几层就地改写的正是 text 与 score。
    # 反过来先 annotate 的话，层② 提分救回的行仍顶着旧的 low_conf_noise 身份，
    # 被 proof_model 从正文里剔除——白跑三趟推理，那几列字照样不出现在辑录里。
    if high:
        ocr_enhance.rescue_small_text(predict_crop, lines, oriented, norm_dir, pid)
        ocr_enhance.enhance_low_confidence_lines(predict_crop, lines, oriented, norm_dir, pid)
    if _confusion_enabled():
        ocr_confusion.correct_ocr_lines(lines)

    lines = ocr_filter.annotate_page_lines(lines, width, height, image_path=norm_path)

    meta = {"body_region": list(ocr_rescue.find_body_region(oriented)),
            "low_recall": low_recall, "columns": len(columns),
            "rescued_columns": len(rescue_columns),
            "det_adaptive": bool(page_det),
            "det_pitch": round(det_pitch, 1),
            "det_scale": round(det_ratio, 4),
            "det_overrides": page_det,
            "device": ACTIVE_DEVICE or "cpu",
            "backend": "ppocrv6_onnx", "runtime": "onnxruntime",
            "det_model": "PP-OCRv6_medium_det",
            "rec_model": "PP-OCRv6_medium_rec"}
    if high:
        meta.update({"profile": "high_accuracy", "low_thresh_pass": low_thresh_used,
                     "merge_stats": merge_stats, "quality": ocr_enhance.quality_summary(lines)})
    return {"image": str(norm_path), "width": width, "height": height, "lines": lines,
            "ocr_meta": meta}



def run_job(engine, images, out, progress=None, log=print, config=None):
    imgs = _list_images(images)
    if not imgs:
        raise FileNotFoundError(f"目录无图片：{images}")
    profile = (config or {}).get("profile")
    failed = []

    def wp(phase, done, total):
        if not progress:
            return
        try:
            with open(progress, "w", encoding="utf-8") as f:
                json.dump({"phase": phase, "done": done, "total": total, "failed": failed}, f)
        except Exception:
            pass

    wp("load", 0, len(imgs))
    norm_dir = Path(out).resolve().parent / "_img"
    norm_dir.mkdir(parents=True, exist_ok=True)
    recog = {}
    for idx, img in enumerate(imgs):
        pid = img.stem
        try:
            recog[pid] = recognize_one(engine, img, norm_dir, profile=profile)
            log(f"  {pid}: {len(recog[pid]['lines'])} lines "
                f"({recog[pid]['width']}x{recog[pid]['height']})")
        except Exception as exc:
            log(f"  FAIL {pid}: {exc!r}")
            failed.append({"name": img.name, "idx": idx + 1})
            norm_path = norm_dir / f"{pid}.jpg"
            recog[pid] = {"image": str(norm_path) if norm_path.exists() else str(img),
                          "width": 0, "height": 0, "lines": [], "failed": True}
        wp("ocr", idx + 1, len(imgs))

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
        _emit({"event": "ready", "ok": False, "error": repr(exc)})
        return 1
    model_type = ("ppocrv6_onnx_high" if config.get("profile") == "high_accuracy"
                  else "ppocrv6_onnx")
    _emit({"event": "ready", "ok": True, "model_type": model_type})

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
        try:
            job = json.loads(line)
            cfg = job.get("config") or {}
            if cfg != config:
                engine = _build_engine(cfg)
                config = dict(cfg)
            pages, nfail = run_job(
                engine, job["images"], job["out"], job.get("progress"), log=log, config=config
            )
            _emit({"event": "result", "ok": True, "out": job["out"], "pages": pages, "failed": nfail})
        except Exception as exc:
            _emit({"event": "result", "ok": False, "error": repr(exc)})
    return 0

class OcrWorker:
    def __init__(self, argv_prefix, env=None, model_type="ppocrv6_onnx", config=None):
        import threading
        self.argv = list(argv_prefix) + ["--serve-worker"]
        if config:
            self.argv += ["--worker-config", json.dumps(config, ensure_ascii=False)]
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
            self._p.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
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
    print(f"Loading PaddleOCR PP-OCRv6 ONNX Runtime ... {len(imgs)} images")
    engine = _build_engine(config)
    run_job(engine, args.images, args.out, args.progress, log=print, config=config)
    print("Wrote", args.out)


if __name__ == "__main__":
    main()
