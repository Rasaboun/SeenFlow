import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";

async function application() {
  expect(existsSync(resolve(import.meta.dirname, "../src/application.ts")), "Missing compiler application layer").toBe(true);
  return import("../src/application.js");
}

test("compiles transitions through alternate input and output adapters", async () => {
  const { compile } = await application();
  const result = compile("alternate input", "flow.custom", {}, {
    parse: (source, file) => {
      expect(source).toBe("alternate input");
      return {
        config: { appId: "test", seenflow: { requireEffects: true } },
        commands: [{ value: { tapOn: { id: "save", expect: { visibleText: "Saved" } } }, location: { file, line: 3, column: 1 } }],
      };
    },
    emit: (plan, runtimePath) => {
      expect(runtimePath).toBe(".seenflow/runtime");
      expect(plan.steps).toEqual([
        { kind: "assertVisual", text: "Saved", state: "not-visible", action: 'tapOn {"id":"save"}', step: 1 },
        { kind: "native", value: { tapOn: { id: "save" } } },
        { kind: "waitVisual", text: "Saved", state: "visible", timeout: 7000, action: 'tapOn {"id":"save"}', step: 1 },
      ]);
      return "alternate output";
    },
  });
  expect(result).toEqual({ yaml: "alternate output", warnings: [] });
});

test("effect policy rejects invalid input before calling the output adapter", async () => {
  const { compile } = await application();
  expect(() => compile("input", "invalid.flow", {}, {
    parse: () => ({ config: {}, commands: [{ value: { visionTap: { text: "Save" } }, location: { file: "invalid.flow", line: 7, column: 1 } }] }),
    emit: () => { throw new Error("must not emit invalid input"); },
  })).toThrow("invalid.flow:7: visionTap requires an expected effect");
});
