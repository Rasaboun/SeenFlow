import type { FlowAst } from "./actions.js";
import { buildFlowAst } from "./ast.js";
import { planFlow, type ExecutionPlan } from "./execution.js";
import type { ParsedFlow } from "./flow.js";

export interface CompileOptions {
  runtimePath?: string;
}

export interface CompileResult {
  yaml: string;
  warnings: FlowAst["warnings"];
}

export interface CompilerPorts {
  parse(source: string, file: string): ParsedFlow;
  emit(plan: ExecutionPlan, runtimePath: string): string;
}

export function compile(source: string, file: string, options: CompileOptions, ports: CompilerPorts): CompileResult {
  const ast = buildFlowAst(ports.parse(source, file));
  return {
    yaml: ports.emit(planFlow(ast), options.runtimePath ?? ".seenflow/runtime"),
    warnings: ast.warnings,
  };
}
