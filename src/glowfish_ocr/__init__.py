"""Public OCR component API."""

from .contracts import OcrHealth, OcrRequest, OcrResult, OcrService, RegionOcrRequest
from .resident import JsonLineOcrWorker, ResidentOcrService
from .service import SubprocessOcrService

__version__ = "1.2.0"

__all__ = [
    "JsonLineOcrWorker",
    "OcrHealth",
    "OcrRequest",
    "OcrResult",
    "OcrService",
    "ResidentOcrService",
    "RegionOcrRequest",
    "SubprocessOcrService",
]
