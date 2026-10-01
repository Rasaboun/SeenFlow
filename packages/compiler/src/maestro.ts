import { stringify } from "yaml";
import type { ExecutionPlan, ExecutionStep } from "./execution.js";

export function emitMaestro(plan: ExecutionPlan, runtimePath: string): string {
  const commands = plan.steps.map((step) => emitStep(step, runtimePath));
  return `${stringify(nativeConfig(plan.config)).trimEnd()}\n---\n${stringify(commands)}`;
}

function emitStep(step: ExecutionStep, runtimePath: string): unknown {
  if (step.kind === "native") return step.value;
  if (step.kind === "tapResolved") return { tapOn: { point: "${output.seenflow.tapX}%,${output.seenflow.tapY}%" } };
  const context = { ACTION: step.action, STEP: String(step.step) };
  if (step.kind === "findText") {
    return runScript(runtimePath, "find-text.js", {
      TEXT: step.selector.text,
      MATCH: step.selector.match,
      THRESHOLD: String(step.selector.threshold),
      OCCURRENCE: String(step.selector.occurrence),
      ...(step.spatial ? { SPATIAL: JSON.stringify(step.spatial) } : {}),
      ...(step.precondition ? { PRECONDITION_TEXT: step.precondition.text, PRECONDITION_STATE: step.precondition.state } : {}),
      ...context,
    });
  }
  return runScript(runtimePath, step.kind === "assertVisual" ? "assert-visual.js" : "wait-visual.js", {
    TEXT: step.text,
    STATE: step.state,
    ...(step.kind === "waitVisual" ? { TIMEOUT: String(step.timeout) } : {}),
    ...context,
  });
}

function runScript(runtimePath: string, file: string, env: Record<string, string>) {
  return { runScript: { file: `${runtimePath}/${file}`, env } };
}

function nativeConfig(config: unknown): unknown {
  if (typeof config !== "object" || config === null || Array.isArray(config)) return config;
  const { seenflow: _compilerConfig, ...maestroConfig } = config as Record<string, unknown>;
  return maestroConfig;
}
