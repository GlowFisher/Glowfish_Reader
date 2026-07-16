# V2 runtime composition

The packaged desktop application now imports `server_v2`, which delegates FastAPI
assembly to the public `glowfish_host.create_app` factory. Existing flat routers are
injected as compatibility adapters; they are no longer responsible for creating the
application or mounting UI assets.

`server.py` remains unchanged as the explicit V1-compatible rollback entry during the
incremental cutover.

## Source development

Install the Host package before starting the V2 entry from source:

```powershell
python -m pip install --no-deps -e .
python .\glowfish_reader\proofread\server_v2.py
```

## Packaging

`glowfish_reader.spec` adds Host `src` to PyInstaller `pathex` and declares
`glowfish_host` plus `server_v2` as hidden imports. The UI remains supplied by the
pinned UI component's deterministic `dist` manifest.

## Rollback

Revert the two `desktop_app.py` imports from `server_v2` to `server`. No document,
account, OCR model, or HTTP contract migration is involved in this slice.

## OCR migration seam

`content_api.configure_ocr_engine_runner()` provides a startup-time injection point
for one resolved OCR engine attempt. With no configured runner, the current resident
worker and one-shot subprocess implementation remains unchanged. A configured runner
may return `False` to decline an attempt; exceptions and missing output also fall back
to the preserved legacy implementation after partial output cleanup.

Engine selection, lightweight fallback order, cache validation, atomic job execution,
and progress reporting remain owned by `content_api` until a later component cutover.

### Public component canary

Set `GLOWFISH_OCR_COMPONENT_RUNTIME=1` before starting the V2 entry to route each
single-engine attempt through one persistent `glowfish_ocr.ResidentOcrService`.
Matching engine/config requests reuse the same JSON-lines worker; configuration changes
restart it, repeated startup failures open a circuit, and the idle TTL releases it.

The adapter injects Host-managed spawn/termination callbacks, preserves job IDs and
cancellation checks, routes prewarm into the component worker, and closes the service
during application shutdown. Component failures still return to the legacy runner
through the existing migration seam.

The canary remains disabled by default pending packaged performance measurements and
field soak. Source development requires `python -m pip install --no-deps -e components/ocr`;
PyInstaller includes the pinned component package directly through `OCR_SRC`.
