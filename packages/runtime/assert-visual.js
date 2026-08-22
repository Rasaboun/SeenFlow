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

function findVisualText() {
  var response = http.post(SEENFLOW_URL + "/v1/text/find", {
    headers: {
      Authorization: "Bearer " + SEENFLOW_TOKEN,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      platform: maestro.platform,
      deviceId: MAESTRO_DEVICE_UDID,
      text: TEXT,
      match: "exact",
      threshold: 0.85,
      occurrence: 0,
    }),
  });
  if (!response.ok) {
    throwSidecarError(response);
  }
  var body = json(response.body);
  if (typeof body.found !== "boolean") {
    throw new Error("OCR_RUNTIME_FAILED\nSidecar returned an invalid visual assertion response.");
  }
  return body.found;
}

var actionDescription = typeof ACTION === "undefined" ? "supported action" : ACTION;
var found = findVisualText();
if (typeof SEENFLOW_DEBUG !== "undefined" && SEENFLOW_DEBUG === "true") {
  console.log(
    "seenflow: precondition text=" + TEXT + " expected=" + STATE + " found=" + found,
  );
}
var satisfied = STATE === "visible" ? found : !found;
if (!satisfied) {
  throw new Error(
    "PRECONDITION_FAILED\nAction:\n  " +
      actionDescription +
      '\nExpected effect for "' +
      TEXT +
      '" was already satisfied before action; the action would not prove a transition.',
  );
}
