import os
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
    def __init__(
        self,
        factory: Callable[..., Any] = _create_engine,
        engine: str | None = None,
    ) -> None:
        selected_engine = engine or os.environ.get(
            "SEENFLOW_OCR_ENGINE", "onnxruntime"
        )
        if selected_engine not in {"paddle", "onnxruntime"}:
            raise ValueError(
                "SEENFLOW_OCR_ENGINE must be 'paddle' or 'onnxruntime', "
                f"got {selected_engine!r}"
            )
        options = dict(
            text_detection_model_name="PP-OCRv6_tiny_det",
            text_recognition_model_name="PP-OCRv6_tiny_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            return_word_box=True,
        )
        if selected_engine == "onnxruntime":
            options["engine"] = selected_engine
        else:
            # Paddle 3.3 oneDNN fails on PP-OCRv6 operators on Linux x64.
            options["enable_mkldnn"] = False
        try:
            self._engine = factory(**options)
        except Exception as error:
            if selected_engine != "onnxruntime":
                raise
            raise RuntimeError(
                f"Failed to initialize OCR engine 'onnxruntime': {error}"
            ) from error

    def detect(self, image: Image) -> list[OCRItem]:
        working = image.convert("RGB")
        working.thumbnail((MAX_OCR_DIMENSION, MAX_OCR_DIMENSION), Resampling.LANCZOS)
        scale_x = image.width / working.width
        scale_y = image.height / working.height
        items: list[OCRItem] = []
        line_id = 0
        for result in self._engine.predict(input=np.asarray(working)):
            data = result.json["res"]
            for result_line, (text, confidence, box) in enumerate(zip(
                data["rec_texts"], data["rec_scores"], data["rec_boxes"], strict=True
            )):
                words, word_boxes, refinement_error = _word_geometry(data, result_line)
                items.append(
                    OCRItem(
                        text=str(text),
                        confidence=float(confidence),
                        box=_scaled_box(box, scale_x, scale_y),
                        line_id=line_id,
                        span_start=0 if words is not None else None,
                        span_end=len(words) if words is not None else None,
                        refinement_error=refinement_error,
                    )
                )
                if words is not None and word_boxes is not None:
                    items.extend(
                        OCRItem(
                            text=word,
                            confidence=float(confidence),
                            box=_scaled_box(word_box, scale_x, scale_y),
                            source="word",
                            line_id=line_id,
                            span_start=index,
                            span_end=index + 1,
                        )
                        for index, (word, word_box) in enumerate(
                            zip(words, word_boxes, strict=True)
                        )
                    )
                line_id += 1
        return items


def _word_geometry(
    data: dict[str, Any], line: int
) -> tuple[list[str] | None, list[Any] | None, str | None]:
    try:
        word_lines = data["text_word"]
        box_lines = data["text_word_boxes"]
    except KeyError:
        return None, None, "WORD_BOXES_UNAVAILABLE"
    try:
        words = word_lines[line]
        boxes = box_lines[line]
        if (
            isinstance(words, (str, bytes))
            or isinstance(boxes, (str, bytes))
            or not words
            or len(words) != len(boxes)
        ):
            return None, None, "MALFORMED_WORD_GEOMETRY"
        word_pairs = [
            (str(word).strip(), box)
            for word, box in zip(words, boxes, strict=True)
            if str(word).strip()
        ]
        if not word_pairs:
            return None, None, "MALFORMED_WORD_GEOMETRY"
        for _word, box in word_pairs:
            if len(box) != 4:
                return None, None, "MALFORMED_WORD_GEOMETRY"
            tuple(float(value) for value in box)
    except (IndexError, TypeError, ValueError):
        return None, None, "MALFORMED_WORD_GEOMETRY"
    return (
        [word for word, _box in word_pairs],
        [box for _word, box in word_pairs],
        None,
    )


def _scaled_box(box: Any, scale_x: float, scale_y: float) -> BoundingBox:
    left, top, right, bottom = (float(value) for value in box)
    return BoundingBox(
        round(left * scale_x),
        round(top * scale_y),
        round((right - left) * scale_x),
        round((bottom - top) * scale_y),
    )
