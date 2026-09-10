import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { afterEach, describe, expect, test, vi } from "vitest";
import { parseArgs } from "../src/index.js";
import { compileFile } from "../src/commands/compile.js";
import { installSignalCleanup, testFile } from "../src/commands/test.js";
import { maestroArgs, maestroFailureCode } from "../src/maestro.js";
import { captureFinalDiagnostic } from "../src/sidecar.js";

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
    expect(
      parseArgs(["test", "flow.yaml", "--repeat", "20", "--min-stability", "0.98"]),
    ).toEqual({
      command: "test",
      flow: "flow.yaml",
      repeat: 20,
      minStability: 0.98,
    });
  });

  test.each([
    [["test", "flow.yaml", "--repeat", "0"], /positive integer/],
    [["test", "flow.yaml", "--repeat", "1.5"], /positive integer/],
    [["test", "flow.yaml", "--repeat", "2", "--min-stability", "1.1"], /between 0 and 1/],
    [["test", "flow.yaml", "--min-stability", "0.9"], /requires --repeat greater than 1/],
  ])("rejects invalid stability options", (args, message) => {
    expect(() => parseArgs(args as string[])).toThrow(message);
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
    const captureFinal = vi.fn(async () => {
      events.push("snapshot");
    });
    const startSidecar = vi.fn(async () => {
      events.push("sidecar");
      return { url: "http://127.0.0.1:43210", token: "token-123", captureFinal, stop };
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
    expect(events).toEqual(["sidecar", "maestro", "snapshot", "stop"]);
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
          SEENFLOW_RUN_ID: expect.any(String),
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
          startSidecar: async () => ({
            url: "http://127.0.0.1:1",
            token: "t",
            captureFinal: async () => undefined,
            stop,
          }),
          runMaestro: async () => {
            throw new Error("spawn failed");
          },
        },
      ),
    ).rejects.toThrow("spawn failed");
    expect(stop).toHaveBeenCalledOnce();
  });

  test("repeats sequentially, evaluates stability, and retains only failed attempts", async () => {
    const { directory, source } = await fixture();
    const artifacts = join(directory, ".seenflow", "artifacts");
    const results = [0, 1, 0];
    const captureFinal = vi.fn(async () => undefined);
    const stop = vi.fn(async () => undefined);
    const runMaestro = vi.fn(async ({ env }: { env: Record<string, string> }) => {
      const runDirectory = join(artifacts, env.SEENFLOW_RUN_ID);
      await mkdir(runDirectory, { recursive: true });
      await writeFile(join(runDirectory, "manifest.json"), "{}\n");
      return results.shift() ?? 0;
    });

    const exitCode = await testFile(
      source,
      { cwd: directory, repeat: 3, minStability: 0.66 },
      {
        startSidecar: async () => ({
          url: "http://127.0.0.1:43210",
          token: "token",
          captureFinal,
          stop,
        }),
        runMaestro,
      },
    );

    expect(exitCode).toBe(0);
    expect(runMaestro).toHaveBeenCalledTimes(3);
    const runIds = runMaestro.mock.calls.map(
      ([options]) => (options as { env: Record<string, string> }).env.SEENFLOW_RUN_ID,
    );
    expect(new Set(runIds).size).toBe(3);
    await expect(stat(join(artifacts, runIds[0]))).rejects.toThrow();
    await expect(stat(join(artifacts, runIds[1]))).resolves.toBeTruthy();
    await expect(stat(join(artifacts, runIds[2]))).rejects.toThrow();
    expect(captureFinal).toHaveBeenCalledWith(runIds[1]);
    expect(stop).toHaveBeenCalledOnce();
  });

  test("fails repeated mode below the required stability", async () => {
    const { directory, source } = await fixture();
    const results = [0, 1, 0];

    const exitCode = await testFile(
      source,
      { cwd: directory, repeat: 3, minStability: 0.67 },
      {
        startSidecar: async () => ({
          url: "http://127.0.0.1:43210",
          token: "token",
          captureFinal: async () => undefined,
          stop: async () => undefined,
        }),
        runMaestro: async () => results.shift() ?? 0,
      },
    );

    expect(exitCode).toBe(1);
  });

  test("debug mode retains successful run journals", async () => {
    const { directory, source } = await fixture();
    const artifacts = join(directory, ".seenflow", "artifacts");
    let runId = "";

    expect(
      await testFile(
        source,
        { cwd: directory, debug: true },
        {
          startSidecar: async () => ({
            url: "http://127.0.0.1:43210",
            token: "token",
            captureFinal: async () => undefined,
            stop: async () => undefined,
          }),
          runMaestro: async ({ env }) => {
            runId = env.SEENFLOW_RUN_ID;
            await mkdir(join(artifacts, runId), { recursive: true });
            return 0;
          },
        },
      ),
    ).toBe(0);
    await expect(stat(join(artifacts, runId))).resolves.toBeTruthy();
  });

  test("final diagnostic requests are authenticated and tolerate missing context", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 404 }));

    await expect(
      captureFinalDiagnostic("http://127.0.0.1:43210", "secret", "run-123", fetch),
    ).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:43210/v1/diagnostics/final", {
      method: "POST",
      headers: {
        Authorization: "Bearer secret",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ runId: "run-123" }),
    });
  });

  test("final diagnostic failure never replaces the Maestro result", async () => {
    const { directory, source } = await fixture();
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    const exitCode = await testFile(
      source,
      { cwd: directory },
      {
        startSidecar: async () => ({
          url: "http://127.0.0.1:43210",
          token: "token",
          captureFinal: async () => {
            throw new Error("snapshot failed");
          },
          stop: async () => undefined,
        }),
        runMaestro: async () => 9,
      },
    );

    expect(exitCode).toBe(9);
    expect(warning).toHaveBeenCalledWith(expect.stringContaining("snapshot failed"));
    warning.mockRestore();
  });
});
