# Task 1 report: shared engine setting

## RED

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\test_import_engine_switch_static.py proofread\test_settings_engine_labels.py -q
```

Result: `2 failed, 2 passed in 0.23s`.

- The import-switch test failed because `impEngineFull` markup/binding did not exist in `settings.js`.
- The settings-label test failed because the ONNX option was still `???`, rather than `???`.

## GREEN

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\test_import_engine_switch_static.py proofread\test_settings_engine_labels.py -q
```

Result: `4 passed in 0.14s`.

