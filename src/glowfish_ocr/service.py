from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable, Sequence

from .contracts import OcrHealth, OcrRequest, OcrResult, RegionOcrRequest
from .registry import LIGHTWEIGHT_ENGINE, normalize_engine, resolve_engine


Runner = Callable[..., subprocess.CompletedProcess]


class SubprocessOcrService:
    """Public adapter around the preserved local v1 OCR worker scripts."""

    def __init__(
        self,
        legacy_dir: Path | None = None,
        paddle_python: Path | None = None,
        desktop_executable: Path | None = None,
        runner: Runner = subprocess.run,
    ):
        self._legacy_dir = (Path(legacy_dir) if legacy_dir else Path(__file__).resolve().parent / "legacy").resolve()
        self._paddle_python = Path(paddle_python).resolve() if paddle_python else None
        self._desktop_executable = Path(desktop_executable).resolve() if desktop_executable else None
        self._runner = runner
        if not self._legacy_dir.is_dir():
            raise FileNotFoundError(f"OCR legacy implementation directory missing: {self._legacy_dir}")

    def _command(self, request: OcrRequest, engine: str) -> tuple[str, Sequence[str]]:
        actual, prefix, defaults = resolve_engine(
            engine,
            self._legacy_dir,
            self._paddle_python,
            self._desktop_executable,
        )
        config = {**defaults, **dict(request.config)}
        command = [*prefix, "--images", str(request.image_dir), "--out", str(request.output_path), "--config", json.dumps(config, ensure_ascii=False)]
        if request.progress_path:
            command.extend(["--progress", str(request.progress_path)])
        return actual, command

    @staticmethod
    def _read_result(path: Path) -> dict:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("OCR output must be a JSON object")
        for page_id, page in data.items():
            if page_id == "_meta":
                continue
            if not isinstance(page, dict) or not isinstance(page.get("lines"), list):
                raise ValueError(f"Invalid OCR page contract: {page_id}")
            for line in page["lines"]:
                if not isinstance(line, dict) or not {"text", "box", "score"}.issubset(line):
                    raise ValueError(f"Invalid OCR line contract on page: {page_id}")
        return data

    def _run(self, request: OcrRequest, engine: str) -> OcrResult:
        request.image_dir.resolve(strict=True)
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        actual, command = self._command(request, engine)
        self._runner(command, check=True, timeout=request.timeout_seconds, cwd=str(self._legacy_dir))
        return OcrResult(request.engine, actual, self._read_result(request.output_path), request.output_path)

    def recognize_exact(self, request: OcrRequest) -> OcrResult:
        """Execute one normalized engine attempt without cross-engine fallback."""
        return self._run(request, normalize_engine(request.engine))

    def recognize(self, request: OcrRequest) -> OcrResult:
        requested = normalize_engine(request.engine)
        try:
            return self._run(request, requested)
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as primary:
            if requested == LIGHTWEIGHT_ENGINE:
                raise
            fallback = self._run(request, LIGHTWEIGHT_ENGINE)
            return OcrResult(requested, fallback.actual_engine, fallback.pages, fallback.output_path, f"{requested}: {type(primary).__name__}")

    def recognize_region(self, request: RegionOcrRequest) -> OcrResult:
        return self.recognize(request)

    def prewarm(self, engine: str) -> OcrHealth:
        try:
            actual, _, _ = resolve_engine(engine, self._legacy_dir, self._paddle_python)
            return OcrHealth(True, actual)
        except Exception as exc:
            return OcrHealth(False, normalize_engine(engine), type(exc).__name__)

    def shutdown(self) -> None:
        return None
