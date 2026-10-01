import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";
import type { TestFlowPorts } from "../src/application/ports.js";

async function application() {
  expect(existsSync(resolve(import.meta.dirname, "../src/application/test-flow.ts")), "Missing CLI application layer").toBe(true);
  return import("../src/application/test-flow.js");
}

function memoryPorts(exitCodes = [0]) {
  const events: string[] = [];
  const retained = new Set<string>();
  const messages: string[] = [];
  let nextId = 0;
  const ports: TestFlowPorts = {
    validate: async () => { events.push("validate"); },
    compile: async () => { events.push("compile"); },
    startSession: async () => {
      events.push("start");
      return {
        run: async ({ runId, flow, debug }) => {
          expect(flow).toBe("compiled");
          expect(debug).toBe(false);
          retained.add(runId);
          events.push(`run:${runId}`);
          return exitCodes.shift() ?? 0;
        },
        captureFinal: async (id) => { events.push(`snapshot:${id}`); },
        stop: async () => { events.push("stop"); },
      };
    },
    removeArtifacts: async (id) => { retained.delete(id); },
    createRunId: () => `run-${++nextId}`,
    installSignalCleanup: () => () => { events.push("remove-signals"); },
    log: (message) => { messages.push(message); },
    warn: (message) => { messages.push(message); },
  };
  return { ports, events, retained, messages };
}

const request = { source: "input", output: "compiled", artifactsDir: "artifacts" };

test("runs sequentially with injected adapters and retains failed attempts", async () => {
  const { testFlow } = await application();
  const memory = memoryPorts([0, 9, 0]);
  const exitCode = await testFlow(request, { repeat: 3, minStability: 0.66 }, memory.ports);
  expect(exitCode).toBe(0);
  expect([...memory.retained]).toEqual(["run-2"]);
  expect(memory.events).toEqual(["validate", "start", "compile", "run:run-1", "run:run-2", "snapshot:run-2", "run:run-3", "remove-signals", "stop"]);
  expect(memory.messages.at(-1)).toContain("2/3 passed");
});

test("stops sidecar and removes signals when compilation fails", async () => {
  const { testFlow } = await application();
  const memory = memoryPorts();
  memory.ports.compile = async () => { throw new Error("write failed"); };
  await expect(testFlow(request, {}, memory.ports)).rejects.toThrow("write failed");
  expect(memory.events).toEqual(["validate", "start", "remove-signals", "stop"]);
});

test("rejects invalid repetitions before starting infrastructure", async () => {
  const { testFlow } = await application();
  const memory = memoryPorts();
  await expect(testFlow(request, { repeat: 0 }, memory.ports)).rejects.toThrow("positive integer");
  expect(memory.events).toEqual([]);
});

test("stops sidecar even if signal registration fails", async () => {
  const { testFlow } = await application();
  const memory = memoryPorts();
  memory.ports.installSignalCleanup = () => { throw new Error("signals failed"); };
  await expect(testFlow(request, {}, memory.ports)).rejects.toThrow("signals failed");
  expect(memory.events).toEqual(["validate", "start", "stop"]);
});

test("stops session even if signal cleanup fails", async () => {
  const { testFlow } = await application();
  const memory = memoryPorts();
  memory.ports.installSignalCleanup = () => () => {
    memory.events.push("remove-signals");
    throw new Error("cleanup failed");
  };
  await expect(testFlow(request, {}, memory.ports)).rejects.toThrow("cleanup failed");
  expect(memory.events.slice(-2)).toEqual(["remove-signals", "stop"]);
});
