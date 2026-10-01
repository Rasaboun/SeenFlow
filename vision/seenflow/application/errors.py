class VisualError(RuntimeError):
    """Application failure; adapters choose how to present it."""

    code: str

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.artifacts: dict[str, str] | None = None


class CaptureFailed(VisualError):
    code = "OCR_CAPTURE_FAILED"


class OCRFailed(VisualError):
    code = "OCR_RUNTIME_FAILED"


class RunContextMissing(VisualError):
    code = "RUN_CONTEXT_MISSING"
