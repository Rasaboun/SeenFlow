import type { SourceLocation } from "./parser.js";

export function failAt(location: SourceLocation, message: string): never {
  throw new Error(`${location.file}:${location.line}: ${message}`);
}
