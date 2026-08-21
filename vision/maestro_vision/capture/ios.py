from .base import ProcessRunner, validate_device_id


class IOSSimulatorCapture:
    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self._runner = runner or ProcessRunner()

    def capture(self, device_id: str) -> bytes:
        udid = validate_device_id(device_id)
        return self._runner.run(["xcrun", "simctl", "io", udid, "screenshot", "-"])
