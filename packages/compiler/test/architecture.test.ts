import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import ts from "typescript";
import { expect, test } from "vitest";

const compiler = resolve(import.meta.dirname, "../src");
const cli = resolve(import.meta.dirname, "../../cli/src/application");
const adapters = new Set(["compiler.ts", "parser.ts", "maestro.ts", "index.ts"]);

function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? files(join(directory, entry.name)) : entry.name.endsWith(".ts") ? [join(directory, entry.name)] : [],
  );
}

test("compiler and CLI inner layers cannot import infrastructure", () => {
  const violations: string[] = [];
  const coreFiles = files(compiler).filter((file) => !adapters.has(file.slice(compiler.length + 1)));
  expect(coreFiles.some((file) => file.endsWith("application.ts"))).toBe(true);
  expect(files(cli).some((file) => file.endsWith("test-flow.ts"))).toBe(true);
  const allowedCompiler = new Set(coreFiles);
  for (const file of [...coreFiles, ...files(cli)]) {
    const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true);
    function visit(node: ts.Node) {
      const module = (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) ? node.moduleSpecifier
        : ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || node.expression.getText(source) === "require") ? node.arguments[0] : undefined;
      if (module && ts.isStringLiteral(module)) {
        const target = resolve(dirname(file), module.text.replace(/\.js$/, ".ts"));
        const allowed = module.text.startsWith(".") && (file.startsWith(cli)
          ? target.startsWith(`${cli}/`) : allowedCompiler.has(target));
        if (!allowed) violations.push(`${file}: ${module.text}`);
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  expect(violations, "Dependencies must point inward").toEqual([]);
});
