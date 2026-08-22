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
          env: { TEXT: "Loading...", STATE: "visible", ACTION: 'visionTap "Save"' },
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
          },
        },
      },
    ]);
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
});
