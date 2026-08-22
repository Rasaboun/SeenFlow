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
from pydantic import BaseModel, ConfigDict, Field, field_validator

from seenflow.capture.android import AndroidCapture
from seenflow.capture.base import CaptureError, ScreenshotCapture
from seenflow.capture.ios import IOSSimulatorCapture
from seenflow.diagnostics import save_failure_artifacts
from seenflow.matching import MatchSelectionError, find_matches, select_match
from seenflow.models import BoundingBox, OCRItem
from seenflow.ocr.paddle import PaddleOCRProvider
from seenflow.ocr.provider import OCRProvider


HOST = "127.0.0.1"
MAX_REQUEST_BYTES = 16_384


class DetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    platform: Literal["ios", "android"]
    device_id: str = Field(alias="deviceId", pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class FindRequest(DetectRequest):
    text: str = Field(min_length=1)
    match: Literal["exact", "contains", "fuzzy"] = "exact"
    threshold: float = Field(default=0.85, ge=0, le=1)
    occurrence: int = Field(default=0, ge=0)
    diagnostics: bool = False

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


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
        image, items = analyze(app, request.platform, request.device_id)
        matches = find_matches(items, request.text, request.match, request.threshold)
        selector = {
            "text": request.text,
            "match": request.match,
            "threshold": request.threshold,
            "occurrence": request.occurrence,
        }
        if not matches and request.occurrence == 0:
            artifacts = save_failure_artifacts(
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
            artifacts = save_failure_artifacts(
                app.state.artifacts_dir, image, items, selector, error.matches
            )
            return {
                "found": False,
                "query": request.text,
                "matches": [
                    {**item_json(candidate.item), "score": candidate.score}
                    for candidate in error.matches
                ],
                "detections": [item_json(item) for item in items],
                "artifacts": artifacts,
                "error": {
                    "code": "ACTION_TARGET_NOT_FOUND",
                    "message": str(error),
                },
            }

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
        if request.diagnostics:
            response["detections"] = [item_json(item) for item in items]
            response["artifacts"] = save_failure_artifacts(
                app.state.artifacts_dir, image, items, selector, matches
            )
        return response

    return app


def analyze(app: FastAPI, platform: str, device_id: str) -> tuple[Image.Image, list[OCRItem]]:
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
    return image, items


def item_json(item: OCRItem) -> dict[str, object]:
    return {
        "text": item.text,
        "confidence": item.confidence,
        "box": box_json(item.box),
    }


def box_json(box: BoundingBox) -> dict[str, int]:
    return {"x": box.x, "y": box.y, "width": box.width, "height": box.height}


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
