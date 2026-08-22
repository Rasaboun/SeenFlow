import subprocess

import pytest

from seenflow.capture.base import CaptureError, ProcessRunner, validate_device_id


def test_process_runner_uses_argument_arrays_without_a_shell() -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def execute(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout=b"png", stderr=b"")

    output = ProcessRunner(execute).run(["capture", "device-id"])

    assert output == b"png"
    assert calls == [
        (
            ["capture", "device-id"],
            {"check": True, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "shell": False},
        )
    ]


def test_process_runner_wraps_command_failures() -> None:
    def execute(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(1, args, stderr=b"capture failed")

    with pytest.raises(CaptureError, match="capture failed"):
        ProcessRunner(execute).run(["capture", "device-id"])


@pytest.mark.parametrize("device_id", ["", "has space", "../../device", "a" * 129])
def test_device_ids_are_validated(device_id: str) -> None:
    with pytest.raises(ValueError, match="device ID"):
        validate_device_id(device_id)


@pytest.mark.parametrize("device_id", ["ABC-123", "emulator-5554", "192.168.1.10:5555"])
def test_supported_device_ids_are_accepted(device_id: str) -> None:
    assert validate_device_id(device_id) == device_id
