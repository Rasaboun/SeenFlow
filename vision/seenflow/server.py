import os
import secrets
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Annotated
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from seenflow.capture.android import AndroidCapture
from seenflow.capture.base import CaptureError, ScreenshotCapture
from seenflow.capture.ios import IOSSimulatorCapture
from seenflow.diagnostics import save_failure_artifacts
from seenflow.journal import VisualJournal
from seenflow.matching import (
    MatchSelectionError,
    evaluate_spatial_matches,
    find_matches,
    select_match,
)
from seenflow.models import BoundingBox, OCRItem, OCRMatch, SpatialEvaluation
from seenflow.ocr.paddle import PaddleOCRProvider
from seenflow.ocr.provider import OCRProvider


HOST = "127.0.0.1"
MAX_REQUEST_BYTES = 16_384


class DetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    platform: Literal["ios", "android"]
    device_id: str = Field(alias="deviceId", pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class AnchorSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1)
    match: Literal["exact", "contains", "fuzzy"] = "exact"
    threshold: float = Field(default=0.85, ge=0, le=1)
    occurrence: int = Field(default=0, ge=0)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class SpatialSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    relation: Literal["near", "above", "below", "leftOf", "rightOf"]
    anchor: AnchorSelector
    max_distance: float = Field(alias="maxDistance", gt=0, le=100)


class FindRequest(DetectRequest):
    text: str = Field(min_length=1)
    match: Literal["exact", "contains", "fuzzy"] = "exact"
    threshold: float = Field(default=0.85, ge=0, le=1)
    occurrence: int = Field(default=0, ge=0)
    spatial: SpatialSelector | None = None
    diagnostics: bool = False
    context: Literal["target", "precondition", "postcondition"] | None = None
    state: Literal["visible", "not-visible"] | None = None
    attempt: int | None = Field(default=None, ge=1)
    run_id: str | None = Field(
        default=None,
        alias="runId",
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
    )
    step: int | None = Field(default=None, ge=1)
    action: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("action")
    @classmethod
    def reject_blank_action(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("action must not be blank")
        return value

    @model_validator(mode="after")
    def require_complete_journal_context(self) -> "FindRequest":
        values = (self.run_id, self.step, self.action)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("runId, step, and action must be provided together")
        if self.run_id is not None and (self.context is None or self.attempt is None):
            raise ValueError("journaled requests require context and attempt")
        return self


class FinalDiagnosticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    run_id: str = Field(alias="runId", pattern=r"^[A-Za-z0-9_-]{1,64}$")


def create_app(
    session_token: str,
    provider_factory: Callable[[], OCRProvider] = PaddleOCRProvider,
    captures: dict[str, ScreenshotCapture] | None = None,
    artifacts_dir: Path | None = None,
    debug: bool = False,
) -> FastAPI:
    if not session_token:
        raise ValueError("session token must not be empty")

    async def authenticate(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {session_token}"
        if authorization is None or not secrets.compare_digest(
            authorization.encode(), expected.encode()
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid session token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    app = FastAPI(
        dependencies=[Depends(authenticate)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.ocr_provider = provider_factory()
    app.state.captures = captures or {
        "ios": IOSSimulatorCapture(),
        "android": AndroidCapture(),
    }
    app.state.artifacts_dir = artifacts_dir or Path(".seenflow/artifacts")
    app.state.journal = VisualJournal(app.state.artifacts_dir)
    app.state.debug = debug

    @app.middleware("http")
    async def limit_request_body(request: Request, call_next):
        body = await request.body()
        if len(body) > MAX_REQUEST_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body too large"})
        request._body = body
        return await call_next(request)

    @app.get("/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/text/detect")
    async def detect(request: DetectRequest) -> dict[str, object]:
        image, items = analyze(app, request.platform, request.device_id)
        return {
            "width": image.width,
            "height": image.height,
            "items": [item_json(item) for item in items],
        }

    @app.post("/v1/text/find")
    async def find(request: FindRequest) -> dict[str, object]:
        journaled = request.run_id is not None
        if journaled:
            app.state.journal.remember_context(
                request.run_id,
                request.platform,
                request.device_id,
                request.step,
                request.action,
            )
        try:
            image, capture_ms = capture_image(app, request.platform, request.device_id)
        except HTTPException as error:
            if journaled:
                app.state.journal.record_error(
                    run_id=request.run_id,
                    step=request.step,
                    phase=request.context,
                    attempt=request.attempt,
                    action=request.action,
                    state=request.state,
                    code="OCR_CAPTURE_FAILED",
                    message=str(error.detail["message"]),
                )
            raise
        try:
            items, ocr_ms = detect_items(app, image)
        except HTTPException as error:
            if journaled:
                artifacts = app.state.journal.record_error(
                    run_id=request.run_id,
                    step=request.step,
                    phase=request.context,
                    attempt=request.attempt,
                    action=request.action,
                    state=request.state,
                    code="OCR_RUNTIME_FAILED",
                    message=str(error.detail["message"]),
                    image=image,
                    capture_ms=capture_ms,
                )
                error.detail["artifacts"] = artifacts
            raise
        matches = find_matches(items, request.text, request.match, request.threshold)
        log_visual_result(app, request, bool(matches))
        selector = {
            "text": request.text,
            "match": request.match,
            "threshold": request.threshold,
            "occurrence": request.occurrence,
        }
        if request.spatial is not None:
            selector["spatial"] = request.spatial.model_dump(by_alias=True)

        def record_journal(
            found: bool,
            candidates: list[OCRMatch] = matches,
            details: dict[str, object] | None = None,
        ) -> dict[str, str] | None:
            if not journaled:
                return None
            return app.state.journal.record(
                run_id=request.run_id,
                step=request.step,
                phase=request.context,
                attempt=request.attempt,
                action=request.action,
                state=request.state,
                image=image,
                items=items,
                selector=selector,
                candidates=candidates,
                found=found,
                capture_ms=capture_ms,
                ocr_ms=ocr_ms,
                details=details,
            )

        def spatial_failure(
            reason: str,
            details: dict[str, object],
            candidates: list[OCRMatch] = matches,
        ) -> dict[str, object]:
            details["reason"] = reason
            journal_artifacts = record_journal(False, candidates, details)
            artifacts = journal_artifacts or save_failure_artifacts(
                app.state.artifacts_dir,
                image,
                items,
                selector,
                candidates,
                details,
            )
            return {
                "found": False,
                "query": request.text,
                "matches": [match_json(candidate) for candidate in candidates],
                "detections": [item_json(item) for item in items],
                "artifacts": artifacts,
                "error": {
                    "code": "ACTION_TARGET_NOT_FOUND",
                    "reason": reason,
                },
            }

        spatial_details: dict[str, object] | None = None
        match: OCRMatch
        if request.spatial is not None:
            spatial = request.spatial
            anchor_matches = find_matches(
                items,
                spatial.anchor.text,
                spatial.anchor.match,
                spatial.anchor.threshold,
            )
            if not anchor_matches:
                return spatial_failure("ANCHOR_TEXT_NOT_FOUND", {"anchor": None, "candidates": []})
            try:
                anchor = select_match(anchor_matches, spatial.anchor.occurrence)
            except MatchSelectionError:
                return spatial_failure(
                    "ANCHOR_OCCURRENCE_NOT_FOUND",
                    {"anchor": None, "candidates": []},
                    anchor_matches,
                )
            if not matches:
                return spatial_failure(
                    "TARGET_TEXT_NOT_FOUND",
                    {"anchor": match_json(anchor), "candidates": []},
                )
            evaluations = evaluate_spatial_matches(
                matches,
                anchor,
                spatial.relation,
                spatial.max_distance,
                image.width,
                image.height,
            )
            spatial_details = {
                "anchor": match_json(anchor),
                "candidates": [spatial_evaluation_json(entry) for entry in evaluations],
            }
            directional = [entry for entry in evaluations if entry.direction_matches]
            if not directional:
                return spatial_failure("DIRECTION_MISMATCH", spatial_details)
            valid = [entry.match for entry in directional if entry.within_distance]
            if not valid:
                return spatial_failure("MAX_DISTANCE_EXCEEDED", spatial_details)
            try:
                match = select_match(valid, request.occurrence)
            except MatchSelectionError:
                return spatial_failure("TARGET_OCCURRENCE_NOT_FOUND", spatial_details, valid)
            spatial_details["reason"] = "MATCHED"
        else:
            if not matches and request.occurrence == 0:
                journal_artifacts = record_journal(False)
                artifacts = journal_artifacts or save_failure_artifacts(
                    app.state.artifacts_dir, image, items, selector, matches
                )
                return {
                    "found": False,
                    "query": request.text,
                    "matches": [],
                    "detections": [item_json(item) for item in items],
                    "artifacts": artifacts,
                }
            try:
                match = select_match(matches, request.occurrence)
            except MatchSelectionError as error:
                journal_artifacts = record_journal(False)
                artifacts = journal_artifacts or save_failure_artifacts(
                    app.state.artifacts_dir, image, items, selector, error.matches
                )
                return {
                    "found": False,
                    "query": request.text,
                    "matches": [match_json(candidate) for candidate in error.matches],
                    "detections": [item_json(item) for item in items],
                    "artifacts": artifacts,
                    "error": {
                        "code": "ACTION_TARGET_NOT_FOUND",
                        "message": str(error),
                    },
                }

        journal_artifacts = record_journal(True, details=spatial_details)

        box = match.item.box
        center_x = box.x + box.width / 2
        center_y = box.y + box.height / 2
        normalized_x = round(center_x / image.width * 100, 2)
        normalized_y = round(center_y / image.height * 100, 2)
        if app.state.debug:
            print(
                f"seenflow: matched text={match.item.text} score={match.score:.3f} "
                f"confidence={match.item.confidence:.3f} "
                f"box=({box.x},{box.y},{box.width},{box.height}) "
                f"normalized=({normalized_x:.2f},{normalized_y:.2f})"
            )
        response: dict[str, object] = {
            "found": True,
            "query": request.text,
            "match": {
                **item_json(match.item),
                "score": match.score,
                "center": {"x": center_x, "y": center_y},
                "normalized": {
                    "x": normalized_x,
                    "y": normalized_y,
                },
            },
        }
        if journal_artifacts is not None:
            response["detections"] = [item_json(item) for item in items]
            response["artifacts"] = journal_artifacts
        elif request.diagnostics:
            response["detections"] = [item_json(item) for item in items]
            response["artifacts"] = save_failure_artifacts(
                app.state.artifacts_dir, image, items, selector, matches
            )
        return response

    @app.post("/v1/diagnostics/final")
    async def final_diagnostic(request: FinalDiagnosticRequest) -> dict[str, object]:
        context = app.state.journal.context(request.run_id)
        if context is None:
            raise HTTPException(status_code=404, detail="No device context for run")
        try:
            image, capture_ms = capture_image(app, context.platform, context.device_id)
            items, ocr_ms = detect_items(app, image)
        except HTTPException:
            raise
        artifacts = app.state.journal.record(
            run_id=request.run_id,
            step=context.step,
            phase="execution-failure",
            attempt=1,
            action=context.action,
            state=None,
            image=image,
            items=items,
            selector={},
            candidates=[],
            found=False,
            capture_ms=capture_ms,
            ocr_ms=ocr_ms,
        )
        return {"artifacts": artifacts}

    return app


def log_visual_result(app: FastAPI, request: FindRequest, found: bool) -> None:
    if not app.state.debug or request.context not in ("precondition", "postcondition"):
        return
    if request.state is None:
        return
    satisfied = found if request.state == "visible" else not found
    attempt = f" attempt={request.attempt}" if request.attempt is not None else ""
    print(
        f"seenflow: {request.context} text={request.text} expected={request.state} "
        f"found={str(found).lower()} satisfied={str(satisfied).lower()}{attempt}"
    )


def capture_image(app: FastAPI, platform: str, device_id: str) -> tuple[Image.Image, float]:
    capture_started = time.perf_counter()
    try:
        screenshot = app.state.captures[platform].capture(device_id)
        image = Image.open(BytesIO(screenshot))
        image.load()
    except (CaptureError, OSError, UnidentifiedImageError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "OCR_CAPTURE_FAILED", "message": str(error)},
        ) from error
    if app.state.debug:
        print(f"seenflow: capture duration={(time.perf_counter() - capture_started) * 1000:.1f}ms")
    return image, (time.perf_counter() - capture_started) * 1000


def detect_items(app: FastAPI, image: Image.Image) -> tuple[list[OCRItem], float]:
    ocr_started = time.perf_counter()
    try:
        items = app.state.ocr_provider.detect(image)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail={"code": "OCR_RUNTIME_FAILED", "message": str(error)},
        ) from error
    if app.state.debug:
        print(f"seenflow: OCR duration={(time.perf_counter() - ocr_started) * 1000:.1f}ms")
    return items, (time.perf_counter() - ocr_started) * 1000


def analyze(app: FastAPI, platform: str, device_id: str) -> tuple[Image.Image, list[OCRItem]]:
    image, _capture_ms = capture_image(app, platform, device_id)
    items, _ocr_ms = detect_items(app, image)
    return image, items


def item_json(item: OCRItem) -> dict[str, object]:
    payload: dict[str, object] = {
        "text": item.text,
        "confidence": item.confidence,
        "box": box_json(item.box),
        "source": item.source,
    }
    if item.line_id is not None:
        payload["lineId"] = item.line_id
    if item.span_start is not None and item.span_end is not None:
        payload["span"] = {"start": item.span_start, "end": item.span_end}
    if item.refinement_error is not None:
        payload["refinementError"] = item.refinement_error
    return payload


def box_json(box: BoundingBox) -> dict[str, int]:
    return {"x": box.x, "y": box.y, "width": box.width, "height": box.height}


def match_json(match: OCRMatch) -> dict[str, object]:
    return {**item_json(match.item), "score": match.score}


def spatial_evaluation_json(evaluation: SpatialEvaluation) -> dict[str, object]:
    reason = None
    if not evaluation.direction_matches:
        reason = "DIRECTION_MISMATCH"
    elif not evaluation.within_distance:
        reason = "MAX_DISTANCE_EXCEEDED"
    return {
        **match_json(evaluation.match),
        "distancePercent": round(evaluation.distance_percent, 4),
        "directionMatches": evaluation.direction_matches,
        "withinDistance": evaluation.within_distance,
        "rejectionReason": reason,
    }


def main() -> None:
    port = int(os.environ["SEENFLOW_PORT"])
    if not 0 < port < 65536:
        raise ValueError("SEENFLOW_PORT must be between 1 and 65535")
    artifacts_dir = Path(
        os.environ.get("SEENFLOW_ARTIFACTS_DIR", ".seenflow/artifacts")
    )
    debug = os.environ.get("SEENFLOW_DEBUG") == "true"
    uvicorn.run(
        create_app(
            os.environ["SEENFLOW_SESSION_TOKEN"],
            artifacts_dir=artifacts_dir,
            debug=debug,
        ),
        host=HOST,
        port=port,
    )
