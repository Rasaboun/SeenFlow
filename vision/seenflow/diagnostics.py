import json
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw

from seenflow.models import OCRItem, OCRMatch


def save_failure_artifacts(
    root: Path,
    image: Image.Image,
    items: list[OCRItem],
    selector: dict[str, object],
    candidates: list[OCRMatch],
    details: dict[str, object] | None = None,
) -> dict[str, str]:
    directory = root / datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S")
    return save_visual_artifacts(directory, image, items, selector, candidates, details)


def save_visual_artifacts(
    directory: Path,
    image: Image.Image,
    items: list[OCRItem],
    selector: dict[str, object],
    candidates: list[OCRMatch],
    details: dict[str, object] | None = None,
) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    screenshot = directory / "screenshot.png"
    annotated = directory / "annotated.png"
    ocr = directory / "ocr.json"

    image.save(screenshot, "PNG")
    marked = image.copy()
    draw = ImageDraw.Draw(marked)
    candidate_boxes = {match.item.box for match in candidates}
    for item in items:
        box = item.box
        color = "#ffbf00" if box in candidate_boxes else {
            "line": "#ff3b30",
            "word": "#0a84ff",
            "phrase": "#0a84ff",
        }[item.source]
        draw.rectangle((box.x, box.y, box.x + box.width, box.y + box.height), outline=color, width=3)
    for match in candidates:
        box = match.item.box
        draw.rectangle(
            (box.x, box.y, box.x + box.width, box.y + box.height),
            outline="#ffbf00",
            width=3,
        )
    marked.save(annotated, "PNG")
    payload = {
        "selector": selector,
        "detections": [_item_json(item) for item in items],
        "candidates": [
            {**_item_json(match.item), "score": match.score} for match in candidates
        ],
    }
    if details is not None:
        payload["spatial"] = details
    ocr.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return {
        "screenshot": str(screenshot),
        "annotated": str(annotated),
        "ocr": str(ocr),
    }


def _item_json(item: OCRItem) -> dict[str, object]:
    box = item.box
    payload: dict[str, object] = {
        "text": item.text,
        "confidence": item.confidence,
        "box": {"x": box.x, "y": box.y, "width": box.width, "height": box.height},
        "source": item.source,
    }
    if item.line_id is not None:
        payload["lineId"] = item.line_id
    if item.span_start is not None and item.span_end is not None:
        payload["span"] = {"start": item.span_start, "end": item.span_end}
    if item.refinement_error is not None:
        payload["refinementError"] = item.refinement_error
    return payload
