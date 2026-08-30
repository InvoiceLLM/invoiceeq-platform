import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

/**
 * Second, SEQUENTIAL pass over the same app with a different server env --
 * same shape as playwright.proxy.config.ts, for the same underlying reason:
 * one behaviour here is decided by a NEXT_PUBLIC_* value baked in at
 * `next dev`/`next build` time, so the main config's single server cannot
 * exercise it.
 *
 *   NEXT_PUBLIC_SANDBOX_KEYS_ENABLED=true -> lib/sandboxKey.ts's
 *   SANDBOX_KEYS_ENABLED flips to true, and SandboxKeyCta.tsx renders the
 *   real "Get Sandbox API Key" button instead of the plain /signup link
 *   (Website Gap 350). The shipped default (flag unset) is covered by the
 *   main config's e2e/plug-and-play-homepage.spec.ts -- that is the state of
 *   every real environment today, so it stays the primary pass.
 *
 * Run via `npx playwright test --config=playwright.sandbox.config.ts`.
 * MUST NOT run concurrently with the main config's `next dev` -- uses its own
 * `NEXT_DIST_DIR` (.next-sandbox) so a developer `npm run dev` on :3000 (or a
 * `test:e2e` run on :3200) can stay up.
 *
 * BACKEND_API_URL points at e2e/sandbox-backend-stub.mjs, not a real
 * invoice-be -- there is no Postgres or FastAPI in this pass. The stub plays
 * only POST /api/v1/sandbox/keys (BE Gap 340's real response shape); the
 * claim step (POST /api/v1/sandbox/claim, driven from app/signup/page.tsx)
 * is out of scope here, same boundary Website Feature 7's own doc draws
 * around Task 7.5 ("not verified through a full real-Clerk signup").
 */

const PORT = Number(process.env.PLAYWRIGHT_SANDBOX_PORT ?? 3202);
const BASE_URL = `http://127.0.0.1:${PORT}`;
const STUB_PORT = Number(process.env.SANDBOX_STUB_PORT ?? 8010);

export default defineConfig({
  ...base,
  testIgnore: undefined,
  testMatch: "**/sandbox-key-cta-enabled.spec.ts",
  use: {
    ...base.use,
    baseURL: BASE_URL,
  },
  webServer: [
    {
      command: "node e2e/sandbox-backend-stub.mjs",
      url: `http://127.0.0.1:${STUB_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: { SANDBOX_STUB_PORT: String(STUB_PORT) },
    },
    {
      command: `npx next dev --port ${PORT}`,
      url: BASE_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: {
        NEXT_PUBLIC_SANDBOX_KEYS_ENABLED: "true",
        BACKEND_API_URL: `http://127.0.0.1:${STUB_PORT}`,
        NEXT_DIST_DIR: ".next-sandbox",
      },
    },
  ],
});
