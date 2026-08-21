from collections.abc import Callable
from typing import Any

import numpy as np
from PIL.Image import Image

from maestro_vision.models import BoundingBox, OCRItem


def _create_engine(**options: Any) -> Any:
    from paddleocr import PaddleOCR

    return PaddleOCR(**options)


class PaddleOCRProvider:
    def __init__(self, factory: Callable[..., Any] = _create_engine) -> None:
        self._engine = factory(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def detect(self, image: Image) -> list[OCRItem]:
        items: list[OCRItem] = []
        for result in self._engine.predict(input=np.asarray(image.convert("RGB"))):
            data = result.json["res"]
            for text, confidence, box in zip(
                data["rec_texts"], data["rec_scores"], data["rec_boxes"], strict=True
            ):
                left, top, right, bottom = (int(value) for value in box)
                items.append(
                    OCRItem(
                        text=str(text),
                        confidence=float(confidence),
                        box=BoundingBox(left, top, right - left, bottom - top),
                    )
                )
        return items
