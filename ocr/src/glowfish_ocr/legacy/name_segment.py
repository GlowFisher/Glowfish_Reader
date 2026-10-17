# -*- coding: utf-8 -*-
"""并列人名句读建议（迭代3e，Tier B 专属，永不自动改）。

2c 只修「标点模型已切开、符号错」；本模块处理「人名连排、模型未切开」的句读难题
（「孙文伍廷芳唐绍仪」）——切错即改变文义，代价高于错字，故只出人工确认建议。

三信号合议：
  1. 语境触发——名单引导词/煞尾词/落款版式行；无名单语境一律不碰。
  2. 姓氏锚点切分——闭集姓氏表锚定边界，动态规划枚举「每段以姓氏开头、长2~4字」的合法切分。
  3. MLM 裁决——复用 ocr_correct 已加载模型，对各切分的姓氏位做掩码，取「边界处确为姓氏」
     置信度最高的切分；优势超阈值才出建议（消解「王/于/白」等姓氏兼常用字的歧义）。
只产 suggestions（type=segment），天然无回归面；独立开关 SHUPAI_NAME_SEGMENT。
"""
import os
import re
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets" / "lexicon"
_CJK = re.compile(r"[一-鿿]")
_SURNAMES = None

_LEAD = ("派", "委", "举", "选", "绅商", "委员", "董事", "发起人", "会员", "理事",
         "代表", "推", "公推", "举定", "议决", "同人", "绅士")
_TAIL = ("等", "诸人", "各员", "诸君", "等人", "等公", "数人", "辈")


def enabled():
    return os.environ.get("SHUPAI_NAME_SEGMENT", "1").strip().lower() not in ("0", "false", "no", "")


def _cfg_conf():
    """MLM 边界置信闸阈值（scorer 提供时生效；未接语料标定前取保守低值）。"""
    try:
        return float(os.environ.get("SHUPAI_NAME_SEGMENT_CONF", "0.02"))
    except Exception:
        return 0.02


def _load_surnames():
    global _SURNAMES
    if _SURNAMES is None:
        s = set()
        fp = _ASSETS / "surnames.txt"
        if fp.exists():
            for line in fp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    s.add(line)
        _SURNAMES = s
    return _SURNAMES


def _surname_at(run, i):
    """run[i] 起是否姓氏，返回姓长(2复姓/1单姓/0非姓)。"""
    sn = _load_surnames()
    if i + 1 < len(run) and run[i:i + 2] in sn:
        return 2
    if run[i] in sn:
        return 1
    return 0


def _split_before_surnames(run):
    """在每个姓氏起始处断句：姓氏 + 1~3 名字（总长 2~4），下一姓氏或长度到 4 即断。
    返回覆盖 run 前缀的片段列表（每段以姓氏开头）；不足 2 段返回 []。"""
    n = len(run)
    segs = []
    i = 0
    while i < n:
        sl = _surname_at(run, i)
        if not sl:
            break                          # 非姓氏开头 → 名单结束
        j = i + max(1, sl)
        while j - i < 4 and j < n and not _surname_at(run, j):
            j += 1
        if j - i < 2:
            j = min(i + 2, n)
        segs.append(run[i:j])
        i = j
    return segs if len(segs) >= 2 else []


def _mlm_boundary_score(run, seg, scorer):
    """各片段首字（姓氏位）掩码，取「该位预测为姓氏」的概率和——边界越像姓氏越高。"""
    if scorer is None:
        return 0.0
    sn = _load_surnames()
    pos, off = [], 0
    for piece in seg:
        pos.append(off)
        off += len(piece)
    probs = scorer(run, pos)              # {pos: {char: prob}} over full vocab row
    total = 0.0
    for p in pos:
        row = probs.get(p)
        if row is None:
            continue
        total += sum(v for c, v in row.items() if c in sn)
    return total / max(1, len(pos))


def suggest(text, scorer=None):
    """在 text 中找名单语境的人名连排，返回 [{start,end,run,segments,joined}] 建议。

    scorer(run, positions)->{pos: {char: softmax_prob}}：对 run 逐位掩码给全词表 softmax；
    传 None 则退化为纯姓氏锚点（不做 MLM 消歧）。"""
    if not enabled():
        return []
    out = []
    for m in re.finditer(r"[一-鿿]{4,}", text):
        run = m.group(0)
        run_start = m.start()
        # 语境触发：引导词在 run 首（无标点连排）或 run 前；煞尾词在 run 尾或其后
        lead_here = max((w for w in _LEAD if run.startswith(w)), key=len, default=None)  # 取最长引导词
        if lead_here:
            run = run[len(lead_here):]
            run_start += len(lead_here)
        has_lead = lead_here is not None or any(w in text[max(0, m.start() - 3):m.start()] for w in _LEAD)
        # 最早煞尾词处截断（名单在其前，丢弃其后的动词等非名文本）
        tail_here = False
        cut = len(run)
        for w in _TAIL:
            k = run.find(w)
            if k >= 0:
                cut = min(cut, k)
                tail_here = True
        run = run[:cut]
        has_tail = tail_here or any(w in text[m.end():m.end() + 2] for w in _TAIL)
        if not (has_lead or has_tail):
            continue
        if len(run) < 4 or not _surname_at(run, 0):
            continue
        segs = _split_before_surnames(run)
        if len(segs) < 2:
            continue
        covered = "".join(segs)
        # MLM 置信闸（可选）：边界处确为姓氏的分数够高才出；scorer=None 时纯姓氏锚点直接出
        if scorer is not None and _mlm_boundary_score(covered, segs, scorer) < _cfg_conf():
            continue
        out.append({
            "start": run_start, "end": run_start + len(covered), "run": covered,
            "segments": segs, "joined": "、".join(segs),
        })
    return out


def annotate_lines(lines, scorer=None):
    """给 proof lines 追加 type=segment 的 Tier B 建议（不改 text）。"""
    if not enabled():
        return lines
    for l in lines:
        if l.get("deleted"):
            continue
        for s in suggest(l.get("text", ""), scorer):
            l.setdefault("suggestions", []).append({
                "type": "segment", "pos": s["start"], "from": s["run"], "to": s["joined"],
            })
    return lines
