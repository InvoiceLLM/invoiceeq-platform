import { defineConfig, devices } from "@playwright/test";

/**
 * First Playwright setup for invoice-website. Mirrors
 * apps/invoice-fe/playwright.config.ts deliberately -- same PLAYWRIGHT_PORT
 * override, same fullyParallel/chromium-only shape, same auto-started
 * `next dev` webServer -- so the two suites stay one pattern rather than two.
 *
 * PORT 3200, not 3000/3100. 3000 is this app's own `npm run dev` port and
 * 3100 is invoice-fe's Playwright port; a run here must not evict either.
 *
 * These specs need the Next dev server and nothing else -- no FastAPI
 * backend, no Postgres, no PayU. The two billing return pages are pure
 * server components that read only `searchParams` and `process.env`
 * (`app/billing/{success,failed}/page.tsx` deliberately make no API call at
 * all -- see the comment in success/page.tsx), and the one route the pricing
 * table can POST to is stubbed via page.route() in its spec.
 *
 * NEXT_PUBLIC_FE_URL is pinned here rather than inherited from the developer's
 * gitignored .env.local, so the appHref() cross-origin assertions are
 * deterministic on any machine. Port 3399 is intentionally a port nothing in
 * this repo listens on -- these links are only ever asserted on, never
 * followed.
 *
 * ENABLE_FE_PROXY is deliberately NOT set here (that is the Azure Multi-Zone
 * config, tracker Gap 12). Its branch is covered by playwright.proxy.config.ts,
 * which runs as a SECOND, SEQUENTIAL pass on its own port -- two `next dev`
 * processes must not share one .next dir concurrently.
 */

const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 3200);
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  // Owned by playwright.proxy.config.ts / playwright.sandbox.config.ts -- both
  // need a differently-configured server, so running them here would assert
  // against the wrong env (see each config's own comment).
  testIgnore: ["**/billing-proxy-mode.spec.ts", "**/sandbox-key-cta-enabled.spec.ts"],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // Capped at 2 locally (CI keeps Playwright's default). Measured, not
  // guessed: a full run at the default local worker count (4 on an 8-core
  // machine) produced 17 flaky page.goto/waitForNavigation timeouts, all
  // against a *single* shared `next dev` server -- each worker's first hit
  // on a not-yet-compiled route (e.g. /billing/failed?reason=X for a route
  // already warm from a different worker's request) queues behind the dev
  // server's JIT compiler, and 4 workers doing that simultaneously routinely
  // exceeded the 30s test timeout. workers: 2 reran the exact same suite
  // clean (32/34 passed, 2 real test bugs found and fixed separately) --
  // this is dev-server contention, not app or CI-runner behavior, so CI's
  // own -- presumably differently-provisioned -- default is left alone.
  workers: process.env.CI ? undefined : 2,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      // channel: "chrome" -- launches this machine's installed Google Chrome
      // instead of Playwright's bundled Chromium/chrome-headless-shell binaries.
      // Required here: this dev machine's Windows Device Guard / WDAC policy
      // blocks chrome-headless-shell.exe outright (confirmed directly --
      // `chrome-headless-shell.exe --version` fails with "was blocked by your
      // organization's Device Guard policy", which Node/Playwright only ever
      // surfaces as the opaque `browserType.launch: spawn UNKNOWN`). The
      // installed Google Chrome is unblocked and runs headless fine (verified:
      // `chrome.exe --headless=new --dump-dom about:blank` exits 0) -- same
      // browser engine, just launched via the channel Playwright already
      // supports for exactly this case rather than the bundled binary.
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
  webServer: {
    command: `npx next dev --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      NEXT_PUBLIC_FE_URL: "http://127.0.0.1:3399",
      // Pinned (not inherited from .env.local's BACKEND_API_URL=localhost:8000) so
      // billing-payu-relay.spec.ts's "backend unreachable" branch is deterministic
      // regardless of whether a real invoice-be happens to be running locally.
      // Next's dotenv loader does not override an already-set process.env value,
      // so this wins over .env.local's BACKEND_API_URL for this spawned server.
      BACKEND_API_URL: "http://127.0.0.1:39999",
    },
  },
});
