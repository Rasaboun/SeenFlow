from io import BytesIO
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from seenflow.capture.base import CaptureError
from seenflow.models import BoundingBox, OCRItem
from seenflow.server import create_app


TOKEN = "test-session-token"


class FakeCapture:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.devices: list[str] = []

    def capture(self, device_id: str) -> bytes:
        self.devices.append(device_id)
        if self.error:
            raise self.error
        output = BytesIO()
        Image.new("RGB", (200, 100), "white").save(output, "PNG")
        return output.getvalue()


class FakeProvider:
    def __init__(self, items: list[OCRItem], error: Exception | None = None) -> None:
        self.items = items
        self.error = error
        self.calls = 0

    def detect(self, _image: Image.Image) -> list[OCRItem]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.items


def client(
    provider: FakeProvider,
    capture: FakeCapture | None = None,
    artifacts_dir: Path | None = None,
    debug: bool = False,
) -> tuple[TestClient, FakeCapture]:
    capture = capture or FakeCapture()
    app = create_app(
        TOKEN,
        lambda: provider,
        {"ios": capture, "android": capture},
        artifacts_dir=artifacts_dir,
        debug=debug,
    )
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}), capture


def test_detect_returns_screen_dimensions_and_all_ocr_items() -> None:
    provider = FakeProvider([OCRItem("Save", 0.97, BoundingBox(80, 40, 40, 20))])
    api, capture = client(provider)

    response = api.post("/v1/text/detect", json={"platform": "ios", "deviceId": "ABC-123"})

    assert response.status_code == 200
    assert response.json() == {
        "width": 200,
        "height": 100,
        "items": [
            {
                "text": "Save",
                "confidence": 0.97,
                "box": {"x": 80, "y": 40, "width": 40, "height": 20},
            }
        ],
    }
    assert capture.devices == ["ABC-123"]


def test_find_returns_deterministic_match_and_percentage_coordinates() -> None:
    provider = FakeProvider(
        [
            OCRItem("Save", 0.8, BoundingBox(120, 50, 40, 20)),
            OCRItem("Save", 0.9, BoundingBox(20, 10, 20, 10)),
        ]
    )
    api, _capture = client(provider)

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "android",
            "deviceId": "emulator-5554",
            "text": "save",
            "match": "exact",
            "threshold": 0.85,
            "occurrence": 1,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "found": True,
        "query": "save",
        "match": {
            "text": "Save",
            "confidence": 0.8,
            "score": 1.0,
            "box": {"x": 120, "y": 50, "width": 40, "height": 20},
            "center": {"x": 140.0, "y": 60.0},
            "normalized": {"x": 70.0, "y": 60.0},
        },
    }


def test_find_returns_absent_and_captures_fresh_screens() -> None:
    provider = FakeProvider([])
    api, capture = client(provider)
    request = {"platform": "ios", "deviceId": "ABC-123", "text": "Missing"}

    first = api.post("/v1/text/find", json=request)
    second = api.post("/v1/text/find", json=request)

    assert first.json()["found"] is False
    assert first.json()["query"] == "Missing"
    assert first.json()["matches"] == []
    assert second.status_code == 200
    assert capture.devices == ["ABC-123", "ABC-123"]
    assert provider.calls == 2


def test_missing_occurrence_returns_all_candidates_and_artifacts(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            OCRItem("Add", 0.9, BoundingBox(10, 10, 30, 20)),
            OCRItem("Add", 0.8, BoundingBox(60, 10, 30, 20)),
        ]
    )
    api, _capture = client(provider, artifacts_dir=tmp_path)

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Add",
            "occurrence": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["found"] is False
    assert [item["text"] for item in response.json()["matches"]] == ["Add", "Add"]
    assert Path(response.json()["artifacts"]["annotated"]).is_file()


@pytest.mark.parametrize(
    "body",
    [
        {"platform": "windows", "deviceId": "ABC-123", "text": "Save"},
        {"platform": "ios", "deviceId": "ABC-123", "text": "   "},
        {"platform": "ios", "deviceId": "ABC-123", "text": "Save", "occurrence": -1},
        {"platform": "ios", "deviceId": "ABC-123", "text": "Save", "threshold": 1.1},
    ],
)
def test_find_rejects_invalid_parameters(body: dict[str, object]) -> None:
    api, _capture = client(FakeProvider([]))

    assert api.post("/v1/text/find", json=body).status_code == 422


def test_capture_and_ocr_failures_have_distinct_codes() -> None:
    capture_api, _ = client(FakeProvider([]), FakeCapture(CaptureError("simctl failed")))
    ocr_api, _ = client(FakeProvider([], RuntimeError("model failed")))
    body = {"platform": "ios", "deviceId": "ABC-123"}

    assert capture_api.post("/v1/text/detect", json=body).json()["detail"]["code"] == "OCR_CAPTURE_FAILED"
    assert ocr_api.post("/v1/text/detect", json=body).json()["detail"]["code"] == "OCR_RUNTIME_FAILED"


def test_missing_text_saves_actionable_visual_artifacts(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            OCRItem("Chicken Katsu", 0.99, BoundingBox(10, 10, 80, 15)),
            OCRItem("START COOKlNG", 0.91, BoundingBox(20, 50, 100, 20)),
        ]
    )
    api, _capture = client(provider, artifacts_dir=tmp_path)

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Start cooking",
            "match": "exact",
            "threshold": 0.85,
            "occurrence": 0,
        },
    )

    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    assert Path(artifacts["screenshot"]).is_file()
    assert Path(artifacts["annotated"]).is_file()
    diagnostic = json.loads(Path(artifacts["ocr"]).read_text())
    assert diagnostic["selector"] == {
        "text": "Start cooking",
        "match": "exact",
        "threshold": 0.85,
        "occurrence": 0,
    }
    assert [item["text"] for item in diagnostic["detections"]] == [
        "Chicken Katsu",
        "START COOKlNG",
    ]


def test_found_text_can_request_failure_diagnostics(tmp_path: Path) -> None:
    provider = FakeProvider([OCRItem("Loading...", 0.96, BoundingBox(20, 20, 80, 20))])
    api, _capture = client(provider, artifacts_dir=tmp_path)

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Loading...",
            "diagnostics": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["found"] is True
    assert response.json()["detections"][0]["text"] == "Loading..."
    assert Path(response.json()["artifacts"]["screenshot"]).is_file()


def test_request_body_size_is_limited() -> None:
    api, _capture = client(FakeProvider([]))

    response = api.post(
        "/v1/text/find",
        content=b"{" + b'"padding":"' + b"x" * 20_000 + b'"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413


def test_debug_mode_logs_capture_and_ocr_timings(capsys: pytest.CaptureFixture[str]) -> None:
    api, _capture = client(
        FakeProvider([OCRItem("Save", 0.97, BoundingBox(80, 40, 40, 20))]),
        debug=True,
    )

    api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Save",
            "context": "precondition",
            "state": "visible",
        },
    )

    output = capsys.readouterr().out
    assert "capture duration=" in output
    assert "OCR duration=" in output
    assert "precondition text=Save expected=visible found=true satisfied=true" in output
    assert "matched text=Save score=1.000 confidence=0.970" in output
    assert "box=(80,40,40,20) normalized=(50.00,50.00)" in output
