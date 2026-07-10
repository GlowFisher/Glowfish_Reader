# -*- coding: utf-8 -*-
"""导入摊平器（codex env）：把用户选的文件夹/文件(jpg/png/pdf)摊成一个有序图片目录。

- 图片：直接拷成 PNG（朝向归一交给 recognize.py）。
- PDF：逐页处理——优先取整页最大内嵌图(原生分辨率)，否则按 dpi 渲染整页。
产出 out_dir/NNNN_<stem>.png（零填充前缀保序，recognize 按文件名排序即得阅读顺序）。
"""
import io
import re
import sys
import shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def _natkey(name: str):
    """自然排序键：把文件名拆成文本/数字交替块，数字块按数值比较，
    使 1<2<…<10<11（而非字典序 1<10<2）。"""
    parts = re.split(r"(\d+)", str(name))
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def _collect(paths):
    """展开 paths(文件/目录) → 有序 [(kind, Path)]，kind ∈ {'img','pdf'}。"""
    items = []

    def add(p):
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.iterdir(), key=lambda x: _natkey(x.name)):
                if f.is_file() and (f.suffix.lower() in IMG_EXT or f.suffix.lower() == ".pdf"):
                    add(f)
        elif p.suffix.lower() == ".pdf":
            items.append(("pdf", p))
        elif p.suffix.lower() in IMG_EXT:
            items.append(("img", p))

    for p in paths:
        add(p)
    return items


def _largest_image_xref(page):
    imgs = page.get_images(full=True)
    if not imgs:
        return None
    return max(imgs, key=lambda im: im[2] * im[3])[0]


# ---- explode / explode_ordered 共用的单图/单页写盘 ----
def _save_image_file(src, dst):
    """图片：旋正 EXIF → RGB → 存为 PNG。"""
    from PIL import Image, ImageOps
    ImageOps.exif_transpose(Image.open(src)).convert("RGB").save(dst)


def _save_pdf_page(doc, pno, dst, dpi):
    """PDF 单页：优先取整页最大内嵌图(原生分辨率)，否则按 dpi 渲染整页。"""
    from PIL import Image
    xref = _largest_image_xref(doc[pno])
    if xref is not None:
        raw = doc.extract_image(xref)
        Image.open(io.BytesIO(raw["image"])).convert("RGB").save(dst)
    else:
        doc[pno].get_pixmap(dpi=dpi).save(str(dst))


def explode(paths, out_dir, dpi=220):
    """把 paths 摊成 out_dir 下的有序 PNG，返回产出文件列表。"""
    import fitz  # PyMuPDF

    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    items = _collect(paths)
    produced, idx = [], 0
    for kind, p in items:
        if kind == "img":
            idx += 1
            dst = out / f"{idx:04d}_{p.stem}.png"
            _save_image_file(p, dst)
            produced.append(dst)
        else:  # pdf
            doc = fitz.open(p)
            for pno in range(len(doc)):
                idx += 1
                dst = out / f"{idx:04d}_{p.stem}_p{pno + 1}.png"
                _save_pdf_page(doc, pno, dst, dpi)
                produced.append(dst)
            doc.close()
    return produced


def explode_ordered(items, out_dir, dpi=220, progress=None):
    """按用户在「导入素材排序弹窗」里定的顺序摊平。
    items: 有序 [{path, type: 'image'|'pdf'|'pdfpage', page?(1基,仅 pdfpage)}]。
    'pdf' = 整本所有页就地展开；'pdfpage' = 仅该页。零填充前缀保用户序。"""
    import fitz  # PyMuPDF

    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    produced, idx, cache = [], 0, {}

    def emit(src, page=None, pages=None):
        if not progress:
            return
        try:
            progress(idx, str(src), page, pages)
        except Exception:
            pass

    def doc_of(p):
        if p not in cache:
            cache[p] = fitz.open(p)
        return cache[p]

    def write_page(p, pno, stem):
        nonlocal idx
        idx += 1
        dst = out / f"{idx:04d}_{stem}_p{pno + 1}.png"
        _save_pdf_page(doc_of(p), pno, dst, dpi)
        produced.append(dst)
        emit(p, pno + 1, len(doc_of(p)))

    try:
        for it in items:
            p = Path(it["path"])
            stem = p.stem
            typ = it.get("type")
            if typ == "pdfpage":
                write_page(p, int(it["page"]) - 1, stem)
            elif typ == "pdf" or p.suffix.lower() == ".pdf":
                for pno in range(len(doc_of(p))):
                    write_page(p, pno, stem)
            else:  # image
                idx += 1
                dst = out / f"{idx:04d}_{stem}.png"
                _save_image_file(p, dst)
                produced.append(dst)
                emit(p)
    finally:
        for d in cache.values():
            d.close()
    return produced


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("paths", nargs="+")
    a = ap.parse_args()
    files = explode(a.paths, a.out)
    print(f"摊平 {len(files)} 图 → {a.out}")
