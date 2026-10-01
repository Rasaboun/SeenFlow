import time
from collections.abc import Callable

from PIL.Image import Image

from seenflow.application.contracts import (
    ConditionResult, Detection, FindResult, FindText, Selection, SpatialEvidence,
    TargetFailure, TextSelector, validate_device, validate_run_id,
)
from seenflow.application.errors import CaptureFailed, OCRFailed, RunContextMissing
from seenflow.application.ports import ArtifactWriter, ImageDecoder, Journal, OCRProvider, ScreenshotCapture
from seenflow.matching import MatchSelectionError, evaluate_spatial_matches, find_matches, select_match
from seenflow.models import OCRItem, OCRMatch


class VisualService:
    def __init__(
        self, provider: OCRProvider, captures: dict[str, ScreenshotCapture], journal: Journal,
        decode_image: ImageDecoder, save_artifacts: ArtifactWriter,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.provider = provider
        self.captures = captures
        self.journal = journal
        self.decode_image = decode_image
        self.save_artifacts = save_artifacts
        self.log = log

    def detect(self, platform: str, device_id: str) -> Detection:
        image, _ = self._capture(platform, device_id)
        items, _ = self._detect(image)
        return Detection(image.width, image.height, items)

    def find(self, request: FindText) -> FindResult:
        journal_context = request.journal_context
        phase = "precondition" if request.precondition is not None else request.context
        state = request.precondition.state if request.precondition else request.state
        if journal_context:
            self.journal.remember_context(
                journal_context.run_id, request.platform, request.device_id, journal_context.step, journal_context.action,
            )
        try:
            image, capture_ms = self._capture(request.platform, request.device_id)
        except CaptureFailed as error:
            if journal_context:
                self.journal.record_error(
                    run_id=journal_context.run_id, step=journal_context.step, phase=phase or journal_context.phase, attempt=journal_context.attempt,
                    action=journal_context.action, state=state, code=error.code, message=str(error),
                )
            raise
        try:
            items, ocr_ms = self._detect(image)
        except OCRFailed as error:
            if journal_context:
                error.artifacts = self.journal.record_error(
                    run_id=journal_context.run_id, step=journal_context.step, phase=phase or journal_context.phase, attempt=journal_context.attempt,
                    action=journal_context.action, state=state, code=error.code, message=str(error),
                    image=image, capture_ms=capture_ms,
                )
            raise

        def record(
            selector: Selection, candidates: list[OCRMatch], found: bool,
            details: SpatialEvidence | None = None, *, entry_phase=request.context, entry_state=request.state,
        ) -> dict[str, str] | None:
            if journal_context is None:
                return None
            return self.journal.record(
                run_id=journal_context.run_id, step=journal_context.step, phase=entry_phase or journal_context.phase, attempt=journal_context.attempt,
                action=journal_context.action, state=entry_state, image=image, items=items,
                selector=selector, candidates=candidates, found=found,
                capture_ms=capture_ms, ocr_ms=ocr_ms, details=details,
            )

        precondition = None
        if request.precondition:
            condition = request.precondition
            candidates = find_matches(items, condition.text, "exact", 0.85)
            precondition = ConditionResult(bool(candidates), condition.text, condition.state)
            selector = Selection(TextSelector(condition.text))
            artifacts = record(selector, candidates, bool(candidates), entry_phase="precondition", entry_state=condition.state)
            satisfied = bool(candidates) if condition.state == "visible" else not candidates
            if not satisfied:
                return FindResult(
                    request.text, image.width, image.height, detections=items,
                    artifacts=artifacts or self.save_artifacts(image, items, selector, candidates, None),
                    precondition=precondition,
                )

        matches = find_matches(items, request.text, request.match, request.threshold)
        self._log_condition(request, bool(matches))
        selector = Selection(request.selector, request.spatial)

        def failure(
            candidates: list[OCRMatch], error: TargetFailure | None = None,
            details: SpatialEvidence | None = None,
        ) -> FindResult:
            artifacts = record(selector, candidates, False, details)
            return FindResult(
                request.text, image.width, image.height, candidates=candidates, detections=items,
                artifacts=artifacts or self.save_artifacts(image, items, selector, candidates, details),
                precondition=precondition, error=error,
            )

        details = None
        if request.spatial:
            spatial = request.spatial
            anchor_matches = find_matches(items, spatial.anchor.text, spatial.anchor.match, spatial.anchor.threshold)

            def spatial_failure(reason, candidates=matches, anchor=None, evaluations=None):
                return failure(candidates, TargetFailure(reason=reason), SpatialEvidence(anchor, evaluations or [], reason))

            if not anchor_matches:
                return spatial_failure("ANCHOR_TEXT_NOT_FOUND")
            try:
                anchor = select_match(anchor_matches, spatial.anchor.occurrence)
            except MatchSelectionError:
                return spatial_failure("ANCHOR_OCCURRENCE_NOT_FOUND", anchor_matches)
            if not matches:
                return spatial_failure("TARGET_TEXT_NOT_FOUND", anchor=anchor)
            evaluations = evaluate_spatial_matches(
                matches, anchor, spatial.relation, spatial.max_distance, image.width, image.height,
            )
            directional = [entry for entry in evaluations if entry.direction_matches]
            if not directional:
                return spatial_failure("DIRECTION_MISMATCH", anchor=anchor, evaluations=evaluations)
            valid = [entry.match for entry in directional if entry.within_distance]
            if not valid:
                return spatial_failure("MAX_DISTANCE_EXCEEDED", anchor=anchor, evaluations=evaluations)
            try:
                match = select_match(valid, request.occurrence)
            except MatchSelectionError:
                return spatial_failure("TARGET_OCCURRENCE_NOT_FOUND", valid, anchor, evaluations)
            details = SpatialEvidence(anchor, evaluations)
        else:
            if not matches and request.occurrence == 0:
                return failure(matches)
            try:
                match = select_match(matches, request.occurrence)
            except MatchSelectionError as error:
                return failure(error.matches, TargetFailure(message=str(error)))

        artifacts = record(selector, matches, True, details)
        if artifacts is None and request.diagnostics:
            artifacts = self.save_artifacts(image, items, selector, matches, None)
        self._log_match(match, image)
        return FindResult(
            request.text, image.width, image.height, match=match,
            detections=items if artifacts is not None else None, artifacts=artifacts, precondition=precondition,
        )

    def final_diagnostic(self, run_id: str) -> dict[str, str]:
        validate_run_id(run_id)
        context = self.journal.context(run_id)
        if context is None:
            raise RunContextMissing("No device context for run")
        image, capture_ms = self._capture(context.platform, context.device_id)
        items, ocr_ms = self._detect(image)
        return self.journal.record(
            run_id=run_id, step=context.step, phase="execution-failure", attempt=1,
            action=context.action, state=None, image=image, items=items, selector=None,
            candidates=[], found=False, capture_ms=capture_ms, ocr_ms=ocr_ms,
        )

    def _capture(self, platform: str, device_id: str) -> tuple[Image, float]:
        validate_device(platform, device_id)
        started = time.perf_counter()
        try:
            image = self.decode_image(self.captures[platform].capture(device_id))
        except (OSError, ValueError) as error:
            raise CaptureFailed(str(error)) from error
        duration = (time.perf_counter() - started) * 1000
        if self.log:
            self.log(f"seenflow: capture duration={duration:.1f}ms")
        return image, duration

    def _detect(self, image: Image) -> tuple[list[OCRItem], float]:
        started = time.perf_counter()
        try:
            items = self.provider.detect(image)
        except Exception as error:
            raise OCRFailed(str(error)) from error
        duration = (time.perf_counter() - started) * 1000
        if self.log:
            self.log(f"seenflow: OCR duration={duration:.1f}ms")
        return items, duration

    def _log_condition(self, request: FindText, found: bool) -> None:
        if not self.log or request.context not in ("precondition", "postcondition") or request.state is None:
            return
        satisfied = found if request.state == "visible" else not found
        attempt = f" attempt={request.attempt}" if request.attempt is not None else ""
        self.log(
            f"seenflow: {request.context} text={request.text} expected={request.state} "
            f"found={str(found).lower()} satisfied={str(satisfied).lower()}{attempt}"
        )

    def _log_match(self, match: OCRMatch, image: Image) -> None:
        if not self.log:
            return
        box = match.item.box
        x = round((box.x + box.width / 2) / image.width * 100, 2)
        y = round((box.y + box.height / 2) / image.height * 100, 2)
        self.log(
            f"seenflow: matched text={match.item.text} score={match.score:.3f} "
            f"confidence={match.item.confidence:.3f} "
            f"box=({box.x},{box.y},{box.width},{box.height}) normalized=({x:.2f},{y:.2f})"
        )
