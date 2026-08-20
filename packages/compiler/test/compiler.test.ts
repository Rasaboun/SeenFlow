import { describe, expect, test } from "vitest";

import { buildFlowAst, parseFlow } from "../src/index.js";

function flow(lines: string[]) {
  return parseFlow(["appId: com.example.app", "---", ...lines, ""].join("\n"), "flows/checkout.yaml");
}

describe("buildFlowAst", () => {
  test("keeps non-visionTap commands as opaque Maestro actions", () => {
    const ast = buildFlowAst(flow(["- launchApp", "- futureCommand:", "    enabled: true"]));

    expect(ast.actions).toEqual([
      {
        kind: "maestro",
        value: "launchApp",
        location: { file: "flows/checkout.yaml", line: 3, column: 1 },
      },
      {
        kind: "maestro",
        value: { futureCommand: { enabled: true } },
        location: { file: "flows/checkout.yaml", line: 4, column: 1 },
      },
    ]);
  });

  test("applies visionTap selector and transition defaults", () => {
    const ast = buildFlowAst(
      flow(["- visionTap:", "    text: Save", "    expect:", "      visibleText: Saved"]),
    );

    expect(ast.actions).toEqual([
      {
        kind: "visionTap",
        text: "Save",
        match: "exact",
        threshold: 0.85,
        occurrence: 0,
        timeout: 7000,
        expect: {
          kind: "visibleText",
          text: "Saved",
          requireTransition: true,
        },
        location: { file: "flows/checkout.yaml", line: 3, column: 1 },
      },
    ]);
  });

  test("supports notVisibleText with an explicit transition escape hatch", () => {
    const ast = buildFlowAst(
      flow([
        "- visionTap:",
        "    text: Close",
        "    match: contains",
        "    threshold: 0",
        "    occurrence: 1",
        "    timeout: 1",
        "    expect:",
        "      notVisibleText: Loading",
        "      requireTransition: false",
      ]),
    );

    expect(ast.actions[0]).toMatchObject({
      kind: "visionTap",
      text: "Close",
      match: "contains",
      threshold: 0,
      occurrence: 1,
      timeout: 1,
      expect: { kind: "notVisibleText", text: "Loading", requireTransition: false },
    });
  });

  const invalidVisionTaps: Array<[string, string[]]> = [
    ["text", ["- visionTap:", "    expect:", "      visibleText: Saved"]],
    ["text", ["- visionTap:", "    text: 12", "    expect:", "      visibleText: Saved"]],
    ["expect", ["- visionTap:", "    text: Save"]],
    ["expect", ["- visionTap:", "    text: Save", "    expect: Saved"]],
    [
      "effect",
      ["- visionTap:", "    text: Save", "    expect:", "      visibleText: Saved", "      notVisibleText: Loading"],
    ],
    [
      "requireTransition",
      ["- visionTap:", "    text: Save", "    expect:", "      visibleText: Saved", "      requireTransition: null"],
    ],
    ["match", ["- visionTap:", "    text: Save", "    match: nearby", "    expect:", "      visibleText: Saved"]],
    ["threshold", ["- visionTap:", "    text: Save", "    threshold: 1.1", "    expect:", "      visibleText: Saved"]],
    ["occurrence", ["- visionTap:", "    text: Save", "    occurrence: -1", "    expect:", "      visibleText: Saved"]],
    ["timeout", ["- visionTap:", "    text: Save", "    timeout: 0", "    expect:", "      visibleText: Saved"]],
  ];

  test.each(invalidVisionTaps)("rejects invalid visionTap %s with the command source location", (_field, lines) => {
    expect(() => buildFlowAst(flow(lines))).toThrow(/flows\/checkout\.yaml:3/);
  });
});
