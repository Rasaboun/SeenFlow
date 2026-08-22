import json
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from seenflow.diagnostics import save_visual_artifacts
from seenflow.models import OCRItem, OCRMatch


_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_PHASES = {"precondition", "target", "postcondition", "execution-failure"}
_STATES = {"visible", "not-visible", None}


@dataclass(frozen=True)
class DeviceContext:
    platform: str
    device_id: str
    step: int
    action: str


class VisualJournal:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._contexts: dict[str, DeviceContext] = {}

    def remember_context(
        self,
        run_id: str,
        platform: str,
        device_id: str,
        step: int,
        action: str,
    ) -> None:
        self._entry_directory(run_id, step, "target", 1, action, None)
        self._contexts[run_id] = DeviceContext(platform, device_id, step, action)

    def context(self, run_id: str) -> DeviceContext | None:
        if _RUN_ID.fullmatch(run_id) is None:
            raise ValueError("run ID must contain only letters, numbers, underscores, or hyphens")
        return self._contexts.get(run_id)

    def record(
        self,
        *,
        run_id: str,
        step: int,
        phase: str,
        attempt: int,
        action: str,
        state: str | None,
        image: Image.Image,
        items: list[OCRItem],
        selector: dict[str, object],
        candidates: list[OCRMatch],
        found: bool,
        capture_ms: float,
        ocr_ms: float,
        details: dict[str, object] | None = None,
    ) -> dict[str, str]:
        directory = self._entry_directory(run_id, step, phase, attempt, action, state)
        artifacts = save_visual_artifacts(directory, image, items, selector, candidates, details)
        entry: dict[str, object] = {
            "step": step,
            "phase": phase,
            "attempt": attempt,
            "action": action,
            "state": state,
            "found": found,
            "captureMs": capture_ms,
            "ocrMs": ocr_ms,
            "artifacts": artifacts,
        }
        if details is not None:
            entry["spatial"] = details
        self._append(run_id, entry)
        return artifacts

    def record_error(
        self,
        *,
        run_id: str,
        step: int,
        phase: str,
        attempt: int,
        action: str,
        state: str | None,
        code: str,
        message: str,
        image: Image.Image | None = None,
        capture_ms: float | None = None,
    ) -> dict[str, str]:
        directory = self._entry_directory(run_id, step, phase, attempt, action, state)
        artifacts: dict[str, str] = {}
        if image is not None:
            directory.mkdir(parents=True, exist_ok=True)
            screenshot = directory / "screenshot.png"
            image.save(screenshot, "PNG")
            artifacts["screenshot"] = str(screenshot)
        entry: dict[str, object] = {
            "step": step,
            "phase": phase,
            "attempt": attempt,
            "action": action,
            "state": state,
            "error": {"code": code, "message": message},
            "artifacts": artifacts,
        }
        if capture_ms is not None:
            entry["captureMs"] = capture_ms
        self._append(run_id, entry)
        return artifacts

    def _entry_directory(
        self,
        run_id: str,
        step: int,
        phase: str,
        attempt: int,
        action: str,
        state: str | None,
    ) -> Path:
        if _RUN_ID.fullmatch(run_id) is None:
            raise ValueError("run ID must contain only letters, numbers, underscores, or hyphens")
        if step < 1 or attempt < 1:
            raise ValueError("step and attempt must be positive")
        if phase not in _PHASES:
            raise ValueError("invalid journal phase")
        if not action or len(action) > 512:
            raise ValueError("action must contain 1 to 512 characters")
        if state not in _STATES:
            raise ValueError("invalid expected state")
        return self.root / run_id / f"{step:03d}-{phase}-{attempt:03d}"

    def _append(self, run_id: str, entry: dict[str, object]) -> None:
        run_directory = self.root / run_id
        run_directory.mkdir(parents=True, exist_ok=True)
        manifest_path = run_directory / "manifest.json"
        manifest = (
            json.loads(manifest_path.read_text())
            if manifest_path.exists()
            else {"runId": run_id, "entries": []}
        )
        manifest["entries"].append(entry)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
