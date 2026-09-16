/**
 * FE Feature 22 Task 22.9 — the LLM-authored Actionable Insights panel is retired.
 *
 * A source scan, because the property is "nothing references it", which no render
 * test can prove: a stale import, a proxy route, or a tab still pointing at the
 * endpoint would each keep BE 33.18's `/dashboard/insights` alive.
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(__dirname, "../..");
const SCANNED = ["app", "components", "hooks", "lib"];

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(entry.name) ? [full] : [];
  });
}

const files = SCANNED.flatMap((dir) => sourceFiles(path.join(ROOT, dir)));

describe("Actionable Insights panel retired (22.9)", () => {
  it("scans a real source tree", () => {
    expect(files.length).toBeGreaterThan(100);
  });

  it.each([
    ["the panel component (import or JSX)", /from\s+["'][^"']*ActionableInsightsPanel|<ActionableInsightsPanel\b/],
    ["the insights proxy path", /["'`]\/(api\/)?dashboard\/insights/],
  ])("no source file references %s", (_label, pattern) => {
    const offenders = files.filter((file) => pattern.test(fs.readFileSync(file, "utf8")));
    expect(offenders.map((file) => path.relative(ROOT, file))).toEqual([]);
  });

  it("the dashboard no longer offers an Insights tab", () => {
    const page = fs.readFileSync(path.join(ROOT, "app/dashboard/page.tsx"), "utf8");
    expect(page).not.toMatch(/id:\s*"insights"/);
  });
});
