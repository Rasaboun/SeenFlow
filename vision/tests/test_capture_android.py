import pytest

from seenflow.capture.android import AndroidCapture


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args: list[str]) -> bytes:
        self.commands.append(args)
        return b"png"


def test_android_capture_targets_the_exact_adb_device() -> None:
    runner = RecordingRunner()

    screenshot = AndroidCapture(runner).capture("emulator-5554")

    assert screenshot == b"png"
    assert runner.commands == [["adb", "-s", "emulator-5554", "exec-out", "screencap", "-p"]]


def test_android_capture_rejects_invalid_ids_before_execution() -> None:
    runner = RecordingRunner()

    with pytest.raises(ValueError, match="device ID"):
        AndroidCapture(runner).capture("device && command")

    assert runner.commands == []
