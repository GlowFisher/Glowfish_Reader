# -*- coding: utf-8 -*-
"""域词确定性修复层（A1）：盐务/公文域高频形近误认的多字词锚替换。

为什么需要它：迭代3 的 GuwenBERT MLM 是殆知阁古文语料训出来的，对晚清民国盐务/机构名
判别力弱——「黔人自组盐号」里它甚至给 盗 > 盐 的打分，纠错层既救不回、又被"修复断词"
闸挡住（详见记忆 project_glowfish_ocr_accuracy_plan 踩坑铁律 3）。这一层用确定性词表兜住
MLM 够不着的域内错误。

安全性怎么来：不靠模型自信，靠**空跑审计**——表里每条错串在 374 万字干净语料 + 全部 gold
中出现次数为 0（bench/audit_domain_fixes.py 每次可复核），所以自动改的误纠率事前可证为 0。
单字裸换永不进表（形近对不携带方向）。

开关：SHUPAI_DOMAIN_FIXES=0 关闭（默认开）。表：assets/lexicon/domain_fixes.txt。
"""
import os
import re
from pathlib import Path

_TABLE = Path(__file__).resolve().parent / "assets" / "lexicon" / "domain_fixes.txt"
_CJK = re.compile(r"[一-鿿]")
_RULES = None


def enabled():
    return os.environ.get("SHUPAI_DOMAIN_FIXES", "1").strip().lower() not in ("0", "false", "no", "")


def load_rules():
    """[(wrong, right)]，按错串长度降序——长词锚优先，避免短锚抢先改坏长锚。"""
    global _RULES
    if _RULES is not None:
        return _RULES
    rules = []
    if _TABLE.exists():
        for raw in _TABLE.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            wrong, right = parts[0], parts[1]
            # 纪律闸：只收 ≥2 字纯汉字词锚，单字裸换一律拒绝加载。
            if len(wrong) < 2 or not all(_CJK.match(c) for c in wrong + right):
                continue
            rules.append((wrong, right))
    rules.sort(key=lambda r: -len(r[0]))
    _RULES = rules
    return _RULES


def apply_text(text):
    """返回 (新文本, corrections)。corrections 记每次替换的位置与前后串。"""
    if not text or not enabled():
        return text, []
    corrections = []
    for wrong, right in load_rules():
        start = 0
        while True:
            pos = text.find(wrong, start)
            if pos < 0:
                break
            text = text[:pos] + right + text[pos + len(wrong):]
            corrections.append({"pos": pos, "from": wrong, "to": right, "rule": "domain_word"})
            start = pos + len(right)
    return text, corrections


def correct_page(lines):
    """就地改 lines 的 text，并累加 corrections（与 ocr_correct 同契约）。"""
    if not enabled():
        return lines
    for l in lines or []:
        if l.get("deleted"):
            continue
        new_text, corr = apply_text(l.get("text", ""))
        if corr:
            l["text"] = new_text
            l["corrections"] = list(l.get("corrections", [])) + corr
    return lines
