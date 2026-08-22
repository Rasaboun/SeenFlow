import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

import { compileFlow, type CompilerWarning } from "../../../compiler/src/index.js";

const runtimeFiles = ["assert-visual.js", "find-text.js", "wait-visual.js"];
const runtimeSource = resolve(import.meta.dirname, "../../../runtime");

export interface CompileFileOptions {
  cwd?: string;
  output?: string;
}

export interface CompileFileResult {
  output: string;
  warnings: CompilerWarning[];
}

export async function compileFile(
  flow: string,
  options: CompileFileOptions = {},
): Promise<CompileFileResult> {
  const cwd = options.cwd ?? process.cwd();
  const sourcePath = resolve(cwd, flow);
  const defaultOutput = join(cwd, ".seenflow", "generated", basename(flow));
  const output = options.output
    ? isAbsolute(options.output)
      ? options.output
      : resolve(cwd, options.output)
    : defaultOutput;
  const runtimeDirectory = options.output
    ? join(dirname(output), ".seenflow", "runtime")
    : join(cwd, ".seenflow", "runtime");
  const runtimePath = relative(dirname(output), runtimeDirectory).split(sep).join("/") || ".";
  const result = compileFlow(await readFile(sourcePath, "utf8"), sourcePath, { runtimePath });

  await mkdir(dirname(output), { recursive: true });
  await mkdir(runtimeDirectory, { recursive: true });
  await Promise.all(runtimeFiles.map((file) => copyFile(join(runtimeSource, file), join(runtimeDirectory, file))));
  await writeFile(output, result.yaml);
  return { output, warnings: result.warnings };
}
