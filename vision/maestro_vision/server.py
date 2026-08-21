import os
import secrets
from collections.abc import Callable
from io import BytesIO
from typing import Annotated
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from maestro_vision.capture.android import AndroidCapture
from maestro_vision.capture.base import CaptureError, ScreenshotCapture
from maestro_vision.capture.ios import IOSSimulatorCapture
from maestro_vision.matching import MatchSelectionError, find_matches, select_match
from maestro_vision.models import BoundingBox, OCRItem
from maestro_vision.ocr.paddle import PaddleOCRProvider
from maestro_vision.ocr.provider import OCRProvider


HOST = "127.0.0.1"


class DetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    platform: Literal["ios", "android"]
    device_id: str = Field(alias="deviceId", pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class FindRequest(DetectRequest):
    text: str = Field(min_length=1)
    match: Literal["exact", "contains", "fuzzy"] = "exact"
    threshold: float = Field(default=0.85, ge=0, le=1)
    occurrence: int = Field(default=0, ge=0)


def create_app(
    session_token: str,
    provider_factory: Callable[[], OCRProvider] = PaddleOCRProvider,
    captures: dict[str, ScreenshotCapture] | None = None,
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
        if not matches and request.occurrence == 0:
            return {"found": False, "query": request.text, "matches": []}
        try:
            match = select_match(matches, request.occurrence)
        except MatchSelectionError as error:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "ACTION_TARGET_NOT_FOUND",
                    "message": str(error),
                    "candidates": [item_json(candidate.item) for candidate in error.matches],
                },
            ) from error

        box = match.item.box
        center_x = box.x + box.width / 2
        center_y = box.y + box.height / 2
        return {
            "found": True,
            "query": request.text,
            "match": {
                **item_json(match.item),
                "score": match.score,
                "center": {"x": center_x, "y": center_y},
                "normalized": {
                    "x": round(center_x / image.width * 100, 2),
                    "y": round(center_y / image.height * 100, 2),
                },
            },
        }

    return app


def analyze(app: FastAPI, platform: str, device_id: str) -> tuple[Image.Image, list[OCRItem]]:
    try:
        screenshot = app.state.captures[platform].capture(device_id)
        image = Image.open(BytesIO(screenshot))
        image.load()
    except (CaptureError, OSError, UnidentifiedImageError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "OCR_CAPTURE_FAILED", "message": str(error)},
        ) from error
    try:
        return image, app.state.ocr_provider.detect(image)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail={"code": "OCR_RUNTIME_FAILED", "message": str(error)},
        ) from error


def item_json(item: OCRItem) -> dict[str, object]:
    return {
        "text": item.text,
        "confidence": item.confidence,
        "box": box_json(item.box),
    }


def box_json(box: BoundingBox) -> dict[str, int]:
    return {"x": box.x, "y": box.y, "width": box.width, "height": box.height}


def main() -> None:
    port = int(os.environ["MAESTRO_VISION_PORT"])
    if not 0 < port < 65536:
        raise ValueError("MAESTRO_VISION_PORT must be between 1 and 65535")
    uvicorn.run(create_app(os.environ["MAESTRO_VISION_SESSION_TOKEN"]), host=HOST, port=port)
