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
      SEENFLOW_URL: "http://127.0.0.1:43123",
      SEENFLOW_TOKEN: "secret-token",
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
        context: "target",
      }),
    });
    expect(globals.output).toEqual({
      seenflow: {
        x: 51.33,
        y: 78.21,
        tapX: 51,
        tapY: 78,
        text: "Save",
        confidence: 0.97,
      },
    });
  });

  test("find-text exposes an actionable target failure", () => {
    const { globals } = baseGlobals({
      found: false,
      query: "Save",
      matches: [],
      detections: [{ text: "START COOKlNG", confidence: 0.91 }],
      artifacts: { annotated: ".seenflow/artifacts/run/annotated.png" },
    });

    expect(() =>
      execute("find-text.js", {
        ...globals,
        TEXT: "Save",
        MATCH: "exact",
        THRESHOLD: "0.85",
        OCCURRENCE: "0",
      }),
    ).toThrowError(
      /ACTION_TARGET_NOT_FOUND[\s\S]*Save[\s\S]*START COOKlNG[\s\S]*annotated\.png/,
    );
  });

  test("find-text treats a missing occurrence as an action target failure", () => {
    const { globals } = baseGlobals({
      found: false,
      query: "Add",
      matches: [
        { text: "Add", confidence: 0.9 },
        { text: "Add", confidence: 0.8 },
      ],
      detections: [{ text: "Add", confidence: 0.9 }],
    });

    expect(() =>
      execute("find-text.js", {
        ...globals,
        TEXT: "Add",
        MATCH: "exact",
        THRESHOLD: "0.85",
        OCCURRENCE: "2",
      }),
    ).toThrowError(/ACTION_TARGET_NOT_FOUND[\s\S]*Matching candidates:[\s\S]*confidence=0\.9/);
  });

  test.each([
    ["visible", false],
    ["not-visible", true],
  ])("rejects an already-satisfied %s effect before the action", (state, found) => {
    const { globals } = baseGlobals({ found, query: "Saved", matches: [] });

    expect(() =>
      execute("assert-visual.js", {
        ...globals,
        ACTION: 'visionTap "Save"',
        TEXT: "Saved",
        STATE: state,
      }),
    ).toThrowError(/PRECONDITION_FAILED[\s\S]*Action:[\s\S]*visionTap "Save"[\s\S]*Saved/);
  });

  test("debug mode logs the visual precondition result", () => {
    const { globals, post } = baseGlobals({ found: false, query: "Saved", matches: [] });

    execute("assert-visual.js", {
      ...globals,
      SEENFLOW_DEBUG: "true",
      TEXT: "Saved",
      STATE: "not-visible",
    });

    expect((globals.console as { log: ReturnType<typeof vi.fn> }).log).toHaveBeenCalledWith(
      "seenflow: precondition text=Saved expected=not-visible found=false",
    );
    expect(JSON.parse((post.mock.calls[0]?.[1] as { body: string }).body)).toMatchObject({
      context: "precondition",
      state: "not-visible",
    });
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
    expect(JSON.parse((post.mock.calls[1]?.[1] as { body: string }).body)).toMatchObject({
      context: "postcondition",
      state: "visible",
      attempt: 2,
    });
  });

  test("wait-visual distinguishes a postcondition timeout", () => {
    let now = 0;
    class FakeDate {
      static now() {
        now += 300;
        return now;
      }
    }
    const { globals } = baseGlobals({
      found: false,
      query: "Saved",
      matches: [],
      detections: [{ text: "Saving...", confidence: 0.93 }],
      artifacts: { screenshot: ".seenflow/artifacts/run/screenshot.png" },
    });

    expect(() =>
      execute("wait-visual.js", {
        ...globals,
        ACTION: 'visionTap "Save"',
        Date: FakeDate,
        TEXT: "Saved",
        STATE: "visible",
        TIMEOUT: "500",
      }),
    ).toThrowError(
      /POSTCONDITION_TIMEOUT[\s\S]*Action:[\s\S]*visionTap "Save"[\s\S]*500ms[\s\S]*Attempts:[\s\S]*Saving\.\.\.[\s\S]*screenshot\.png/,
    );
  });

  test("not-visible timeout takes a final diagnostic screenshot", () => {
    let now = 0;
    class FakeDate {
      static now() {
        now += 300;
        return now;
      }
    }
    const { globals, post } = baseGlobals(null);
    post.mockImplementation((_url, options: { body: string }) => {
      const diagnostic = JSON.parse(options.body).diagnostics === true;
      return diagnostic
        ? {
        ok: true,
        status: 200,
        body: JSON.stringify({
          found: true,
          match: { text: "Loading..." },
          detections: [{ text: "Loading...", confidence: 0.96 }],
          artifacts: { screenshot: ".seenflow/artifacts/run/screenshot.png" },
        }),
          }
        : {
            ok: true,
            status: 200,
            body: JSON.stringify({ found: true, match: { text: "Loading..." } }),
          };
    });

    expect(() =>
      execute("wait-visual.js", {
        ...globals,
        ACTION: 'visionTap "Close"',
        Date: FakeDate,
        TEXT: "Loading...",
        STATE: "not-visible",
        TIMEOUT: "500",
      }),
    ).toThrowError(/POSTCONDITION_TIMEOUT[\s\S]*Loading\.\.\.[\s\S]*screenshot\.png/);
    const lastCall = post.mock.calls.at(-1)?.[1] as { body: string };
    expect(JSON.parse(lastCall.body)).toMatchObject({
      diagnostics: true,
    });
  });

  test("rejects sidecar HTTP failures instead of accepting malformed state", () => {
    const { globals, post } = baseGlobals(null);
    post.mockReturnValue({ ok: false, status: 401, body: "unauthorized" });

    expect(() =>
      execute("assert-visual.js", { ...globals, TEXT: "Saved", STATE: "not-visible" }),
    ).toThrowError(/OCR_RUNTIME_FAILED[\s\S]*401/);
  });

  test.each(["assert-visual.js", "find-text.js", "wait-visual.js"])(
    "%s preserves sidecar capture failure codes",
    (file) => {
      const { globals, post } = baseGlobals(null);
      post.mockReturnValue({
        ok: false,
        status: 502,
        body: JSON.stringify({
          detail: { code: "OCR_CAPTURE_FAILED", message: "adb screencap failed" },
        }),
      });

      expect(() =>
        execute(file, {
          ...globals,
          ACTION: 'visionTap "Save"',
          TEXT: "Save",
          MATCH: "exact",
          THRESHOLD: "0.85",
          OCCURRENCE: "0",
          STATE: "visible",
          TIMEOUT: "500",
        }),
      ).toThrowError(/^OCR_CAPTURE_FAILED[\s\S]*adb screencap failed/);
    },
  );

  test.each([
    [{ found: "yes" }, "invalid find response"],
    [
      {
        found: true,
        match: { text: "Save", confidence: 0.9, normalized: { x: 101, y: 50 } },
      },
      "invalid coordinates",
    ],
  ])("rejects malformed find responses", (body, message) => {
    const { globals } = baseGlobals(body);

    expect(() =>
      execute("find-text.js", {
        ...globals,
        TEXT: "Save",
        MATCH: "exact",
        THRESHOLD: "0.85",
        OCCURRENCE: "0",
      }),
    ).toThrowError(new RegExp(`OCR_RUNTIME_FAILED[\\s\\S]*${message}`));
  });
});
