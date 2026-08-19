import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

/**
 * Second, SEQUENTIAL pass over the same app with a different server env.
 *
 * Two behaviours in these pages are decided by server-only env vars read at
 * request time, so they cannot be exercised by the main config's single
 * server:
 *
 *   ENABLE_FE_PROXY=true          -> lib/billingPlans.ts::appHref() returns a
 *                                    same-origin path instead of a full
 *                                    NEXT_PUBLIC_FE_URL origin. This is the
 *                                    Azure Multi-Zone configuration
 *                                    (website_features_tracker.md Gap 12),
 *                                    where invoice-fe has internal-only
 *                                    ingress and a cross-origin link to it
 *                                    would be unreachable from a browser.
 *   NEXT_PUBLIC_SUPPORT_EMAIL set -> /billing/failed swaps its "reach out
 *                                    through your usual support channel"
 *                                    fallback text for a real mailto: CTA.
 *
 * Run via `npm run test:e2e:proxy` (or `test:e2e:all` for both passes).
 * MUST NOT run concurrently with the main Playwright config's `next dev`
 * unless `NEXT_DIST_DIR` differs — this config uses `.next-proxy` so a
 * developer `npm run dev` on :3000 can stay up.
 *
 * FE_INTERNAL_URL is required by next.config.js whenever ENABLE_FE_PROXY is
 * "true" (it throws otherwise). Gap 184's rewrite tests need a live upstream
 * on that URL — `e2e/fe-proxy-stub.mjs` (not the real invoice-fe).
 */

const PORT = Number(process.env.PLAYWRIGHT_PROXY_PORT ?? 3201);
const BASE_URL = `http://127.0.0.1:${PORT}`;

export const SUPPORT_EMAIL = "billing-support@invoice.test";

export default defineConfig({
  ...base,
  testIgnore: undefined,
  testMatch: "**/billing-proxy-mode.spec.ts",
  use: {
    ...base.use,
    baseURL: BASE_URL,
  },
  webServer: [
    {
      command: "node e2e/fe-proxy-stub.mjs",
      url: "http://127.0.0.1:3399/health",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: `npx next dev --port ${PORT}`,
      url: BASE_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: {
        ENABLE_FE_PROXY: "true",
        FE_INTERNAL_URL: "http://127.0.0.1:3399",
        NEXT_PUBLIC_SUPPORT_EMAIL: SUPPORT_EMAIL,
        NEXT_DIST_DIR: ".next-proxy",
      },
    },
  ],
});
