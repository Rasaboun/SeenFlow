import unicodedata
from difflib import SequenceMatcher
from math import hypot
from typing import Literal

from seenflow.models import OCRItem, OCRMatch, SpatialEvaluation


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
    for item in items:
        candidate = normalize_text(item.text)
        score = similarity(normalized_query, candidate, mode)
        if score is not None and (mode != "fuzzy" or score >= threshold):
            matches.append(OCRMatch(item, score))

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
