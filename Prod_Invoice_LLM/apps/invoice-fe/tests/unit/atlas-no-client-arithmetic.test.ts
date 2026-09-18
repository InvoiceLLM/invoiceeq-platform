// =============================================================================
// FILE: tests/unit/atlas-no-client-arithmetic.test.ts
// FEATURE: FE Feature 23 §2 / §10 — "No arithmetic client-side, ever", asserted
//          grep-shaped over the source of every ATLAS component.
//
// WHY GREP AND NOT A RENDER ASSERTION: a render test proves one payload printed
// correctly. This proves the capability is absent — nobody can add two figures
// on a later Tuesday, because the operator is not in the file and this test
// fails the moment one appears. It is the same shape the spec asks for.
//
// Comments and strings are stripped first: a prose em dash or a URL slash is
// not arithmetic, and a test that cannot tell the difference gets disabled
// rather than fixed.
// =============================================================================

import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..", "..");
const COMPONENT_DIR = path.join(ROOT, "components", "atlas");

const FILES = [
  ...readdirSync(COMPONENT_DIR).map((name) => path.join(COMPONENT_DIR, name)),
  path.join(ROOT, "lib", "atlas.ts"),
];

/** Source with comments and string/template literals removed. */
function code(file: string): string {
  return readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/\/\/[^\n]*/g, " ")
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/'(?:[^'\\]|\\.)*'/g, "''")
    .replace(/`(?:[^`\\]|\\.)*`/g, "``");
}

/**
 * The operators and the helpers that stand in for them.
 *
 * `+` is listed once and covers string concatenation too, deliberately: gluing
 * "1,00,000.00" onto "52,000.00" is not arithmetic, but it is the client
 * composing a figure, which §5.3 forbids for the same reason.
 */
const FORBIDDEN: Array<[string, RegExp]> = [
  ["addition", /[^+]\+[^+]/],
  ["increment or decrement", /(\+\+|--)/],
  ["compound assignment", /[-+*/%]=/],
  ["multiplication", /\*[^/]/],
  ["division", /[^<*/]\/[^/*>]/],
  ["modulo", /\s%\s/],
  ["Math", /\bMath\./],
  ["Number()", /\bNumber\s*\(/],
  ["parseInt / parseFloat", /\bparse(Int|Float)\s*\(/],
  ["toFixed", /\.toFixed\s*\(/],
  ["toLocaleString", /\.toLocaleString\s*\(/],
  ["Intl.NumberFormat", /\bIntl\.NumberFormat\b/],
  ["reduce", /\.reduce\s*\(/],
];

describe("no ATLAS component can compute a number", () => {
  it("has files to check at all", () => {
    // A guard against the silent version of this test passing: a renamed
    // directory would otherwise make it green over nothing.
    expect(FILES.length).toBeGreaterThan(2);
  });

  it.each(FILES)("%s contains no numeric operator", (file) => {
    const source = code(file);
    for (const [name, pattern] of FORBIDDEN) {
      expect(pattern.test(source), `${path.basename(file)} uses ${name}`).toBe(false);
    }
  });
});

describe("no batch control exists anywhere in the feature (D42)", () => {
  it.each(FILES)("%s ships no batch affordance", (file) => {
    const source = readFileSync(file, "utf8");
    // Asserted over the whole source INCLUDING comments and copy: a "select
    // all" label is a batch control even if the logic behind it is absent.
    expect(source).not.toMatch(/type="checkbox"/);
    expect(source).not.toMatch(/select[ -]all/i);
    expect(source).not.toMatch(/approve (all|these)/i);
    expect(source).not.toMatch(/\bbulk\b/i);
  });
});
