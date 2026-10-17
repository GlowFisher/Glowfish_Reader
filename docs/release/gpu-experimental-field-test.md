# GPU experimental field-test protocol

This protocol applies only after release engineering has produced a signed GPU
runtime archive and an HTTPS `gpu-runtime.json` manifest.  The current
`local-trial` runtime is a developer-only environment and must not be copied to
another computer.

## Tester scope

- Windows 10 or 11 x64, with an NVIDIA GPU.
- Prefer one machine each with 6 GB, 8 GB, and 12 GB or more of VRAM.
- Do not send private documents.  Use the supplied test material or locally
  created non-sensitive images.

## Test sequence

1. Install the normal CPU-only desktop package.
2. Open Settings, request the optional GPU runtime, and record the displayed
   device, VRAM, runtime version, and installation result.
3. Run five to ten representative pages with the lightweight profile, then
   five to ten with the high-accuracy profile.
4. Check each generated `_recog.json`: every successfully accelerated page
   must record `ocr_meta.provider: "cuda"`, the GPU device, and the installed
   runtime version.
5. Repeat a short import after application restart.  Cancel one multi-page
   import, reopen the application, and verify completed pages remain usable.
6. Switch back to CPU and verify the same input still completes when GPU is
   unavailable or disabled.

## Report back

Report only the following local diagnostics: GPU model, reported VRAM, Windows
version, driver version, runtime version, the provider/device fields from the
result metadata, page count, elapsed time, and any visible error code.  Include
the local OCR log only after removing document paths and recognised text.

## Pass criteria

- No lost pages, crashes, or persistent GPU-memory growth during a 20-page
  run.
- CUDA is proven by result metadata, not by a settings label alone.
- On a failed GPU startup or recognition, the import completes on CPU and
  records a stable reason code.
- GPU is opt-in; CPU remains the default for users who require the established
  CPU output path.
- Text-quality differences are recorded for review.  A stable, documented
  small GPU/CPU difference does not by itself reject the speed-priority mode,
  but any page loss, repeat-run instability, or unexplained regression does.
  The field test does not replace the golden-corpus quality gate.
