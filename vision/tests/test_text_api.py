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


def ocr(text: str, confidence: float, center_x: int, center_y: int) -> OCRItem:
    return OCRItem(text, confidence, BoundingBox(center_x - 5, center_y - 5, 10, 10))


def spatial(
    relation: str = "rightOf",
    *,
    anchor_occurrence: int = 0,
    max_distance: float = 100,
) -> dict[str, object]:
    return {
        "relation": relation,
        "anchor": {
            "text": "Chicken Curry",
            "match": "exact",
            "threshold": 0.85,
            "occurrence": anchor_occurrence,
        },
        "maxDistance": max_distance,
    }


def test_detect_returns_screen_dimensions_and_all_ocr_items() -> None:
    provider = FakeProvider(
        [
            OCRItem(
                "Save",
                0.97,
                BoundingBox(80, 40, 40, 20),
                "word",
                3,
                1,
                2,
            )
        ]
    )
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
                "source": "word",
                "lineId": 3,
                "span": {"start": 1, "end": 2},
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
            "source": "line",
            "center": {"x": 140.0, "y": 60.0},
            "normalized": {"x": 70.0, "y": 60.0},
        },
    }


def test_find_evaluates_target_and_precondition_from_one_screenshot() -> None:
    provider = FakeProvider(
        [
            OCRItem("Save", 0.97, BoundingBox(80, 40, 40, 20)),
            OCRItem("Saved", 0.99, BoundingBox(20, 10, 40, 20)),
        ]
    )
    api, capture = client(provider)

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Save",
            "precondition": {"text": "Saved", "state": "not-visible"},
        },
    )

    assert response.status_code == 200
    assert response.json()["precondition"] == {
        "found": True,
        "query": "Saved",
        "state": "not-visible",
    }
    assert capture.devices == ["ABC-123"]
    assert provider.calls == 1


def test_failed_combined_precondition_is_journaled_before_target(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        [
            OCRItem("Save", 0.97, BoundingBox(80, 40, 40, 20)),
            OCRItem("Saved", 0.99, BoundingBox(20, 10, 40, 20)),
        ]
    )
    api, capture = client(provider, artifacts_dir=tmp_path)

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Save",
            "precondition": {"text": "Saved", "state": "not-visible"},
            "context": "target",
            "attempt": 1,
            "runId": "run-combined",
            "step": 1,
            "action": 'visionTap "Save"',
        },
    )

    assert response.status_code == 200
    manifest = json.loads((tmp_path / "run-combined" / "manifest.json").read_text())
    assert [(entry["phase"], entry["state"], entry["found"]) for entry in manifest["entries"]] == [
        ("precondition", "not-visible", True)
    ]
    assert capture.devices == ["ABC-123"]
    assert provider.calls == 1


def test_find_reports_reconstructed_phrase_provenance() -> None:
    provider = FakeProvider(
        [
            OCRItem(
                "Chicken Curry Edit",
                0.97,
                BoundingBox(10, 20, 180, 40),
                "line",
                0,
                0,
                3,
            ),
            OCRItem("Chicken", 0.97, BoundingBox(10, 20, 65, 40), "word", 0, 0, 1),
            OCRItem("Curry", 0.97, BoundingBox(80, 20, 45, 40), "word", 0, 1, 2),
            OCRItem("Edit", 0.97, BoundingBox(150, 20, 40, 40), "word", 0, 2, 3),
        ]
    )
    api, _capture = client(provider)

    response = api.post(
        "/v1/text/find",
        json={"platform": "ios", "deviceId": "ABC-123", "text": "Chicken Curry"},
    )

    assert response.status_code == 200
    assert response.json()["match"] == {
        "text": "Chicken Curry",
        "confidence": 0.97,
        "score": 1.0,
        "box": {"x": 10, "y": 20, "width": 115, "height": 40},
        "source": "phrase",
        "lineId": 0,
        "span": {"start": 0, "end": 2},
        "center": {"x": 67.5, "y": 40.0},
        "normalized": {"x": 33.75, "y": 40.0},
    }


@pytest.mark.parametrize(
    ("relation", "target_center"),
    [
        ("near", (150, 50)),
        ("rightOf", (150, 50)),
        ("leftOf", (50, 50)),
        ("above", (100, 20)),
        ("below", (100, 80)),
    ],
)
def test_find_resolves_every_spatial_relationship_from_one_analysis(
    relation: str, target_center: tuple[int, int]
) -> None:
    provider = FakeProvider(
        [
            ocr("Chicken Curry", 0.99, 100, 50),
            ocr("Edit", 0.90, 20, 80),
            ocr("Edit", 0.95, *target_center),
        ]
    )
    api, capture = client(provider)

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Edit",
            "spatial": spatial(relation),
        },
    )

    assert response.status_code == 200
    assert response.json()["found"] is True
    assert response.json()["match"]["center"] == {
        "x": float(target_center[0]),
        "y": float(target_center[1]),
    }
    assert capture.devices == ["ABC-123"]
    assert provider.calls == 1


@pytest.mark.parametrize(
    "spatial_value",
    [
        {**spatial(), "extra": True},
        {**spatial(), "relation": "diagonal"},
        {**spatial(), "maxDistance": 0},
        {**spatial(), "maxDistance": 101},
        {**spatial(), "anchor": {**spatial()["anchor"], "text": " "}},
        {**spatial(), "anchor": {**spatial()["anchor"], "match": "nearby"}},
        {**spatial(), "anchor": {**spatial()["anchor"], "threshold": 1.1}},
        {**spatial(), "anchor": {**spatial()["anchor"], "occurrence": -1}},
        {**spatial(), "anchor": {**spatial()["anchor"], "extra": True}},
    ],
)
def test_find_strictly_validates_spatial_selector(spatial_value: dict[str, object]) -> None:
    api, _capture = client(FakeProvider([]))

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Edit",
            "spatial": spatial_value,
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("items", "spatial_value", "occurrence", "reason"),
    [
        ([ocr("Edit", 0.9, 150, 50)], spatial(), 0, "ANCHOR_TEXT_NOT_FOUND"),
        (
            [ocr("Chicken Curry", 0.99, 100, 50), ocr("Edit", 0.9, 150, 50)],
            spatial(anchor_occurrence=1),
            0,
            "ANCHOR_OCCURRENCE_NOT_FOUND",
        ),
        ([ocr("Chicken Curry", 0.99, 100, 50)], spatial(), 0, "TARGET_TEXT_NOT_FOUND"),
        (
            [ocr("Chicken Curry", 0.99, 100, 50), ocr("Edit", 0.9, 50, 50)],
            spatial(),
            0,
            "DIRECTION_MISMATCH",
        ),
        (
            [ocr("Chicken Curry", 0.99, 100, 50), ocr("Edit", 0.9, 150, 50)],
            spatial(max_distance=1),
            0,
            "MAX_DISTANCE_EXCEEDED",
        ),
        (
            [ocr("Chicken Curry", 0.99, 100, 50), ocr("Edit", 0.9, 150, 50)],
            spatial(),
            1,
            "TARGET_OCCURRENCE_NOT_FOUND",
        ),
    ],
)
def test_find_distinguishes_spatial_failures(
    items: list[OCRItem],
    spatial_value: dict[str, object],
    occurrence: int,
    reason: str,
    tmp_path: Path,
) -> None:
    api, _capture = client(FakeProvider(items), artifacts_dir=tmp_path)

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Edit",
            "occurrence": occurrence,
            "spatial": spatial_value,
        },
    )

    assert response.status_code == 200
    assert response.json()["found"] is False
    assert response.json()["error"] == {
        "code": "ACTION_TARGET_NOT_FOUND",
        "reason": reason,
    }
    diagnostic = json.loads(Path(response.json()["artifacts"]["ocr"]).read_text())
    assert diagnostic["spatial"]["reason"] == reason


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


def test_journal_records_missing_occurrence_as_not_found(tmp_path: Path) -> None:
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
            "context": "target",
            "attempt": 1,
            "runId": "run-occurrence",
            "step": 1,
            "action": 'visionTap "Add"',
        },
    )

    assert response.json()["found"] is False
    manifest = json.loads((tmp_path / "run-occurrence" / "manifest.json").read_text())
    assert manifest["entries"][0]["found"] is False


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


def test_combined_capture_failure_is_journaled_as_precondition(tmp_path: Path) -> None:
    api, _capture = client(
        FakeProvider([]),
        FakeCapture(CaptureError("simctl failed")),
        artifacts_dir=tmp_path,
    )

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Save",
            "precondition": {"text": "Saved", "state": "not-visible"},
            "context": "target",
            "attempt": 1,
            "runId": "run-capture-failure",
            "step": 1,
            "action": 'visionTap "Save"',
        },
    )

    assert response.status_code == 502
    manifest = json.loads((tmp_path / "run-capture-failure" / "manifest.json").read_text())
    assert manifest["entries"][0]["phase"] == "precondition"
    assert manifest["entries"][0]["state"] == "not-visible"
    assert manifest["entries"][0]["error"]["code"] == "OCR_CAPTURE_FAILED"


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


def test_precondition_mismatch_returns_exact_journal_artifacts(tmp_path: Path) -> None:
    provider = FakeProvider([OCRItem("Saved", 0.99, BoundingBox(20, 20, 80, 20))])
    api, capture = client(provider, artifacts_dir=tmp_path)

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Saved",
            "context": "precondition",
            "state": "not-visible",
            "attempt": 1,
            "runId": "run-123",
            "step": 2,
            "action": 'visionTap "Save"',
        },
    )

    assert response.status_code == 200
    assert response.json()["found"] is True
    assert Path(response.json()["artifacts"]["annotated"]).is_file()
    assert capture.devices == ["ABC-123"]
    manifest = json.loads((tmp_path / "run-123" / "manifest.json").read_text())
    assert manifest["entries"][0]["phase"] == "precondition"
    assert manifest["entries"][0]["found"] is True


@pytest.mark.parametrize(
    "metadata",
    [
        {"runId": "run-only"},
        {"runId": "../escape", "step": 1, "action": "swipe"},
        {"runId": "run", "step": 0, "action": "swipe"},
        {"runId": "run", "step": 1, "action": " "},
    ],
)
def test_journal_metadata_is_strictly_validated(metadata: dict[str, object]) -> None:
    api, _capture = client(FakeProvider([]))

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Saved",
            "context": "precondition",
            "state": "not-visible",
            "attempt": 1,
            **metadata,
        },
    )

    assert response.status_code == 422


def test_ocr_failure_retains_source_screenshot_in_journal(tmp_path: Path) -> None:
    api, _capture = client(
        FakeProvider([], RuntimeError("model failed")),
        artifacts_dir=tmp_path,
    )

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Save",
            "context": "target",
            "attempt": 1,
            "runId": "run-ocr",
            "step": 1,
            "action": 'visionTap "Save"',
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "OCR_RUNTIME_FAILED"
    screenshot = response.json()["detail"]["artifacts"]["screenshot"]
    assert Path(screenshot).is_file()


def test_capture_failure_writes_manifest_without_promising_an_image(tmp_path: Path) -> None:
    api, _capture = client(
        FakeProvider([]),
        FakeCapture(CaptureError("simctl failed")),
        artifacts_dir=tmp_path,
    )

    response = api.post(
        "/v1/text/find",
        json={
            "platform": "ios",
            "deviceId": "ABC-123",
            "text": "Save",
            "context": "target",
            "attempt": 1,
            "runId": "run-capture",
            "step": 1,
            "action": 'visionTap "Save"',
        },
    )

    assert response.status_code == 502
    assert "artifacts" not in response.json()["detail"]
    manifest = json.loads((tmp_path / "run-capture" / "manifest.json").read_text())
    assert manifest["entries"][0]["error"]["code"] == "OCR_CAPTURE_FAILED"


def test_final_diagnostic_uses_last_validated_run_device_context(tmp_path: Path) -> None:
    provider = FakeProvider([OCRItem("Save", 0.97, BoundingBox(80, 40, 40, 20))])
    api, capture = client(provider, artifacts_dir=tmp_path)
    find = {
        "platform": "android",
        "deviceId": "emulator-5554",
        "text": "Save",
        "context": "target",
        "attempt": 1,
        "runId": "run-final",
        "step": 3,
        "action": 'visionTap "Save"',
    }

    assert api.post("/v1/text/find", json=find).status_code == 200
    response = api.post("/v1/diagnostics/final", json={"runId": "run-final"})

    assert response.status_code == 200
    assert Path(response.json()["artifacts"]["annotated"]).is_file()
    assert capture.devices == ["emulator-5554", "emulator-5554"]
    manifest = json.loads((tmp_path / "run-final" / "manifest.json").read_text())
    assert [entry["phase"] for entry in manifest["entries"]] == [
        "target",
        "execution-failure",
    ]


def test_final_diagnostic_rejects_unknown_run_context() -> None:
    api, _capture = client(FakeProvider([]))

    assert api.post("/v1/diagnostics/final", json={"runId": "missing"}).status_code == 404


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
