from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from maestro_vision.capture.base import CaptureError
from maestro_vision.models import BoundingBox, OCRItem
from maestro_vision.server import create_app


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


def client(provider: FakeProvider, capture: FakeCapture | None = None) -> tuple[TestClient, FakeCapture]:
    capture = capture or FakeCapture()
    app = create_app(TOKEN, lambda: provider, {"ios": capture, "android": capture})
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

    assert first.json() == {"found": False, "query": "Missing", "matches": []}
    assert second.status_code == 200
    assert capture.devices == ["ABC-123", "ABC-123"]
    assert provider.calls == 2


@pytest.mark.parametrize(
    "body",
    [
        {"platform": "windows", "deviceId": "ABC-123", "text": "Save"},
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
