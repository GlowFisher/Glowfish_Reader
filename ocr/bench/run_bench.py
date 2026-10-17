# -*- coding: utf-8 -*-
"""Accuracy regression bench for GlowFish Reader.

口径（迭代0 起）：默认 = 线上默认引擎 + 产品同源读序，让 bench 测的就是用户看到的。
  --engine ppocrv6_onnx_high  默认，满血档 = ONNX 高精（= engines.py DEFAULT_ENGINE，config 单一信源）。
  --engine ppocrv6       官方本地 PaddleOCR PP-OCRv6。
  --quick                快档 = ppocrv6_onnx 轻量 ONNX 引擎（开发内环回归，非验收口径）。
  paddle                 历史 PaddleOCR chinese_cht 对照路径。
读序：默认 product（proof_model.build_proof 产品链）；--legacy-order 回旧 recog_to_pred_rtl 自拼。
门槛：印刷 F1≥0.98&CER≤0.03 / 手写 F1≥0.92&CER≤0.12；草书公文桶只记录基线不卡门。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BENCH = Path(__file__).resolve().parent
OUT = BENCH / "out"
ROOT = BENCH.parent
PROOFREAD = ROOT / "proofread"
IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(PROOFREAD))
import eval_cer  # noqa: E402
import subprocess_env  # noqa: E402

try:
    import appconfig  # noqa: E402
except Exception:  # pragma: no cover - bench remains usable without appconfig imports.
    appconfig = None

# 引擎参数单一信源：优先从 proofread/engines.py 读，杜绝 bench 与产品口径漂移（迭代0）。
try:
    import engines as _engines  # noqa: E402
    _ENGINE_PARAMS = {name: dict(spec.get("params") or {}) for name, spec in _engines.ENGINES.items()}
except Exception:  # pragma: no cover - fallback keeps bench runnable if engines import fails.
    _engines = None
    _ENGINE_PARAMS = {
        "ppocrv6_onnx_high": {"ocr_version": "PP-OCRv6", "lang": "chinese_cht", "profile": "high_accuracy", "text_det_box_thresh": 0.45},
        "ppocrv6": {"ocr_version": "PP-OCRv6", "lang": "chinese_cht", "column_rescue": True},
        "ppocrv6_onnx": {"ocr_version": "PP-OCRv6", "lang": "chinese_cht"},
    }


_PROFILE_OVERRIDE = {}  # --profile-config 覆盖（迭代4 逐项 A/B）


def _engine_params(name):
    """该引擎传给识别子进程的 config（engines.py 单一信源 + --profile-config 覆盖）。"""
    return {**_ENGINE_PARAMS.get(name, {}), **_PROFILE_OVERRIDE}


ENGINE_ALIASES = {"onnx": "ppocrv6_onnx"}
BASELINE_ONLY_GENRES = {"草书公文"}  # 新体裁桶：只记录基线、不卡门（防 CI 上线即红，迭代0）


def _clean_env():
    return subprocess_env.clean_subprocess_env()


def _page_no(stem):
    match = re.search(r"_p(\d+)$", stem)
    return int(match.group(1)) if match else 0


def group_pages_to_docs(pred, gold_stems):
    docs = {}
    for doc in gold_stems:
        keys = [key for key in pred if re.match(rf"^{re.escape(doc)}(_p\d+)?$", key)]
        keys.sort(key=_page_no)
        docs[doc] = "".join(pred[key] for key in keys)
    return docs


def _mean_xy_box(box):
    try:
        x1, y1, x2, y2 = box
        return (float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0
    except Exception:
        return 0.0, 0.0


def recog_to_pred_rtl(recog):
    pred = {}
    for pid, page in recog.items():
        keyed = []
        for line in page.get("lines") or []:
            mx, my = _mean_xy_box(line.get("box") or [0, 0, 0, 0])
            keyed.append((mx, my, line.get("text", "")))
        keyed.sort(key=lambda item: (-item[0], item[1]))
        pred[pid] = {"text": "".join(item[2] for item in keyed), "order": "rtl"}
    return pred


def recog_to_pred_product(recog):
    """产品同源读序：走 proof_model.build_proof（aggregate_columns + 产品 order），
    与用户在点校器里看到的读序完全一致。后续迭代对 build_proof 的增强（夹注读序/
    语义纠错）会自动反映到 bench 分数。lazy import：仅此路径需 opencc + python-docx。"""
    import proof_model  # noqa: E402  server/codex env 提供 opencc + python-docx
    proof = proof_model.build_proof(recog, batch_name="bench", engine="bench")
    pred = {}
    for pg in proof.get("pages", []):
        lmap = {l["id"]: l for l in pg.get("lines", [])}
        order_ids = [lid for lid in pg.get("order", [])
                     if lmap.get(lid) and not lmap[lid].get("deleted")]
        text = "".join(lmap[lid].get("text", "") for lid in order_ids)
        pred[pg.get("page_id")] = {"text": text, "order": "product"}
    return pred


def _resolve_paddle_py(args, cfg):
    candidates = [
        args.paddle_py,
        os.environ.get("SHUPAI_PADDLE_PY"),
        cfg.get("paddle_py"),
    ]
    if appconfig is not None:
        try:
            candidates.append(appconfig.detect_paddle_python())
        except Exception:
            pass
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def _recognition_command(engine, img_dir, recog_json, paddle_py):
    normalized = ENGINE_ALIASES.get(engine, engine)
    if normalized == "paddle":
        if not paddle_py:
            raise RuntimeError("paddle engine requires --paddle-py, SHUPAI_PADDLE_PY, or bench_sets.json:paddle_py")
        pred_raw = OUT / f"{img_dir.name}_pred_raw.json"
        pred_rtl = OUT / f"{img_dir.name}_pred_rtl.json"
        return [
            paddle_py,
            str(BENCH / "run_paddle.py"),
            "--images", str(img_dir),
            "--out-raw", str(pred_raw),
            "--out-rtl", str(pred_rtl),
        ], pred_rtl
    if normalized == "ppocrv6":
        if not paddle_py:
            raise RuntimeError(f"{normalized} requires a PaddleOCR-capable interpreter")
        return [
            paddle_py,
            str(PROOFREAD / "recognize_ppocrv6.py"),
            "--images", str(img_dir),
            "--out", str(recog_json),
            "--config", json.dumps(_engine_params(normalized), ensure_ascii=False),
        ], None
    if normalized in ("ppocrv6_onnx", "ppocrv6_onnx_high"):
        return [
            sys.executable,
            str(PROOFREAD / "recognize_ppocrv6_onnx.py"),
            "--images", str(img_dir),
            "--out", str(recog_json),
            "--config", json.dumps(_engine_params(normalized), ensure_ascii=False),
        ], None
    raise RuntimeError(f"unsupported engine: {engine}")


def run_set(dataset, engine, t2s, punct, paddle_py, reuse_pred=False, legacy_order=False):
    img_dir = BENCH / dataset["images"]
    gold_dir = BENCH / dataset["gold"]
    name = dataset["name"]
    normalized_engine = ENGINE_ALIASES.get(engine, engine)

    if not gold_dir.is_dir() or not any(gold_dir.glob("*.gt.json")):
        return None, f"skip {name}: no *.gt.json in {gold_dir}"
    if not img_dir.is_dir() or not any(path.suffix.lower() in IMG_EXT for path in img_dir.iterdir()):
        return None, f"skip {name}: no images in {img_dir}"

    OUT.mkdir(parents=True, exist_ok=True)
    recog_json = OUT / f"{name}_{normalized_engine}_recog.json"

    # --- 识别：产出 recog dict（ppocrv6*）或 paddle 直出 pred_rtl 文件 ---
    recog = None
    direct_pred_file = None
    if reuse_pred and recog_json.exists():
        print(f"\n[{name}] reuse {recog_json.name}")
        recog = json.loads(recog_json.read_text(encoding="utf-8"))
    else:
        try:
            cmd, direct_pred = _recognition_command(normalized_engine, img_dir, recog_json, paddle_py)
        except RuntimeError as exc:
            return None, f"skip {name}: {exc}"
        print(f"\n[{name}] recognizing with {normalized_engine}: {img_dir}")
        proc = subprocess.run(
            cmd, env=_clean_env(), capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        sys.stdout.write(proc.stdout or "")
        if proc.returncode != 0:
            return None, f"{name} recognition failed rc={proc.returncode}: {(proc.stderr or '')[-800:]}"
        if direct_pred is not None:
            direct_pred_file = direct_pred              # paddle：已是 rtl pred 文件
        else:
            recog = json.loads(recog_json.read_text(encoding="utf-8"))

    # --- 组装 pred：默认产品同源读序；--legacy-order 或 paddle(无 recog) 走旧 rtl ---
    use_legacy = legacy_order or recog is None
    if use_legacy:
        if recog is not None:
            pred_map = recog_to_pred_rtl(recog)
        else:
            pred_map = json.loads(direct_pred_file.read_text(encoding="utf-8"))
        pred_file = OUT / f"{name}_pred_rtl.json"
        order_tag = "legacy-rtl"
    else:
        try:
            pred_map = recog_to_pred_product(recog)
        except Exception as exc:  # 产品读序需 opencc + python-docx
            return None, (f"{name}: 产品同源读序需 opencc+python-docx（请用 server/codex env 跑 "
                          f"run_bench，或加 --legacy-order）。{type(exc).__name__}: {exc}")
        pred_file = OUT / f"{name}_pred_product.json"
        order_tag = "product"
    pred_file.write_text(json.dumps(pred_map, ensure_ascii=False, indent=2), encoding="utf-8")

    pred = eval_cer.load_pred(str(pred_file))
    gold = eval_cer.load_gold(str(gold_dir))
    if dataset.get("group_pages"):
        doc_pred = group_pages_to_docs(pred, list(gold.keys()))
        pred = {key: eval_cer.norm_cjk(value) for key, value in doc_pred.items()}

    result = eval_cer.evaluate(gold, pred, t2s=t2s, punct=punct)
    if t2s and not result["t2s_applied"]:
        print("warning: OpenCC unavailable; t2s normalization was not applied")
    report = OUT / f"CER报告_{name}_{normalized_engine}_{order_tag}.md"
    report.write_text(eval_cer.render_report(f"{name}·{normalized_engine}·{order_tag}", result), encoding="utf-8")
    overall = result["overall"]
    print(
        f"[{name}] order={order_tag} F1={overall['f1']:.3f} recall={overall['recall']:.3f} "
        f"precision={overall['precision']:.3f} CER={overall['cer']:.3f} images={overall['n_img']} -> {report.name}"
    )
    return result, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(BENCH / "bench_sets.json"))
    parser.add_argument(
        "--engine",
        default="ppocrv6_onnx_high",
        choices=["ppocrv6_onnx_high", "ppocrv6", "ppocrv6_onnx", "onnx", "paddle"],
        help="OCR engine（默认 ppocrv6_onnx_high = 线上满血档）。onnx 是 ppocrv6_onnx 别名。",
    )
    parser.add_argument("--quick", action="store_true",
                        help="快档：等价 --engine ppocrv6_onnx（开发内环快速回归用，非验收口径）")
    parser.add_argument("--legacy-order", dest="legacy_order", action="store_true",
                        help="用旧 recog_to_pred_rtl 自拼读序（隔离“识别 vs 读序”两类回归）")
    parser.add_argument("--paddle-py", default=None, help="Python interpreter for ppocrv6 or legacy paddle engine")
    parser.add_argument("--profile-config", dest="profile_config", default=None,
                        help='JSON 覆盖引擎 params 逐项 A/B（迭代4，如 {"degraded_preproc":true} / {"use_textline_orientation":true}）')
    parser.add_argument("--only", default=None, help="Run only the dataset with this name")
    parser.add_argument("--no-t2s", dest="t2s", action="store_false")
    parser.add_argument("--keep-punct", dest="punct", action="store_true", help="Keep punctuation in scoring")
    parser.add_argument("--reuse-pred", dest="reuse", action="store_true", help="Reuse existing recog output (skip OCR)")
    parser.set_defaults(t2s=True, punct=False, reuse=False)
    args = parser.parse_args()

    engine = "ppocrv6_onnx" if args.quick else args.engine
    if args.profile_config:
        _PROFILE_OVERRIDE.update(json.loads(args.profile_config))
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    paddle_py = _resolve_paddle_py(args, cfg)
    normalized_engine = ENGINE_ALIASES.get(engine, engine)
    order_tag = "legacy-rtl" if args.legacy_order else "product"

    summary = []
    notes = []
    for dataset in cfg["sets"]:
        if args.only and dataset["name"] != args.only:
            continue
        result, note = run_set(dataset, normalized_engine, args.t2s, args.punct,
                               paddle_py, args.reuse, args.legacy_order)
        if note:
            notes.append(note)
            print("-", note)
        if result:
            summary.append((dataset["name"], result))

    lines = [
        f"# 准确率回归报告 · engine={normalized_engine} · order={order_tag} · "
        f"t2s={'on' if args.t2s else 'off'} · 标点={'计入' if args.punct else '剥除'}\n",
        "| 测试集 | 图数 | GT字数 | **字符识别准确率F1** | 召回 | 精确 | CER | 门槛(F1/CER) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    # 门槛计序 CER 纳入（迭代0）；草书公文等基线体裁不卡门，仅单列记录。
    gates = {"印刷": {"f1": 0.98, "cer": 0.03}, "手写": {"f1": 0.92, "cer": 0.12}}
    for name, result in summary:
        overall = result["overall"]
        gate = gates.get(name)
        gated_rows = [r for r in result["rows"] if r["genre"] not in BASELINE_ONLY_GENRES]
        gated = eval_cer._agg(gated_rows) if gated_rows else overall
        if gate is None:
            status = "—"
        elif gated["f1"] >= gate["f1"] and gated["cer"] <= gate["cer"]:
            status = "达标"
        elif gated["f1"] < gate["f1"]:
            status = f"F1<{gate['f1']}"
        else:
            status = f"CER>{gate['cer']}"
        lines.append(
            f"| {name} | {overall['n_img']} | {overall['n_ref']} | **{overall['f1']:.3f}** | "
            f"{overall['recall']:.3f} | {overall['precision']:.3f} | {overall['cer']:.3f} | {status} |"
        )
        for g, a in sorted(result["by_genre"].items()):
            if g in BASELINE_ONLY_GENRES:
                lines.append(
                    f"| └ {g}（基线·不卡门） | {a['n_img']} | {a['n_ref']} | {a['f1']:.3f} | "
                    f"{a['recall']:.3f} | {a['precision']:.3f} | {a['cer']:.3f} | 记录 |"
                )
    if notes:
        lines.append("\n## 备注")
        lines.extend(f"- {note}" for note in notes)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "回归报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nsummary written:", OUT / "回归报告.md")
    if not summary:
        print("no evaluable dataset; check gold directories and *.gt.json files")


if __name__ == "__main__":
    main()
