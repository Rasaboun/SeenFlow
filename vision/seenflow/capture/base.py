import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Protocol


_DEVICE_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class CaptureError(RuntimeError):
    pass


class ScreenshotCapture(Protocol):
    def capture(self, device_id: str) -> bytes: ...


class ProcessRunner:
    def __init__(
        self,
        execute: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    ) -> None:
        self._execute = execute

    def run(self, args: Sequence[str]) -> bytes:
        command = list(args)
        try:
            return self._execute(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            ).stdout
        except FileNotFoundError as error:
            raise CaptureError(str(error)) from error
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode(errors="replace").strip() if error.stderr else str(error)
            raise CaptureError(detail) from error


def validate_device_id(device_id: str) -> str:
    if _DEVICE_ID.fullmatch(device_id) is None:
        raise ValueError("invalid device ID")
    return device_id
