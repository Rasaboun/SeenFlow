import pytest

from seenflow.matching import MatchSelectionError, find_matches, normalize_text, select_match
from seenflow.models import BoundingBox, OCRItem


def item(text: str, confidence: float, x: int, y: int) -> OCRItem:
    return OCRItem(text, confidence, BoundingBox(x, y, 40, 20))


def test_normalization_handles_unicode_case_and_whitespace_but_keeps_punctuation() -> None:
    assert normalize_text("  ＳＴＡＲＴ   Cooking \n") == "start cooking"
    assert normalize_text("Save!") != normalize_text("Save")


def test_exact_and_contains_use_normalized_text() -> None:
    items = [item("  START   COOKING ", 0.9, 10, 20), item("Start cooking now", 0.8, 10, 50)]

    assert [match.item.text for match in find_matches(items, "start cooking", "exact")] == [
        "  START   COOKING "
    ]
    assert [match.item.text for match in find_matches(items, "start cooking", "contains")] == [
        "  START   COOKING ",
        "Start cooking now",
    ]


def test_fuzzy_matching_applies_threshold_and_ranks_deterministically() -> None:
    items = [
        item("START COOKlNG", 0.91, 40, 80),
        item("Start cooking", 0.80, 10, 100),
        item("Start cook", 0.99, 10, 20),
    ]

    matches = find_matches(items, "Start cooking", "fuzzy", threshold=0.85)

    assert [match.item.text for match in matches] == ["Start cooking", "START COOKlNG", "Start cook"]
    assert matches[0].score == 1.0
    assert matches[1].score > matches[2].score >= 0.85


def test_duplicate_exact_text_uses_screen_order_not_confidence() -> None:
    items = [item("Add", 0.99, 200, 100), item("Add", 0.70, 10, 20), item("Add", 0.95, 30, 20)]

    matches = find_matches(items, "Add", "exact")

    assert [(match.item.box.x, match.item.box.y) for match in matches] == [(10, 20), (30, 20), (200, 100)]
    assert select_match(matches, 1).item.box.x == 30


def test_missing_occurrence_lists_every_candidate() -> None:
    matches = find_matches([item("Add", 0.9, 10, 20)], "Add", "exact")

    with pytest.raises(MatchSelectionError, match='occurrence 2.*"Add"') as error:
        select_match(matches, 2)

    assert error.value.matches == matches
