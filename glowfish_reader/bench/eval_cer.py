# -*- coding: utf-8 -*-
"""Phase 0 评估器 v2：字符识别准确率（不计顺序：P/R/F1）+ 字级 CER（含顺序，参考）。

复用 Historical_Archive_Workflow/scripts/htr_eval.py 的 Levenshtein 与归一思路，
针对中文 + 本项目「简体点校整理本」口径改造。

验收主指标（本项目锁定口径：字符识别准确率，不计阅读顺序）：
  字符召回   recall    = |multiset(ref) ∩ multiset(hyp)| / |ref|
  字符精确率 precision = |multiset(ref) ∩ multiset(hyp)| / |hyp|   （防止多吐字虚高）
  字符识别准确率 F1     = 2·P·R / (P+R)   ← 楷体手写 ≥0.92 / 清晰印刷 ≥0.98 的验收数字
  字级 CER（Levenshtein / |ref|，含顺序错）保留为「版面/阅读序」参考。
  CER 高但 F1 高 ⇒ 字认得出、阅读顺序错（右起栏序/多栏串位问题）。

繁简归一：本项目输出简体整理本，gold 多为简体。`--t2s`（默认开）把 ref/hyp 都用
  OpenCC t2s 归一后再比，消除繁简差导致的虚高 CER；opencc 缺失则跳过并告警。

体裁分桶：gt.json 可带 "genre"（楷书/行楷/行书/草书/印刷/未分类），报告按体裁分桶 + 总分。

数据模型（与 batch.json 解耦，便于跨引擎基准）：
  金标准目录 gold/：每张图 <stem>.<ext> 配 <stem>.gt.json
      { "reading_order_rtl": "按右起阅读顺序的全文", "genre": "楷书", "columns": [...] }
  引擎预测 pred.json：{ "<stem>": {"text": "引擎输出全文（其自身阅读顺序）"} }

用法（CLI）：
  python eval_cer.py --gold <金标准目录> --pred <pred.json> [--label 引擎名] [--out 报告.md] [--no-t2s]
也可被 run_bench.py 直接 import 复用（evaluate / char_metrics / load_gold）。
"""
import sys
import os
import json
import re
import argparse
import unicodedata
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def edit_distance(a, b):
    """标准 Levenshtein，O(len(a)*len(b))。a、b 为序列（str 或 list[str]）。"""
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ai = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ai == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


def norm_cjk(s):
    """中文 CER 归一：去掉所有空白（中文无词间空格，OCR 插入的空格不应计入），
    保留标点与字形（辑录保真）。"""
    return re.sub(r"\s+", "", (s or "")).strip()


def strip_punct(s):
    """剥除标点/符号/分隔符（Unicode 类别 P/S/Z + 控制 C），只留汉字/字母/数字。
    本项目 gold 是「简体点校整理本」——现代标点是编者点校时加的、源图里没有，
    若计入会让 OCR 为读不到的标点背锅，故「识别准确率」口径下默认剥标点（与旧基线一致）。"""
    return "".join(ch for ch in (s or "")
                   if unicodedata.category(ch)[0] not in ("P", "S", "Z", "C"))


def multiset_overlap(ref, hyp):
    """多重集重叠字数：忽略顺序，衡量纯识别召回。"""
    return sum((Counter(ref) & Counter(hyp)).values())


# ---- 繁简归一（可选，缺 opencc 不阻断）----
_T2S = None
_T2S_READY = None


def _get_t2s():
    """惰性加载 OpenCC t2s；不可用返回 None（调用方据此告警）。"""
    global _T2S, _T2S_READY
    if _T2S_READY is None:
        try:
            from opencc import OpenCC
            _T2S = OpenCC("t2s")
            _T2S_READY = True
        except Exception:
            _T2S = None
            _T2S_READY = False
    return _T2S


def char_metrics(ref, hyp):
    """对一对（已归一）文本算全部指标。ref/hyp 为字符串。
    返回 dict：n_ref,n_hyp,overlap,cer,recall,precision,f1。"""
    n_ref, n_hyp = len(ref), len(hyp)
    ov = multiset_overlap(ref, hyp)
    cd = edit_distance(ref, hyp)
    recall = ov / n_ref if n_ref else 0.0
    precision = ov / n_hyp if n_hyp else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    cer = cd / n_ref if n_ref else (0.0 if n_hyp == 0 else 1.0)
    return {"n_ref": n_ref, "n_hyp": n_hyp, "overlap": ov,
            "cer": cer, "recall": recall, "precision": precision, "f1": f1}


def load_gold(gold_dir):
    """读 gold/*.gt.json -> {stem: {"text": 右起全文(已 norm), "genre": 体裁}}。"""
    gold = {}
    for fn in os.listdir(gold_dir):
        if fn.endswith(".gt.json"):
            stem = fn[: -len(".gt.json")]
            with open(os.path.join(gold_dir, fn), encoding="utf-8") as f:
                d = json.load(f)
            txt = d.get("reading_order_rtl")
            if txt is None:
                txt = "".join(d.get("columns", []) or [])
            gold[stem] = {"text": norm_cjk(txt), "genre": (d.get("genre") or "未分类")}
    return gold


def load_pred(pred_path):
    with open(pred_path, encoding="utf-8") as f:
        data = json.load(f)
    return {k: norm_cjk((v or {}).get("text", "") if isinstance(v, dict) else v)
            for k, v in data.items()}


def evaluate(gold, pred, t2s=True, punct=False):
    """核心评估（可被 run_bench import 复用）。
    gold: {stem: {"text","genre"}}；pred: {stem: 文本(已 norm)}。
    t2s：繁→简归一（默认开，本项目简体口径）。
    punct：是否保留标点参与评分（默认 False=剥标点，识别准确率口径）。
    返回 dict：{rows, overall, by_genre, aligned, missing, t2s_applied, punct}。"""
    conv = _get_t2s() if t2s else None
    t2s_applied = bool(conv)

    def _norm(x):
        if conv:
            x = conv.convert(x)
        if not punct:
            x = strip_punct(x)
        return x

    stems = sorted(gold)
    aligned = [s for s in stems if s in pred]
    missing = [s for s in stems if s not in pred]

    rows = []
    for s in aligned:
        ref = _norm(gold[s]["text"])
        hyp = _norm(pred[s])
        m = char_metrics(ref, hyp)
        m.update({"stem": s, "genre": gold[s]["genre"]})
        rows.append(m)

    overall = _agg(rows)
    genres = sorted({r["genre"] for r in rows})
    by_genre = {g: _agg([r for r in rows if r["genre"] == g]) for g in genres}
    return {"rows": rows, "overall": overall, "by_genre": by_genre,
            "aligned": aligned, "missing": missing,
            "t2s_applied": t2s_applied, "punct": punct}


def _agg(rows):
    """按 GT 字数加权聚合一组 rows -> 总指标。"""
    if not rows:
        return {"n_img": 0, "n_ref": 0, "cer": 0.0, "recall": 0.0, "precision": 0.0, "f1": 0.0}
    tot_ref = sum(r["n_ref"] for r in rows)
    tot_hyp = sum(r["n_hyp"] for r in rows)
    tot_ov = sum(r["overlap"] for r in rows)
    tot_cd = sum(round(r["cer"] * r["n_ref"]) for r in rows)
    recall = tot_ov / tot_ref if tot_ref else 0.0
    precision = tot_ov / tot_hyp if tot_hyp else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    cer = tot_cd / tot_ref if tot_ref else 0.0
    return {"n_img": len(rows), "n_ref": tot_ref, "cer": cer,
            "recall": recall, "precision": precision, "f1": f1}


def render_report(label, result):
    """把 evaluate() 结果渲染成 markdown。"""
    o = result["overall"]
    L = []
    L.append(f"# Phase 0 基准评估 v2 · {label}\n")
    L.append(f"- 对齐: {len(result['aligned'])} 项　|　t2s 简体归一: "
             + ("开" if result["t2s_applied"] else "**关（opencc 不可用，繁简差会拉高 CER）**")
             + "　|　标点: " + ("计入" if result.get("punct") else "剥除（识别准确率口径，源图无点校标点）"))
    if result["missing"]:
        L.append(f"- ⚠ 缺预测(未计入): {', '.join(result['missing'])}")
    L.append("\n## 总分（字符识别准确率 = F1，验收主指标）")
    L.append(f"- **字符识别准确率 F1: {o['f1']:.3f}**　（召回 {o['recall']:.3f} / 精确 {o['precision']:.3f}）")
    L.append(f"- 字级 CER（参考·含阅读顺序）: {o['cer']:.3f}　GT 字数 {o['n_ref']}")
    L.append("\n## 分体裁")
    L.append("| 体裁 | 图数 | GT字数 | **F1** | 召回 | 精确 | CER |\n|---|---|---|---|---|---|---|")
    for g, a in sorted(result["by_genre"].items()):
        L.append(f"| {g} | {a['n_img']} | {a['n_ref']} | **{a['f1']:.3f}** | "
                 f"{a['recall']:.3f} | {a['precision']:.3f} | {a['cer']:.3f} |")
    L.append("\n## 逐图")
    L.append("| 图 | 体裁 | GT字数 | F1 | 召回 | 精确 | CER |\n|---|---|---|---|---|---|---|")
    for r in result["rows"]:
        L.append(f"| {r['stem']} | {r['genre']} | {r['n_ref']} | {r['f1']:.3f} | "
                 f"{r['recall']:.3f} | {r['precision']:.3f} | {r['cer']:.3f} |")
    L.append("\n## 判读门槛（验收口径=字符识别准确率 F1）")
    L.append("- 清晰印刷体：F1 ≥ 0.98 → 免校档达标。")
    L.append("- 楷体手写：F1 ≥ 0.92 → 达标（待核初稿质量优，配人工校对成成品）。")
    L.append("- 0.85 ≤ F1 < 目标 → 待核初稿可用、未达标，需升级识别（视觉大模型/微调）。")
    L.append("- F1 < 0.85 → 通用引擎不胜任。")
    L.append("- CER ≫ (1−F1) ⇒ 字对序错，归 P3 版面栏序引擎，不计入字准口径。")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True, help="金标准目录（含 <stem>.gt.json）")
    ap.add_argument("--pred", required=True, help="引擎预测 pred.json")
    ap.add_argument("--label", default="engine", help="引擎名（写入报告）")
    ap.add_argument("--out", default=None, help="报告输出路径（默认 pred 同目录）")
    ap.add_argument("--no-t2s", dest="t2s", action="store_false",
                    help="关闭繁→简归一（默认开；本项目简体整理本口径建议保持开）")
    ap.add_argument("--keep-punct", dest="punct", action="store_true",
                    help="标点计入评分（默认剥除；识别准确率口径下源图无点校标点，建议保持剥除）")
    ap.set_defaults(t2s=True, punct=False)
    args = ap.parse_args()

    gold = load_gold(args.gold)
    pred = load_pred(args.pred)
    if not gold:
        sys.exit(f"金标准目录无 *.gt.json：{args.gold}")

    result = evaluate(gold, pred, t2s=args.t2s, punct=args.punct)
    if args.t2s and not result["t2s_applied"]:
        print("⚠ 请求 t2s 但 opencc 不可用——已按原文比对，繁简差会拉高 CER。"
              "请在含 opencc 的 server/codex env 跑，或加 --no-t2s 明确关闭。")

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.pred)),
                                   f"CER报告_{args.label}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_report(args.label, result))
    o = result["overall"]
    print(f"[{args.label}] F1={o['f1']:.3f} 召回={o['recall']:.3f} 精确={o['precision']:.3f} "
          f"CER={o['cer']:.3f} 对齐 {len(result['aligned'])} 项"
          + (f"（缺 {len(result['missing'])}）" if result["missing"] else ""))
    print("已写出:", out)


if __name__ == "__main__":
    main()
