from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class BoundingBox:
    x: int
    y: int
    width: int
    height: int


OCRSource = Literal["line", "word", "phrase"]


@dataclass(frozen=True)
class OCRItem:
    text: str
    confidence: float
    box: BoundingBox
    source: OCRSource = "line"
    line_id: int | None = None
    span_start: int | None = None
    span_end: int | None = None


@dataclass(frozen=True)
class OCRMatch:
    item: OCRItem
    score: float


@dataclass(frozen=True)
class SpatialEvaluation:
    match: OCRMatch
    distance_percent: float
    direction_matches: bool
    within_distance: bool

    @property
    def accepted(self) -> bool:
        return self.direction_matches and self.within_distance
