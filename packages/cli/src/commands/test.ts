import { readFile } from "node:fs/promises";
import { basename, join, resolve } from "node:path";

import { compileFlow } from "../../../compiler/src/index.js";
import { runMaestro as defaultRunMaestro, type MaestroOptions } from "../maestro.js";
import { startSidecar as defaultStartSidecar, type SidecarHandle } from "../sidecar.js";
import { compileFile } from "./compile.js";

export interface TestFileOptions {
  cwd?: string;
  device?: string;
  debug?: boolean;
}

interface Dependencies {
  startSidecar(options: { debug?: boolean }): Promise<SidecarHandle>;
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
  const output = join(cwd, ".maestro-vision", "generated", basename(flow));

  compileFlow(await readFile(source, "utf8"), source);
  const sidecar = await dependencies.startSidecar({ debug: options.debug });
  const removeSignalCleanup = installSignalCleanup(sidecar.stop);
  try {
    await compileFile(source, { cwd });
    return await dependencies.runMaestro({
      flow: output,
      device: options.device,
      env: {
        MAESTRO_VISION_URL: sidecar.url,
        MAESTRO_VISION_TOKEN: sidecar.token,
        MAESTRO_VISION_DEBUG: String(options.debug ?? false),
      },
    });
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
