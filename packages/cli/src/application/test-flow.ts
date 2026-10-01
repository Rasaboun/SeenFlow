import type { TestFlowPorts } from "./ports.js";

export interface TestFlowRequest {
  source: string;
  output: string;
  artifactsDir: string;
}

export interface TestFlowOptions {
  device?: string;
  debug?: boolean;
  repeat?: number;
  minStability?: number;
}

export async function testFlow(
  request: TestFlowRequest, options: TestFlowOptions, ports: TestFlowPorts,
): Promise<number> {
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

  await ports.validate(request.source);
  const session = await ports.startSession({ debug: options.debug, artifactsDir: request.artifactsDir });
  let removeSignalCleanup: (() => void) | undefined;
  try {
    removeSignalCleanup = ports.installSignalCleanup(session.stop);
    await ports.compile(request.source);
    let passes = 0;
    let singleExitCode = 0;
    for (let attempt = 1; attempt <= repeat; attempt += 1) {
      const runId = ports.createRunId();
      const exitCode = await session.run({
        flow: request.output,
        device: options.device,
        debug: options.debug ?? false,
        runId,
      });
      singleExitCode = exitCode;
      if (exitCode === 0) {
        passes += 1;
        if (!options.debug) await ports.removeArtifacts(runId);
      } else {
        try {
          await session.captureFinal(runId);
        } catch (error) {
          ports.warn(`Seenflow could not capture final diagnostics: ${error instanceof Error ? error.message : String(error)}`);
        }
      }
      if (repeat > 1) ports.log(`Attempt ${attempt}/${repeat}: ${exitCode === 0 ? "PASS" : "FAIL"}`);
    }
    if (repeat === 1) return singleExitCode;
    const stability = passes / repeat;
    ports.log(`Stability: ${passes}/${repeat} passed (${(stability * 100).toFixed(2)}%); required ${(minStability * 100).toFixed(2)}%`);
    return stability >= minStability ? 0 : 1;
  } finally {
    try {
      removeSignalCleanup?.();
    } finally {
      await session.stop();
    }
  }
}
