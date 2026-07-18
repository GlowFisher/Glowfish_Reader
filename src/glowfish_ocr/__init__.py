"""Public OCR component API."""

from .contracts import OcrHealth, OcrRequest, OcrResult, OcrService, RegionOcrRequest
from .resident import JsonLineOcrWorker, OcrWorkerError, ResidentOcrService
from .service import SubprocessOcrService

__version__ = "1.2.0"

__all__ = [
    "JsonLineOcrWorker",
    "OcrHealth",
    "OcrRequest",
    "OcrResult",
    "OcrService",
    "OcrWorkerError",
    "ResidentOcrService",
    "RegionOcrRequest",
    "SubprocessOcrService",
]
