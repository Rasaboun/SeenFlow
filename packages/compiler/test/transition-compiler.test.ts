import { describe, expect, test } from "vitest";
import { parseAllDocuments } from "yaml";

import { compileFlow } from "../src/index.js";

function compile(commands: string[], config = ["appId: com.example.app"]) {
  return compileFlow([...config, "---", ...commands, ""].join("\n"), "flows/checkout.yaml");
}

function documents(yaml: string) {
  return parseAllDocuments(yaml).map((document) => document.toJS());
}

describe("compileFlow", () => {
  test("preserves standard and unknown Maestro commands", () => {
    const result = compile(["- launchApp", "- futureCommand:", "    enabled: true"]);

    expect(documents(result.yaml)).toEqual([
      { appId: "com.example.app" },
      ["launchApp", { futureCommand: { enabled: true } }],
    ]);
  });

  test("compiles tapOn visibleText as inverse assertion, native tap, and wait", () => {
    const result = compile([
      "- tapOn:",
      "    id: save-button",
      "    retryTapIfNoChange: true",
      "    expect:",
      "      visibleText: Saved",
    ]);

    expect(documents(result.yaml)[1]).toEqual([
      {
        runScript: {
          file: ".seenflow/runtime/assert-visual.js",
          env: {
            TEXT: "Saved",
            STATE: "not-visible",
            ACTION: 'tapOn {"id":"save-button","retryTapIfNoChange":true}',
            STEP: "1",
          },
        },
      },
      { tapOn: { id: "save-button", retryTapIfNoChange: true } },
      {
        runScript: {
          file: ".seenflow/runtime/wait-visual.js",
          env: {
            TEXT: "Saved",
            STATE: "visible",
            TIMEOUT: "7000",
            ACTION: 'tapOn {"id":"save-button","retryTapIfNoChange":true}',
            STEP: "1",
          },
        },
      },
    ]);
  });

  test("compiles visionTap with OCR target resolution and deterministic defaults", () => {
    const result = compile([
      "- visionTap:",
      "    text: Save",
      "    expect:",
      "      notVisibleText: Loading...",
    ]);

    expect(documents(result.yaml)[1]).toEqual([
      {
        runScript: {
          file: ".seenflow/runtime/assert-visual.js",
          env: { TEXT: "Loading...", STATE: "visible", ACTION: 'visionTap "Save"', STEP: "1" },
        },
      },
      {
        runScript: {
          file: ".seenflow/runtime/find-text.js",
          env: {
            TEXT: "Save",
            MATCH: "exact",
            THRESHOLD: "0.85",
            OCCURRENCE: "0",
            ACTION: 'visionTap "Save"',
            STEP: "1",
          },
        },
      },
      { tapOn: { point: "${output.seenflow.tapX}%,${output.seenflow.tapY}%" } },
      {
        runScript: {
          file: ".seenflow/runtime/wait-visual.js",
          env: {
            TEXT: "Loading...",
            STATE: "not-visible",
            TIMEOUT: "7000",
            ACTION: 'visionTap "Save"',
            STEP: "1",
          },
        },
      },
    ]);
  });

  test("compiles a spatial visionTap into the existing runtime bridge", () => {
    const result = compile([
      "- visionTap:",
      "    text: Edit",
      "    rightOf:",
      "      text: Chicken Curry",
      "      maxDistance: 20",
      "    expect:",
      "      visibleText: Edit recipe",
    ]);

    const commands = documents(result.yaml)[1] as Array<Record<string, unknown>>;
    expect(commands[1]).toEqual({
      runScript: {
        file: ".seenflow/runtime/find-text.js",
        env: {
          TEXT: "Edit",
          MATCH: "exact",
          THRESHOLD: "0.85",
          OCCURRENCE: "0",
          SPATIAL: JSON.stringify({
            relation: "rightOf",
            anchor: {
              text: "Chicken Curry",
              match: "exact",
              threshold: 0.85,
              occurrence: 0,
            },
            maxDistance: 20,
          }),
          ACTION: 'visionTap "Edit" rightOf "Chicken Curry"',
          STEP: "1",
        },
      },
    });
    expect(commands).not.toContainEqual(expect.objectContaining({ rightOf: expect.anything() }));
  });

  test("skips only the inverse assertion when transitions are optional", () => {
    const result = compile([
      "- visionTap:",
      "    text: Home",
      "    match: fuzzy",
      "    threshold: 0.9",
      "    occurrence: 2",
      "    timeout: 1200",
      "    expect:",
      "      visibleText: Home",
      "      requireTransition: false",
    ]);

    expect(documents(result.yaml)[1]).toEqual([
      {
        runScript: {
          file: ".seenflow/runtime/find-text.js",
          env: {
            TEXT: "Home",
            MATCH: "fuzzy",
            THRESHOLD: "0.9",
            OCCURRENCE: "2",
            ACTION: 'visionTap "Home"',
            STEP: "1",
          },
        },
      },
      { tapOn: { point: "${output.seenflow.tapX}%,${output.seenflow.tapY}%" } },
      {
        runScript: {
          file: ".seenflow/runtime/wait-visual.js",
          env: {
            TEXT: "Home",
            STATE: "visible",
            TIMEOUT: "1200",
            ACTION: 'visionTap "Home"',
            STEP: "1",
          },
        },
      },
    ]);
  });

  test("removes compiler configuration and preserves warnings", () => {
    const result = compile(
      ['- tapOn: "Save"'],
      ["appId: com.example.app", "seenflow:", "  requireEffects: true"],
    );

    expect(documents(result.yaml)[0]).toEqual({ appId: "com.example.app" });
    expect(result.warnings).toMatchObject([
      {
        location: { file: "flows/checkout.yaml", line: 5, column: 1 },
        message: expect.stringContaining("tapOn action has no expected effect"),
      },
    ]);
  });

  test("allows the generated workspace to choose a valid relative runtime path", () => {
    const source = [
      "appId: com.example.app",
      "---",
      "- visionTap:",
      "    text: Save",
      "    expect:",
      "      visibleText: Saved",
      "",
    ].join("\n");

    const result = compileFlow(source, "flow.yaml", { runtimePath: "../runtime" });

    expect(documents(result.yaml)[1]).toMatchObject([
      { runScript: { file: "../runtime/assert-visual.js" } },
      { runScript: { file: "../runtime/find-text.js" } },
      { tapOn: expect.anything() },
      { runScript: { file: "../runtime/wait-visual.js" } },
    ]);
  });

  test("compiles swipe and longPressOn through visual transitions", () => {
    const result = compile([
      "- swipe:",
      "    direction: UP",
      "    waitToSettleTimeoutMs: 500",
      "    expect:",
      "      visibleText: Orders",
      "- longPressOn:",
      "    point: 50%,50%",
      "    expect:",
      "      visibleText: Actions",
    ]);

    expect(documents(result.yaml)[1]).toEqual([
      {
        runScript: {
          file: ".seenflow/runtime/assert-visual.js",
          env: {
            TEXT: "Orders",
            STATE: "not-visible",
            ACTION: 'swipe {"direction":"UP","waitToSettleTimeoutMs":500}',
            STEP: "1",
          },
        },
      },
      { swipe: { direction: "UP", waitToSettleTimeoutMs: 500 } },
      {
        runScript: {
          file: ".seenflow/runtime/wait-visual.js",
          env: {
            TEXT: "Orders",
            STATE: "visible",
            TIMEOUT: "7000",
            ACTION: 'swipe {"direction":"UP","waitToSettleTimeoutMs":500}',
            STEP: "1",
          },
        },
      },
      {
        runScript: {
          file: ".seenflow/runtime/assert-visual.js",
          env: {
            TEXT: "Actions",
            STATE: "not-visible",
            ACTION: 'longPressOn {"point":"50%,50%"}',
            STEP: "2",
          },
        },
      },
      { longPressOn: { point: "50%,50%" } },
      {
        runScript: {
          file: ".seenflow/runtime/wait-visual.js",
          env: {
            TEXT: "Actions",
            STATE: "visible",
            TIMEOUT: "7000",
            ACTION: 'longPressOn {"point":"50%,50%"}',
            STEP: "2",
          },
        },
      },
    ]);
  });
});
