# -*- coding: utf-8 -*-
"""上下文语义纠错层（迭代3b）：现成古文 MLM 掩码重打分。

形近误认判定不靠字形（「盗」在别处合法），只靠上下文语义：逐位 mask，候选**严格限定
confusion 组内**（+原字），MLM 给各候选打分，概率比 = exp(logit[候选]-logit[原字])。
  Tier A 自动改：概率比 ≥ T_A 且替换后与邻字构成词锚（bigram）→ 改 text，记 corrections。
  Tier B 只建议：概率比落中间带（或无词锚的单字裸换）→ 记 suggestions，不改文本。
两遍收敛（抗邻位错字污染）：一遍贪心应用 Tier A，用改后文本整列重打分第二遍。
性能预算：疑错位攒 batch 一次 forward；每页 mask 调用设上限，超限只保留低分行。
本地 onnxruntime（无 torch）；模型缺失静默降级 no-op，不阻塞主流程。
"""
import os
import re
import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "models" / "mlm"
_ASSETS = Path(__file__).resolve().parent / "assets" / "lexicon"
_CJK = re.compile(r"[一-鿿]")

_SESS = _VOCAB = _META = _CONF = _BIGRAMS = None
_SUGGEST_ONLY = set()   # 这些字所在的组只出 Tier B 建议，永不自动改（held-out 证明放开会变差）


def enabled():
    return os.environ.get("SHUPAI_OCR_CORRECT", "1").strip().lower() not in ("0", "false", "no", "")


def _cfg_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return float(default)


def _model_path():
    q = _DIR / "model_int8.onnx"
    return q if q.exists() else _DIR / "model.onnx"


def available():
    return _model_path().exists() and (_DIR / "vocab.txt").exists() and (_DIR / "meta.json").exists()


def _load():
    global _SESS, _VOCAB, _META, _CONF, _BIGRAMS
    if _SESS is not None:
        return
    import onnxruntime as ort
    _META = json.loads((_DIR / "meta.json").read_text(encoding="utf-8"))
    toks = (_DIR / "vocab.txt").read_text(encoding="utf-8").split("\n")
    _VOCAB = {t: i for i, t in enumerate(toks) if t != ""}
    so = ort.SessionOptions()
    so.intra_op_num_threads = 0
    _SESS = ort.InferenceSession(str(_model_path()), sess_options=so, providers=["CPUExecutionProvider"])
    _CONF = load_confusion()
    _BIGRAMS = _load_bigrams()


def _read_groups(fp, groups):
    if not fp.exists():
        return []
    seen = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        grp = {c for c in line.split() if len(c) == 1 and _CJK.match(c)}
        if len(grp) >= 2:
            for c in grp:
                groups.setdefault(c, set()).update(grp)
            seen.extend(grp)
    return seen


def load_confusion():
    """形近组 -> {char: 同组集合(含自身)}。

    confusion.txt          = Tier A 可自动改（双闸仍须满足）。
    confusion_suggest.txt  = 只出 Tier B 建议；其独有字记入 _SUGGEST_ONLY，永不自动改。
    """
    global _SUGGEST_ONLY
    groups = {}
    a_chars = set(_read_groups(_ASSETS / "confusion.txt", groups))
    b_chars = set(_read_groups(_ASSETS / "confusion_suggest.txt", groups))
    _SUGGEST_ONLY = b_chars - a_chars
    return groups


def _load_bigrams():
    fp = _ASSETS / "bigrams.txt"
    return set(fp.read_text(encoding="utf-8").split("\n")) if fp.exists() else set()


def _word_anchor(text, pos, new_ch):
    """替换后 new_ch 与左邻或右邻构成已知 bigram（≥2 相邻字词锚）。"""
    left = text[pos - 1] + new_ch if pos > 0 else ""
    right = new_ch + text[pos + 1] if pos + 1 < len(text) else ""
    return (left in _BIGRAMS) or (right in _BIGRAMS)


def _score_positions(text, positions):
    """batch：对 text 中每个 position 逐位 mask，返回 {pos: logits_row(np.ndarray)}。"""
    import numpy as np
    cls, sep, mask = _META["cls_id"], _META["sep_id"], _META["mask_id"]
    unk = _META["unk_id"]
    maxc = int(_META.get("max_content", 510))
    base = [_VOCAB.get(c, unk) for c in text[:maxc]]
    seqs, mpos, keep = [], [], []
    for p in positions:
        if p >= len(base):
            continue
        ids = [cls] + base + [sep]
        ids[p + 1] = mask
        seqs.append(ids)
        mpos.append(p + 1)
        keep.append(p)
    if not seqs:
        return {}
    maxlen = max(len(s) for s in seqs)
    input_ids = np.zeros((len(seqs), maxlen), dtype=np.int64)
    attn = np.zeros((len(seqs), maxlen), dtype=np.int64)
    for i, s in enumerate(seqs):
        input_ids[i, : len(s)] = s
        attn[i, : len(s)] = 1
    logits = _SESS.run(["logits"], {"input_ids": input_ids, "attention_mask": attn})[0]
    return {keep[i]: logits[i, mpos[i]] for i in range(len(seqs))}


def _best_alt(row, orig_ch, cand_chars):
    """同组候选里 logit 最高的非原字，及其相对原字的概率比 exp(Δlogit)。"""
    import numpy as np
    if orig_ch not in _VOCAB:
        return None, 0.0
    lo = float(row[_VOCAB[orig_ch]])
    best, best_lg = None, -1e30
    for c in cand_chars:
        if c == orig_ch or c not in _VOCAB:
            continue
        lg = float(row[_VOCAB[c]])
        if lg > best_lg:
            best, best_lg = c, lg
    if best is None:
        return None, 0.0
    return best, float(np.exp(best_lg - lo))


def correct_page(lines):
    """页级两遍纠错：就地改 lines（text / text_draft-不动 / corrections / suggestions）。"""
    if not enabled() or not available():
        return lines
    _load()
    if not _CONF:
        return lines
    t_a = _cfg_float("SHUPAI_MLM_TA", 8.0)     # 概率比闸；配合“修复断词”词锚双闸，s02 空跑 0 误纠
    t_b = _cfg_float("SHUPAI_MLM_TB", 1.5)
    max_mask = int(_cfg_float("SHUPAI_MLM_MAXMASK", 220))

    # 触发位（char 命中 confusion 组）；预算超限时优先低分行
    triggers = []  # (line_idx, pos, orig, cand_chars)
    for li, l in enumerate(lines):
        if l.get("deleted"):
            continue
        text = l.get("text", "")
        for p, ch in enumerate(text):
            if ch in _CONF:
                triggers.append((float(l.get("score", 1.0)), li, p, ch))
    if len(triggers) > max_mask:
        triggers.sort(key=lambda x: x[0])          # 低分优先
        triggers = triggers[:max_mask]

    by_line = {}
    for _s, li, p, ch in triggers:
        by_line.setdefault(li, []).append((p, ch))

    for li, poslist in by_line.items():
        l = lines[li]
        text = l.get("text", "")
        corrections = list(l.get("corrections", []))
        suggestions = list(l.get("suggestions", []))
        positions = [p for p, _ in poslist]

        applied = {}          # pos -> new_ch（本行已应用 Tier A）
        # Tier A 只看「可自动改」的触发位：suggest-only 位置一旦混进这两遍打分/贪心流程，
        # 会扰动 ratio 与应用顺序，把本该成立的自动改挤掉（实测页2 掉 0.54pt、丢 点→黔）。
        positions_a = [p for p in positions if p < len(text) and text[p] not in _SUGGEST_ONLY]
        for _pass in range(2):
            rows = _score_positions(text, [p for p in positions_a if p not in applied])
            proposals = []    # (ratio, pos, orig, best_alt, anchored)
            for p in positions_a:
                if p in applied or p >= len(text):
                    continue
                orig = text[p]
                if orig not in _CONF or orig in _SUGGEST_ONLY:
                    continue
                row = rows.get(p)
                if row is None:
                    continue
                # 候选同样剔除 suggest-only 字，避免它们抢到最高 logit 顶掉合法自动改。
                cands_a = [c for c in _CONF[orig] if c not in _SUGGEST_ONLY]
                best, ratio = _best_alt(row, orig, cands_a)
                if not best:
                    continue
                # 词锚判据：替换后成词 且 原字本不成词（纠错是“修复断词”）——
                # 挡掉「盐号→尽号」这类原字已合法却被域外模型改坏的误纠。
                fixes_word = _word_anchor(text, p, best) and not _word_anchor(text, p, orig)
                proposals.append((ratio, p, orig, best, fixes_word))
            # 贪心按概率比降序应用 Tier A（高概率比 + 词锚），其余留待第二遍/建议
            proposals.sort(key=lambda x: -x[0])
            changed = False
            for ratio, p, orig, best, anchored in proposals:
                if p in applied:
                    continue
                if ratio >= t_a and anchored:
                    text = text[:p] + best + text[p + 1:]
                    applied[p] = best
                    corrections.append({"pos": p, "from": orig, "to": best,
                                        "rule": "mlm", "ratio": round(ratio, 2)})
                    changed = True
            if not changed:
                break

        # Tier B 建议（概率比中间带 或 有力但无词锚的单字裸换）——不改文本
        rows = _score_positions(text, [p for p in positions if p not in applied])
        for p in positions:
            if p in applied or p >= len(text):
                continue
            orig = text[p]
            if orig not in _CONF:
                continue
            row = rows.get(p)
            if row is None:
                continue
            best, ratio = _best_alt(row, orig, _CONF[orig])
            if not best:
                continue
            if ratio >= t_b:                 # 未达 Tier A 自动改闸的疑点 → 只建议
                suggestions.append({"pos": p, "from": orig, "to": best, "ratio": round(ratio, 2),
                                    "anchored": _word_anchor(text, p, best)})

        l["text"] = text
        if corrections:
            l["corrections"] = corrections
        if suggestions:
            l["suggestions"] = suggestions
    return lines
