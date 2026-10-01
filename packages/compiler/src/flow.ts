export interface SourceLocation {
  file: string;
  line: number;
  column: number;
}

export interface ParsedCommand {
  value: unknown;
  location: SourceLocation;
}

export interface ParsedFlow {
  config: unknown;
  commands: ParsedCommand[];
}
