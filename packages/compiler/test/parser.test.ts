import { describe, expect, test } from "vitest";

import { parseFlow } from "../src/index.js";

describe("parseFlow", () => {
  test("passes standard Maestro commands through unchanged", () => {
    const flow = parseFlow(
      `appId: com.example.app
---
- launchApp
- tapOn: "Login"
- inputText: "hello"
- swipe:
    direction: UP
`,
      "flows/login.yaml",
    );

    expect(flow.config).toEqual({ appId: "com.example.app" });
    expect(flow.commands.map(({ value }) => value)).toEqual([
      "launchApp",
      { tapOn: "Login" },
      { inputText: "hello" },
      { swipe: { direction: "UP" } },
    ]);
  });

  test("passes unknown command values through unchanged", () => {
    const flow = parseFlow(
      `appId: com.example.app
---
- futureCommand:
    nested:
      - keep: true
      - values: [1, null, { anything: "goes" }]
`,
      "flows/future.yaml",
    );

    expect(flow.commands[0]?.value).toEqual({
      futureCommand: {
        nested: [{ keep: true }, { values: [1, null, { anything: "goes" }] }],
      },
    });
  });

  test("retains each command source location", () => {
    const flow = parseFlow(
      `appId: com.example.app
---
- launchApp
- tapOn: "Login"
`,
      "flows/login.yaml",
    );

    expect(flow.commands.map(({ location }) => location)).toEqual([
      { file: "flows/login.yaml", line: 3, column: 1 },
      { file: "flows/login.yaml", line: 4, column: 1 },
    ]);
  });

  test("reports malformed YAML with its filename and line", () => {
    expect(() =>
      parseFlow("appId: com.example.app\n---\n- tapOn: [\n", "flows/bad.yaml"),
    ).toThrow(/flows\/bad\.yaml:4/);
  });

  test("reports an invalid two-document shape with its filename and line", () => {
    expect(() =>
      parseFlow("appId: com.example.app\n---\ntapOn: Login\n", "flows/bad.yaml"),
    ).toThrow(/flows\/bad\.yaml:3/);
  });
});
