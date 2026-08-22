from collections.abc import Callable
from typing import Any

import numpy as np
from PIL.Image import Image, Resampling

from seenflow.models import BoundingBox, OCRItem


MAX_OCR_DIMENSION = 960


def _create_engine(**options: Any) -> Any:
    from paddleocr import PaddleOCR

    return PaddleOCR(**options)


class PaddleOCRProvider:
    def __init__(self, factory: Callable[..., Any] = _create_engine) -> None:
        self._engine = factory(
            text_detection_model_name="PP-OCRv6_tiny_det",
            text_recognition_model_name="PP-OCRv6_tiny_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def detect(self, image: Image) -> list[OCRItem]:
        working = image.convert("RGB")
        working.thumbnail((MAX_OCR_DIMENSION, MAX_OCR_DIMENSION), Resampling.LANCZOS)
        scale_x = image.width / working.width
        scale_y = image.height / working.height
        items: list[OCRItem] = []
        for result in self._engine.predict(input=np.asarray(working)):
            data = result.json["res"]
            for text, confidence, box in zip(
                data["rec_texts"], data["rec_scores"], data["rec_boxes"], strict=True
            ):
                left, top, right, bottom = (float(value) for value in box)
                items.append(
                    OCRItem(
                        text=str(text),
                        confidence=float(confidence),
                        box=BoundingBox(
                            round(left * scale_x),
                            round(top * scale_y),
                            round((right - left) * scale_x),
                            round((bottom - top) * scale_y),
                        ),
                    )
                )
        return items
