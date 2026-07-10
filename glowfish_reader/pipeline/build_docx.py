# -*- coding: utf-8 -*-
"""整理本 docx 生成器（成品管线「识别后」末端，可复用）。

输入：段落列表（每段一行文本）。输出：对齐用户「输出样式」的简体整理本 docx——
A4、左右 3.2cm / 上下 2.5cm、五号字(10.5pt)、宋体、首行缩进 2 字符。

可选 --t2s：用 OpenCC 繁→简（识别若保留繁体原貌，导出简体成品时开启）。
⚠ 繁→简一对多（後/后、乾·幹→干、裡→里）会坍缩，整理本可接受；高保真辑录本勿盲转。

用法：
  python build_docx.py --paras-json paras.json --out out.docx [--t2s] [--title 标题]
  paras.json: {"paragraphs": ["第一段", "第二段", ...]}
"""
import sys
import json
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from docx import Document
from docx.shared import Pt, Cm
from docx.oxml.ns import qn


def make_doc(paragraphs, out_path, t2s=False, font="宋体", size_pt=10.5,
             indent_chars=2):
    if t2s:
        from opencc import OpenCC
        cc = OpenCC("t2s")
        paragraphs = [cc.convert(p) for p in paragraphs]

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)      # A4
    sec.left_margin = sec.right_margin = Cm(3.2)
    sec.top_margin = sec.bottom_margin = Cm(2.5)

    # Normal 样式：五号宋体
    normal = doc.styles["Normal"]
    normal.font.size = Pt(size_pt)
    normal.font.name = font
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), font)

    indent = Pt(size_pt * indent_chars)  # 首行缩进 = 字号 * 字数
    for text in paragraphs:
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = indent
        run = p.add_run(text)
        run.font.size = Pt(size_pt)
        run.font.name = font
        run._element.rPr.rFonts.set(qn("w:eastAsia"), font)

    doc.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paras-json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--t2s", action="store_true", help="OpenCC 繁→简")
    args = ap.parse_args()
    with open(args.paras_json, encoding="utf-8") as f:
        paras = json.load(f)["paragraphs"]
    make_doc(paras, args.out, t2s=args.t2s)
    print("已写出:", args.out, f"（{len(paras)} 段, t2s={args.t2s}）")


if __name__ == "__main__":
    main()
