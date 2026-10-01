import type { SourceLocation } from "./flow.js";

export function failAt(location: SourceLocation, message: string): never {
  throw new Error(`${location.file}:${location.line}: ${message}`);
}
