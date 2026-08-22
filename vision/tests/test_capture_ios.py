from pathlib import Path

import pytest

from seenflow.capture.ios import IOSSimulatorCapture


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args: list[str]) -> bytes:
        self.commands.append(args)
        Path(args[-1]).write_bytes(b"png")
        return b""


def test_ios_capture_targets_the_exact_simulator_udid() -> None:
    runner = RecordingRunner()

    screenshot = IOSSimulatorCapture(runner).capture("ABC-123")

    assert screenshot == b"png"
    command = runner.commands[0]
    assert command[:6] == ["xcrun", "simctl", "io", "ABC-123", "screenshot", "--type=png"]
    assert command[6].endswith(".png")
    assert not Path(command[6]).exists()


def test_ios_capture_rejects_invalid_udids_before_execution() -> None:
    runner = RecordingRunner()

    with pytest.raises(ValueError, match="device ID"):
        IOSSimulatorCapture(runner).capture("booted; rm")

    assert runner.commands == []
