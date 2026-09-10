from PIL import Image

from seenflow.models import OCRItem
from seenflow.ocr.provider import OCRProvider


class StubProvider:
    def detect(self, _image: Image.Image) -> list[OCRItem]:
        return []


def test_ocr_provider_is_structural() -> None:
    provider = StubProvider()

    assert isinstance(provider, OCRProvider)
