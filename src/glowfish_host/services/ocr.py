from __future__ import annotations

from typing import Any


class OcrApplicationService:
    def __init__(self, port: Any):
        self._port = port

    def recognize(self, request):
        return self._port.recognize(request)

    def recognize_region(self, request):
        return self._port.recognize_region(request)

    def prewarm(self, engine: str):
        return self._port.prewarm(engine)

    def shutdown(self) -> None:
        self._port.shutdown()
