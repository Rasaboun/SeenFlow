import unicodedata
from difflib import SequenceMatcher
from math import hypot
from typing import Literal

from seenflow.models import BoundingBox, OCRItem, OCRMatch, SpatialEvaluation


MatchMode = Literal["exact", "contains", "fuzzy"]
SpatialRelation = Literal["near", "above", "below", "leftOf", "rightOf"]


class MatchSelectionError(LookupError):
    def __init__(self, occurrence: int, matches: list[OCRMatch]) -> None:
        self.matches = matches
        candidates = ", ".join(f'"{match.item.text}"' for match in matches) or "none"
        super().__init__(f"occurrence {occurrence} does not exist; candidates: {candidates}")


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).strip().split()).casefold()


def find_matches(
    items: list[OCRItem],
    query: str,
    mode: MatchMode,
    threshold: float = 0.85,
) -> list[OCRMatch]:
    normalized_query = normalize_text(query)
    if not normalized_query:
        raise ValueError("query must not be empty")
    if mode not in ("exact", "contains", "fuzzy"):
        raise ValueError("invalid match mode")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")

    matches: list[OCRMatch] = []
    for item in [*items, *_phrase_items(items)]:
        candidate = normalize_text(item.text)
        score = similarity(normalized_query, candidate, mode)
        if score is not None and (mode != "fuzzy" or score >= threshold):
            matches.append(OCRMatch(item, score))
    matches = _deduplicate_overlapping(matches)

    if mode == "fuzzy":
        return sorted(
            matches,
            key=lambda match: (
                -match.score,
                -match.item.confidence,
                match.item.box.y,
                match.item.box.x,
            ),
        )
    return sorted(matches, key=lambda match: (match.item.box.y, match.item.box.x))


def _phrase_items(items: list[OCRItem]) -> list[OCRItem]:
    lines = {
        item.line_id: item
        for item in items
        if item.source == "line" and item.line_id is not None
    }
    words_by_line: dict[int, list[OCRItem]] = {}
    for item in items:
        if item.source == "word" and item.line_id is not None:
            words_by_line.setdefault(item.line_id, []).append(item)

    phrases: list[OCRItem] = []
    for line_id, words in words_by_line.items():
        parent = lines.get(line_id)
        ordered = sorted(words, key=lambda item: item.span_start or 0)
        if parent is None or len(ordered) < 2 or not _contiguous(ordered):
            continue
        character_spans = _character_spans(parent.text, ordered)
        if character_spans is None:
            continue
        for start in range(len(ordered) - 1):
            for end in range(start + 2, len(ordered) + 1):
                phrase_words = ordered[start:end]
                text_start = character_spans[start][0]
                text_end = character_spans[end - 1][1]
                phrases.append(
                    OCRItem(
                        text=parent.text[text_start:text_end],
                        confidence=parent.confidence,
                        box=_union_box(phrase_words),
                        source="phrase",
                        line_id=line_id,
                        span_start=phrase_words[0].span_start,
                        span_end=phrase_words[-1].span_end,
                    )
                )
    return phrases


def _contiguous(words: list[OCRItem]) -> bool:
    return all(
        current.span_start is not None
        and current.span_end is not None
        and following.span_start == current.span_end
        for current, following in zip(words, words[1:])
    ) and words[-1].span_end is not None


def _character_spans(text: str, words: list[OCRItem]) -> list[tuple[int, int]] | None:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for word in words:
        start = text.find(word.text, cursor)
        if start < 0:
            return None
        end = start + len(word.text)
        spans.append((start, end))
        cursor = end
    return spans


def _union_box(items: list[OCRItem]) -> BoundingBox:
    left = min(item.box.x for item in items)
    top = min(item.box.y for item in items)
    right = max(item.box.x + item.box.width for item in items)
    bottom = max(item.box.y + item.box.height for item in items)
    return BoundingBox(left, top, right - left, bottom - top)


def _deduplicate_overlapping(matches: list[OCRMatch]) -> list[OCRMatch]:
    ungrouped = [
        match
        for match in matches
        if match.item.line_id is None
        or match.item.span_start is None
        or match.item.span_end is None
    ]
    grouped: dict[int, list[OCRMatch]] = {}
    for match in matches:
        if (
            match.item.line_id is not None
            and match.item.span_start is not None
            and match.item.span_end is not None
        ):
            grouped.setdefault(match.item.line_id, []).append(match)

    selected = list(ungrouped)
    source_rank = {"word": 0, "phrase": 1, "line": 2}
    for group in grouped.values():
        kept: list[OCRMatch] = []
        for match in sorted(
            group,
            key=lambda candidate: (
                -candidate.score,
                candidate.item.span_end - candidate.item.span_start,
                source_rank[candidate.item.source],
                candidate.item.box.width * candidate.item.box.height,
                -candidate.item.confidence,
            ),
        ):
            if any(_spans_overlap(match.item, other.item) for other in kept):
                continue
            kept.append(match)
        selected.extend(kept)
    return selected


def _spans_overlap(left: OCRItem, right: OCRItem) -> bool:
    assert left.span_start is not None and left.span_end is not None
    assert right.span_start is not None and right.span_end is not None
    return left.span_start < right.span_end and right.span_start < left.span_end


def select_match(matches: list[OCRMatch], occurrence: int) -> OCRMatch:
    if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 0:
        raise ValueError("occurrence must be a non-negative integer")
    if occurrence >= len(matches):
        raise MatchSelectionError(occurrence, matches)
    return matches[occurrence]


def evaluate_spatial_matches(
    matches: list[OCRMatch],
    anchor: OCRMatch,
    relation: SpatialRelation,
    max_distance: float,
    width: int,
    height: int,
) -> list[SpatialEvaluation]:
    if relation not in ("near", "above", "below", "leftOf", "rightOf"):
        raise ValueError("invalid spatial relation")
    if not 0 < max_distance <= 100:
        raise ValueError("max distance must be greater than 0 and at most 100")
    if width <= 0 or height <= 0:
        raise ValueError("screen dimensions must be positive")

    anchor_x, anchor_y = _center(anchor.item)
    diagonal = hypot(width, height)
    evaluations: list[SpatialEvaluation] = []
    for match in matches:
        if match.item == anchor.item:
            continue
        x, y = _center(match.item)
        dx, dy = x - anchor_x, y - anchor_y
        distance = hypot(dx, dy) / diagonal * 100
        evaluations.append(
            SpatialEvaluation(
                match=match,
                distance_percent=distance,
                direction_matches=_in_direction(relation, dx, dy),
                within_distance=distance <= max_distance,
            )
        )
    return sorted(
        evaluations,
        key=lambda entry: (
            not entry.accepted,
            entry.distance_percent,
            -entry.match.score,
            -entry.match.item.confidence,
            entry.match.item.box.y,
            entry.match.item.box.x,
        ),
    )


def _center(item: OCRItem) -> tuple[float, float]:
    return item.box.x + item.box.width / 2, item.box.y + item.box.height / 2


def _in_direction(relation: SpatialRelation, dx: float, dy: float) -> bool:
    if relation == "near":
        return True
    if relation == "rightOf":
        return dx > 0 and abs(dy) <= dx
    if relation == "leftOf":
        return dx < 0 and abs(dy) <= -dx
    if relation == "above":
        return dy < 0 and abs(dx) <= -dy
    return dy > 0 and abs(dx) <= dy


def similarity(query: str, candidate: str, mode: MatchMode) -> float | None:
    if mode == "exact":
        return 1.0 if candidate == query else None
    if mode == "contains":
        return 1.0 if query in candidate else None
    return SequenceMatcher(None, query, candidate, autojunk=False).ratio()
