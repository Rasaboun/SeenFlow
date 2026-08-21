from typing import Protocol, runtime_checkable

from PIL.Image import Image

from maestro_vision.models import OCRItem


@runtime_checkable
class OCRProvider(Protocol):
    def detect(self, image: Image) -> list[OCRItem]: ...
