function requestFind(payload) {
  var response = http.post(MAESTRO_VISION_URL + "/v1/text/find", {
    headers: {
      Authorization: "Bearer " + MAESTRO_VISION_TOKEN,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error("OCR_RUNTIME_FAILED\nSidecar returned HTTP " + response.status + ".\n" + response.body);
  }
  return json(response.body);
}

var result = requestFind({
  platform: maestro.platform,
  deviceId: MAESTRO_DEVICE_UDID,
  text: TEXT,
  match: MATCH,
  threshold: Number(THRESHOLD),
  occurrence: Number(OCCURRENCE),
});

if (!result.found) {
  throw new Error('ACTION_TARGET_NOT_FOUND\nVisual text "' + TEXT + '" was not found.');
}
if (
  !result.match ||
  !result.match.normalized ||
  typeof result.match.normalized.x !== "number" ||
  typeof result.match.normalized.y !== "number"
) {
  throw new Error("OCR_RUNTIME_FAILED\nSidecar returned invalid coordinates.");
}

output.maestroVision = {
  x: result.match.normalized.x,
  y: result.match.normalized.y,
  text: result.match.text,
  confidence: result.match.confidence,
};

