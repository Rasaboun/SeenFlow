from collections.abc import Callable
from typing import Protocol, runtime_checkable

from PIL.Image import Image

from seenflow.application.contracts import DeviceContext, Selection, SpatialEvidence
from seenflow.models import OCRItem, OCRMatch


@runtime_checkable
class OCRProvider(Protocol):
    def detect(self, image: Image) -> list[OCRItem]: ...


class ScreenshotCapture(Protocol):
    def capture(self, device_id: str) -> bytes: ...


ImageDecoder = Callable[[bytes], Image]
ArtifactWriter = Callable[
    [Image, list[OCRItem], Selection, list[OCRMatch], SpatialEvidence | None],
    dict[str, str],
]


class Journal(Protocol):
    def remember_context(self, run_id: str, platform: str, device_id: str, step: int, action: str) -> None: ...
    def context(self, run_id: str) -> DeviceContext | None: ...
    def record(
        self, *, run_id: str, step: int, phase: str, attempt: int, action: str,
        state: str | None, image: Image, items: list[OCRItem], selector: Selection | None,
        candidates: list[OCRMatch], found: bool, capture_ms: float, ocr_ms: float,
        details: SpatialEvidence | None = None,
    ) -> dict[str, str]: ...
    def record_error(
        self, *, run_id: str, step: int, phase: str, attempt: int, action: str,
        state: str | None, code: str, message: str, image: Image | None = None,
        capture_ms: float | None = None,
    ) -> dict[str, str]: ...
