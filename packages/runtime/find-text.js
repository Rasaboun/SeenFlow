function throwSidecarError(response) {
  var code = "OCR_RUNTIME_FAILED";
  var message = response.body;
  try {
    var body = json(response.body);
    if (body.detail && body.detail.code === "OCR_CAPTURE_FAILED") code = body.detail.code;
    if (body.detail && typeof body.detail.message === "string") message = body.detail.message;
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
var result = requestFind({
  platform: maestro.platform,
  deviceId: MAESTRO_DEVICE_UDID,
  text: TEXT,
  match: MATCH,
  threshold: Number(THRESHOLD),
  occurrence: Number(OCCURRENCE),
});

if (!result || typeof result.found !== "boolean") {
  throw new Error("OCR_RUNTIME_FAILED\nSidecar returned an invalid find response.");
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
  throw new Error(
    "ACTION_TARGET_NOT_FOUND\nAction:\n  " +
      actionDescription +
      '\nVisual text "' +
      TEXT +
      '" was not found.\nOCR detected:\n' +
      (detected || "  nothing") +
      (candidates ? "\nMatching candidates:\n" + candidates : "") +
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
