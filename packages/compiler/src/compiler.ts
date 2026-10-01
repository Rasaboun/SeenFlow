// Composition root: YAML input, pure compiler policy, Maestro/YAML output.
import { compile, type CompileOptions, type CompileResult } from "./application.js";
import { emitMaestro } from "./maestro.js";
import { parseFlow } from "./parser.js";

export { buildFlowAst } from "./ast.js";
export type { CompileOptions, CompileResult } from "./application.js";

export function compileFlow(source: string, file: string, options: CompileOptions = {}): CompileResult {
  return compile(source, file, options, { parse: parseFlow, emit: emitMaestro });
}
