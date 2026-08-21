import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

import { describe, expect, test, vi } from "vitest";

const runtime = resolve(import.meta.dirname, "..");

function execute(file: string, globals: Record<string, unknown>) {
  return runInNewContext(readFileSync(resolve(runtime, file), "utf8"), globals, { filename: file });
}

function baseGlobals(body: unknown, overrides: Record<string, unknown> = {}) {
  const post = vi.fn(() => ({ ok: true, status: 200, body: JSON.stringify(body) }));
  return {
    globals: {
      MAESTRO_VISION_URL: "http://127.0.0.1:43123",
      MAESTRO_VISION_TOKEN: "secret-token",
      MAESTRO_DEVICE_UDID: "device-123",
      maestro: { platform: "ios" },
      http: { post },
      json: JSON.parse,
      output: {},
      console: { log: vi.fn() },
      ...overrides,
    },
    post,
  };
}

describe("Maestro runtime bridge", () => {
  test("find-text requests OCR and publishes normalized coordinates", () => {
    const { globals, post } = baseGlobals({
      found: true,
      match: {
        text: "Save",
        confidence: 0.97,
        normalized: { x: 51.33, y: 78.21 },
      },
    });

    execute("find-text.js", {
      ...globals,
      TEXT: "Save",
      MATCH: "exact",
      THRESHOLD: "0.85",
      OCCURRENCE: "0",
    });

    expect(post).toHaveBeenCalledWith("http://127.0.0.1:43123/v1/text/find", {
      headers: {
        Authorization: "Bearer secret-token",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        platform: "ios",
        deviceId: "device-123",
        text: "Save",
        match: "exact",
        threshold: 0.85,
        occurrence: 0,
      }),
    });
    expect(globals.output).toEqual({
      maestroVision: { x: 51.33, y: 78.21, text: "Save", confidence: 0.97 },
    });
  });

  test("find-text exposes an actionable target failure", () => {
    const { globals } = baseGlobals({ found: false, query: "Save", matches: [] });

    expect(() =>
      execute("find-text.js", {
        ...globals,
        TEXT: "Save",
        MATCH: "exact",
        THRESHOLD: "0.85",
        OCCURRENCE: "0",
      }),
    ).toThrowError(/ACTION_TARGET_NOT_FOUND[\s\S]*Save/);
  });

  test.each([
    ["visible", false],
    ["not-visible", true],
  ])("rejects an already-satisfied %s effect before the action", (state, found) => {
    const { globals } = baseGlobals({ found, query: "Saved", matches: [] });

    expect(() =>
      execute("assert-visual.js", { ...globals, TEXT: "Saved", STATE: state }),
    ).toThrowError(/PRECONDITION_FAILED[\s\S]*Saved/);
  });

  test("wait-visual polls until the visual postcondition is satisfied", () => {
    const responses = [
      { found: false, query: "Saved", matches: [] },
      { found: true, query: "Saved", match: { text: "Saved" } },
    ];
    const { globals, post } = baseGlobals(null);
    post.mockImplementation(() => ({
      ok: true,
      status: 200,
      body: JSON.stringify(responses.shift()),
    }));

    execute("wait-visual.js", {
      ...globals,
      TEXT: "Saved",
      STATE: "visible",
      TIMEOUT: "7000",
    });

    expect(post).toHaveBeenCalledTimes(2);
  });

  test("wait-visual distinguishes a postcondition timeout", () => {
    let now = 0;
    class FakeDate {
      static now() {
        now += 300;
        return now;
      }
    }
    const { globals } = baseGlobals({ found: false, query: "Saved", matches: [] });

    expect(() =>
      execute("wait-visual.js", {
        ...globals,
        Date: FakeDate,
        TEXT: "Saved",
        STATE: "visible",
        TIMEOUT: "500",
      }),
    ).toThrowError(/POSTCONDITION_TIMEOUT[\s\S]*500ms/);
  });

  test("rejects sidecar HTTP failures instead of accepting malformed state", () => {
    const { globals, post } = baseGlobals(null);
    post.mockReturnValue({ ok: false, status: 401, body: "unauthorized" });

    expect(() =>
      execute("assert-visual.js", { ...globals, TEXT: "Saved", STATE: "not-visible" }),
    ).toThrowError(/OCR_RUNTIME_FAILED[\s\S]*401/);
  });
});
