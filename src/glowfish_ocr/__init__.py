"""Public OCR component API."""

from .contracts import OcrHealth, OcrRequest, OcrResult, OcrService, RegionOcrRequest
from .service import SubprocessOcrService

__version__ = "1.1.0"

__all__ = [
    "OcrHealth",
    "OcrRequest",
    "OcrResult",
    "OcrService",
    "RegionOcrRequest",
    "SubprocessOcrService",
]
