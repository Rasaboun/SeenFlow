import unicodedata
from difflib import SequenceMatcher
from typing import Literal

from seenflow.models import OCRItem, OCRMatch


MatchMode = Literal["exact", "contains", "fuzzy"]


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


def similarity(query: str, candidate: str, mode: MatchMode) -> float | None:
    if mode == "exact":
        return 1.0 if candidate == query else None
    if mode == "contains":
        return 1.0 if query in candidate else None
    return SequenceMatcher(None, query, candidate, autojunk=False).ratio()
