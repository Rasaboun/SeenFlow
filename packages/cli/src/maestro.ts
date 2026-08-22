import { spawn } from "node:child_process";

export interface MaestroOptions {
  flow: string;
  device?: string;
  env: Record<string, string>;
}

export function maestroArgs(options: MaestroOptions): string[] {
  return [
    ...(options.device ? ["--device", options.device] : []),
    "test",
    ...Object.entries(options.env).flatMap(([key, value]) => ["-e", `${key}=${value}`]),
    options.flow,
  ];
}

export function runMaestro(options: MaestroOptions): Promise<number> {
  const child = spawn("maestro", maestroArgs(options), { stdio: ["inherit", "pipe", "pipe"] });
  // ponytail: one flow's logs stay in memory; use a rolling marker scan if logs become huge.
  const output: Buffer[] = [];
  child.stdout.on("data", (chunk: Buffer) => {
    output.push(chunk);
    process.stdout.write(chunk);
  });
  child.stderr.on("data", (chunk: Buffer) => {
    output.push(chunk);
    process.stderr.write(chunk);
  });
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code) => {
      const exitCode = code ?? 1;
      const failure = maestroFailureCode(exitCode, Buffer.concat(output).toString());
      if (failure) {
        console.error(
          `\n${failure}\nOfficial Maestro failed while executing the generated flow. See its output above.`,
        );
      }
      resolve(exitCode);
    });
  });
}

const classifiedFailures =
  /PRECONDITION_FAILED|ACTION_TARGET_NOT_FOUND|ACTION_EXECUTION_FAILED|POSTCONDITION_TIMEOUT|OCR_CAPTURE_FAILED|OCR_RUNTIME_FAILED/;

export function maestroFailureCode(
  exitCode: number,
  output: string,
): "ACTION_EXECUTION_FAILED" | undefined {
  return exitCode !== 0 && !classifiedFailures.test(output) ? "ACTION_EXECUTION_FAILED" : undefined;
}
