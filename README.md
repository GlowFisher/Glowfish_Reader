# Glowfish OCR

Independent local OCR component for Glowfish Reader.

- Public package: `glowfish_ocr`
- Current worker implementation: `legacy/`
- Regression corpus and reports: `bench/`
- Model integrity contract: `models.lock.json`

The public package does not import Host, UI, or Account code. Source images are processed locally only.

## Execution modes

`SubprocessOcrService.recognize()` preserves the component-owned lightweight fallback.
Use `recognize_exact()` when a Host owns fallback ordering and needs exactly one normalized
engine attempt.

Source development executes the matching legacy worker script with Python. Packaged desktop
hosts may pass `desktop_executable` to use the frozen dispatch protocol:
`glowfish-reader.exe --ocr <engine> ...`.

`ResidentOcrService` keeps one JSON-lines worker alive across matching requests,
restarts it when engine configuration changes, retries startup, opens a startup
circuit after repeated failure, releases it after an idle TTL, and closes it during
shutdown. Hosts can inject process spawn/termination through `JsonLineOcrWorker`
without introducing a dependency from the OCR component back to the Host.
