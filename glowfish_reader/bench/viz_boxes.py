# -*- coding: utf-8 -*-
"""检测框叠图：把 OCR 行框、列检测框、未覆盖列画到原图上，肉眼定位「丢列」。

行框按 source 着色（full_enhanced / column_rescue / …），列框（ocr_rescue.
find_vertical_text_columns）画虚线，uncovered_columns 用粗红框高亮——红框 = 列检测
认为有字、但没有任何 OCR 行盖住它，即整列漏检的几何证据。

用法（paddleocr env，需 PIL + numpy）：
  python bench/viz_boxes.py --recog out/手写_ppocrv6_onnx_high_recog.json --out out/_viz
  python bench/viz_boxes.py --recog out/s04_baseline_recog.json --only s04_p1
"""
import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "proofread"))

import ocr_rescue  # noqa: E402

SOURCE_COLORS = {
    "full_enhanced": (0, 170, 0),
    "full_degraded_preproc": (0, 190, 190),
    "body_crop": (30, 90, 240),
    "column_rescue": (255, 140, 0),
    "column_wide_rescue": (170, 0, 200),
    "column_uncovered_rescue": (0, 200, 120),
}
DEFAULT_COLOR = (120, 120, 120)
COLUMN_COLOR = (0, 0, 0)
UNCOVERED_COLOR = (230, 0, 0)
MAX_SIDE = 1600


def _dashed_rect(draw, box, color, dash=18, gap=12, width=2):
    """PIL 无虚线，手工分段画矩形。"""
    x1, y1, x2, y2 = box
    for x in range(int(x1), int(x2), dash + gap):
        xe = min(x + dash, x2)
        draw.line([(x, y1), (xe, y1)], fill=color, width=width)
        draw.line([(x, y2), (xe, y2)], fill=color, width=width)
    for y in range(int(y1), int(y2), dash + gap):
        ye = min(y + dash, y2)
        draw.line([(x1, y), (x1, ye)], fill=color, width=width)
        draw.line([(x2, y), (x2, ye)], fill=color, width=width)


def _scaled(box, k):
    return [v * k for v in box]


def _load_page_image(page, images_dir):
    from PIL import Image, ImageOps

    for cand in (page.get("image"), images_dir):
        if not cand:
            continue
        path = Path(cand)
        if path.is_file():
            return ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return None


def _legend(draw, font, sources, columns, uncovered):
    rows = [(f"columns={columns}  uncovered={uncovered}", UNCOVERED_COLOR if uncovered else (0, 0, 0))]
    rows += [(f"{s} x{n}", SOURCE_COLORS.get(s, DEFAULT_COLOR)) for s, n in sorted(sources.items())]
    for i, (text, color) in enumerate(rows):
        y = 6 + i * 14
        draw.rectangle([4, y, 14, y + 10], fill=color)
        draw.text((18, y), text, fill=(0, 0, 0), font=font)


def render_page(pid, page, images_dir, out_dir):
    from PIL import Image, ImageDraw, ImageFont

    image = _load_page_image(page, images_dir)
    if image is None:
        print(f"  [{pid}] 找不到原图，跳过")
        return None

    lines = page.get("lines") or []
    columns = ocr_rescue.find_vertical_text_columns(image)
    uncovered = ocr_rescue.uncovered_columns(columns, lines)
    uncovered_set = {tuple(b) for b in uncovered}

    k = min(1.0, MAX_SIDE / max(image.size))
    canvas = image.resize((max(1, int(image.width * k)), max(1, int(image.height * k))), Image.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for idx, col in enumerate(columns):
        hit = tuple(col) in uncovered_set
        box = _scaled(col, k)
        if hit:
            draw.rectangle(box, outline=UNCOVERED_COLOR, width=4)
            draw.text((box[0] + 4, box[1] + 4), f"MISS c{idx}", fill=UNCOVERED_COLOR, font=font)
        else:
            _dashed_rect(draw, box, COLUMN_COLOR)

    sources = {}
    for line in lines:
        src = line.get("source") or "?"
        sources[src] = sources.get(src, 0) + 1
        color = SOURCE_COLORS.get(src, DEFAULT_COLOR)
        draw.rectangle(_scaled(line.get("box") or [0, 0, 0, 0], k), outline=color, width=2)

    _legend(draw, font, sources, len(columns), len(uncovered))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pid}_viz.png"
    canvas.save(out_path)
    print(f"  [{pid}] lines={len(lines)} columns={len(columns)} uncovered={len(uncovered)} -> {out_path.name}")
    return {"page_id": pid, "lines": len(lines), "columns": len(columns),
            "uncovered": len(uncovered), "uncovered_boxes": [list(b) for b in uncovered]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recog", required=True, help="识别输出 *_recog.json")
    ap.add_argument("--images", default=None, help="原图目录（recog 内 image 路径失效时兜底）")
    ap.add_argument("--out", default="out/_viz", help="叠框图输出目录")
    ap.add_argument("--only", default=None, help="只画这一页（page_id）")
    args = ap.parse_args()

    recog = json.loads((HERE / args.recog).read_text(encoding="utf-8")
                       if not Path(args.recog).is_absolute() else
                       Path(args.recog).read_text(encoding="utf-8"))
    out_dir = HERE / args.out if not Path(args.out).is_absolute() else Path(args.out)

    stats = []
    for pid, page in sorted(recog.items()):
        if args.only and pid != args.only:
            continue
        row = render_page(pid, page, args.images, out_dir)
        if row:
            stats.append(row)

    summary = out_dir / "_viz_summary.json"
    summary.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(r["uncovered"] for r in stats)
    print(f"[viz] {len(stats)} 页，未覆盖列合计 {total} -> {summary}")


if __name__ == "__main__":
    main()
