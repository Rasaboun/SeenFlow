import { randomUUID } from "node:crypto";
import { readFile, rm } from "node:fs/promises";
import { basename, join, resolve } from "node:path";

import { compileFlow } from "../../../compiler/src/index.js";
import { runMaestro as defaultRunMaestro, type MaestroOptions } from "../maestro.js";
import {
  startSidecar as defaultStartSidecar,
  type SidecarHandle,
  type SidecarOptions,
} from "../sidecar.js";
import { compileFile } from "./compile.js";

export interface TestFileOptions {
  cwd?: string;
  device?: string;
  debug?: boolean;
  repeat?: number;
  minStability?: number;
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

export async function testFile(
  flow: string,
  options: TestFileOptions = {},
  dependencies: Dependencies = defaults,
): Promise<number> {
  const cwd = options.cwd ?? process.cwd();
  const source = resolve(cwd, flow);
  const output = join(cwd, ".seenflow", "generated", basename(flow));
  const artifactsDir = join(cwd, ".seenflow", "artifacts");
  const repeat = options.repeat ?? 1;
  const minStability = options.minStability ?? 1;
  if (!Number.isInteger(repeat) || repeat <= 0) {
    throw new Error("repeat must be a positive integer");
  }
  if (!Number.isFinite(minStability) || minStability < 0 || minStability > 1) {
    throw new Error("minStability must be between 0 and 1");
  }
  if (options.minStability !== undefined && repeat <= 1) {
    throw new Error("minStability requires repeat greater than 1");
  }

  compileFlow(await readFile(source, "utf8"), source);
  const sidecar = await dependencies.startSidecar({
    debug: options.debug,
    artifactsDir,
  });
  const removeSignalCleanup = installSignalCleanup(sidecar.stop);
  try {
    await compileFile(source, { cwd });
    let passes = 0;
    let singleExitCode = 0;
    for (let attempt = 1; attempt <= repeat; attempt += 1) {
      const runId = randomUUID();
      const exitCode = await dependencies.runMaestro({
        flow: output,
        device: options.device,
        env: {
          SEENFLOW_URL: sidecar.url,
          SEENFLOW_TOKEN: sidecar.token,
          SEENFLOW_DEBUG: String(options.debug ?? false),
          SEENFLOW_RUN_ID: runId,
        },
      });
      singleExitCode = exitCode;
      if (exitCode === 0) {
        passes += 1;
        if (!options.debug) {
          await rm(join(artifactsDir, runId), { recursive: true, force: true });
        }
      } else {
        try {
          await sidecar.captureFinal(runId);
        } catch (error) {
          console.warn(
            `Seenflow could not capture final diagnostics: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
      }
      if (repeat > 1) {
        console.log(`Attempt ${attempt}/${repeat}: ${exitCode === 0 ? "PASS" : "FAIL"}`);
      }
    }
    if (repeat === 1) return singleExitCode;
    const stability = passes / repeat;
    console.log(
      `Stability: ${passes}/${repeat} passed (${(stability * 100).toFixed(2)}%); required ${(minStability * 100).toFixed(2)}%`,
    );
    return stability >= minStability ? 0 : 1;
  } finally {
    removeSignalCleanup();
    await sidecar.stop();
  }
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
