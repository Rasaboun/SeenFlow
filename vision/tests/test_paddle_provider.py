from typing import Any

import pytest
from PIL import Image

from seenflow.models import BoundingBox, OCRItem
from seenflow.ocr.paddle import PaddleOCRProvider


class FakeResult:
    json = {
        "res": {
            "rec_texts": ["Chicken Curry Edit"],
            "rec_scores": [0.97],
            "rec_boxes": [[10, 20, 190, 60]],
            "text_word": [["Chicken", "Curry", "Edit"]],
            "text_word_boxes": [
                [[10, 20, 75, 60], [80, 20, 125, 60], [150, 20, 190, 60]]
            ],
        }
    }


class FakeEngine:
    def __init__(self, result: type[Any] = FakeResult) -> None:
        self.result = result
        self.inputs: list[Any] = []

    def predict(self, input: Any) -> list[FakeResult]:
        self.inputs.append(input)
        return [self.result()]


def test_paddle_provider_initializes_once_and_converts_results() -> None:
    engine = FakeEngine()
    initializations: list[dict[str, Any]] = []

    def factory(**options: Any) -> FakeEngine:
        initializations.append(options)
        return engine

    provider = PaddleOCRProvider(factory)
    image = Image.new("RGB", (200, 120))

    expected = [
        OCRItem(
            "Chicken Curry Edit",
            0.97,
            BoundingBox(10, 20, 180, 40),
            "line",
            0,
            0,
            3,
        ),
        OCRItem("Chicken", 0.97, BoundingBox(10, 20, 65, 40), "word", 0, 0, 1),
        OCRItem("Curry", 0.97, BoundingBox(80, 20, 45, 40), "word", 0, 1, 2),
        OCRItem("Edit", 0.97, BoundingBox(150, 20, 40, 40), "word", 0, 2, 3),
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
            "return_word_box": True,
        }
    ]
    assert len(engine.inputs) == 2


def test_paddle_provider_selects_onnx_runtime_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("SEENFLOW_OCR_ENGINE", "onnxruntime")
    initializations: list[dict[str, Any]] = []

    PaddleOCRProvider(
        lambda **options: initializations.append(options) or FakeEngine()
    )

    assert initializations[0]["engine"] == "onnxruntime"


def test_paddle_provider_explicit_engine_overrides_environment(monkeypatch) -> None:
    monkeypatch.setenv("SEENFLOW_OCR_ENGINE", "onnxruntime")
    initializations: list[dict[str, Any]] = []

    PaddleOCRProvider(
        lambda **options: initializations.append(options) or FakeEngine(),
        engine="paddle",
    )

    assert "engine" not in initializations[0]


def test_paddle_provider_rejects_unknown_engine(monkeypatch) -> None:
    monkeypatch.setenv("SEENFLOW_OCR_ENGINE", "metal")

    with pytest.raises(ValueError, match="SEENFLOW_OCR_ENGINE.*paddle.*onnxruntime"):
        PaddleOCRProvider(lambda **_options: FakeEngine())


def test_paddle_provider_reports_onnx_initialization_failure() -> None:
    def fail(**_options: Any) -> FakeEngine:
        raise RuntimeError("missing runtime")

    with pytest.raises(
        RuntimeError,
        match="Failed to initialize OCR engine 'onnxruntime'.*missing runtime",
    ):
        PaddleOCRProvider(fail, engine="onnxruntime")


def test_paddle_provider_downscales_large_screens_and_restores_original_boxes() -> None:
    engine = FakeEngine()
    provider = PaddleOCRProvider(lambda **_options: engine)

    items = provider.detect(Image.new("RGB", (1200, 2400)))

    assert engine.inputs[0].shape[:2] == (960, 480)
    assert items == [
        OCRItem(
            "Chicken Curry Edit",
            0.97,
            BoundingBox(25, 50, 450, 100),
            "line",
            0,
            0,
            3,
        ),
        OCRItem("Chicken", 0.97, BoundingBox(25, 50, 162, 100), "word", 0, 0, 1),
        OCRItem("Curry", 0.97, BoundingBox(200, 50, 112, 100), "word", 0, 1, 2),
        OCRItem("Edit", 0.97, BoundingBox(375, 50, 100, 100), "word", 0, 2, 3),
    ]


def test_paddle_provider_ignores_malformed_word_geometry_for_that_line() -> None:
    class MalformedResult:
        json = {
            "res": {
                "rec_texts": ["Chicken Curry Edit"],
                "rec_scores": [0.97],
                "rec_boxes": [[10, 20, 190, 60]],
                "text_word": [["Chicken", "Curry", "Edit"]],
                "text_word_boxes": [[[10, 20, 75, 60]]],
            }
        }

    provider = PaddleOCRProvider(lambda **_options: FakeEngine(MalformedResult))

    assert provider.detect(Image.new("RGB", (200, 120))) == [
        OCRItem(
            "Chicken Curry Edit",
            0.97,
            BoundingBox(10, 20, 180, 40),
            line_id=0,
            refinement_error="MALFORMED_WORD_GEOMETRY",
        )
    ]


def test_paddle_provider_marks_unavailable_word_geometry() -> None:
    class MissingResult:
        json = {
            "res": {
                "rec_texts": ["Save"],
                "rec_scores": [0.97],
                "rec_boxes": [[10, 20, 50, 60]],
            }
        }

    provider = PaddleOCRProvider(lambda **_options: FakeEngine(MissingResult))

    assert provider.detect(Image.new("RGB", (200, 120))) == [
        OCRItem(
            "Save",
            0.97,
            BoundingBox(10, 20, 40, 40),
            line_id=0,
            refinement_error="WORD_BOXES_UNAVAILABLE",
        )
    ]


def test_paddle_provider_omits_whitespace_alignment_boxes() -> None:
    class WhitespaceResult:
        json = {
            "res": {
                "rec_texts": ["Chicken Curry"],
                "rec_scores": [0.97],
                "rec_boxes": [[10, 20, 125, 60]],
                "text_word": [["Chicken", " ", "Curry"]],
                "text_word_boxes": [
                    [[10, 20, 75, 60], [75, 20, 80, 60], [80, 20, 125, 60]]
                ],
            }
        }

    provider = PaddleOCRProvider(lambda **_options: FakeEngine(WhitespaceResult))

    assert provider.detect(Image.new("RGB", (200, 120))) == [
        OCRItem("Chicken Curry", 0.97, BoundingBox(10, 20, 115, 40), "line", 0, 0, 2),
        OCRItem("Chicken", 0.97, BoundingBox(10, 20, 65, 40), "word", 0, 0, 1),
        OCRItem("Curry", 0.97, BoundingBox(80, 20, 45, 40), "word", 0, 1, 2),
    ]
