# -*- coding: utf-8 -*-
"""域词修复表空跑审计（A1 准入闸）。

铁律：一条 `错串→正串` 只有当**错串在干净语料里一次都不出现**时才准自动改。
形近字对不携带方向（「盗」在别处合法），所以"改得对"不可由规则自证；能自证的只有
"改了不会误伤"——把错串拿到大规模正确文本里空跑，命中即拒。

语料：退想斋整理版 405 万字（perday/_all.jsonl，日记体）+ bench 全部 gold（含公文体）。
用法：python bench/audit_domain_fixes.py [--table proofread/assets/lexicon/domain_fixes.txt]
退出码 1 = 有条目未通过审计。
"""
import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent
DEFAULT_TABLE = ROOT / "proofread" / "assets" / "lexicon" / "domain_fixes.txt"
# 可选的日记语料（用于审计域词修复命中率）；通过环境变量指定，避免硬编码本机路径。
_DIARY_CORPUS_ENV = os.environ.get("GLOWFISH_DIARY_CORPUS")
DIARY_CORPUS = Path(_DIARY_CORPUS_ENV) if _DIARY_CORPUS_ENV else None


def load_table(path):
    """每行 `错串<TAB或空格>正串   # 出处`，返回 [(wrong, right, comment)]。"""
    rows = []
    if not Path(path).exists():
        return rows
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        rows.append((parts[0], parts[1]))
    return rows


def clean_corpus_texts():
    """干净语料：退想斋整理版正文 + bench gold 全文。"""
    texts = []
    if DIARY_CORPUS and DIARY_CORPUS.exists():
        for line in DIARY_CORPUS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            body = obj.get("body") or obj.get("text") or ""
            if body:
                texts.append(body)
    for gold_dir in ("gold_handwritten", "gold_printed"):
        for fp in (BENCH / gold_dir).glob("*.gt.json"):
            try:
                obj = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(obj, dict):
                for v in obj.values():
                    if isinstance(v, str):
                        texts.append(v)
            elif isinstance(obj, str):
                texts.append(obj)
    return texts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default=str(DEFAULT_TABLE))
    args = ap.parse_args()

    rows = load_table(args.table)
    if not rows:
        print(f"no entries in {args.table}")
        return 0

    texts = clean_corpus_texts()
    total_chars = sum(len(t) for t in texts)
    print(f"审计语料：{len(texts)} 段 / {total_chars:,} 字\n")

    failed = []
    for wrong, right in rows:
        hits = sum(t.count(wrong) for t in texts)
        status = "PASS" if hits == 0 else "REJECT"
        if hits:
            failed.append((wrong, right, hits))
        print(f"  [{status}] {wrong} → {right}   干净语料命中={hits}")

    print()
    if failed:
        print(f"❌ {len(failed)} 条未通过（错串在干净语料中合法出现，自动改会误伤）：")
        for w, r, h in failed:
            print(f"   {w} → {r}  ({h} 次)")
        return 1
    print(f"✅ 全部 {len(rows)} 条通过：错串在 {total_chars:,} 字干净语料中零出现 → 误纠率可事前证明为 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
