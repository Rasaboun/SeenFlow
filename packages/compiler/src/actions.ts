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

export interface MaestroAction {
  kind: "maestro";
  location: SourceLocation;
  value: unknown;
}

export type FlowAction = MaestroAction | VisionTapAction;

export interface FlowAst {
  config: unknown;
  actions: FlowAction[];
}
