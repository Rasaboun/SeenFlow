import { describe, expect, test } from "vitest";

import { buildFlowAst, parseFlow } from "../src/index.js";

function flow(lines: string[]) {
  return parseFlow(["appId: com.example.app", "---", ...lines, ""].join("\n"), "flows/checkout.yaml");
}

function flowWithConfig(config: string[], lines: string[]) {
  return parseFlow([...config, "---", ...lines, ""].join("\n"), "flows/checkout.yaml");
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

  test("normalizes a spatial anchor selector", () => {
    const ast = buildFlowAst(
      flow([
        "- visionTap:",
        "    text: Edit",
        "    rightOf:",
        "      text: Chicken Curry",
        "      match: fuzzy",
        "      threshold: 0.88",
        "      occurrence: 1",
        "      maxDistance: 20",
        "    expect:",
        "      visibleText: Edit recipe",
      ]),
    );

    expect(ast.actions[0]).toMatchObject({
      kind: "visionTap",
      spatial: {
        relation: "rightOf",
        anchor: {
          text: "Chicken Curry",
          match: "fuzzy",
          threshold: 0.88,
          occurrence: 1,
        },
        maxDistance: 20,
      },
    });
  });

  test.each([
    [
      "multiple relationships",
      [
        "    near:",
        "      text: Chicken Curry",
        "      maxDistance: 20",
        "    above:",
        "      text: Chicken Curry",
        "      maxDistance: 20",
      ],
    ],
    ["blank anchor text", ["    near:", '      text: ""', "      maxDistance: 20"]],
    ["anchor match", ["    near:", "      text: Chicken Curry", "      match: nearby", "      maxDistance: 20"]],
    ["anchor threshold", ["    near:", "      text: Chicken Curry", "      threshold: 1.1", "      maxDistance: 20"]],
    ["anchor occurrence", ["    near:", "      text: Chicken Curry", "      occurrence: -1", "      maxDistance: 20"]],
    ["fractional anchor occurrence", ["    near:", "      text: Chicken Curry", "      occurrence: 1.5", "      maxDistance: 20"]],
    ["unknown anchor option", ["    near:", "      text: Chicken Curry", "      maxDistance: 20", "      color: red"]],
    ["missing maxDistance", ["    near:", "      text: Chicken Curry"]],
    ["zero maxDistance", ["    near:", "      text: Chicken Curry", "      maxDistance: 0"]],
    ["large maxDistance", ["    near:", "      text: Chicken Curry", "      maxDistance: 101"]],
  ])("rejects invalid spatial selector: %s", (_name, spatial) => {
    expect(() =>
      buildFlowAst(
        flow([
          "- visionTap:",
          "    text: Edit",
          ...spatial,
          "    expect:",
          "      visibleText: Edit recipe",
        ]),
      ),
    ).toThrow(/flows\/checkout\.yaml:3/);
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

  test("explains how to add a missing visionTap effect", () => {
    expect(() => buildFlowAst(flow(["- visionTap:", "    text: Save"]))).toThrow(
      /visionTap requires an expected effect[\s\S]*expect:[\s\S]*visibleText: "Saved"/,
    );
  });

  test("extracts tapOn expect while preserving every native property", () => {
    const ast = buildFlowAst(
      flow([
        "- tapOn:",
        "    id: save-button",
        "    retryTapIfNoChange: true",
        "    expect:",
        "      visibleText: Saved",
      ]),
    );

    expect(ast.actions[0]).toEqual({
      kind: "tapOn",
      tapOn: { id: "save-button", retryTapIfNoChange: true },
      expect: { kind: "visibleText", text: "Saved", requireTransition: true },
      location: { file: "flows/checkout.yaml", line: 3, column: 1 },
    });
  });

  test("supports tapOn notVisibleText without transition enforcement", () => {
    const ast = buildFlowAst(
      flow([
        "- tapOn:",
        "    text: Close",
        "    expect:",
        "      notVisibleText: Loading...",
        "      requireTransition: false",
      ]),
    );

    expect(ast.actions[0]).toMatchObject({
      kind: "tapOn",
      tapOn: { text: "Close" },
      expect: { kind: "notVisibleText", text: "Loading...", requireTransition: false },
    });
  });

  test("rejects expanded tapOn without expect in strict mode", () => {
    expect(() => buildFlowAst(flow(["- tapOn:", "    text: Save"]))).toThrow(
      /flows\/checkout\.yaml:3: tapOn requires an expected effect/,
    );
  });

  test("passes expanded tapOn without expect through when effects are optional", () => {
    const parsed = flowWithConfig(
      ["appId: com.example.app", "seenflow:", "  requireEffects: false"],
      ["- tapOn:", "    text: Save"],
    );

    const ast = buildFlowAst(parsed);
    expect(ast.actions[0]).toMatchObject({
      kind: "maestro",
      value: { tapOn: { text: "Save" } },
    });
    expect(ast.warnings).toEqual([]);
  });

  test("keeps shorthand tapOn compatible and emits its transition warning", () => {
    const ast = buildFlowAst(flow(['- tapOn: "Save"']));

    expect(ast.actions[0]).toMatchObject({ kind: "maestro", value: { tapOn: "Save" } });
    expect(ast.warnings).toEqual([
      {
        location: { file: "flows/checkout.yaml", line: 3, column: 1 },
        message:
          "tapOn action has no expected effect. Use expanded tapOn syntax to make this action transition-safe.",
      },
    ]);
  });

  test("rejects invalid tapOn effects with the command source location", () => {
    expect(() =>
      buildFlowAst(
        flow([
          "- tapOn:",
          "    text: Save",
          "    expect:",
          "      visibleText: Saved",
          "      requireTransition: null",
        ]),
      ),
    ).toThrow(/flows\/checkout\.yaml:3: tapOn\.expect\.requireTransition must be a boolean/);
  });

  test("extracts swipe expect while preserving native gesture properties", () => {
    const ast = buildFlowAst(
      flow([
        "- swipe:",
        "    direction: UP",
        "    waitToSettleTimeoutMs: 500",
        "    expect:",
        "      visibleText: Orders",
      ]),
    );

    expect(ast.actions[0]).toEqual({
      kind: "nativeEffect",
      command: "swipe",
      value: { direction: "UP", waitToSettleTimeoutMs: 500 },
      expect: { kind: "visibleText", text: "Orders", requireTransition: true },
      location: { file: "flows/checkout.yaml", line: 3, column: 1 },
    });
  });

  test("extracts longPressOn expect while preserving native selector properties", () => {
    const ast = buildFlowAst(
      flow([
        "- longPressOn:",
        "    id: product-card",
        "    point: 50%,50%",
        "    expect:",
        "      notVisibleText: Closed",
      ]),
    );

    expect(ast.actions[0]).toMatchObject({
      kind: "nativeEffect",
      command: "longPressOn",
      value: { id: "product-card", point: "50%,50%" },
      expect: { kind: "notVisibleText", text: "Closed", requireTransition: true },
    });
  });

  test.each([
    ["swipe", ["- swipe:", "    direction: UP"]],
    ["longPressOn", ['- longPressOn: "Product"']],
  ])("keeps effectless %s compatible and warns", (command, lines) => {
    const ast = buildFlowAst(flow(lines));

    expect(ast.actions[0]).toMatchObject({ kind: "maestro" });
    expect(ast.warnings).toEqual([
      {
        location: { file: "flows/checkout.yaml", line: 3, column: 1 },
        message: `${command} action has no expected effect. Add expect to make this action transition-safe.`,
      },
    ]);
  });

  test("rejects invalid native gesture effects at the command source", () => {
    expect(() =>
      buildFlowAst(
        flow([
          "- swipe:",
          "    direction: UP",
          "    expect:",
          "      visibleText: Orders",
          "      requireTransition: null",
        ]),
      ),
    ).toThrow(/flows\/checkout\.yaml:3: swipe\.expect\.requireTransition must be a boolean/);
  });
});
