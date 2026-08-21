import type { SourceLocation } from "./parser.js";

export type MatchMode = "exact" | "contains" | "fuzzy";

export interface ExpectedVisualEffect {
  kind: "visibleText" | "notVisibleText";
  text: string;
  requireTransition: boolean;
}

export interface VisionTapAction {
  kind: "visionTap";
  location: SourceLocation;
  text: string;
  match: MatchMode;
  threshold: number;
  occurrence: number;
  timeout: number;
  expect: ExpectedVisualEffect;
}

export interface TapOnAction {
  kind: "tapOn";
  location: SourceLocation;
  tapOn: Record<string, unknown>;
  expect: ExpectedVisualEffect;
}

export interface MaestroAction {
  kind: "maestro";
  location: SourceLocation;
  value: unknown;
}

export type FlowAction = MaestroAction | TapOnAction | VisionTapAction;

export interface CompilerWarning {
  location: SourceLocation;
  message: string;
}

export interface FlowAst {
  config: unknown;
  actions: FlowAction[];
  warnings: CompilerWarning[];
}
