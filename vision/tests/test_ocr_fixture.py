from pathlib import Path

from PIL import Image

from seenflow.matching import (
    evaluate_spatial_matches,
    find_matches,
    select_match,
)
from seenflow.ocr.paddle import PaddleOCRProvider


FIXTURE = Path(__file__).parent / "fixtures" / "text-screen.png"
SPATIAL_FIXTURE = Path(__file__).parent / "fixtures" / "spatial-merged-row.png"


def test_real_ocr_fixture_preserves_boxes_and_visual_order() -> None:
    items = PaddleOCRProvider().detect(Image.open(FIXTURE))
    lines = [item for item in items if item.source == "line"]

    assert [item.text for item in lines] == [
        "Save",
        "ADD",
        "Add",
        "start cooking",
        "small text",
        "Chicken Katsu",
        "25 min",
        "Welcome",
    ]
    assert abs(lines[0].box.x - 73) <= 10
    assert abs(lines[0].box.y - 78) <= 10
    assert abs(lines[0].box.width - 164) <= 15
    assert abs(lines[0].box.height - 73) <= 15
    assert lines[5].confidence < 0.98

    duplicates = find_matches(lines, "add", "exact")
    assert [(match.item.text, match.item.box.x) for match in duplicates] == [
        ("ADD", lines[1].box.x),
        ("Add", lines[2].box.x),
    ]
    assert [match.item.text for match in find_matches(lines, "  START   COOKING ", "exact")] == [
        "start cooking"
    ]
    assert find_matches(lines, "Chicken Katzu", "fuzzy", 0.85)[0].item.text == "Chicken Katsu"


def test_real_ocr_refines_a_merged_spatial_row() -> None:
    image = Image.open(SPATIAL_FIXTURE)
    items = PaddleOCRProvider().detect(image)

    line = next(
        item
        for item in items
        if item.source == "line" and "Chicken Curry" in item.text and "Edit" in item.text
    )
    anchor = select_match(find_matches(items, "Chicken Curry", "exact"), 0)
    targets = find_matches(items, "Edit", "exact")
    evaluations = evaluate_spatial_matches(
        targets, anchor, "rightOf", 20, image.width, image.height
    )

    assert line.box.width > anchor.item.box.width
    assert anchor.item.source == "phrase"
    assert evaluations[0].accepted
    assert evaluations[0].match.item.source == "word"
    assert evaluations[0].match.item.box.x > anchor.item.box.x + anchor.item.box.width
