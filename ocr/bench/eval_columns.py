# -*- coding: utf-8 -*-
"""列级丢失指标：补上「整列漏检」在 eval_cer 里只能靠 recall 掉分间接观察的空白。

两个口径：
  GT 口径   del_run_chars —— 连续漏 ≥3 字的编辑操作字符数（复用 analyze_hw_errors.classify）。
            整列丢失必然表现为一段长 del_run，故它是「丢列」最贴近 GT 的代理指标。
  几何口径  uncovered      —— 列检测框里没有任何 OCR 行盖住的列数，无需 GT，逐页可算。
            同时给两种覆盖判据：
              lib  = ocr_rescue.uncovered_columns（线上现用；x 重叠按含 pad 列宽算）
              core = 剥掉 ±35% pad 后要求行的 x 中心落在列核心区间
            lib≫core 说明线上判据被邻列长行「假覆盖」骗过——这正是丢列漏报的原因。
            （core 判据 Phase-1 将迁入 proofread/ocr_coverage.py，届时本文件改为 import。）

用法（paddleocr env）：
  python bench/eval_columns.py --recog out/手写_ppocrv6_onnx_high_recog.json --report out/列级指标.md
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "proofread"))

import eval_cer                                     # noqa: E402
import ocr_rescue                                   # noqa: E402
from analyze_hw_errors import classify              # noqa: E402
from run_bench import recog_to_pred_rtl, group_pages_to_docs  # noqa: E402

PAD_RATIO = 0.35        # find_vertical_text_columns 的 pad_x 比例（相对原始 span）
CORE_Y_MIN = 0.35       # 与 uncovered_columns 的 y 判据保持一致


def core_span(box, width_limit=None):
    """把 find_vertical_text_columns 的含 pad 列框还原成核心区间。

    padded_w = span*(1+2*PAD_RATIO) ⇒ pad = padded_w*PAD_RATIO/(1+2*PAD_RATIO)。
    贴边列（x1=0 或 x2=图宽）只有一侧 pad 被裁掉，这里按对称估计，宁可核心区间偏窄。
    """
    x1, x2 = float(box[0]), float(box[2])
    pad = (x2 - x1) * PAD_RATIO / (1.0 + 2.0 * PAD_RATIO)
    return x1 + pad, x2 - pad


def _y_overlap(col, box):
    cy1, cy2 = float(col[1]), float(col[3])
    ch = max(1.0, cy2 - cy1)
    return max(0.0, min(cy2, float(box[3])) - max(cy1, float(box[1]))) / ch


def uncovered_core(columns, lines):
    """严判：行的 x 中心必须落在列核心区间内，才算盖住这一列。"""
    missing = []
    for col in columns or []:
        lo, hi = core_span(col)
        covered = False
        for line in lines or []:
            box = (line.get("box") or [0, 0, 0, 0])[:4]
            cx = (float(box[0]) + float(box[2])) / 2.0
            if lo <= cx <= hi and _y_overlap(col, box) >= CORE_Y_MIN:
                covered = True
                break
        if not covered:
            missing.append(col)
    return missing


def geometric_rows(recog):
    from PIL import Image, ImageOps

    rows = []
    for pid, page in sorted(recog.items()):
        path = Path(page.get("image") or "")
        if not path.is_file():
            rows.append({"page_id": pid, "error": "原图缺失"})
            continue
        image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        lines = page.get("lines") or []
        columns = ocr_rescue.find_vertical_text_columns(image)
        rows.append({
            "page_id": pid,
            "columns": len(columns),
            "lines": len(lines),
            "uncovered_lib": len(ocr_rescue.uncovered_columns(columns, lines)),
            "uncovered_core": len(uncovered_core(columns, lines)),
        })
    return rows


def _run_len(item):
    """classify() 的 del_run 条目形如 `上文【漏:被漏字串】下文`，取被漏字串长度。"""
    try:
        return len(item.split("【漏:")[1].split("】")[0])
    except (IndexError, AttributeError):
        return 0


def gt_rows(recog, gold_dir):
    gold = eval_cer.load_gold(str(gold_dir))
    pages = {k: eval_cer.norm_cjk(v["text"]) for k, v in recog_to_pred_rtl(recog).items()}
    docs = group_pages_to_docs(pages, list(gold))
    conv = eval_cer._get_t2s()

    def _norm(text):
        return eval_cer.strip_punct(conv.convert(text) if conv else text)

    rows = []
    for stem in sorted(gold):
        ref, hyp = _norm(gold[stem]["text"]), _norm(docs.get(stem, ""))
        buckets = classify(ref, hyp)
        runs = buckets["del_run"]
        chars = sum(_run_len(item) for item in runs)
        metrics = eval_cer.char_metrics(ref, hyp)
        rows.append({
            "stem": stem, "genre": gold[stem]["genre"], "n_ref": len(ref),
            "del_runs": len(runs), "del_run_chars": chars,
            "del_run_share": chars / len(ref) if ref else 0.0,
            "recall": metrics["recall"], "f1": metrics["f1"], "cer": metrics["cer"],
            "worst_run": max(runs, key=_run_len, default=""),
        })
    return rows


def render(gt, geo, label):
    lines = [f"# 列级丢失指标 · {label}", "",
             "- `del_run_chars`：连续漏 ≥3 字的总字符数（整列丢失的 GT 代理指标）。",
             "- `uncovered_lib` / `uncovered_core`：线上判据 vs 剥 pad 严判。"
             "两者不等 ⇒ 线上 `uncovered_columns` 被邻列长行假覆盖骗过。", ""]
    if gt:
        lines += ["## GT 口径（按文档）", "",
                  "| 文档 | 体裁 | GT字数 | 漏段数 | 漏段字数 | 占比 | 召回 | F1 | CER |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in gt:
            lines.append(
                f"| {r['stem']} | {r['genre']} | {r['n_ref']} | {r['del_runs']} | "
                f"**{r['del_run_chars']}** | {r['del_run_share']:.1%} | {r['recall']:.3f} | "
                f"{r['f1']:.3f} | {r['cer']:.3f} |")
        lines.append("")
        worst = [r for r in gt if r["worst_run"]]
        if worst:
            lines += ["### 最长漏段（每文档）", ""]
            lines += [f"- `{r['stem']}`: {r['worst_run']}" for r in worst]
            lines.append("")
    lines += ["## 几何口径（按页，无需 GT）", "",
              "| 页 | 列检出 | OCR行 | uncovered_lib | uncovered_core |", "|---|---|---|---|---|"]
    for r in geo:
        if r.get("error"):
            lines.append(f"| {r['page_id']} | - | - | - | {r['error']} |")
            continue
        flag = " ⚠" if r["uncovered_core"] > r["uncovered_lib"] else ""
        lines.append(f"| {r['page_id']} | {r['columns']} | {r['lines']} | "
                     f"{r['uncovered_lib']} | **{r['uncovered_core']}**{flag} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recog", required=True)
    ap.add_argument("--gold", default="gold_handwritten")
    ap.add_argument("--report", default="out/列级指标.md")
    ap.add_argument("--label", default=None)
    ap.add_argument("--no-gt", dest="use_gt", action="store_false")
    ap.set_defaults(use_gt=True)
    args = ap.parse_args()

    recog_path = Path(args.recog) if Path(args.recog).is_absolute() else HERE / args.recog
    recog = json.loads(recog_path.read_text(encoding="utf-8"))

    geo = geometric_rows(recog)
    gt = gt_rows(recog, HERE / args.gold) if args.use_gt else []

    out = HERE / args.report if not Path(args.report).is_absolute() else Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(gt, geo, args.label or recog_path.stem), encoding="utf-8")

    total_del = sum(r["del_run_chars"] for r in gt)
    total_core = sum(r.get("uncovered_core", 0) for r in geo)
    total_lib = sum(r.get("uncovered_lib", 0) for r in geo)
    print(f"[eval_columns] del_run_chars={total_del}  uncovered_lib={total_lib}  "
          f"uncovered_core={total_core}  -> {out}")


if __name__ == "__main__":
    main()
