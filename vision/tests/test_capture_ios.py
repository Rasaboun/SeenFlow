import pytest

from maestro_vision.capture.ios import IOSSimulatorCapture


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args: list[str]) -> bytes:
        self.commands.append(args)
        return b"png"


def test_ios_capture_targets_the_exact_simulator_udid() -> None:
    runner = RecordingRunner()

    screenshot = IOSSimulatorCapture(runner).capture("ABC-123")

    assert screenshot == b"png"
    assert runner.commands == [["xcrun", "simctl", "io", "ABC-123", "screenshot", "-"]]


def test_ios_capture_rejects_invalid_udids_before_execution() -> None:
    runner = RecordingRunner()

    with pytest.raises(ValueError, match="device ID"):
        IOSSimulatorCapture(runner).capture("booted; rm")

    assert runner.commands == []
