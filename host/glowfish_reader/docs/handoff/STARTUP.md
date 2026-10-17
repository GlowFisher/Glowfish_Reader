# Glowfish Reader Startup Notes

Project root:

```powershell
D:\CC-first\glowfish-reader\glowfish-reader-main\glowfish_reader
```

## Normal Startup Order

1. Check whether the service is already running:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8799/health" -TimeoutSec 5
```

Expected healthy response:

```json
{"ok":true}
```

2. If it is already running, open:

```text
http://127.0.0.1:8799/
```

3. If it is not running, start it from the project root:

```powershell
.\.venv\Scripts\python.exe proofread\desktop_app.py --serve 8799
```

4. For a long-running background service from Codex, start it outside the sandbox so the child process is not cleaned up when the command ends.

## Known Pitfalls

- Do not recursively scan the whole project before startup. Avoid `.venv`, `.paddle_venv`, `.uv-cache`, `.pytest_cache`, and pytest temp directories.
- The app service port is `8799`.
- The main app directory is the nested `glowfish_reader` directory, not the outer `Glowfish_reader v1.04` folder.
- PowerShell `Start-Process` may fail if the process environment contains both `Path` and `PATH`. Clear the duplicate key first or use another launch method.
- Running the server in the foreground proves that startup works, but a command timeout will terminate it. Use a proper background launch for persistent service.

## Verified Command Shape

```powershell
cd /d "D:\CC-first\glowfish-reader\glowfish-reader-main\glowfish_reader"
.\.venv\Scripts\python.exe proofread\desktop_app.py --serve 8799
```

Health URL:

```text
http://127.0.0.1:8799/health
```

App URL:

```text
http://127.0.0.1:8799/
```
