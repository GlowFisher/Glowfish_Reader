# Frozen payload size boundary

The desktop runtime uses pre-exported ONNX models. Model training, conversion,
benchmarking, and general-purpose transformer pipelines are not product runtime
features.

## Excluded toolchains

The PyInstaller specification excludes:

- Torch and Transformers runtime packages;
- ONNX Runtime conversion, benchmark, and transformer tool modules;
- their copied source/data directories and Torch distribution metadata.

ModelScope remains bundled because the current PaddleX utility package imports it
during module initialization, including the OCR dependency self-test path.

## Verified baseline

On the `Glowfish Reader V2.0.0` onedir build:

| Measurement | Before | After |
| --- | ---: | ---: |
| Uncompressed size | 1,145.0 MB | 704.1 MB |
| File count | 7,945 | 3,079 |
| Clean build time | about 439 s | about 180 s |

The optimized build passed all frozen capability, service, dependency, real OCR,
export/logging, payload-audit, and legacy/component OCR A-B gates. Required OCR
models, OpenCV, ONNX Runtime core, PaddleOCR/PaddleX compatibility modules, PDF
processing, document export, licensing, and UI assets remain bundled.

Future size work should replace broad PaddleX package collection with a maintained
allow-list. That is a higher-risk change and must preserve ModelScope compatibility
or first remove PaddleX's import-time dependency upstream.
