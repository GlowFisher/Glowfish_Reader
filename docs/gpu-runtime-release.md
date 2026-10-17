# Optional GPU runtime release contract

The desktop installer remains CPU-only. GPU acceleration is installed only after
the user selects it in Settings and the Host receives a release-owned manifest
URL through `GLOWFISH_GPU_RUNTIME_MANIFEST`.

The manifest URL and `artifact.url` must use HTTPS. The artifact is a ZIP that
contains `glowfish_gpu_worker.exe`; the Host downloads it to `.part`, verifies
its exact byte count and SHA-256, extracts it under `staging/<version>`, runs
the injected Authenticode/self-test hooks, then atomically writes `active.json`.
When activation replaces an existing runtime, the former `active.json` is
retained as `previous.json`; the Host can atomically restore that verified
version once if a new runtime needs rollback.

Release assembly must provide all of the following before enabling the setting
for users:

- a pinned `models_lock_sha256` matching `ocr/models.lock.json`;
- Authenticode validation that accepts only the manifest publisher subject;
- a Worker `--selftest` that loads CUDA/cuDNN and runs a real locked-model OCR
  smoke test; and
- an archive layout containing no duplicate OCR models.

If any gate fails, the runtime remains inactive and OCR continues on CPU.

Build the Worker in a dedicated GPU environment.  Choose and install the
matching `paddlepaddle-gpu` wheel from Paddle's official Windows/CUDA matrix,
then install `ocr/gpu-runtime-requirements.txt` and `pyinstaller`.  The build
script verifies the exact package/Python lock, requires
`CUDAExecutionProvider`, and writes `gpu-build-provenance.json` beside the
artifact.  The checked-in lock currently describes only the proven local
candidate; a clean final lock must set `release_qualified` and is required by
the `-RequireReleaseQualified` build switch.

## Approved full-Worker release boundary

The approved release direction is the complete PaddleOCR/PaddleX Worker.  Its
known-good dependency set is required for a real CUDA Session on the current
build environment.  A trial retaining only CUDA Runtime, cuBLAS and cuDNN
reduced the single-file Worker to 1.91 GB but failed its strict CUDA check with
`LoadLibrary` error 126; it must not be distributed.

The functional complete Worker is approximately 2.56 GB.  This is an explicit
product-size exception, not evidence that the local artifact is releasable.
Do not delete more NVIDIA DLLs.  The release archive must contain exactly the
signed `glowfish_gpu_worker.exe` (no duplicate OCR models), be served through
HTTPS, and pass the same strict self-test, corpus-quality comparison and
install/rollback validation described above.

The ONNX-only experiment remains non-integrated because it does not meet the
text-equivalence gate; it is not a release dependency.

## Benchmark acceptance

Run the existing component benchmark with the CPU baseline and the signed CUDA
runtime explicitly selected.  The CUDA path is never inferred from the machine:

```powershell
python host/scripts/run_ocr_runtime_ab.py --output-dir .build/gpu-benchmark --component-provider cuda --gpu-runtime-dir C:\\ProgramData\\Glowfish\\gpu-runtime\\versions\\<version> --gpu-runtime-version <version> --model-root <locked-model-root>
```

The generated `summary.json` records the provider, warm and prewarm latency,
worker reuse/release, memory growth, output fingerprint, and acceptance result.
Release approval requires `ok: true`; investigate a mismatched fingerprint or
any lifecycle regression before shipping.  The performance ratios are safety
ceilings, not a claim that every document must be faster on every GPU.

## Speed-priority quality policy

GPU OCR is an explicit user opt-in; CPU remains the default and the fallback
when CUDA cannot start.  GPU execution must be proven by output metadata, not
by a device-selection label.  CUDA kernels can produce stable but slightly
different results from CPU at recognition decision boundaries, so a release
must never claim byte-for-byte CPU equivalence unless it has actually passed
that stricter gate on the target corpus.

For the speed-priority option, retain and compare a representative golden
corpus on every Worker rebuild.  Release review must record the CPU/CUDA text
and geometry parity, source-corpus CER for both providers, page completion,
and repeat-run stability.  Reject any lost page, unstable repeated CUDA result,
or unexplained quality regression.  Small, stable output differences may be
accepted only after they are recorded in the release evidence; users who need
CPU-identical output keep acceleration disabled.
