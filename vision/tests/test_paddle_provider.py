from typing import Any

from PIL import Image

from seenflow.models import BoundingBox, OCRItem
from seenflow.ocr.paddle import PaddleOCRProvider


class FakeResult:
    json = {
        "res": {
            "rec_texts": ["Save", "Loading..."],
            "rec_scores": [0.97, 0.91],
            "rec_boxes": [[10, 20, 50, 60], [70, 80, 170, 100]],
        }
    }


class FakeEngine:
    def __init__(self) -> None:
        self.inputs: list[Any] = []

    def predict(self, input: Any) -> list[FakeResult]:
        self.inputs.append(input)
        return [FakeResult()]


def test_paddle_provider_initializes_once_and_converts_results() -> None:
    engine = FakeEngine()
    initializations: list[dict[str, Any]] = []

    def factory(**options: Any) -> FakeEngine:
        initializations.append(options)
        return engine

    provider = PaddleOCRProvider(factory)
    image = Image.new("RGB", (200, 120))

    expected = [
        OCRItem("Save", 0.97, BoundingBox(10, 20, 40, 40)),
        OCRItem("Loading...", 0.91, BoundingBox(70, 80, 100, 20)),
    ]
    assert provider.detect(image) == expected
    assert provider.detect(image) == expected
    assert initializations == [
        {
            "text_detection_model_name": "PP-OCRv6_tiny_det",
            "text_recognition_model_name": "PP-OCRv6_tiny_rec",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
    ]
    assert len(engine.inputs) == 2


def test_paddle_provider_downscales_large_screens_and_restores_original_boxes() -> None:
    engine = FakeEngine()
    provider = PaddleOCRProvider(lambda **_options: engine)

    items = provider.detect(Image.new("RGB", (1200, 2400)))

    assert engine.inputs[0].shape[:2] == (960, 480)
    assert items == [
        OCRItem("Save", 0.97, BoundingBox(25, 50, 100, 100)),
        OCRItem("Loading...", 0.91, BoundingBox(175, 200, 250, 50)),
    ]
