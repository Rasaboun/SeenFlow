function findVisualText() {
  var response = http.post(MAESTRO_VISION_URL + "/v1/text/find", {
    headers: {
      Authorization: "Bearer " + MAESTRO_VISION_TOKEN,
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
    throw new Error("OCR_RUNTIME_FAILED\nSidecar returned HTTP " + response.status + ".\n" + response.body);
  }
  var body = json(response.body);
  if (typeof body.found !== "boolean") {
    throw new Error("OCR_RUNTIME_FAILED\nSidecar returned an invalid visual assertion response.");
  }
  return body.found;
}

var found = findVisualText();
var satisfied = STATE === "visible" ? found : !found;
if (!satisfied) {
  throw new Error(
    'PRECONDITION_FAILED\nExpected effect for "' +
      TEXT +
      '" was already satisfied before action; the action would not prove a transition.',
  );
}

