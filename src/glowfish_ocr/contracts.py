from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class OcrRequest:
    image_dir: Path
    output_path: Path
    engine: str = "ppocrv6_onnx_high"
    progress_path: Path | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class RegionOcrRequest(OcrRequest):
    """A request whose image directory contains a Host-created local crop."""


@dataclass(frozen=True)
class OcrResult:
    requested_engine: str
    actual_engine: str
    pages: Mapping[str, Any]
    output_path: Path
    fallback: str | None = None


@dataclass(frozen=True)
class OcrHealth:
    ok: bool
    engine: str
    detail: str = ""


class OcrService(Protocol):
    def recognize_exact(self, request: OcrRequest) -> OcrResult: ...
    def recognize(self, request: OcrRequest) -> OcrResult: ...
    def recognize_region(self, request: RegionOcrRequest) -> OcrResult: ...
    def prewarm(self, engine: str) -> OcrHealth: ...
    def shutdown(self) -> None: ...
