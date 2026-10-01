"""Use cases run without an HTTP server or concrete OCR/device adapters."""
from importlib.util import find_spec

import pytest
from PIL import Image

from seenflow.models import BoundingBox, OCRItem


class Capture:
    def capture(self, device_id):
        assert device_id == "ABC-123"
        return b"screen"


class Provider:
    def __init__(self, items, error=None):
        self.items, self.error = items, error

    def detect(self, image):
        assert image.size == (200, 100)
        if self.error:
            raise self.error
        return self.items


class Recorder:
    def __init__(self):
        self.contexts, self.entries, self.errors = {}, [], []

    def remember_context(self, run_id, platform, device_id, step, action):
        from seenflow.application.contracts import DeviceContext
        self.contexts[run_id] = DeviceContext(platform, device_id, step, action)

    def context(self, run_id):
        return self.contexts.get(run_id)

    def record(self, **entry):
        self.entries.append(entry)
        return {"screenshot": "journal.png"}

    def record_error(self, **entry):
        self.errors.append(entry)
        return {"screenshot": "failed.png"} if entry.get("image") else {}


def service(items, *, provider_error=None, capture=None):
    assert find_spec("seenflow.application") is not None, "Missing independent application layer"
    from seenflow.application.visual import VisualService
    recorder = Recorder()
    saved = []

    def save(*args):
        saved.append(args)
        return {"screenshot": "failure.png"}

    return VisualService(
        Provider(items, provider_error), {"ios": capture or Capture()}, recorder,
        lambda data: Image.new("RGB", (200, 100)), save,
    ), recorder, saved


def request(**options):
    from seenflow.application.contracts import FindText
    return FindText(platform="ios", device_id="ABC-123", text="Save", **options)


def test_find_returns_domain_match_without_http():
    item = OCRItem("Save", 0.97, BoundingBox(80, 40, 40, 20))
    app, journal, saved = service([item])
    result = app.find(request())
    assert result.match.item == item
    assert result.match.score == 1
    assert (result.width, result.height) == (200, 100)
    assert result.artifacts is None
    assert journal.entries == saved == []


def test_precondition_stops_target_and_journals_same_screen():
    app, journal, saved = service([OCRItem("Saved", 0.97, BoundingBox(20, 20, 40, 20))])
    from seenflow.application.contracts import VisualCondition
    result = app.find(request(
        precondition=VisualCondition("Saved", "not-visible"),
        run_id="run", step=1, action="tap", context="target", attempt=1,
    ))
    assert result.match is None
    assert result.precondition.found is True
    assert [(e["phase"], e["state"], e["found"]) for e in journal.entries] == [
        ("precondition", "not-visible", True)
    ]
    assert result.artifacts == {"screenshot": "journal.png"}
    assert saved == []


def test_spatial_filtering_happens_before_occurrence_selection():
    app, journal, _ = service([
        OCRItem("Anchor", 0.99, BoundingBox(95, 45, 10, 10)),
        OCRItem("Save", 0.9, BoundingBox(45, 45, 10, 10)),
        OCRItem("Save", 0.9, BoundingBox(145, 45, 10, 10)),
    ])
    from seenflow.application.contracts import SpatialSelector, TextSelector
    result = app.find(request(spatial=SpatialSelector("rightOf", TextSelector("Anchor"), 100)))
    assert result.match.item.box.x == 145


def test_missing_occurrence_returns_candidates_and_failure_evidence():
    app, _, saved = service([OCRItem("Save", 0.9, BoundingBox(20, 20, 40, 20))])
    result = app.find(request(occurrence=1))
    assert result.match is None
    assert len(result.candidates) == 1
    assert result.error.code == "ACTION_TARGET_NOT_FOUND"
    assert result.artifacts == {"screenshot": "failure.png"}
    assert len(saved) == 1


def test_ocr_failure_is_application_error_and_retains_screen():
    app, journal, _ = service([], provider_error=RuntimeError("model failed"))
    from seenflow.application.errors import OCRFailed
    with pytest.raises(OCRFailed) as caught:
        app.find(request(run_id="run", step=1, action="tap", context="target", attempt=1))
    assert str(caught.value) == "model failed"
    assert caught.value.artifacts == {"screenshot": "failed.png"}
    assert journal.errors[0]["image"].size == (200, 100)


def test_capture_failure_records_error_without_image():
    app, journal, _ = service([])
    from seenflow.application.errors import CaptureFailed

    class BrokenCapture:
        def capture(self, _device):
            raise CaptureFailed("device failed")

    app.captures["ios"] = BrokenCapture()
    with pytest.raises(CaptureFailed) as caught:
        app.find(request(run_id="run", step=1, action="tap", context="target", attempt=1))
    assert caught.value.artifacts is None
    assert "image" not in journal.errors[0]


def test_final_diagnostic_uses_application_context():
    app, journal, _ = service([OCRItem("Save", 0.9, BoundingBox(20, 20, 40, 20))])
    app.find(request(run_id="run", step=3, action="tap", context="target", attempt=1))
    assert app.final_diagnostic("run") == {"screenshot": "journal.png"}
    assert [e["phase"] for e in journal.entries] == ["target", "execution-failure"]
    assert journal.entries[-1]["step"] == 3


def test_unknown_final_run_is_application_error():
    app, _, _ = service([])
    from seenflow.application.errors import RunContextMissing
    with pytest.raises(RunContextMissing):
        app.final_diagnostic("missing")


def test_detection_returns_items_without_http():
    item = OCRItem("Save", 0.9, BoundingBox(20, 20, 40, 20))
    app, _, _ = service([item])
    result = app.detect("ios", "ABC-123")
    assert (result.width, result.height, result.items) == (200, 100, [item])


@pytest.mark.parametrize("options", [
    {"text": " "}, {"platform": "windows"}, {"device_id": "../escape"},
    {"occurrence": -1}, {"occurrence": True}, {"threshold": float("nan")},
    {"match": "unknown"}, {"run_id": "run"},
    {"run_id": "../escape", "step": 1, "action": "tap", "context": "target", "attempt": 1},
    {"run_id": "run", "step": 1, "action": "tap"}, {"state": "unknown"},
])
def test_application_inputs_are_validated_without_http(options):
    from seenflow.application.contracts import FindText
    values = {"platform": "ios", "device_id": "ABC-123", "text": "Save", **options}
    with pytest.raises(ValueError):
        FindText(**values)


def test_capture_os_errors_are_translated_to_application_errors():
    app, _, _ = service([])
    from seenflow.application.errors import CaptureFailed

    class MissingScreen:
        def capture(self, _device):
            raise OSError("screenshot unavailable")

    app.captures["ios"] = MissingScreen()
    with pytest.raises(CaptureFailed, match="screenshot unavailable"):
        app.detect("ios", "ABC-123")


@pytest.mark.parametrize("run_id", ["../escape", "", "contains space"])
def test_final_diagnostic_validates_run_ids_before_adapter_access(run_id):
    app, _, _ = service([])
    with pytest.raises(ValueError, match="run ID"):
        app.final_diagnostic(run_id)
