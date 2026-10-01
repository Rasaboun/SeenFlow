import type { ExpectedVisualEffect, FlowAction, FlowAst, SpatialConstraint, TextSelector } from "./actions.js";

export interface VisualCondition {
  text: string;
  state: "visible" | "not-visible";
}

interface StepContext {
  action: string;
  step: number;
}

export type ExecutionStep =
  | { kind: "native"; value: unknown }
  | ({ kind: "assertVisual" } & VisualCondition & StepContext)
  | ({ kind: "waitVisual"; timeout: number } & VisualCondition & StepContext)
  | ({ kind: "findText"; selector: TextSelector; spatial?: SpatialConstraint; precondition?: VisualCondition } & StepContext)
  | { kind: "tapResolved" };

export interface ExecutionPlan {
  config: unknown;
  steps: ExecutionStep[];
}

export function planFlow(ast: FlowAst): ExecutionPlan {
  return { config: ast.config, steps: ast.actions.flatMap((action, index) => planAction(action, index + 1)) };
}

function planAction(action: FlowAction, step: number): ExecutionStep[] {
  if (action.kind === "maestro") return [{ kind: "native", value: action.value }];
  if (action.kind === "tapOn") {
    return transition(action.expect, { tapOn: action.tapOn }, `tapOn ${JSON.stringify(action.tapOn)}`, step);
  }
  if (action.kind === "nativeEffect") {
    return transition(action.expect, { [action.command]: action.value }, `${action.command} ${JSON.stringify(action.value)}`, step);
  }
  const description = action.spatial
    ? `visionTap ${JSON.stringify(action.text)} ${action.spatial.relation} ${JSON.stringify(action.spatial.anchor.text)}`
    : `visionTap ${JSON.stringify(action.text)}`;
  const condition = visualCondition(action.expect);
  const context = { action: description, step };
  return [
    {
      kind: "findText",
      selector: { text: action.text, match: action.match, threshold: action.threshold, occurrence: action.occurrence },
      ...(action.spatial ? { spatial: action.spatial } : {}),
      ...(action.expect.requireTransition ? { precondition: inverse(condition) } : {}),
      ...context,
    },
    { kind: "tapResolved" },
    { kind: "waitVisual", ...condition, timeout: action.timeout, ...context },
  ];
}

function transition(effect: ExpectedVisualEffect, native: unknown, action: string, step: number): ExecutionStep[] {
  const condition = visualCondition(effect);
  return [
    ...(effect.requireTransition ? [{ kind: "assertVisual" as const, ...inverse(condition), action, step }] : []),
    { kind: "native", value: native },
    { kind: "waitVisual", ...condition, timeout: 7000, action, step },
  ];
}

function visualCondition(effect: ExpectedVisualEffect): VisualCondition {
  return { text: effect.text, state: effect.kind === "visibleText" ? "visible" : "not-visible" };
}

function inverse(condition: VisualCondition): VisualCondition {
  return { text: condition.text, state: condition.state === "visible" ? "not-visible" : "visible" };
}
