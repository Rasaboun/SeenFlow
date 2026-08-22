function throwSidecarError(response) {
  var code = "OCR_RUNTIME_FAILED";
  var message = response.body;
  try {
    var body = json(response.body);
    if (body.detail && body.detail.code === "OCR_CAPTURE_FAILED") code = body.detail.code;
    if (body.detail && typeof body.detail.message === "string") message = body.detail.message;
    if (body.detail && body.detail.artifacts) {
      message += "\nArtifacts:\n  " + Object.keys(body.detail.artifacts).map(function (key) {
        return body.detail.artifacts[key];
      }).join("\n  ");
    }
  } catch (_error) {}
  throw new Error(code + "\nSidecar returned HTTP " + response.status + ".\n" + message);
}

function requestFind(payload) {
  var response = http.post(SEENFLOW_URL + "/v1/text/find", {
    headers: {
      Authorization: "Bearer " + SEENFLOW_TOKEN,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throwSidecarError(response);
  }
  return json(response.body);
}

var actionDescription = typeof ACTION === "undefined" ? 'visionTap "' + TEXT + '"' : ACTION;
var spatial;
if (typeof SPATIAL !== "undefined") {
  try {
    spatial = json(SPATIAL);
  } catch (_error) {
    throw new Error("OCR_RUNTIME_FAILED\nSeenflow received invalid spatial configuration.");
  }
}
var payload = {
  platform: maestro.platform,
  deviceId: MAESTRO_DEVICE_UDID,
  text: TEXT,
  match: MATCH,
  threshold: Number(THRESHOLD),
  occurrence: Number(OCCURRENCE),
  context: "target",
  runId: SEENFLOW_RUN_ID,
  step: Number(STEP),
  action: actionDescription,
  attempt: 1,
};
if (spatial !== undefined) payload.spatial = spatial;
var hasPreconditionText = typeof PRECONDITION_TEXT !== "undefined";
var hasPreconditionState = typeof PRECONDITION_STATE !== "undefined";
if (hasPreconditionText !== hasPreconditionState) {
  throw new Error("OCR_RUNTIME_FAILED\nSeenflow received incomplete precondition configuration.");
}
if (hasPreconditionText) {
  if (PRECONDITION_STATE !== "visible" && PRECONDITION_STATE !== "not-visible") {
    throw new Error("OCR_RUNTIME_FAILED\nSeenflow received invalid precondition state.");
  }
  payload.precondition = { text: PRECONDITION_TEXT, state: PRECONDITION_STATE };
}
var result = requestFind(payload);

if (!result || typeof result.found !== "boolean") {
  throw new Error("OCR_RUNTIME_FAILED\nSidecar returned an invalid find response.");
}
if (hasPreconditionText) {
  if (
    !result.precondition ||
    typeof result.precondition.found !== "boolean" ||
    result.precondition.query !== PRECONDITION_TEXT ||
    result.precondition.state !== PRECONDITION_STATE
  ) {
    throw new Error("OCR_RUNTIME_FAILED\nSidecar returned an invalid precondition response.");
  }
  var preconditionSatisfied = PRECONDITION_STATE === "visible"
    ? result.precondition.found
    : !result.precondition.found;
  if (typeof SEENFLOW_DEBUG !== "undefined" && SEENFLOW_DEBUG === "true") {
    console.log(
      "seenflow: precondition text=" + PRECONDITION_TEXT +
      " expected=" + PRECONDITION_STATE +
      " found=" + result.precondition.found,
    );
  }
  if (!preconditionSatisfied) {
    var preconditionDetections = (result.detections || [])
      .map(function (item) {
        return '  "' + item.text + '" confidence=' + item.confidence;
      })
      .join("\n");
    var preconditionArtifacts = result.artifacts
      ? "\nArtifacts:\n  " + Object.keys(result.artifacts).map(function (key) {
        return result.artifacts[key];
      }).join("\n  ")
      : "";
    throw new Error(
      "PRECONDITION_FAILED\nAction:\n  " + actionDescription +
      '\nExpected effect for "' + PRECONDITION_TEXT +
      '" was already satisfied before action; the action would not prove a transition.\nOCR detected:\n' +
      (preconditionDetections || "  nothing") + preconditionArtifacts,
    );
  }
}
if (!result.found) {
  var detected = (result.detections || [])
    .map(function (item) {
      return '  "' + item.text + '" confidence=' + item.confidence;
    })
    .join("\n");
  var candidates = (result.matches || [])
    .map(function (item) {
      return '  "' + item.text + '" confidence=' + item.confidence + " score=" + item.score;
    })
    .join("\n");
  var artifacts = result.artifacts
    ? "\nArtifacts:\n  " + Object.keys(result.artifacts).map(function (key) {
        return result.artifacts[key];
      }).join("\n  ")
    : "";
  var reason = result.error && typeof result.error.reason === "string"
    ? "\nReason:\n  " + result.error.reason
    : "";
  throw new Error(
    "ACTION_TARGET_NOT_FOUND\nAction:\n  " +
      actionDescription +
      '\nVisual text "' +
      TEXT +
      '" was not found.\nOCR detected:\n' +
      (detected || "  nothing") +
      (candidates ? "\nMatching candidates:\n" + candidates : "") +
      reason +
      artifacts,
  );
}
if (
  !result.match ||
  !result.match.normalized ||
  typeof result.match.text !== "string" ||
  typeof result.match.confidence !== "number" ||
  typeof result.match.normalized.x !== "number" ||
  typeof result.match.normalized.y !== "number" ||
  !Number.isFinite(result.match.normalized.x) ||
  !Number.isFinite(result.match.normalized.y) ||
  result.match.normalized.x < 0 ||
  result.match.normalized.x > 100 ||
  result.match.normalized.y < 0 ||
  result.match.normalized.y > 100
) {
  throw new Error("OCR_RUNTIME_FAILED\nSidecar returned invalid coordinates.");
}

output.seenflow = {
  x: result.match.normalized.x,
  y: result.match.normalized.y,
  tapX: Math.round(result.match.normalized.x),
  tapY: Math.round(result.match.normalized.y),
  text: result.match.text,
  confidence: result.match.confidence,
};
