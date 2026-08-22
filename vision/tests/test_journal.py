import json
from pathlib import Path

import pytest
from PIL import Image

from seenflow.journal import VisualJournal
from seenflow.models import BoundingBox, OCRItem, OCRMatch


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


def test_journal_records_spatial_evidence_in_manifest_and_ocr_json(tmp_path: Path) -> None:
    journal = VisualJournal(tmp_path)
    details = {
        "reason": "DIRECTION_MISMATCH",
        "anchor": {"text": "Chicken Curry"},
        "candidates": [{"text": "Edit", "distancePercent": 12.5}],
    }

    paths = journal.record(
        run_id="run-spatial",
        step=1,
        phase="target",
        attempt=1,
        action='visionTap "Edit" rightOf "Chicken Curry"',
        state=None,
        image=Image.new("RGB", (200, 100), "white"),
        items=[],
        selector={"text": "Edit"},
        candidates=[],
        found=False,
        capture_ms=10.0,
        ocr_ms=20.0,
        details=details,
    )

    manifest = json.loads((tmp_path / "run-spatial" / "manifest.json").read_text())
    assert manifest["entries"][0]["spatial"] == details
    ocr_json = json.loads(Path(paths["ocr"]).read_text())
    assert ocr_json["spatial"] == details


def test_journal_records_and_draws_box_provenance(tmp_path: Path) -> None:
    journal = VisualJournal(tmp_path)
    line = OCRItem(
        "Chicken Curry",
        0.97,
        BoundingBox(10, 10, 50, 30),
        "line",
        0,
        refinement_error="MALFORMED_WORD_GEOMETRY",
    )
    word = OCRItem("Chicken", 0.97, BoundingBox(20, 20, 20, 10), "word", 0, 0, 1)
    phrase = OCRItem("Chicken Curry", 0.97, BoundingBox(80, 10, 40, 20), "phrase", 0, 0, 2)

    paths = journal.record(
        run_id="run-provenance",
        step=1,
        phase="target",
        attempt=1,
        action='visionTap "Chicken Curry"',
        state=None,
        image=Image.new("RGB", (140, 60), "white"),
        items=[line, word],
        selector={"text": "Chicken Curry"},
        candidates=[OCRMatch(phrase, 1.0)],
        found=True,
        capture_ms=10.0,
        ocr_ms=20.0,
    )

    ocr_json = json.loads(Path(paths["ocr"]).read_text())
    assert ocr_json["detections"][1] == {
        "text": "Chicken",
        "confidence": 0.97,
        "box": {"x": 20, "y": 20, "width": 20, "height": 10},
        "source": "word",
        "lineId": 0,
        "span": {"start": 0, "end": 1},
    }
    assert ocr_json["detections"][0]["refinementError"] == "MALFORMED_WORD_GEOMETRY"
    assert ocr_json["candidates"][0]["source"] == "phrase"

    annotated = Image.open(paths["annotated"]).convert("RGB")
    assert annotated.getpixel((10, 10)) == (255, 59, 48)
    assert annotated.getpixel((20, 20)) == (10, 132, 255)
    assert annotated.getpixel((80, 10)) == (255, 191, 0)
