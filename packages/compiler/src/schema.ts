import type {
  ExpectedVisualEffect,
  MatchMode,
  NativeEffectAction,
  TapOnAction,
  VisionTapAction,
} from "./actions.js";
import { failAt } from "./errors.js";
import type { ParsedCommand, SourceLocation } from "./parser.js";

const matchModes = new Set<MatchMode>(["exact", "contains", "fuzzy"]);
const effectKeys = ["visibleText", "notVisibleText"] as const;
const nativeEffectCommands = ["swipe", "longPressOn"] as const;
type NativeEffectCommand = (typeof nativeEffectCommands)[number];

export function effectsRequired(config: unknown): boolean {
  return !(
    isRecord(config) &&
    isRecord(config.seenflow) &&
    config.seenflow.requireEffects === false
  );
}

export function isVisionTap(command: ParsedCommand): boolean {
  return isRecord(command.value) && Object.hasOwn(command.value, "visionTap");
}

export function parseVisionTap(command: ParsedCommand): VisionTapAction {
  if (!isRecord(command.value) || !isRecord(command.value.visionTap)) {
    failAt(command.location, "visionTap must be an object.");
  }

  const input = command.value.visionTap;
  if (!Object.hasOwn(input, "expect")) {
    failAt(
      command.location,
      'visionTap requires an expected effect.\n\nExample:\n\n  expect:\n    visibleText: "Saved"',
    );
  }
  return {
    kind: "visionTap",
    location: command.location,
    text: requiredText(input.text, command.location, "visionTap.text"),
    match: match(input.match, command.location),
    threshold: threshold(input.threshold, command.location),
    occurrence: occurrence(input.occurrence, command.location),
    timeout: timeout(input.timeout, command.location),
    expect: effect(input.expect, command.location, "visionTap"),
  };
}

export function isExpandedTapOn(command: ParsedCommand): boolean {
  return isRecord(command.value) && isRecord(command.value.tapOn);
}

export function isShorthandTapOn(command: ParsedCommand): boolean {
  return isRecord(command.value) && typeof command.value.tapOn === "string";
}

export function parseTapOn(command: ParsedCommand): TapOnAction {
  if (!isRecord(command.value) || !isRecord(command.value.tapOn)) {
    failAt(command.location, "tapOn must be an object.");
  }

  const { expect, ...tapOn } = command.value.tapOn;
  return {
    kind: "tapOn",
    location: command.location,
    tapOn,
    expect: effect(expect, command.location, "tapOn"),
  };
}

export function hasExpectedEffect(command: ParsedCommand): boolean {
  return isRecord(command.value) && isRecord(command.value.tapOn) && Object.hasOwn(command.value.tapOn, "expect");
}

export function nativeEffectCommand(command: ParsedCommand): NativeEffectCommand | undefined {
  if (!isRecord(command.value)) return undefined;
  return nativeEffectCommands.find((name) => Object.hasOwn(command.value as object, name));
}

export function hasNativeExpectedEffect(
  command: ParsedCommand,
  name: NativeEffectCommand,
): boolean {
  return (
    isRecord(command.value) &&
    isRecord(command.value[name]) &&
    Object.hasOwn(command.value[name], "expect")
  );
}

export function parseNativeEffect(
  command: ParsedCommand,
  name: NativeEffectCommand,
): NativeEffectAction {
  if (!isRecord(command.value) || !isRecord(command.value[name])) {
    failAt(command.location, `${name} must be an object to use expect.`);
  }
  const { expect, ...value } = command.value[name];
  return {
    kind: "nativeEffect",
    location: command.location,
    command: name,
    value,
    expect: effect(expect, command.location, name),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredText(value: unknown, location: SourceLocation, name: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    failAt(location, `${name} must be a non-empty string.`);
  }
  return value;
}

function match(value: unknown, location: SourceLocation): MatchMode {
  if (value === undefined) return "exact";
  if (typeof value !== "string" || !matchModes.has(value as MatchMode)) {
    failAt(location, "visionTap.match must be exact, contains, or fuzzy.");
  }
  return value as MatchMode;
}

function threshold(value: unknown, location: SourceLocation): number {
  if (value === undefined) return 0.85;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    failAt(location, "visionTap.threshold must be a number between 0 and 1.");
  }
  return value;
}

function occurrence(value: unknown, location: SourceLocation): number {
  if (value === undefined) return 0;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    failAt(location, "visionTap.occurrence must be a non-negative integer.");
  }
  return value;
}

function timeout(value: unknown, location: SourceLocation): number {
  if (value === undefined) return 7000;
  if (typeof value !== "number" || !Number.isInteger(value) || value <= 0) {
    failAt(location, "visionTap.timeout must be a positive integer.");
  }
  return value;
}

function effect(
  value: unknown,
  location: SourceLocation,
  action: "tapOn" | "visionTap" | NativeEffectCommand,
): ExpectedVisualEffect {
  if (!isRecord(value)) failAt(location, `${action}.expect must be an object.`);

  const selected = effectKeys.filter((key) => value[key] !== undefined);
  if (selected.length !== 1 || Object.keys(value).some((key) => !effectKeys.includes(key as (typeof effectKeys)[number]) && key !== "requireTransition")) {
    failAt(location, `${action}.expect must contain exactly one supported effect.`);
  }

  const kind = selected[0];
  const requireTransition = value.requireTransition === undefined ? true : value.requireTransition;
  if (typeof requireTransition !== "boolean") {
    failAt(location, `${action}.expect.requireTransition must be a boolean.`);
  }
  return {
    kind,
    text: requiredText(value[kind], location, `${action}.expect.${kind}`),
    requireTransition,
  };
}
