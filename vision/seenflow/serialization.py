from dataclasses import asdict

from seenflow.application.contracts import FindResult, Selection, SpatialEvidence
from seenflow.models import BoundingBox, OCRItem, OCRMatch, SpatialEvaluation


def item_json(item: OCRItem) -> dict[str, object]:
    payload: dict[str, object] = {
        "text": item.text,
        "confidence": item.confidence,
        "box": box_json(item.box),
        "source": item.source,
    }
    if item.line_id is not None:
        payload["lineId"] = item.line_id
    if item.span_start is not None and item.span_end is not None:
        payload["span"] = {"start": item.span_start, "end": item.span_end}
    if item.refinement_error is not None:
        payload["refinementError"] = item.refinement_error
    return payload


def box_json(box: BoundingBox) -> dict[str, int]:
    return {"x": box.x, "y": box.y, "width": box.width, "height": box.height}


def match_json(match: OCRMatch) -> dict[str, object]:
    return {**item_json(match.item), "score": match.score}


def spatial_evaluation_json(evaluation: SpatialEvaluation) -> dict[str, object]:
    reason = None
    if not evaluation.direction_matches:
        reason = "DIRECTION_MISMATCH"
    elif not evaluation.within_distance:
        reason = "MAX_DISTANCE_EXCEEDED"
    return {
        **match_json(evaluation.match),
        "distancePercent": round(evaluation.distance_percent, 4),
        "directionMatches": evaluation.direction_matches,
        "withinDistance": evaluation.within_distance,
        "rejectionReason": reason,
    }


def selection_json(selector: Selection | dict[str, object] | None) -> dict[str, object]:
    if selector is None:
        return {}
    if isinstance(selector, dict):
        return selector
    result = asdict(selector.text)
    if selector.spatial:
        spatial = selector.spatial
        result["spatial"] = {
            "relation": spatial.relation,
            "anchor": asdict(spatial.anchor),
            "maxDistance": spatial.max_distance,
        }
    return result


def spatial_json(details: SpatialEvidence | dict[str, object] | None) -> dict[str, object] | None:
    if details is None or isinstance(details, dict):
        return details
    return {
        "anchor": match_json(details.anchor) if details.anchor else None,
        "candidates": [spatial_evaluation_json(entry) for entry in details.evaluations],
        "reason": details.reason,
    }


def find_result_json(result: FindResult) -> dict[str, object]:
    response: dict[str, object] = {"found": result.match is not None, "query": result.query}
    if result.match is not None:
        box = result.match.item.box
        center_x, center_y = box.x + box.width / 2, box.y + box.height / 2
        response["match"] = {
            **match_json(result.match),
            "center": {"x": center_x, "y": center_y},
            "normalized": {
                "x": round(center_x / result.width * 100, 2),
                "y": round(center_y / result.height * 100, 2),
            },
        }
    else:
        response["matches"] = [match_json(candidate) for candidate in result.candidates]
    if result.precondition is not None:
        response["precondition"] = asdict(result.precondition)
    if result.detections is not None:
        response["detections"] = [item_json(item) for item in result.detections]
    if result.artifacts is not None:
        response["artifacts"] = result.artifacts
    if result.error is not None:
        response["error"] = {key: value for key, value in asdict(result.error).items() if value is not None}
    return response
