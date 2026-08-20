import type { FlowAst } from "./actions.js";
import type { ParsedFlow } from "./parser.js";
import { isVisionTap, parseVisionTap } from "./schema.js";

export function buildFlowAst(parsed: ParsedFlow): FlowAst {
  return {
    config: parsed.config,
    actions: parsed.commands.map((command) =>
      isVisionTap(command)
        ? parseVisionTap(command)
        : { kind: "maestro", value: command.value, location: command.location },
    ),
  };
}
