import { isSeq, LineCounter, parseAllDocuments, type Node } from "yaml";

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

export function parseFlow(source: string, file: string): ParsedFlow {
  const lineCounter = new LineCounter();
  const documents = parseAllDocuments(source, { lineCounter });
  const yamlError = documents.flatMap((document) => document.errors)[0];

  if (yamlError) {
    throw parseError(file, lineCounter, yamlError.pos[0], yamlError.message);
  }

  if (documents.length !== 2) {
    throw parseError(file, lineCounter, source.length, "Expected a two-document Maestro flow.");
  }

  const [configDocument, commandsDocument] = documents;
  if (!isSeq(commandsDocument.contents)) {
    throw parseError(file, lineCounter, commandsDocument.contents?.range?.[0] ?? commandsDocument.range?.[0] ?? source.length, "Expected the second document to contain a command sequence.");
  }

  const values = commandsDocument.toJS() as unknown[];
  return {
    config: configDocument.toJS(),
    commands: commandsDocument.contents.items.map((node, index) => ({
      value: values[index],
      location: location(file, lineCounter, commandOffset(source, node)),
    })),
  };
}

function commandOffset(source: string, node: Node | null): number {
  const offset = node?.range?.[0] ?? 0;
  const lineStart = source.lastIndexOf("\n", offset - 1) + 1;
  const marker = source.slice(lineStart, offset).match(/^\s*-/);
  return marker ? lineStart + marker[0].length - 1 : offset;
}

function location(file: string, lineCounter: LineCounter, offset: number): SourceLocation {
  const { line, col } = lineCounter.linePos(offset);
  return { file, line: line || 1, column: col || 1 };
}

function parseError(file: string, lineCounter: LineCounter, offset: number, message: string): Error {
  return new Error(`${file}:${location(file, lineCounter, offset).line}: ${message}`);
}
