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

function pause(milliseconds) {
  var until = Date.now() + milliseconds;
  while (Date.now() < until) {}
}

var timeout = Number(TIMEOUT);
var deadline = Date.now() + timeout;
var attempts = 0;
while (true) {
  attempts += 1;
  var found = findVisualText();
  if (STATE === "visible" ? found : !found) break;
  if (Date.now() >= deadline) {
    throw new Error(
      'POSTCONDITION_TIMEOUT\nExpected "' +
        TEXT +
        '" to become ' +
        STATE +
        ".\nTimeout: " +
        timeout +
        "ms",
    );
  }
  pause(250);
}

if (typeof MAESTRO_VISION_DEBUG !== "undefined" && MAESTRO_VISION_DEBUG === "true") {
  console.log("maestro-vision: postcondition satisfied after " + attempts + " OCR attempt(s)");
}
