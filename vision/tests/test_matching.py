import pytest

from seenflow.matching import (
    MatchSelectionError,
    evaluate_spatial_matches,
    find_matches,
    normalize_text,
    select_match,
)
from seenflow.models import BoundingBox, OCRItem, OCRMatch


def item(text: str, confidence: float, x: int, y: int) -> OCRItem:
    return OCRItem(text, confidence, BoundingBox(x, y, 40, 20))


def centered(text: str, confidence: float, x: int, y: int) -> OCRItem:
    return OCRItem(text, confidence, BoundingBox(x - 5, y - 5, 10, 10))


def merged_row() -> list[OCRItem]:
    return [
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


def test_exact_match_reconstructs_a_phrase_from_adjacent_words() -> None:
    matches = find_matches(merged_row(), "Chicken Curry", "exact")

    assert [(match.item.text, match.item.source, match.item.box) for match in matches] == [
        ("Chicken Curry", "phrase", BoundingBox(10, 20, 115, 40))
    ]


def test_precise_word_suppresses_overlapping_line_and_phrase_matches() -> None:
    matches = find_matches(merged_row(), "Edit", "contains")

    assert [(match.item.source, match.item.box.x) for match in matches] == [("word", 150)]


def test_phrase_reconstruction_never_crosses_ocr_lines() -> None:
    items = [
        OCRItem("Chicken", 0.97, BoundingBox(10, 20, 65, 40), "line", 0, 0, 1),
        OCRItem("Chicken", 0.97, BoundingBox(10, 20, 65, 40), "word", 0, 0, 1),
        OCRItem("Curry", 0.97, BoundingBox(10, 80, 45, 40), "line", 1, 0, 1),
        OCRItem("Curry", 0.97, BoundingBox(10, 80, 45, 40), "word", 1, 0, 1),
    ]

    assert find_matches(items, "Chicken Curry", "exact") == []


def test_duplicate_words_remain_separate_visual_occurrences() -> None:
    items = [
        OCRItem("Edit Edit", 0.97, BoundingBox(10, 20, 100, 40), "line", 0, 0, 2),
        OCRItem("Edit", 0.97, BoundingBox(10, 20, 40, 40), "word", 0, 0, 1),
        OCRItem("Edit", 0.97, BoundingBox(70, 20, 40, 40), "word", 0, 1, 2),
    ]

    matches = find_matches(items, "Edit", "contains")

    assert [(match.item.source, match.item.box.x) for match in matches] == [
        ("word", 10),
        ("word", 70),
    ]


def test_phrase_text_preserves_the_parent_lines_real_separators() -> None:
    items = [
        OCRItem("保存设置", 0.97, BoundingBox(10, 20, 100, 40), "line", 0, 0, 2),
        OCRItem("保存", 0.97, BoundingBox(10, 20, 45, 40), "word", 0, 0, 1),
        OCRItem("设置", 0.97, BoundingBox(65, 20, 45, 40), "word", 0, 1, 2),
    ]

    matches = find_matches(items, "保存设置", "exact")

    assert [(match.item.text, match.item.source) for match in matches] == [
        ("保存设置", "phrase")
    ]


def test_missing_occurrence_lists_every_candidate() -> None:
    matches = find_matches([item("Add", 0.9, 10, 20)], "Add", "exact")

    with pytest.raises(MatchSelectionError, match='occurrence 2.*"Add"') as error:
        select_match(matches, 2)

    assert error.value.matches == matches


@pytest.mark.parametrize(
    ("relation", "accepted_center", "rejected_center"),
    [
        ("rightOf", (150, 50), (120, 80)),
        ("leftOf", (50, 50), (80, 80)),
        ("above", (100, 20), (140, 30)),
        ("below", (100, 80), (140, 70)),
    ],
)
def test_directional_relationships_use_90_degree_cones(
    relation: str,
    accepted_center: tuple[int, int],
    rejected_center: tuple[int, int],
) -> None:
    anchor = OCRMatch(centered("Anchor", 0.99, 100, 50), 1.0)
    accepted = OCRMatch(centered("Edit", 0.9, *accepted_center), 1.0)
    rejected = OCRMatch(centered("Edit", 0.9, *rejected_center), 1.0)

    evaluations = evaluate_spatial_matches(
        [rejected, accepted], anchor, relation, 100, 200, 100
    )

    assert [entry.match for entry in evaluations if entry.accepted] == [accepted]
    assert next(entry for entry in evaluations if entry.match == rejected).direction_matches is False


def test_near_accepts_any_direction_and_ranks_by_distance() -> None:
    anchor = OCRMatch(centered("Anchor", 0.99, 100, 50), 1.0)
    farther = OCRMatch(centered("Edit", 0.9, 160, 50), 1.0)
    closer = OCRMatch(centered("Edit", 0.9, 80, 40), 1.0)

    evaluations = evaluate_spatial_matches(
        [farther, closer], anchor, "near", 100, 200, 100
    )

    assert [entry.match for entry in evaluations if entry.accepted] == [closer, farther]


def test_spatial_distance_is_screen_diagonal_percentage_and_includes_boundary() -> None:
    anchor = OCRMatch(centered("Anchor", 0.99, 50, 50), 1.0)
    candidate = OCRMatch(centered("Edit", 0.9, 100, 50), 1.0)
    boundary = 50 / (200**2 + 100**2) ** 0.5 * 100

    evaluation = evaluate_spatial_matches(
        [candidate], anchor, "rightOf", boundary, 200, 100
    )[0]

    assert evaluation.distance_percent == pytest.approx(boundary)
    assert evaluation.within_distance is True


def test_spatial_matching_excludes_the_selected_anchor_detection() -> None:
    anchor_item = centered("Edit", 0.99, 100, 50)
    anchor = OCRMatch(anchor_item, 1.0)
    other = OCRMatch(centered("Edit", 0.9, 120, 50), 1.0)

    evaluations = evaluate_spatial_matches(
        [OCRMatch(anchor_item, 1.0), other], anchor, "near", 100, 200, 100
    )

    assert [entry.match for entry in evaluations] == [other]


def test_spatial_ranking_uses_score_confidence_then_screen_order_after_distance() -> None:
    anchor = OCRMatch(centered("Anchor", 0.99, 100, 50), 1.0)
    lower_score = OCRMatch(centered("low score", 0.99, 120, 50), 0.8)
    lower_confidence = OCRMatch(centered("low confidence", 0.8, 80, 50), 1.0)
    lower_on_screen = OCRMatch(centered("lower", 0.9, 100, 70), 1.0)
    higher_on_screen = OCRMatch(centered("higher", 0.9, 100, 30), 1.0)

    evaluations = evaluate_spatial_matches(
        [lower_score, lower_on_screen, lower_confidence, higher_on_screen],
        anchor,
        "near",
        100,
        200,
        100,
    )

    assert [entry.match for entry in evaluations] == [
        higher_on_screen,
        lower_on_screen,
        lower_confidence,
        lower_score,
    ]


@pytest.mark.parametrize(
    ("relation", "max_distance", "width", "height"),
    [("diagonal", 20, 200, 100), ("near", 0, 200, 100), ("near", 101, 200, 100), ("near", 20, 0, 100)],
)
def test_spatial_matching_rejects_invalid_geometry(
    relation: str, max_distance: float, width: int, height: int
) -> None:
    anchor = OCRMatch(centered("Anchor", 0.99, 100, 50), 1.0)

    with pytest.raises(ValueError):
        evaluate_spatial_matches([], anchor, relation, max_distance, width, height)
