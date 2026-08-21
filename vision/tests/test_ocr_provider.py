from PIL import Image

from maestro_vision.models import BoundingBox, OCRItem
from maestro_vision.ocr.provider import OCRProvider


class StubProvider:
    def detect(self, _image: Image.Image) -> list[OCRItem]:
        return [OCRItem(text="Save", confidence=0.97, box=BoundingBox(1, 2, 3, 4))]


def test_ocr_provider_is_structural_and_returns_typed_items() -> None:
    provider = StubProvider()

    assert isinstance(provider, OCRProvider)
    assert provider.detect(Image.new("RGB", (10, 10))) == [
        OCRItem(text="Save", confidence=0.97, box=BoundingBox(x=1, y=2, width=3, height=4))
    ]
