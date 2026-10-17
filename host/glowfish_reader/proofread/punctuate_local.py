# -*- coding: utf-8 -*-
"""本地古文标点（ONNX + onnxruntime；不引 torch、不外呼，满足「本地不上传」铁律）。

模型：raynardj/classical-chinese-punctuation-guwen-biaodian 导出的 ONNX
（BERT token 分类，21 类，label = 该字之后应插入的现代标点；'O'=不插）。

「不增删汉字」结构性保证：按**原始字符流逐字对齐**预测，标点只在两字之间插入，
原字一个不改 → 再做 CJK 序列校验兜底，违则该行回退原文。

接口为逐行入、逐行出；整页同跑以获跨行上下文。
模型缺失时 available()=False，调用方应静默跳过（不阻断导入）。
"""
import sys
import os
import re
import json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_DIR = Path(__file__).resolve().parent / "models" / "punct"
_CJK = re.compile(r"[㐀-䶿一-鿿]")

_SESS = None
_VOCAB = None
_META = None
_L2P = None     # label id -> 标点串（'O' → ''）


def _cjk_only(s):
    return "".join(_CJK.findall(s or ""))


def _model_path():
    """优先 int8 量化模型（97MB，实测断句 F1 与 fp32 持平，见 bench/out/punct_report.md）；
    无则回落 fp32 model.onnx（388MB）。"""
    q = _DIR / "model_int8.onnx"
    return q if q.exists() else _DIR / "model.onnx"


def available():
    """本地标点模型是否就绪（缺则调用方静默跳过）。"""
    return _model_path().exists() and (_DIR / "vocab.txt").exists() and (_DIR / "meta.json").exists()


def _load():
    global _SESS, _VOCAB, _META, _L2P
    if _SESS is not None:
        return
    import onnxruntime as ort
    _META = json.loads((_DIR / "meta.json").read_text(encoding="utf-8"))
    toks = (_DIR / "vocab.txt").read_text(encoding="utf-8").split("\n")
    _VOCAB = {t: i for i, t in enumerate(toks) if t != ""}
    id2label = {int(k): v for k, v in _META["id2label"].items()}
    _L2P = {i: ("" if v == "O" else v) for i, v in id2label.items()}
    so = ort.SessionOptions()
    so.intra_op_num_threads = 0          # 0 = onnxruntime 自决线程数
    _SESS = ort.InferenceSession(str(_model_path()), sess_options=so,
                                 providers=["CPUExecutionProvider"])


def _predict_labels(chars):
    """对字符列表逐字预测 label id（与 chars 等长）。超 max_content 自动分块。"""
    import numpy as np
    _load()
    cls, sep = _META["cls_id"], _META["sep_id"]
    unk = _META["unk_id"]
    maxc = int(_META.get("max_content", 510))
    labels = [0] * len(chars)
    i = 0
    while i < len(chars):
        chunk = chars[i:i + maxc]
        cids = [_VOCAB.get(c, unk) for c in chunk]
        ids = [cls] + cids + [sep]
        n = len(ids)

        def a(x):
            return np.array([x], dtype=np.int64)

        logits = _SESS.run(["logits"], {
            "input_ids": a(ids), "attention_mask": a([1] * n),
            "token_type_ids": a([0] * n)})[0][0]
        pred = logits.argmax(-1).tolist()        # 含 CLS/SEP
        for k in range(len(chunk)):
            labels[i + k] = int(pred[k + 1])     # +1 跳过 CLS
        i += maxc
    return labels


# ---- 2c：并列短项顿号修复（模型无“、”类，只能字符串后注入；读序流上判定，跨行有效）----
_ASSETS = Path(__file__).resolve().parent / "assets" / "lexicon"
_SURNAMES = None
_PLACE_SUFFIX = set("省县村镇乡州府路街道区市庄屯堡")


def _enum_comma_enabled():
    return os.environ.get("SHUPAI_ENUM_COMMA", "1").strip().lower() not in ("0", "false", "no", "")


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


def _starts_with_surname(item):
    sn = _load_surnames()
    return bool(item) and (item[:2] in sn or item[:1] in sn)   # 复姓优先，再单姓


def _fix_enumeration_commas(chars, puncts):
    """并列短项间的句号→顿号（只动标点，CJK 不变）。

    触发：≥2 个“链式”句号分隔符（=≥3 并列项，防两项误伤），各分隔符左项为 2~4 字短项，
    且右项起于姓氏（人名）/ 与左项同地名后缀 / 与左项等长。串首、串尾及非并列句号保留。"""
    puncts = list(puncts)
    n = len(chars)
    bpos = [i for i in range(n) if puncts[i] == "。"]
    if len(bpos) < 2:
        return puncts

    def cjk_between(lo, hi):
        return "".join(ch for ch in chars[lo:hi] if _CJK.match(ch))

    seps = []
    for t, i in enumerate(bpos):
        left = cjk_between((bpos[t - 1] + 1) if t > 0 else 0, i + 1)
        right = cjk_between(i + 1, bpos[t + 1] + 1 if t + 1 < len(bpos) else n)
        left_short = 2 <= len(left) <= 4
        # 两个高精度触发（都要求分隔符两侧“同型”，避免把「一步。广东孙文」误当并列）：
        #   人名——左右项皆起于姓氏；地名——左右项同后缀（省/县/村…）。
        # 纯“等长短项”形态触发误伤高（如“天下。人皆。知之”），暂不启用，待错误面板量化后再议。
        both_names = _starts_with_surname(left) and _starts_with_surname(right)
        same_suffix = bool(left) and bool(right) and left[-1] in _PLACE_SUFFIX and right[-1:] == left[-1:]
        seps.append(left_short and (both_names or same_suffix))

    flip = [False] * len(bpos)
    t = 0
    while t < len(bpos):
        if not seps[t]:
            t += 1
            continue
        j = t
        while j + 1 < len(bpos) and seps[j + 1]:
            j += 1
        if j - t + 1 >= 2:               # 链长≥2 分隔符 = ≥3 并列项
            for k in range(t, j + 1):
                flip[k] = True
        t = j + 1

    for t, i in enumerate(bpos):
        if flip[t]:
            puncts[i] = "、"
    return puncts


def local_punctuate(lines):
    """逐行文本 → 逐行加现代标点（整页拼接同跑取上下文，再按字归位回各行）。

    不增删汉字：每行输出的汉字序列必须与输入一致，违则该行回退原文。"""
    if not available():
        raise RuntimeError("本地标点模型缺失：proofread/models/punct/（先跑导出脚本）")
    lines = list(lines or [])
    chars, line_of = [], []
    for li, t in enumerate(lines):
        for c in (t or ""):
            chars.append(c)
            line_of.append(li)
    if not chars:
        return lines
    labels = _predict_labels(chars)
    puncts = [_L2P.get(labels[idx], "") for idx in range(len(chars))]
    if _enum_comma_enabled():
        puncts = _fix_enumeration_commas(chars, puncts)  # 2c：并列短项 。→、（读序流上判定，跨行有效）
    out = ["" for _ in lines]
    for idx, c in enumerate(chars):
        li = line_of[idx]
        out[li] += c + puncts[idx]
    res = []
    for li, orig in enumerate(lines):
        cand = out[li]
        res.append(cand if _cjk_only(cand) == _cjk_only(orig) else orig)   # 改了字就回退
    return res


def main():
    """CLI 自测：每行一句无标点古文，输出加标点结果。"""
    data = sys.stdin.read().splitlines() if not sys.stdin.isatty() else [
        "子曰學而時習之不亦說乎有朋自遠方來不亦樂乎人不知而不慍不亦君子乎"]
    for o in local_punctuate(data):
        print(o)


if __name__ == "__main__":
    main()
