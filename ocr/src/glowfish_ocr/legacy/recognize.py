# -*- coding: utf-8 -*-
"""富识别（paddleocr env）：把一个图片目录识别成每页逐行 {text, box, score}。

输出 _recog.json：
  { "<page_id>": {"image": "<file>", "width": W, "height": H,
                  "lines": [ {"text": "...", "box": [x1,y1,x2,y2], "score": 0.97} ]} }
box 为原图坐标系下的外接矩形。校对界面据此叠框、定位、排序。

用法：python recognize.py --images <目录> --out _recog.json
"""
import os
import sys
import json
import argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def to_bbox(poly):
    """4 点 [[x,y]*4] 或 [x1,y1,x2,y2] → [xmin,ymin,xmax,ymax]。"""
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


def extract(r):
    """PaddleOCR 3.x 单图结果 → (texts, scores, polys)。"""
    try:
        dd = r.json
    except Exception:
        dd = r if isinstance(r, dict) else {}
    inner = dd.get("res", dd) if isinstance(dd, dict) else {}
    texts = inner.get("rec_texts") or []
    scores = inner.get("rec_scores") or []
    polys = (inner.get("rec_polys") or inner.get("dt_polys")
             or inner.get("rec_boxes") or inner.get("boxes"))
    return list(texts), list(scores), polys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--progress", default=None, help="进度 json 路径（导入进度展示用，可选）")
    args = ap.parse_args()

    # 进度回写（best-effort，不影响识别结果）：{phase: load/ocr/done, done, total, failed:[{name,idx}]}
    failed = []

    def wp(phase, done, total):
        if not args.progress:
            return
        try:
            with open(args.progress, "w", encoding="utf-8") as f:
                json.dump({"phase": phase, "done": done, "total": total, "failed": failed}, f)
        except Exception:
            pass

    img_dir = Path(args.images)
    imgs = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMG_EXT)
    if not imgs:
        sys.exit(f"目录无图片：{img_dir}")
    wp("load", 0, len(imgs))

    from PIL import Image, ImageOps
    from paddleocr import PaddleOCR
    # 归一图目录：把 EXIF 朝向烘焙进像素、去 EXIF，OCR/服务/尺寸三方统一坐标系
    norm_dir = Path(args.out).resolve().parent / "_img"
    norm_dir.mkdir(parents=True, exist_ok=True)
    print(f"加载 PaddleOCR(chinese_cht) … 共 {len(imgs)} 图")
    try:
        ocr = PaddleOCR(lang="chinese_cht", use_textline_orientation=True)
    except Exception as e:
        print("ctor(use_textline_orientation) failed -> plain:", repr(e))
        ocr = PaddleOCR(lang="chinese_cht")

    recog = {}
    for idx, img in enumerate(imgs):
        pid = img.stem
        norm_path = norm_dir / f"{pid}.jpg"
        try:
            oriented = ImageOps.exif_transpose(Image.open(img)).convert("RGB")  # 旋正
            W, H = oriented.size
            oriented.save(norm_path, "JPEG", quality=92)
            res = ocr.predict(str(norm_path))  # OCR 跑归一图，框落在 W×H 同一坐标系
            lines = []
            for r in res:
                texts, scores, polys = extract(r)
                polys = list(polys) if polys is not None else [None] * len(texts)
                for t, s, p in zip(texts, scores, polys):
                    lines.append({"text": t, "box": to_bbox(p) if p is not None else [0, 0, 0, 0],
                                  "score": round(float(s), 4)})
            recog[pid] = {"image": str(norm_path), "width": W, "height": H, "lines": lines}
            print(f"  {pid}: {len(lines)} 行  ({W}x{H})")
        except Exception as e:                 # 单图失败不阻断整体；登记空页保留原图供人工录入
            print(f"  FAIL {pid}: {e!r}")
            failed.append({"name": img.name, "idx": idx + 1})
            recog[pid] = {"image": str(norm_path) if norm_path.exists() else str(img),
                          "width": 0, "height": 0, "lines": [], "failed": True}
        wp("ocr", idx + 1, len(imgs))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(recog, f, ensure_ascii=False, indent=2)
    print("已写出:", args.out)
    wp("done", len(imgs), len(imgs))


if __name__ == "__main__":
    main()
