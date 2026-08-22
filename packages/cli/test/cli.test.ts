import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { afterEach, describe, expect, test, vi } from "vitest";
import { parseArgs } from "../src/index.js";
import { compileFile } from "../src/commands/compile.js";
import { installSignalCleanup, testFile } from "../src/commands/test.js";
import { maestroArgs, maestroFailureCode } from "../src/maestro.js";

const temporary: string[] = [];

async function fixture() {
  const directory = await mkdtemp(join(tmpdir(), "seenflow-cli-"));
  temporary.push(directory);
  const source = join(directory, "flow.yaml");
  await writeFile(
    source,
    [
      "appId: com.example.app",
      "---",
      "- visionTap:",
      "    text: Continue",
      "    expect:",
      "      visibleText: Welcome",
      "",
    ].join("\n"),
  );
  return { directory, source };
}

afterEach(async () => {
  for (const directory of temporary.splice(0)) {
    await rm(directory, { recursive: true, force: true });
  }
});

describe("CLI", () => {
  test("exposes the repository CLI as seenflow", async () => {
    const manifest = JSON.parse(
      await readFile(resolve(import.meta.dirname, "../../../package.json"), "utf8"),
    );

    expect(manifest.bin).toEqual({ seenflow: "packages/cli/src/index.ts" });
  });

  test("parses supported compile and test flags", () => {
    expect(parseArgs(["compile", "flow.yaml", "--output", "/tmp/out.yaml"])).toEqual({
      command: "compile",
      flow: "flow.yaml",
      output: "/tmp/out.yaml",
    });
    expect(parseArgs(["test", "flow.yaml", "--device", "ABC-123", "--debug"])).toEqual({
      command: "test",
      flow: "flow.yaml",
      device: "ABC-123",
      debug: true,
    });
  });

  test("places Maestro device targeting before the test command", () => {
    expect(
      maestroArgs({
        flow: "generated.yaml",
        device: "ABC-123",
        env: { SEENFLOW_TOKEN: "secret" },
      }),
    ).toEqual([
      "--device",
      "ABC-123",
      "test",
      "-e",
      "SEENFLOW_TOKEN=secret",
      "generated.yaml",
    ]);
  });

  test("classifies only otherwise-unclassified Maestro failures as action execution errors", () => {
    expect(maestroFailureCode(0, "")).toBeUndefined();
    expect(maestroFailureCode(1, "PRECONDITION_FAILED\n...")).toBeUndefined();
    expect(maestroFailureCode(1, "Element not found")).toBe("ACTION_EXECUTION_FAILED");
  });

  test("terminates the sidecar on SIGINT", async () => {
    const listeners = new Map<string, () => void>();
    const stop = vi.fn(async () => undefined);
    const exit = vi.fn();
    const processTarget = {
      once: (signal: string, listener: () => void) => listeners.set(signal, listener),
      off: (signal: string) => listeners.delete(signal),
      exit,
    };
    const remove = installSignalCleanup(stop, processTarget);

    listeners.get("SIGINT")?.();
    await vi.waitFor(() => expect(stop).toHaveBeenCalledOnce());
    expect(exit).toHaveBeenCalledWith(130);
    remove();
  });

  test("compile writes official YAML and copies runtime beside the generated workspace", async () => {
    const { directory, source } = await fixture();
    const output = join(directory, ".seenflow", "generated", "flow.yaml");

    const result = await compileFile(source, { cwd: directory });

    expect(result.output).toBe(output);
    expect(await readFile(output, "utf8")).not.toContain("- visionTap:");
    expect(await readFile(output, "utf8")).toContain("../runtime/find-text.js");
    await expect(stat(join(directory, ".seenflow", "runtime", "find-text.js"))).resolves.toBeTruthy();
  });

  test("test starts sidecar, compiles, forwards the exact Maestro exit code, and stops", async () => {
    const { directory, source } = await fixture();
    const events: string[] = [];
    const stop = vi.fn(async () => {
      events.push("stop");
    });
    const startSidecar = vi.fn(async () => {
      events.push("sidecar");
      return { url: "http://127.0.0.1:43210", token: "token-123", stop };
    });
    const runMaestro = vi.fn(async () => {
      events.push("maestro");
      return 17;
    });

    const exitCode = await testFile(
      source,
      { device: "ABC-123", debug: true, cwd: directory },
      { startSidecar, runMaestro },
    );

    expect(exitCode).toBe(17);
    expect(events).toEqual(["sidecar", "maestro", "stop"]);
    expect(startSidecar).toHaveBeenCalledWith({
      debug: true,
      artifactsDir: join(directory, ".seenflow", "artifacts"),
    });
    expect(runMaestro).toHaveBeenCalledWith(
      expect.objectContaining({
        flow: join(directory, ".seenflow", "generated", "flow.yaml"),
        device: "ABC-123",
        env: {
          SEENFLOW_URL: "http://127.0.0.1:43210",
          SEENFLOW_TOKEN: "token-123",
          SEENFLOW_DEBUG: "true",
        },
      }),
    );
  });

  test("test stops the sidecar when Maestro execution fails", async () => {
    const { directory, source } = await fixture();
    const stop = vi.fn(async () => undefined);

    await expect(
      testFile(
        source,
        { cwd: directory },
        {
          startSidecar: async () => ({ url: "http://127.0.0.1:1", token: "t", stop }),
          runMaestro: async () => {
            throw new Error("spawn failed");
          },
        },
      ),
    ).rejects.toThrow("spawn failed");
    expect(stop).toHaveBeenCalledOnce();
  });
});
