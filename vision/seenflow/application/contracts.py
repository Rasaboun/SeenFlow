from dataclasses import dataclass, field
from math import isfinite
import re
from typing import Literal

from seenflow.matching import MatchMode, SpatialRelation
from seenflow.models import OCRItem, OCRMatch, SpatialEvaluation

VisualState = Literal["visible", "not-visible"]
_DEVICE_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def validate_device_id(device_id: str) -> str:
    if not isinstance(device_id, str) or _DEVICE_ID.fullmatch(device_id) is None:
        raise ValueError("invalid device ID")
    return device_id


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise ValueError("invalid run ID")
    return run_id


def validate_device(platform: str, device_id: str) -> None:
    if platform not in ("ios", "android"):
        raise ValueError("invalid platform")
    validate_device_id(device_id)


def _text(text: str) -> None:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must not be blank")


def _integer(value: int, minimum: int, name: str) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer at least {minimum}")


def _number(value: float, name: str) -> None:
    if type(value) not in (float, int) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def _state(state: str) -> None:
    if state not in ("visible", "not-visible"):
        raise ValueError("invalid expected state")


@dataclass(frozen=True)
class TextSelector:
    text: str
    match: MatchMode = "exact"
    threshold: float = 0.85
    occurrence: int = 0

    def __post_init__(self) -> None:
        _text(self.text)
        if self.match not in ("exact", "contains", "fuzzy"):
            raise ValueError("invalid match mode")
        _number(self.threshold, "threshold")
        if not 0 <= self.threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")
        _integer(self.occurrence, 0, "occurrence")


@dataclass(frozen=True)
class SpatialSelector:
    relation: SpatialRelation
    anchor: TextSelector
    max_distance: float

    def __post_init__(self) -> None:
        if self.relation not in ("near", "above", "below", "leftOf", "rightOf"):
            raise ValueError("invalid spatial relation")
        _number(self.max_distance, "max_distance")
        if not 0 < self.max_distance <= 100:
            raise ValueError("max_distance must be greater than 0 and at most 100")


@dataclass(frozen=True)
class VisualCondition:
    text: str
    state: VisualState

    def __post_init__(self) -> None:
        _text(self.text)
        _state(self.state)


@dataclass(frozen=True)
class FindText:
    platform: str
    device_id: str
    text: str
    match: MatchMode = "exact"
    threshold: float = 0.85
    occurrence: int = 0
    spatial: SpatialSelector | None = None
    precondition: VisualCondition | None = None
    diagnostics: bool = False
    context: str | None = None
    state: VisualState | None = None
    attempt: int | None = None
    run_id: str | None = None
    step: int | None = None
    action: str | None = None

    def __post_init__(self) -> None:
        validate_device(self.platform, self.device_id)
        _ = self.selector  # Validate selector invariants for non-HTTP callers too.
        if type(self.diagnostics) is not bool:
            raise ValueError("diagnostics must be a boolean")
        if self.context is not None and self.context not in ("target", "precondition", "postcondition"):
            raise ValueError("invalid context")
        if self.state is not None:
            _state(self.state)
        if self.attempt is not None:
            _integer(self.attempt, 1, "attempt")
        if self.step is not None:
            _integer(self.step, 1, "step")
        if self.action is not None and (not self.action.strip() or len(self.action) > 512):
            raise ValueError("action must contain 1 to 512 characters")
        values = (self.run_id, self.step, self.action)
        if any(value is not None for value in values) and not all(value is not None for value in values):
            raise ValueError("run_id, step, and action must be provided together")
        if self.run_id is not None:
            validate_run_id(self.run_id)
            if self.context is None or self.attempt is None:
                raise ValueError("journaled requests require context and attempt")

    @property
    def journal_context(self) -> "JournalContext | None":
        if self.run_id is None:
            return None
        assert self.step is not None and self.action is not None
        assert self.context is not None and self.attempt is not None
        return JournalContext(self.run_id, self.step, self.action, self.context, self.attempt)

    @property
    def selector(self) -> TextSelector:
        return TextSelector(self.text, self.match, self.threshold, self.occurrence)


@dataclass(frozen=True)
class JournalContext:
    run_id: str
    step: int
    action: str
    phase: str
    attempt: int


@dataclass(frozen=True)
class DeviceContext:
    platform: str
    device_id: str
    step: int
    action: str


@dataclass(frozen=True)
class Detection:
    width: int
    height: int
    items: list[OCRItem]


@dataclass(frozen=True)
class ConditionResult:
    found: bool
    query: str
    state: VisualState


@dataclass(frozen=True)
class TargetFailure:
    code: str = "ACTION_TARGET_NOT_FOUND"
    reason: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class SpatialEvidence:
    anchor: OCRMatch | None
    evaluations: list[SpatialEvaluation] = field(default_factory=list)
    reason: str = "MATCHED"


@dataclass(frozen=True)
class Selection:
    text: TextSelector
    spatial: SpatialSelector | None = None


@dataclass(frozen=True)
class FindResult:
    query: str
    width: int
    height: int
    match: OCRMatch | None = None
    candidates: list[OCRMatch] = field(default_factory=list)
    detections: list[OCRItem] | None = None
    artifacts: dict[str, str] | None = None
    precondition: ConditionResult | None = None
    error: TargetFailure | None = None
