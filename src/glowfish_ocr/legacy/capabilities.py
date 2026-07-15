# -*- coding: utf-8 -*-
"""逐项报告「能力是否真的可用」——把静默降级变成可观测的事实。

背景：assets/lexicon、models/punct、models/mlm 都曾因为打包脚本的 `if exists` 静默跳过
而漏进安装包。程序照跑、纠错层加载成空表、断句直接 no-op，用户拿到的是残废包却毫无察觉。

三处消费本模块：
1. `desktop_app.py --selftest-capabilities`：任一项缺失即非零退出（构建期硬闸）。
2. `release.ps1`：编包后跑冻结 exe 的自检，失败即构建失败。
3. App 启动自检：缺件时在 UI 顶部挂持久横幅。

只做「资产在不在」的静态探测，不加载模型（加载 onnx 要几百毫秒且吃内存）。
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MODELS = _HERE / "models"
_LEXICON = _HERE / "assets" / "lexicon"

# 每项能力 -> (中文名, 必须存在的路径清单)
_REQUIRED = {
    "ocr_engine": (
        "OCR 识别引擎",
        [_MODELS / "ppocrv6_onnx" / sub / "inference.onnx" for sub in ("det", "rec")],
    ),
    "punctuate": (
        "古文自动断句",
        [_MODELS / "punct" / f for f in ("model_int8.onnx", "vocab.txt", "meta.json")],
    ),
    "ocr_correct": (
        "语义纠错（AI）",
        [_MODELS / "mlm" / f for f in ("model_int8.onnx", "vocab.txt", "meta.json")],
    ),
    "lexicon": (
        "词表（域词修复 / 形近字 / 人名切分）",
        [
            _LEXICON / f
            for f in (
                "bigrams.txt",
                "confusion.txt",
                "confusion_suggest.txt",
                "domain_fixes.txt",
                "surnames.txt",
            )
        ],
    ),
}


def capabilities():
    """返回 {key: {"label": 中文名, "ok": bool, "missing": [缺失路径字符串]}}。"""
    report = {}
    for key, (label, paths) in _REQUIRED.items():
        missing = [str(p) for p in paths if not p.exists()]
        report[key] = {"label": label, "ok": not missing, "missing": missing}
    return report


def missing_labels():
    """只要中文名列表，供 UI 横幅直接拼句子。"""
    return [c["label"] for c in capabilities().values() if not c["ok"]]


def selftest(stream=None):
    """打印逐项结果；全通过返回 0，有缺件返回 1（供 --selftest-capabilities 用作退出码）。"""
    out = stream or sys.stdout
    if stream is None:
        try:                                      # Windows 控制台默认 GBK，中文标签会乱码/抛错
            out.reconfigure(encoding="utf-8")
        except Exception:
            pass
    report = capabilities()
    for key, cap in report.items():
        mark = "OK  " if cap["ok"] else "FAIL"
        print(f"[{mark}] {key:<12} {cap['label']}", file=out)
        for path in cap["missing"]:
            print(f"         缺失：{path}", file=out)
    bad = [c["label"] for c in report.values() if not c["ok"]]
    if bad:
        print(f"\n能力自检未通过，缺失 {len(bad)} 项：{'、'.join(bad)}", file=out)
        return 1
    print("\n能力自检通过：全部资产在位。", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(selftest())
