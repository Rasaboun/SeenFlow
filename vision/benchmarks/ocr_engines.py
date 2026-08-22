import argparse
import json
from statistics import median
from time import perf_counter

from PIL import Image

from seenflow.models import OCRItem
from seenflow.ocr.paddle import PaddleOCRProvider


def summarize(items: list[OCRItem]) -> list[dict[str, object]]:
    return [
        {
            "text": item.text,
            "source": item.source,
            "lineId": item.line_id,
            "span": [item.span_start, item.span_end],
            "box": [item.box.x, item.box.y, item.box.width, item.box.height],
        }
        for item in items
    ]


def benchmark(engine: str, image: Image.Image) -> dict[str, object]:
    provider = PaddleOCRProvider(engine=engine)
    provider.detect(image)
    durations: list[float] = []
    items: list[OCRItem] = []
    for _ in range(5):
        started = perf_counter()
        items = provider.detect(image)
        durations.append((perf_counter() - started) * 1_000)
    return {
        "durationsMs": durations,
        "medianMs": median(durations),
        "summary": summarize(items),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    args = parser.parse_args()
    image = Image.open(args.image)
    results = {
        engine: benchmark(engine, image) for engine in ("paddle", "onnxruntime")
    }
    paddle_ms = float(results["paddle"]["medianMs"])
    onnx_ms = float(results["onnxruntime"]["medianMs"])
    print(
        json.dumps(
            {
                "compatible": (
                    results["paddle"]["summary"]
                    == results["onnxruntime"]["summary"]
                ),
                "speedupPercent": (paddle_ms - onnx_ms) / paddle_ms * 100,
                "engines": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
