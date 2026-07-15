# -*- coding: utf-8 -*-
"""双行夹注检测与层级读序（纯几何，零模型）—— 迭代1.

在 proof_model.build_proof 内、aggregate_columns 之前调用：把配成对的双行小字夹注
合并成一条“合成行”（text=右半+左半，box=并集，宽≈主列宽）。这样下游
aggregate_columns（x-overlap 并查集）与 default_order（-mean_x 栏序）零改动即可把
夹注正确放回其所属主列的 y 位——避免旧行为里“夹注左右小行被误并、y 重叠致文字交错”。

宁漏勿错：配不上对的候选一律不动；三行小注/眉批 out of scope。
开关：SHUPAI_INTERLINEAR=0 关闭（默认开）。
审计：合成行带 interlinear=True + member_boxes/member_texts/member_scores 可还原到成员小行
（注：若合成行随后被 aggregate_columns 并入多行主列，成员粒度会折叠为列级 member，属已知限制，
不影响读序正确性）。
"""
import os


def _w(b):
    return b[2] - b[0]


def _h(b):
    return b[3] - b[1]


def _cx(b):
    return (b[0] + b[2]) / 2.0


def _y_overlap_ratio(a, b):
    """两框在 y 方向的重叠占较矮高度的比例。"""
    inter = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    short = max(1.0, min(_h(a), _h(b)))
    return inter / short


def _x_overlap(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def _main_column_width(boxes):
    """主列宽 W = 行框宽前 60% 分位的中位数（滤掉窄夹注/碎块对 W 的拉低）。"""
    ws = sorted((_w(b) for b in boxes), reverse=True)
    if not ws:
        return 0.0
    top = ws[: max(1, int(len(ws) * 0.6))]
    n = len(top)
    mid = n // 2
    return float(top[mid]) if n % 2 else (top[mid - 1] + top[mid]) / 2.0


def enabled():
    """SHUPAI_INTERLINEAR=0/false 关闭；默认开（迭代后为新满血版默认档）。"""
    return os.environ.get("SHUPAI_INTERLINEAR", "1").strip().lower() not in ("0", "false", "no", "")


def _valid_pair(bi, bj, W):
    """夹注配对三条件：y 重叠≥0.6；x 互补（并集宽∈[0.8W,1.3W] 且交叠≤0.25×小行宽）；高度比∈[0.5,2]。"""
    if _y_overlap_ratio(bi, bj) < 0.6:
        return False
    union_w = max(bi[2], bj[2]) - min(bi[0], bj[0])
    if not (0.8 * W <= union_w <= 1.3 * W):
        return False
    if _x_overlap(bi, bj) > 0.25 * min(_w(bi), _w(bj)):
        return False
    hr = _h(bi) / max(1.0, _h(bj))
    return 0.5 <= hr <= 2.0


def pair_and_merge(raw_lines):
    """把双行夹注对合并为合成行；其余原样保留。返回新的 line 列表（不改入参）。

    输出顺序不敏感——下游 aggregate_columns 按 x 重聚类、default_order 按栏序重排，
    合成行凭其并集 box（落在夹注 y 带、宽≈主列）自然归位。"""
    if not enabled() or len(raw_lines) < 3:
        return list(raw_lines)
    boxes = [[float(x) for x in l.get("box", [0, 0, 0, 0])] for l in raw_lines]
    W = _main_column_width(boxes)
    if W <= 0:
        return list(raw_lines)
    lo, hi = 0.30 * W, 0.65 * W
    cand = [i for i, b in enumerate(boxes) if lo <= _w(b) <= hi]
    if len(cand) < 2:
        return list(raw_lines)

    used = set()
    pairs = []  # (right_idx, left_idx)：右半（cx 大）在前
    for i in cand:
        if i in used:
            continue
        best, best_yov = None, 0.0
        for j in cand:
            if j == i or j in used:
                continue
            if not _valid_pair(boxes[i], boxes[j], W):
                continue
            yov = _y_overlap_ratio(boxes[i], boxes[j])
            if yov > best_yov:
                best, best_yov = j, yov
        if best is not None:
            used.add(i)
            used.add(best)
            if _cx(boxes[i]) >= _cx(boxes[best]):
                pairs.append((i, best))
            else:
                pairs.append((best, i))

    if not pairs:
        return list(raw_lines)

    paired = {k for p in pairs for k in p}
    out = [l for k, l in enumerate(raw_lines) if k not in paired]
    for right, left in pairs:
        rb, lb = boxes[right], boxes[left]
        rl, ll = raw_lines[right], raw_lines[left]
        union = [min(rb[0], lb[0]), min(rb[1], lb[1]), max(rb[2], lb[2]), max(rb[3], lb[3])]
        merged = {
            "text": rl.get("text", "") + ll.get("text", ""),      # 右半 + 左半
            "box": union,
            "score": min(float(rl.get("score", 0.0)), float(ll.get("score", 0.0))),
            "interlinear": True,
            "member_boxes": [rb, lb],
            "member_texts": [rl.get("text", ""), ll.get("text", "")],
            "member_scores": [float(rl.get("score", 0.0)), float(ll.get("score", 0.0))],
        }
        for key in ("source", "filter_status", "filter_reason"):
            rv, lv = rl.get(key), ll.get(key)
            if rv is not None and rv == lv:
                merged[key] = rv
        out.append(merged)
    return out
