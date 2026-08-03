import { test, expect } from "@playwright/test";

/**
 * `app/api/v1/billing/payu/{success,failure}/route.ts` — the public
 * pass-through PayU's `surl`/`furl` actually hit (`relay.ts::relayPayuCallback`).
 *
 * What IS reasonably testable at this layer, and what isn't:
 *
 *   Testable here: the relay's own behaviour when it cannot reach
 *   `BACKEND_API_URL` -- the `catch` branch that must send a possibly-just-
 *   -paid user to an honest "we could not verify this" page rather than a
 *   raw 500. `playwright.config.ts` pins `BACKEND_API_URL` to a port nothing
 *   listens on specifically so this branch is deterministic regardless of
 *   whether a real invoice-be happens to be running on the machine the
 *   suite executes on.
 *
 *   NOT reasonably testable here: the "backend responds, forward its
 *   redirect verbatim" branch and everything the backend's redirect target
 *   depends on (hash verification, reason-code selection, plan/tenant
 *   resolution). Playwright's `page.route()` intercepts *browser-initiated*
 *   requests; this relay's `fetch()` call happens inside the Next.js server
 *   process, which `page.route()` cannot see or stub. Exercising the real
 *   forward-and-relay path would need a live HTTP server standing in for
 *   invoice-be, which is exactly what `invoice-be/tests/test_billing.py`
 *   already covers server-side (20 tests: hash checks, all 5 `reason=`
 *   branches, plan/tenant resolution) -- left there rather than duplicated
 *   with a hand-rolled stub server here.
 *
 * Uses the `request` fixture (not `page`) -- these are server routes, no
 * browser rendering involved, and the redirect must be inspected
 * un-followed to assert the 303 + Location itself.
 */

const FORM_BODY = "txnid=REL-TEST-1&status=success&amount=4999.00";

for (const outcome of ["success", "failure"] as const) {
  test.describe(`POST /api/v1/billing/payu/${outcome} — backend unreachable`, () => {
    test("redirects 303 to /billing/failed?reason=unverifiable, carrying txnid through", async ({
      request,
    }) => {
      const response = await request.post(`/api/v1/billing/payu/${outcome}`, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        data: FORM_BODY,
        maxRedirects: 0,
      });

      expect(response.status()).toBe(303);
      const location = response.headers()["location"];
      expect(location).toBeTruthy();

      const target = new URL(location!, "http://127.0.0.1");
      expect(target.pathname).toBe("/billing/failed");
      expect(target.searchParams.get("reason")).toBe("unverifiable");
      expect(target.searchParams.get("txnid")).toBe("REL-TEST-1");
    });

    test("still redirects (with no txnid) when the callback body carries none", async ({
      request,
    }) => {
      const response = await request.post(`/api/v1/billing/payu/${outcome}`, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        data: "status=failure",
        maxRedirects: 0,
      });

      expect(response.status()).toBe(303);
      const target = new URL(response.headers()["location"]!, "http://127.0.0.1");
      expect(target.pathname).toBe("/billing/failed");
      expect(target.searchParams.get("reason")).toBe("unverifiable");
      expect(target.searchParams.has("txnid")).toBe(false);
    });
  });
}

test.describe("Relay redirect target actually renders the unconfirmed page", () => {
  test("browser POST to the relay lands on billing/failed with the unconfirmed messaging", async ({
    page,
  }) => {
    // Navigate to a real same-origin page first -- setContent() does not
    // itself change page.url() (Playwright docs: "does not change the
    // current URL, so it is not considered a navigation"), so without this
    // the injected form's relative action="/api/v1/..." would resolve
    // against "about:blank" instead of this server's origin, and the POST
    // never actually reaches the route. This is what caused this test's
    // first-draft failure (30s waitForNavigation timeout, found by actually
    // running the suite -- see test_evidence for the run that caught it).
    await page.goto("/billing/success");

    // A real browser form POST (mirrors how PayU actually reaches this route
    // -- an auto-submitted <form method="POST">), so the 303 is followed by
    // the browser itself end to end, landing on the real rendered page.
    await page.setContent(`
      <form id="f" method="POST" action="/api/v1/billing/payu/failure">
        <input type="hidden" name="txnid" value="REL-E2E-1" />
        <input type="hidden" name="status" value="failure" />
      </form>
    `);
    await page.locator("#f").evaluate((f: HTMLFormElement) => f.submit());
    await page.waitForURL(/\/billing\/failed\?.*reason=unverifiable/);

    await expect(page.getByText("We couldn't reach PayU to confirm this payment")).toBeVisible();
    await expect(page.getByText("REL-E2E-1")).toBeVisible();
  });
});
