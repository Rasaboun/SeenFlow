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
