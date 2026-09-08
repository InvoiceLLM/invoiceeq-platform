// =============================================================================
// FILE: vitest.config.mts
// FEATURE: FE Feature 21 — Business Intelligence bubble (task 21.1).
//
// WHY THIS EXISTS: until this feature, invoice-fe had NO unit-test harness at
// all — `lib/chatAttachments.ts`'s own header records that, and Feature 26 had
// to prove pure-TS helpers through a Playwright spec because a `.tsx` component
// cannot be rendered inside Playwright's babel transform. Feature 21's
// verification plan asks for a byte-identical render snapshot of a message
// WITHOUT insights, which is only provable by rendering the component. Vitest +
// jsdom + Testing Library is the smallest harness that does that, and it runs
// beside the existing Playwright suite rather than replacing it.
//
// `.mts`, not `.ts`: package.json has no `"type": "module"`, so Vite would
// `require()` this file and `@vitejs/plugin-react` is ESM-only.
//
// `e2e/**` is excluded on purpose: those are Playwright specs and would fail
// under Vitest's runner.
// =============================================================================
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  // tsconfig.json sets `"jsx": "preserve"` for Next's own compiler, which leaves
  // esbuild on the classic runtime and every render fails with "React is not
  // defined". Next itself uses the automatic runtime; this says the same thing
  // to the test transform rather than adding a `import React` line to files that
  // do not need one in the app.
  esbuild: { jsx: "automatic" },
  resolve: {
    alias: { "@": path.resolve(rootDir, ".") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**"],
  },
});
