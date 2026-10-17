#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Glowfish Reader 模型检测 / 下载 / 校验脚本。

依据 `ocr/models.lock.json`（权威清单）对本地模型目录做三件事：
  1. 检测  —— 逐文件检查「是否存在 + 大小 + SHA256 是否匹配」；
  2. 下载  —— 对带 `download` 来源的缺失/校验失败文件，按镜像列表依次重试下载；
  3. 校验  —— 下载完成后重新校验 SHA256 与大小。

两类模型：
  * 可直接下载：PP-OCRv6 det/rec 的 inference.onnx / inference.json / inference.yml
    （来自 HuggingFace `PaddlePaddle/PP-OCRv6_medium_{det,rec}_onnx`，含 hf-mirror 镜像）。
  * 需本地构建：mlm / punct 模型由 HuggingFace 开源 PyTorch 权重经
    `setup_mlm_model.py` / `setup_punct_model.py` 导出并 int8 量化，本脚本无法替代
    该过程，仅检测并给出明确指引（见 docs/MODELS.md）。

用法：
    python scripts/fetch_models.py                 # 检测 + 下载缺失 + 校验（不构建）
    python scripts/fetch_models.py --check-only     # 仅检测，不下载
    python scripts/fetch_models.py --force          # 强制重新下载（忽略已存在的合法文件）
    python scripts/fetch_models.py --root <DIR>     # 指定模型根目录（默认 host/glowfish_reader/proofread/models）

环境变量：
    GLOWFISH_OCR_MODELS   模型根目录（优先级高于 --root）
    HF_ENDPOINT           覆盖 HuggingFace 端点（默认自动在官方站与 hf-mirror 间回退）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "ocr" / "models.lock.json"

# 模型根目录解析优先级：环境变量 > --root 参数 > 清单 default_root > 约定路径
_DEFAULT_ROOT = ROOT / "host" / "glowfish_reader" / "proofread" / "models"

# 下载块大小（1 MiB）与进度条刷新阈值
_CHUNK = 1024 * 1024


def _reconfigure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def resolve_model_root(args_root: str | None) -> Path:
    env = os.environ.get("GLOWFISH_OCR_MODELS")
    if env:
        return Path(env)
    if args_root:
        return Path(args_root)
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock.get("default_root"):
        return ROOT / lock["default_root"]
    return _DEFAULT_ROOT


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_file(entry: dict, model_root: Path) -> str | None:
    """返回 None 表示合法；否则返回问题描述字符串。"""
    path = model_root / entry["path"]
    if not path.is_file():
        return f"缺失 {entry['path']}"
    if path.stat().st_size != entry["bytes"]:
        return f"大小不符 {entry['path']} (实际 {path.stat().st_size}, 期望 {entry['bytes']})"
    if _sha256(path).lower() != entry["sha256"].lower():
        return f"SHA256 不符 {entry['path']}"
    return None


def _download_url(entry: dict, mirror: str) -> str:
    repo = entry["download"]["repo"]
    file = entry["download"]["file"]
    return f"{mirror.rstrip('/')}/{repo}/resolve/main/{file}"


def _download_one(entry: dict, model_root: Path) -> bool:
    """下载单个文件，镜像回退；成功且校验通过返回 True。"""
    dest = model_root / entry["path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    mirrors = entry["download"].get("mirrors", ["https://huggingface.co"])
    if os.environ.get("HF_ENDPOINT"):
        mirrors.insert(0, os.environ["HF_ENDPOINT"].rstrip("/"))

    last_err: Exception | None = None
    for mirror in mirrors:
        url = _download_url(entry, mirror)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            print(f"  下载 {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "glowfish-fetch/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        print(f"\r    {done // 1048576} / {total // 1048576} MB ({pct}%)", end="")
                    else:
                        print(f"\r    {done // 1048576} MB", end="")
            print()
            # 先校验下载结果，再替换原文件
            if tmp.stat().st_size != entry["bytes"]:
                raise ValueError(f"大小不符：{tmp.stat().st_size} != {entry['bytes']}")
            if _sha256(tmp).lower() != entry["sha256"].lower():
                raise ValueError(f"SHA256 不符：{tmp}")
            tmp.replace(dest)
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
            last_err = e
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            print(f"    失败（{mirror}）：{e}，尝试下一镜像…")
    if last_err:
        print(f"    全部镜像失败：{last_err}")
    return False


def main() -> int:
    _reconfigure_stdout()
    ap = argparse.ArgumentParser(description="检测 / 下载 / 校验 Glowfish Reader 模型")
    ap.add_argument("--check-only", action="store_true", help="仅检测，不下载")
    ap.add_argument("--force", action="store_true", help="强制重新下载，忽略已存在的合法文件")
    ap.add_argument("--root", default=None, help="模型根目录")
    args = ap.parse_args()

    if not LOCK_PATH.is_file():
        print(f"错误：找不到模型清单 {LOCK_PATH}", file=sys.stderr)
        return 1

    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    model_root = resolve_model_root(args.root)

    downloadable: list[dict] = []
    build_required: list[dict] = []
    ok_count = 0

    print(f"模型根目录：{model_root}")
    print(f"清单条目：{len(lock['files'])} 个文件\n")

    # 第一遍：分类
    for entry in lock["files"]:
        problem = check_file(entry, model_root)
        if problem is None:
            ok_count += 1
            continue
        if "download" in entry:
            downloadable.append(entry)
            print(f"[下载] {problem}")
        elif "build" in entry:
            build_required.append(entry)
            print(f"[构建] {problem}")
        else:
            print(f"[未知] {problem}")

    print(f"\n已有且校验通过：{ok_count}")

    # 下载可下载项
    if downloadable and not args.check_only:
        print(f"\n开始下载 {len(downloadable)} 个缺失文件…")
        failed = []
        for entry in downloadable:
            if not args.force and check_file(entry, model_root) is None:
                continue
            if _download_one(entry, model_root):
                print(f"  ✓ {entry['path']}")
            else:
                failed.append(entry)
                print(f"  ✗ {entry['path']}")
        if failed:
            print(f"\n下载失败 {len(failed)} 个文件。")

    # 构建项提示
    if build_required:
        print("\n以下模型需本地构建（无法直接下载）：")
        seen_scripts = {}
        for entry in build_required:
            b = entry["build"]
            seen_scripts.setdefault(b["script"], []).append(entry["path"])
        for script, paths in seen_scripts.items():
            src = lock.get("files", [])
            source_model = next(
                (e["build"]["source_model"] for e in src
                 if e.get("build", {}).get("script") == script),
                "?",
            )
            print(f"  脚本：{script}")
            print(f"    来源模型：{source_model}")
            print(f"    缺失文件：{', '.join(paths)}")
            print(f"    说明：见 docs/MODELS.md，需 torch + transformers 环境执行该脚本。")

    # 最终校验
    if args.check_only:
        print("\n（--check-only：未执行下载）")
    else:
        print("\n重新校验…")
    final_errors = []
    for entry in lock["files"]:
        err = check_file(entry, model_root)
        if err:
            final_errors.append(err)
    if final_errors:
        print(f"仍有 {len(final_errors)} 个文件不完整：")
        for e in final_errors:
            print(f"  - {e}")
        return 2
    print(f"\n✓ 全部 {len(lock['files'])} 个模型文件校验通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
