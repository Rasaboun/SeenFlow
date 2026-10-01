import { randomUUID } from "node:crypto";
import { readFile, rm } from "node:fs/promises";
import { basename, join, resolve } from "node:path";

import { compileFlow } from "../../../compiler/src/index.js";
import { testFlow, type TestFlowOptions } from "../application/test-flow.js";
import { runMaestro as defaultRunMaestro, type MaestroOptions } from "../maestro.js";
import { startSidecar as defaultStartSidecar, type SidecarHandle, type SidecarOptions } from "../sidecar.js";
import { compileFile } from "./compile.js";

export interface TestFileOptions extends TestFlowOptions {
  cwd?: string;
}

interface Dependencies {
  startSidecar(options: SidecarOptions): Promise<SidecarHandle>;
  runMaestro(options: MaestroOptions): Promise<number>;
}

interface ProcessTarget {
  once(signal: string, listener: () => void): unknown;
  off(signal: string, listener: () => void): unknown;
  exit(code: number): never | void;
}

const defaults: Dependencies = { startSidecar: defaultStartSidecar, runMaestro: defaultRunMaestro };

// Composition root for the test command's process/filesystem adapters.
export async function testFile(
  flow: string, options: TestFileOptions = {}, dependencies: Dependencies = defaults,
): Promise<number> {
  const cwd = options.cwd ?? process.cwd();
  const source = resolve(cwd, flow);
  const output = join(cwd, ".seenflow", "generated", basename(flow));
  const artifactsDir = join(cwd, ".seenflow", "artifacts");
  return testFlow({ source, output, artifactsDir }, options, {
    startSession: async (sessionOptions) => {
      const sidecar = await dependencies.startSidecar(sessionOptions);
      return {
        run: ({ flow, device, debug, runId }) => dependencies.runMaestro({
          flow,
          device,
          env: {
            SEENFLOW_URL: sidecar.url,
            SEENFLOW_TOKEN: sidecar.token,
            SEENFLOW_DEBUG: String(debug),
            SEENFLOW_RUN_ID: runId,
          },
        }),
        captureFinal: (runId) => sidecar.captureFinal(runId),
        stop: () => sidecar.stop(),
      };
    },
    validate: async (path) => { compileFlow(await readFile(path, "utf8"), path); },
    compile: async (path) => { await compileFile(path, { cwd }); },
    removeArtifacts: (runId) => rm(join(artifactsDir, runId), { recursive: true, force: true }),
    createRunId: randomUUID,
    installSignalCleanup,
    log: console.log,
    warn: console.warn,
  });
}

export function installSignalCleanup(
  stop: () => Promise<void>,
  target: ProcessTarget = process,
): () => void {
  const onInterrupt = () => void stop().finally(() => target.exit(130));
  const onTerminate = () => void stop().finally(() => target.exit(143));
  target.once("SIGINT", onInterrupt);
  target.once("SIGTERM", onTerminate);
  return () => {
    target.off("SIGINT", onInterrupt);
    target.off("SIGTERM", onTerminate);
  };
}
