# -*- coding: utf-8 -*-
"""PaddleOCR(chinese_cht) 批量跑分器：识别一个图片目录，产出 eval 格式 pred.json。

一次加载模型，对每张图同时产出两种阅读顺序的预测，便于量化「右起栏序」的影响：
  - raw  ：PaddleOCR 给出的原始顺序（已知对竖排是左起，会有栏序错）。
  - rtl  ：按每行检测框的平均 x 坐标【降序】重排（右起），列内按平均 y 升序。
           这是「右起栏序」的朴素版，用来看 Phase 1 真要做的重排能救回多少 CER。

用法：
  python run_paddle.py --images <目录> --out-raw pred_raw.json [--out-rtl pred_rtl.json]
输出 pred.json：{ "<stem>": {"text": "...", "texts": [...], "scores": [...], "order": "raw|rtl"} }
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


def mean_x_y(poly):
    """poly 可能是 4 点 [[x,y]*4] 或盒子 [x1,y1,x2,y2]；返回 (mean_x, mean_y)。"""
    try:
        flat = list(poly)
        if flat and hasattr(flat[0], "__len__"):  # 点列表
            xs = [float(p[0]) for p in flat]
            ys = [float(p[1]) for p in flat]
            return sum(xs) / len(xs), sum(ys) / len(ys)
        if len(flat) == 4:  # [x1,y1,x2,y2]
            return (float(flat[0]) + float(flat[2])) / 2, (float(flat[1]) + float(flat[3])) / 2
    except Exception:
        pass
    return 0.0, 0.0


def extract(r):
    """从 PaddleOCR 3.x 单图结果取 (texts, scores, polys)。"""
    dd = None
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
    ap.add_argument("--images", required=True, help="图片目录")
    ap.add_argument("--out-raw", required=True, help="原始序 pred.json 输出路径")
    ap.add_argument("--out-rtl", default=None, help="右起重排 pred.json 输出路径（可选）")
    args = ap.parse_args()

    img_dir = Path(args.images)
    imgs = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMG_EXT)
    if not imgs:
        sys.exit(f"目录无图片：{img_dir}")

    from paddleocr import PaddleOCR
    print(f"加载 PaddleOCR(chinese_cht) … 共 {len(imgs)} 图")
    try:
        ocr = PaddleOCR(lang="chinese_cht", use_textline_orientation=True)
    except Exception as e:
        print("ctor(use_textline_orientation) failed -> plain:", repr(e))
        ocr = PaddleOCR(lang="chinese_cht")

    pred_raw, pred_rtl = {}, {}
    no_poly = 0
    for img in imgs:
        stem = img.stem
        res = ocr.predict(str(img))
        texts, scores, polys = [], [], None
        for r in res:
            t, s, p = extract(r)
            texts += t
            scores += s
            if p is not None:
                polys = list(p) if polys is None else polys + list(p)
        pred_raw[stem] = {"text": "".join(texts), "texts": texts,
                          "scores": [round(float(x), 4) for x in scores], "order": "raw"}
        # 右起重排
        if polys is not None and len(polys) == len(texts) and texts:
            keyed = []
            for t, p in zip(texts, polys):
                mx, my = mean_x_y(p)
                keyed.append((mx, my, t))
            keyed.sort(key=lambda z: (-z[0], z[1]))  # x 降序(右起)，y 升序(列内自上而下)
            rtl_texts = [z[2] for z in keyed]
        else:
            no_poly += 1
            rtl_texts = texts  # 无框信息退回原序
        pred_rtl[stem] = {"text": "".join(rtl_texts), "texts": rtl_texts, "order": "rtl"}
        print(f"  {stem}: {len(texts)} 行")

    Path(args.out_raw).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_raw, "w", encoding="utf-8") as f:
        json.dump(pred_raw, f, ensure_ascii=False, indent=2)
    print("已写出:", args.out_raw)
    if args.out_rtl:
        Path(args.out_rtl).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out_rtl, "w", encoding="utf-8") as f:
            json.dump(pred_rtl, f, ensure_ascii=False, indent=2)
        print("已写出:", args.out_rtl, f"（{no_poly} 图缺框信息退回原序）" if no_poly else "")


if __name__ == "__main__":
    main()
