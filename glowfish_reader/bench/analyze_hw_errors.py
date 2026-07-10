# -*- coding: utf-8 -*-
"""手写集失败样本归因：对 PP-OCRv6（或任意引擎）的识别输出做字级编辑操作回溯，
把错误分类为 字形混淆 / 漏字 / 漏行漏段(连续删≥3) / 幻觉插入(连续插≥3) / 多字，
并用 CER 与 (1−F1) 的差值提示阅读序错位占比。产出 go/no-go 归因报告。

用法（.venv python）：
  python bench/analyze_hw_errors.py --recog out/手写_ppocrv6_recog.json \
      --gold gold_handwritten --report out/hw_error_taxonomy.md
"""
import sys
import json
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import eval_cer                       # noqa: E402  复用 norm/strip/t2s/度量
from run_bench import recog_to_pred_rtl, group_pages_to_docs  # noqa: E402


def edit_ops(ref, hyp):
    """Levenshtein 回溯 → [(op, i_ref, j_hyp)]，op ∈ eq/sub/del/ins。O(nm)，777 字级别无压力。"""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            c = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + c)
    ops, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1):
            ops.append(("eq" if ref[i - 1] == hyp[j - 1] else "sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(("del", i - 1, j))
            i -= 1
        else:
            ops.append(("ins", i, j - 1))
            j -= 1
    return list(reversed(ops))


def classify(ref, hyp, ctx=5):
    """编辑操作 → 错误分类桶（带上下文样本）。"""
    ops = edit_ops(ref, hyp)
    buckets = {"sub": [], "del_run": [], "del_iso": [], "ins_run": [], "ins_iso": []}
    k = 0
    while k < len(ops):
        op, i, j = ops[k]
        if op == "eq":
            k += 1
            continue
        run = [ops[k]]
        while k + 1 < len(ops) and ops[k + 1][0] == op:
            run.append(ops[k + 1])
            k += 1
        k += 1
        if op == "sub":
            for _, ri, hj in run:
                lo = max(0, ri - ctx)
                buckets["sub"].append(
                    f"{ref[lo:ri]}【{ref[ri]}→{hyp[hj]}】{ref[ri + 1:ri + 1 + ctx]}")
        elif op == "del":
            seg = "".join(ref[ri] for _, ri, _ in run)
            lo = max(0, run[0][1] - ctx)
            item = f"{ref[lo:run[0][1]]}【漏:{seg}】{ref[run[-1][1] + 1:run[-1][1] + 1 + ctx]}"
            buckets["del_run" if len(run) >= 3 else "del_iso"].append(item)
        elif op == "ins":
            seg = "".join(hyp[hj] for _, _, hj in run)
            lo = max(0, run[0][2] - ctx)
            item = f"{hyp[lo:run[0][2]]}【多:{seg}】{hyp[run[-1][2] + 1:run[-1][2] + 1 + ctx]}"
            buckets["ins_run" if len(run) >= 3 else "ins_iso"].append(item)
    return buckets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recog", default="out/手写_ppocrv6_recog.json")
    ap.add_argument("--gold", default="gold_handwritten")
    ap.add_argument("--report", default="out/hw_error_taxonomy.md")
    args = ap.parse_args()

    recog = json.loads((HERE / args.recog).read_text(encoding="utf-8"))
    gold = eval_cer.load_gold(str(HERE / args.gold))
    pred_pages = {k: v["text"] for k, v in recog_to_pred_rtl(recog).items()}
    pred_pages = {k: eval_cer.norm_cjk(t) for k, t in pred_pages.items()}
    docs = group_pages_to_docs(pred_pages, list(gold.keys()))

    conv = eval_cer._get_t2s()

    def _norm(x):
        x = conv.convert(x) if conv else x
        return eval_cer.strip_punct(x)

    lines = ["# 手写集失败样本归因（错误类型分布）", "",
             f"- 识别输出: `{args.recog}`　金标准: `{args.gold}`",
             "- 口径: t2s 简体归一 + 剥标点后按字级编辑操作分类；"
             "「漏行漏段/幻觉插入」= 连续删/插 ≥3 字。", ""]
    titles = {"sub": "字形混淆（替换）", "del_run": "漏行漏段（连续漏≥3字）",
              "del_iso": "漏字（孤立）", "ins_run": "幻觉插入（连续多≥3字）",
              "ins_iso": "多字（孤立）"}
    for stem in sorted(gold):
        ref, hyp = _norm(gold[stem]["text"]), _norm(docs.get(stem, ""))
        m = eval_cer.char_metrics(ref, hyp)
        order_gap = m["cer"] - (1 - m["f1"])
        buckets = classify(ref, hyp)
        total_err = sum(len(v) for v in buckets.values())
        lines.append(f"## {stem}（{gold[stem]['genre']}）  F1={m['f1']:.3f}  CER={m['cer']:.3f}"
                     f"  阅读序错位信号(CER−(1−F1))={order_gap:.3f}")
        lines.append("")
        lines.append("| 类型 | 计数 | 占比 |")
        lines.append("|---|---|---|")
        for key, title in titles.items():
            n = len(buckets[key])
            lines.append(f"| {title} | {n} | {n / total_err:.0%} |" if total_err
                         else f"| {title} | 0 | - |")
        lines.append("")
        for key, title in titles.items():
            if buckets[key]:
                lines.append(f"### {stem} · {title}（前 15）")
                lines += [f"- {s}" for s in buckets[key][:15]]
                lines.append("")
    out = HERE / args.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[analyze_hw] 报告已写出: {out}")


if __name__ == "__main__":
    main()
