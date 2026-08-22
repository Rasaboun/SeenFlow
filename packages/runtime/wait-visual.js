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

function findVisualText(diagnostics, attempt) {
  var payload = {
    platform: maestro.platform,
    deviceId: MAESTRO_DEVICE_UDID,
    text: TEXT,
    match: "exact",
    threshold: 0.85,
    occurrence: 0,
    context: "postcondition",
    state: STATE,
    attempt: attempt,
    runId: SEENFLOW_RUN_ID,
    step: Number(STEP),
    action: actionDescription,
  };
  if (diagnostics) payload.diagnostics = true;
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
  var body = json(response.body);
  if (typeof body.found !== "boolean") {
    throw new Error("OCR_RUNTIME_FAILED\nSidecar returned an invalid visual assertion response.");
  }
  return body;
}

function pause(milliseconds) {
  var until = Date.now() + milliseconds;
  while (Date.now() < until) {}
}

var actionDescription = typeof ACTION === "undefined" ? "supported action" : ACTION;
var timeout = Number(TIMEOUT);
var deadline = Date.now() + timeout;
var attempts = 0;
var lastResult;
while (true) {
  attempts += 1;
  lastResult = findVisualText(false, attempts);
  if (STATE === "visible" ? lastResult.found : !lastResult.found) break;
  if (Date.now() >= deadline) {
    if (!lastResult.artifacts) lastResult = findVisualText(true, attempts);
    var detected = (lastResult.detections || [])
      .map(function (item) {
        return '  "' + item.text + '" confidence=' + item.confidence;
      })
      .join("\n");
    var artifacts = lastResult.artifacts
      ? "\nArtifacts:\n  " + Object.keys(lastResult.artifacts).map(function (key) {
          return lastResult.artifacts[key];
        }).join("\n  ")
      : "";
    throw new Error(
      "POSTCONDITION_TIMEOUT\nAction:\n  " +
        actionDescription +
        '\nExpected "' +
        TEXT +
        '" to become ' +
        STATE +
        ".\nTimeout: " +
        timeout +
        "ms\nAttempts: " +
        attempts +
        "\nLast OCR detections:\n" +
        (detected || "  nothing") +
        artifacts,
    );
  }
  pause(250);
}

if (typeof SEENFLOW_DEBUG !== "undefined" && SEENFLOW_DEBUG === "true") {
  console.log("seenflow: postcondition satisfied after " + attempts + " OCR attempt(s)");
}
