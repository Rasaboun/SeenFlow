import json
from pathlib import Path

import pytest
from PIL import Image

from seenflow.journal import VisualJournal
from seenflow.models import BoundingBox, OCRItem


def test_journal_records_exact_step_artifacts_and_ordered_manifest(tmp_path: Path) -> None:
    journal = VisualJournal(tmp_path)
    item = OCRItem("Saved", 0.99, BoundingBox(10, 10, 60, 20))

    paths = journal.record(
        run_id="run-123",
        step=2,
        phase="precondition",
        attempt=1,
        action='visionTap "Save"',
        state="not-visible",
        image=Image.new("RGB", (200, 100), "white"),
        items=[item],
        selector={"text": "Saved", "match": "exact"},
        candidates=[],
        found=True,
        capture_ms=10.0,
        ocr_ms=20.0,
    )

    directory = tmp_path / "run-123" / "002-precondition-001"
    assert Path(paths["screenshot"]) == directory / "screenshot.png"
    assert Path(paths["annotated"]).is_file()
    manifest = json.loads((tmp_path / "run-123" / "manifest.json").read_text())
    assert manifest == {
        "runId": "run-123",
        "entries": [
            {
                "step": 2,
                "phase": "precondition",
                "attempt": 1,
                "action": 'visionTap "Save"',
                "state": "not-visible",
                "found": True,
                "captureMs": 10.0,
                "ocrMs": 20.0,
                "artifacts": paths,
            }
        ],
    }


@pytest.mark.parametrize("run_id", ["../escape", "", "contains space"])
def test_journal_rejects_unsafe_run_ids(tmp_path: Path, run_id: str) -> None:
    journal = VisualJournal(tmp_path)

    with pytest.raises(ValueError, match="run ID"):
        journal.record_error(
            run_id=run_id,
            step=1,
            phase="precondition",
            attempt=1,
            action="swipe",
            state="visible",
            code="OCR_CAPTURE_FAILED",
            message="failed",
        )

    assert list(tmp_path.iterdir()) == []


def test_journal_retains_captured_image_when_ocr_fails(tmp_path: Path) -> None:
    journal = VisualJournal(tmp_path)

    paths = journal.record_error(
        run_id="run-ocr",
        step=1,
        phase="target",
        attempt=1,
        action='visionTap "Save"',
        state=None,
        code="OCR_RUNTIME_FAILED",
        message="model failed",
        image=Image.new("RGB", (40, 20), "white"),
        capture_ms=4.2,
    )

    assert Path(paths["screenshot"]).is_file()
    manifest = json.loads((tmp_path / "run-ocr" / "manifest.json").read_text())
    assert manifest["entries"][0]["error"] == {
        "code": "OCR_RUNTIME_FAILED",
        "message": "model failed",
    }
