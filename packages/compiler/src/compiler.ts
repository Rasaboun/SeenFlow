import { stringify } from "yaml";

import type { ExpectedVisualEffect, FlowAction, FlowAst, VisionTapAction } from "./actions.js";
import { failAt } from "./errors.js";
import { parseFlow, type ParsedFlow } from "./parser.js";
import {
  effectsRequired,
  hasExpectedEffect,
  isExpandedTapOn,
  isShorthandTapOn,
  isVisionTap,
  parseTapOn,
  parseVisionTap,
} from "./schema.js";

const shorthandWarning =
  "tapOn action has no expected effect. Use expanded tapOn syntax to make this action transition-safe.";
const defaultRuntimePath = ".seenflow/runtime";

export interface CompileOptions {
  runtimePath?: string;
}

export interface CompileResult {
  yaml: string;
  warnings: FlowAst["warnings"];
}

export function buildFlowAst(parsed: ParsedFlow): FlowAst {
  const warnings: FlowAst["warnings"] = [];
  const requireEffects = effectsRequired(parsed.config);
  return {
    config: parsed.config,
    actions: parsed.commands.map((command) => {
      if (isVisionTap(command)) return parseVisionTap(command);
      if (isExpandedTapOn(command)) {
        if (hasExpectedEffect(command)) return parseTapOn(command);
        if (requireEffects) {
          failAt(
            command.location,
            'tapOn requires an expected effect.\n\nExample:\n\n  expect:\n    visibleText: "Saved"',
          );
        }
      } else if (isShorthandTapOn(command)) {
        warnings.push({ location: command.location, message: shorthandWarning });
      }
      return { kind: "maestro", value: command.value, location: command.location };
    }),
    warnings,
  };
}

export function compileFlow(source: string, file: string, options: CompileOptions = {}): CompileResult {
  const ast = buildFlowAst(parseFlow(source, file));
  const config = nativeConfig(ast.config);
  const runtimePath = options.runtimePath ?? defaultRuntimePath;
  const commands = ast.actions.flatMap((action) => compileAction(action, runtimePath));
  return {
    yaml: `${stringify(config).trimEnd()}\n---\n${stringify(commands)}`,
    warnings: ast.warnings,
  };
}

function compileAction(action: FlowAction, runtimePath: string): unknown[] {
  if (action.kind === "maestro") return [action.value];
  if (action.kind === "tapOn") {
    const description = `tapOn ${JSON.stringify(action.tapOn)}`;
    return transition(action.expect, [{ tapOn: action.tapOn }], 7000, runtimePath, description);
  }
  const description = `visionTap ${JSON.stringify(action.text)}`;
  return transition(
    action.expect,
    visionTap(action, runtimePath, description),
    action.timeout,
    runtimePath,
    description,
  );
}

function visionTap(action: VisionTapAction, runtimePath: string, description: string): unknown[] {
  return [
    runScript(runtimePath, "find-text.js", {
      TEXT: action.text,
      MATCH: action.match,
      THRESHOLD: String(action.threshold),
      OCCURRENCE: String(action.occurrence),
      ACTION: description,
    }),
    { tapOn: { point: "${output.seenflow.tapX}%,${output.seenflow.tapY}%" } },
  ];
}

function transition(
  effect: ExpectedVisualEffect,
  action: unknown[],
  timeout: number,
  runtimePath: string,
  description: string,
): unknown[] {
  const state = effect.kind === "visibleText" ? "visible" : "not-visible";
  return [
    ...(effect.requireTransition
      ? [
          runScript(runtimePath, "assert-visual.js", {
            TEXT: effect.text,
            STATE: inverse(state),
            ACTION: description,
          }),
        ]
      : []),
    ...action,
    runScript(runtimePath, "wait-visual.js", {
      TEXT: effect.text,
      STATE: state,
      TIMEOUT: String(timeout),
      ACTION: description,
    }),
  ];
}

function inverse(state: "not-visible" | "visible") {
  return state === "visible" ? "not-visible" : "visible";
}

function runScript(runtimePath: string, file: string, env: Record<string, string>) {
  return { runScript: { file: `${runtimePath}/${file}`, env } };
}

function nativeConfig(config: unknown): unknown {
  if (typeof config !== "object" || config === null || Array.isArray(config)) return config;
  const { seenflow: _compilerConfig, ...maestroConfig } = config as Record<string, unknown>;
  return maestroConfig;
}
