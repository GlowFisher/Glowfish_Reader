# Dependency Tracks

Update date: 2026-07-07

GlowFish uses several Python environments. Do not treat every requirement file as a direct-runtime dependency list.

## Files

| File | Role | Notes |
|---|---|---|
| `requirements-server.txt` | Minimal service/proofing environment | Used by the local FastAPI/proofing/export/bench environment. This is the best starting point for a clean `.venv` on Python 3.12. |
| `requirements-paddle.txt` | OCR subprocess environment | Used by the separate PaddleOCR interpreter. The main server should not import Paddle directly. |
| `proofread/requirements-app.txt` | Frozen app/build snapshot | Captures a broader working app/build environment. It includes direct dependencies, transitive dependencies, tests, OCR/model ecosystem packages, and packaging-era pins. Do not prune it only because deptry marks packages unused. |

## Direct Runtime Dependencies

These are directly imported or required by the local app, API, proofing, export, update, notice, licensing, and bench code:

- `fastapi`
- `uvicorn`
- `opencc-python-reimplemented` / `OpenCC`
- `python-docx`
- `PyMuPDF`
- `pillow`
- `requests`
- `PyNaCl`
- `onnxruntime`
- `numpy`

`pywebview` should be treated as a direct desktop-shell dependency even though the import name is `webview` and dependency tools may classify it as transitive.

`build_docx` is first-party code from `pipeline/build_docx.py`, not a PyPI dependency.

## OCR And Model Dependencies

These belong to OCR/model environments rather than the minimal local service runtime:

- `paddleocr`
- `paddlex`
- `shapely`
- `pyclipper`
- `opencv-contrib-python`
- `pypdfium2`
- `modelscope`
- `modelscope-hub`
- `huggingface-hub`
- `aistudio-sdk`
- `pandas`
- `ujson`
- `python-bidi`

`paddlepaddle` or `paddlepaddle-gpu` remains platform-specific and should be installed from the official PaddlePaddle instructions instead of being pinned blindly.

## Test Dependencies

- `pytest`
- `pluggy`
- `iniconfig`
- `Pygments`

## Optional Model-Build Dependencies

`proofread/setup_punct_model.py` is an offline one-time model export utility. It imports:

- `torch`
- `transformers`
- `onnx` for export/quantization workflows when needed

These should be documented as optional model-build dependencies, not product runtime dependencies.

## Transitive Or Lockfile-Style Dependencies

Packages such as `annotated-doc`, `annotated-types`, `anyio`, `certifi`, `charset-normalizer`, `h11`, `idna`, `pydantic_core`, `urllib3`, `typing_extensions`, and similar pins are often transitive dependencies. They may belong in a frozen app/build snapshot, but they should not be promoted to direct-runtime dependency claims without a real import or packaging reason.

## Tooling Notes

`deptry` is useful as a candidate generator, not as an automatic deletion tool for this project. Current expected noise includes:

- direct imports that use a different package name, such as `webview` from `pywebview`
- first-party path imports, such as `build_docx`
- optional model-build imports, such as `torch` and `transformers`
- transitive packages preserved in frozen build snapshots
- OCR packages used by subprocesses or packaged engines

## Safe Governance Plan

1. Keep `requirements-server.txt` focused on the smallest local service/proofing runtime.
2. Keep `requirements-paddle.txt` focused on the separate OCR subprocess environment.
3. Treat `proofread/requirements-app.txt` as a frozen app/build snapshot unless and until a reproducible packaging process replaces it.
4. Before deleting any dependency, verify all of the following:
   - static import search has no production or subprocess use
   - focused pytest suites pass
   - desktop self-test passes when relevant
   - OCR bench still runs for the affected engine
   - packaging/build scripts still resolve hidden imports and dynamic resources
5. Do not delete OCR/model dependencies based solely on deptry output.