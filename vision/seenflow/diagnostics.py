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
) -> dict[str, str]:
    directory = root / datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S")
    return save_visual_artifacts(directory, image, items, selector, candidates)


def save_visual_artifacts(
    directory: Path,
    image: Image.Image,
    items: list[OCRItem],
    selector: dict[str, object],
    candidates: list[OCRMatch],
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
        color = "#ffbf00" if box in candidate_boxes else "#ff3b30"
        draw.rectangle((box.x, box.y, box.x + box.width, box.y + box.height), outline=color, width=3)
    marked.save(annotated, "PNG")
    ocr.write_text(
        json.dumps(
            {
                "selector": selector,
                "detections": [_item_json(item) for item in items],
                "candidates": [
                    {**_item_json(match.item), "score": match.score} for match in candidates
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return {
        "screenshot": str(screenshot),
        "annotated": str(annotated),
        "ocr": str(ocr),
    }


def _item_json(item: OCRItem) -> dict[str, object]:
    box = item.box
    return {
        "text": item.text,
        "confidence": item.confidence,
        "box": {"x": box.x, "y": box.y, "width": box.width, "height": box.height},
    }
