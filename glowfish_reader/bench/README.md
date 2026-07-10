# GlowFish Reader Bench

Accuracy regression bench for vertical traditional-Chinese historical OCR.

## Current Engine Matrix (v1.0.4)

| Engine | Role | Runtime |
|---|---|---|
| `ppocrv6` | Default quality-first engine: official local PaddleOCR PP-OCRv6 | PaddleOCR-capable Python from `SHUPAI_PADDLE_PY`, `bench_sets.json:paddle_py`, or appconfig auto-detect |
| `ppocrv6_onnx` | Lightweight/fallback engine: PP-OCRv6 ONNX Runtime | Project `.venv` |
| `onnx` | Compatibility alias for `ppocrv6_onnx` | Project `.venv` |
| `paddle` | Historical PaddleOCR `chinese_cht` comparison path | Legacy conda env |

Historical `vl_gguf` bench reports have been moved to `bench/out/archive_vl_gguf/` and are not v1.0.4 release evidence.

## Usage

PowerShell examples:

```powershell
cd "D:\桌面\Glowfish_reader v1.02\glowfish_reader"
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6_onnx --only 手写
.\.venv\Scripts\python.exe bench\run_bench.py --engine ppocrv6 --only 手写
.\.venv\Scripts\python.exe bench\run_bench.py --engine paddle --only 手写
```

`ppocrv6` needs a PaddleOCR-capable interpreter. Resolution order:

1. `--paddle-py <path>`
2. `SHUPAI_PADDLE_PY`
3. `bench_sets.json` field `paddle_py`
4. `appconfig.detect_paddle_python()`

## Scripts

- `run_bench.py`: recommended entry. Runs recognition, converts contract output to right-to-left reading order, scores with `eval_cer.py`, and writes `bench/out/回归报告.md`.
- `eval_cer.py`: metric core. Main acceptance metric is character-recognition F1 after optional t2s normalization and punctuation stripping.
- `run_paddle.py`: legacy PaddleOCR comparison helper.
- `smoke_test_paddle.py`: historical synthetic smoke check.

## Metric Rules

- Default scoring applies traditional-to-simplified normalization when OpenCC is available.
- Default scoring strips punctuation and whitespace-like noise from the OCR-accuracy metric.
- F1 high but CER high means characters are mostly right but reading order is wrong.
- F1 low means recognition itself is failing.

## Gold Data

`bench_sets.json` defines each set. Current sets:

- `手写`: images in `bench/_hw_images`, gold in `bench/gold_handwritten`, grouped by page.
- `印刷`: images and gold in `bench/gold_printed`.

For printed-material coverage, add real pages to `bench/gold_printed/` and matching `<stem>.gt.json` files:

```json
{"reading_order_rtl": "按右起阅读顺序的全文"}
```

or:

```json
{"columns": ["右列", "次列"]}
```

A small but real 5-10 page printed set is more useful than another synthetic fixture.

## Output Hygiene

Generated reports and recognition JSON are written to `bench/out/`. Historical VL/GGUF outputs are archived under `bench/out/archive_vl_gguf/`.
