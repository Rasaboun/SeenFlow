#!/usr/bin/env bun
import { pathToFileURL } from "node:url";

import { compileFile } from "./commands/compile.js";
import { testFile } from "./commands/test.js";

export type CliArgs =
  | { command: "compile"; flow: string; output?: string }
  | {
      command: "test";
      flow: string;
      device?: string;
      debug?: boolean;
      repeat?: number;
      minStability?: number;
    };

export function parseArgs(args: string[]): CliArgs {
  const [command, flow, ...flags] = args;
  if ((command !== "compile" && command !== "test") || !flow || flow.startsWith("-")) {
    throw new Error("Usage: seenflow <compile|test> <flow.yaml> [options]");
  }
  const parsed: Record<string, string | number | boolean> = { command, flow };
  for (let index = 0; index < flags.length; index += 1) {
    const flag = flags[index];
    if (flag === "--debug" && command === "test") parsed.debug = true;
    else if (flag === "--output" && command === "compile" && flags[index + 1]) parsed.output = flags[++index];
    else if (flag === "--device" && command === "test" && flags[index + 1]) parsed.device = flags[++index];
    else if (flag === "--repeat" && command === "test" && flags[index + 1]) {
      const repeat = Number(flags[++index]);
      if (!Number.isInteger(repeat) || repeat <= 0) {
        throw new Error("--repeat must be a positive integer");
      }
      parsed.repeat = repeat;
    } else if (flag === "--min-stability" && command === "test" && flags[index + 1]) {
      const minStability = Number(flags[++index]);
      if (!Number.isFinite(minStability) || minStability < 0 || minStability > 1) {
        throw new Error("--min-stability must be between 0 and 1");
      }
      parsed.minStability = minStability;
    }
    else throw new Error(`Unknown or incomplete option: ${flag}`);
  }
  if (
    parsed.minStability !== undefined &&
    (typeof parsed.repeat !== "number" || parsed.repeat <= 1)
  ) {
    throw new Error("--min-stability requires --repeat greater than 1");
  }
  return parsed as unknown as CliArgs;
}

export async function main(args = process.argv.slice(2)): Promise<number> {
  const options = parseArgs(args);
  if (options.command === "compile") {
    const result = await compileFile(options.flow, { output: options.output });
    for (const warning of result.warnings) {
      console.warn(`${warning.location.file}:${warning.location.line}: ${warning.message}`);
    }
    console.log(result.output);
    return 0;
  }
  return testFile(options.flow, options);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then(
    (code) => {
      process.exitCode = code;
    },
    (error: unknown) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    },
  );
}
