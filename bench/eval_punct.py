# -*- coding: utf-8 -*-
"""本地标点（punctuate_local）断句质量评测 + 错误归因。

思路：金标准 .gt.json 的 reading_order_rtl 带人工句读 → 剥掉标点得素文 →
喂 punctuate_local 重新断句 → 以「字 i 之后是否有标点」为事件比对边界，算断句 P/R/F1；
在双方都断的位置再比符号是否一致（类型准确率）。错误分三类：
  漏断（金标准有、模型无）/ 多断（模型有、金标准无）/ 类型不同（都断但符号异）。

模型「不增删汉字」结构性保证 → 双方素文逐字对齐，无需编辑距离对齐。
可选 --int8-ab：fp32 与 int8 两个模型各跑一遍，出量化退化对照（量化闸门用）。

用法（.venv python，PYTHONUTF8=1）：
  python bench/eval_punct.py                      # 全部金标准集
  python bench/eval_punct.py --gold gold_handwritten --report out/punct_report.md
"""
import sys
import json
import argparse
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "proofread"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import punctuate_local  # noqa: E402


def _is_punct(ch):
    return unicodedata.category(ch)[0] in ("P", "S")


def split_events(text):
    """带标点文本 → (素文字符列表, {字下标: 其后紧跟的标点串})。空白忽略。"""
    chars, events = [], {}
    for ch in text or "":
        if ch.isspace():
            continue
        if _is_punct(ch):
            if chars:                              # 句首标点（罕见）无所附字，忽略
                events[len(chars) - 1] = events.get(len(chars) - 1, "") + ch
        else:
            chars.append(ch)
    return chars, events


def compare_events(gold_events, pred_events, chars, ctx=6):
    """边界事件比对 → 指标与错误样本（带上下文，供人工归因）。"""
    g, p = set(gold_events), set(pred_events)
    hit = g & p
    miss = sorted(g - p)                            # 漏断
    extra = sorted(p - g)                           # 多断
    typediff = sorted(i for i in hit if gold_events[i] != pred_events[i])

    def _ctx(i, mark_pred=False):
        lo, hi = max(0, i - ctx + 1), min(len(chars), i + ctx + 1)
        seg = "".join(chars[lo:i + 1]) + "▏" + "".join(chars[i + 1:hi])
        note = pred_events.get(i, "") if mark_pred else gold_events.get(i, "")
        return f"…{seg}…（金:{gold_events.get(i, '∅')} 模:{pred_events.get(i, '∅')}）" if note or True else seg

    prec = len(hit) / len(p) if p else 1.0
    rec = len(hit) / len(g) if g else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    type_acc = (len(hit) - len(typediff)) / len(hit) if hit else 1.0
    return {
        "gold_breaks": len(g), "pred_breaks": len(p), "hit": len(hit),
        "precision": prec, "recall": rec, "f1": f1, "type_acc": type_acc,
        "miss": [_ctx(i) for i in miss],
        "extra": [_ctx(i, True) for i in extra],
        "typediff": [_ctx(i) for i in typediff],
    }


def eval_doc(gold_text, punctuate_fn):
    chars, gold_events = split_events(gold_text)
    raw = "".join(chars)
    pred_lines = punctuate_fn([raw])
    pred_chars, pred_events = split_events(pred_lines[0])
    if pred_chars != chars:                        # 理论上不可能（不增删汉字保证）
        raise RuntimeError("素文对齐失败：模型改动了汉字序列")
    return compare_events(gold_events, pred_events, chars)


def load_gold_texts(gold_dir):
    docs = {}
    for f in sorted(Path(gold_dir).glob("*.gt.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        t = d.get("reading_order_rtl") or ""
        if t:
            docs[f.stem.replace(".gt", "")] = t
    return docs


def render(rows, label, max_samples=20):
    lines = [f"## {label}", ""]
    lines.append("| 文档 | 金标准断点 | 模型断点 | 命中 | 断句P | 断句R | 断句F1 | 符号一致率 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    tg = tp = th = ttd = 0
    for name, r in rows:
        lines.append(f"| {name} | {r['gold_breaks']} | {r['pred_breaks']} | {r['hit']} | "
                     f"{r['precision']:.3f} | {r['recall']:.3f} | {r['f1']:.3f} | {r['type_acc']:.3f} |")
        tg += r["gold_breaks"]; tp += r["pred_breaks"]; th += r["hit"]
        ttd += round((1 - r["type_acc"]) * r["hit"])
    prec = th / tp if tp else 1.0
    rec = th / tg if tg else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    lines.append(f"| **总计** | {tg} | {tp} | {th} | **{prec:.3f}** | **{rec:.3f}** | "
                 f"**{f1:.3f}** | {(th - ttd) / th if th else 1.0:.3f} |")
    lines.append("")
    for kind, title in (("miss", "漏断"), ("extra", "多断"), ("typediff", "符号类型不同")):
        samples = [s for _, r in rows for s in r[kind]]
        lines.append(f"### {title}（共 {len(samples)}，示例前 {min(len(samples), max_samples)} 条）")
        lines += [f"- {s}" for s in samples[:max_samples]]
        lines.append("")
    return "\n".join(lines), f1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="gold_handwritten", help="金标准目录（相对 bench/）")
    ap.add_argument("--report", default="out/punct_report.md")
    ap.add_argument("--int8-ab", action="store_true",
                    help="fp32 vs int8 双跑对照（需 models/punct/model_int8.onnx）")
    args = ap.parse_args()

    docs = load_gold_texts(HERE / args.gold)
    if not docs:
        print(f"金标准目录无 .gt.json：{args.gold}")
        return 1

    sections = []
    rows = [(n, eval_doc(t, punctuate_local.local_punctuate)) for n, t in sorted(docs.items())]
    sec, f1_default = render(rows, f"当前默认模型 · {args.gold}")
    sections.append(sec)
    print(f"[eval_punct] 默认模型 断句F1 = {f1_default:.3f}")

    if args.int8_ab:
        # 双跑对照：借 SHUPAI 无关、直接切 punctuate_local 的模型文件指向
        variants = [("fp32", "model.onnx"), ("int8", "model_int8.onnx")]
        for tag, fname in variants:
            mp = Path(punctuate_local._DIR) / fname
            if not mp.exists():
                print(f"[eval_punct] 跳过 {tag}：缺 {mp.name}")
                continue
            punctuate_local._SESS = None                       # 强制重载
            orig = punctuate_local._load

            def _load_with(fname=fname):
                import onnxruntime as ort
                punctuate_local._META = json.loads(
                    (punctuate_local._DIR / "meta.json").read_text(encoding="utf-8"))
                toks = (punctuate_local._DIR / "vocab.txt").read_text(encoding="utf-8").split("\n")
                punctuate_local._VOCAB = {t: i for i, t in enumerate(toks) if t != ""}
                id2label = {int(k): v for k, v in punctuate_local._META["id2label"].items()}
                punctuate_local._L2P = {i: ("" if v == "O" else v) for i, v in id2label.items()}
                so = ort.SessionOptions()
                punctuate_local._SESS = ort.InferenceSession(
                    str(punctuate_local._DIR / fname), sess_options=so,
                    providers=["CPUExecutionProvider"])

            punctuate_local._load = _load_with
            try:
                rows = [(n, eval_doc(t, punctuate_local.local_punctuate))
                        for n, t in sorted(docs.items())]
                sec, f1 = render(rows, f"{tag}（{fname}）· {args.gold}")
                sections.append(sec)
                print(f"[eval_punct] {tag} 断句F1 = {f1:.3f}")
            finally:
                punctuate_local._load = orig
                punctuate_local._SESS = None

    out = HERE / args.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# 本地标点断句评测报告\n\n" + "\n\n".join(sections), encoding="utf-8")
    print(f"[eval_punct] 报告已写出: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
