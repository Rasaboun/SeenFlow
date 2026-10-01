import type { FlowAst } from "./actions.js";
import { failAt } from "./errors.js";
import type { ParsedFlow } from "./flow.js";
import {
  effectsRequired,
  hasExpectedEffect,
  hasNativeExpectedEffect,
  isExpandedTapOn,
  isShorthandTapOn,
  isVisionTap,
  nativeEffectCommand,
  parseNativeEffect,
  parseTapOn,
  parseVisionTap,
} from "./schema.js";

const shorthandWarning =
  "tapOn action has no expected effect. Use expanded tapOn syntax to make this action transition-safe.";

export function buildFlowAst(parsed: ParsedFlow): FlowAst {
  const warnings: FlowAst["warnings"] = [];
  const requireEffects = effectsRequired(parsed.config);
  return {
    config: parsed.config,
    actions: parsed.commands.map((command) => {
      if (isVisionTap(command)) return parseVisionTap(command);
      const nativeCommand = nativeEffectCommand(command);
      if (nativeCommand) {
        if (hasNativeExpectedEffect(command, nativeCommand)) {
          return parseNativeEffect(command, nativeCommand);
        }
        warnings.push({
          location: command.location,
          message: `${nativeCommand} action has no expected effect. Add expect to make this action transition-safe.`,
        });
        return { kind: "maestro", value: command.value, location: command.location };
      }
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
