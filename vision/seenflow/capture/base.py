import subprocess
from collections.abc import Callable, Sequence
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from seenflow.application.errors import CaptureFailed as CaptureError
from seenflow.application.ports import ScreenshotCapture as ScreenshotCapture
from seenflow.application.contracts import validate_device_id as validate_device_id


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


def decode_screenshot(screenshot: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(screenshot))
        image.load()
        return image
    except (OSError, UnidentifiedImageError, ValueError) as error:
        raise CaptureError(str(error)) from error
