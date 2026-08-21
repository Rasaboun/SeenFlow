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
  const child = spawn("maestro", maestroArgs(options), { stdio: "inherit" });
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code) => resolve(code ?? 1));
  });
}
