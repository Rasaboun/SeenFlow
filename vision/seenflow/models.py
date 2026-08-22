from dataclasses import dataclass


@dataclass(frozen=True)
class BoundingBox:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class OCRItem:
    text: str
    confidence: float
    box: BoundingBox


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
