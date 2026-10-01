"""Composition root for the visual sidecar."""
import os
from collections.abc import Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from seenflow.application.ports import OCRProvider, ScreenshotCapture
from seenflow.application.visual import VisualService
from seenflow.capture.android import AndroidCapture
from seenflow.capture.base import decode_screenshot
from seenflow.capture.ios import IOSSimulatorCapture
from seenflow.diagnostics import save_failure_artifacts
from seenflow.http import create_http_app
from seenflow.journal import VisualJournal
from seenflow.ocr.paddle import PaddleOCRProvider

HOST = "127.0.0.1"


def create_app(
    session_token: str,
    provider_factory: Callable[[], OCRProvider] = PaddleOCRProvider,
    captures: dict[str, ScreenshotCapture] | None = None,
    artifacts_dir: Path | None = None,
    debug: bool = False,
) -> FastAPI:
    if not session_token:
        raise ValueError("session token must not be empty")
    provider = provider_factory()
    captures = captures or {"ios": IOSSimulatorCapture(), "android": AndroidCapture()}
    root = artifacts_dir or Path(".seenflow/artifacts")
    journal = VisualJournal(root)
    service = VisualService(
        provider, captures, journal, decode_screenshot,
        lambda image, items, selector, candidates, details: save_failure_artifacts(
            root, image, items, selector, candidates, details,
        ),
        print if debug else None,
    )
    app = create_http_app(session_token, service)
    app.state.ocr_provider = provider
    return app


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
