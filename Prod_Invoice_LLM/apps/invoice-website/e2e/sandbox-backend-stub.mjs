/**
 * Tiny invoice-be stand-in for playwright.sandbox.config.ts.
 *
 * Website Gap 350's SandboxKeyCta is the one component in Feature 7 that
 * makes a network call, and it does so through a server-side relay
 * (app/api/sandbox/keys/route.ts) rather than directly -- see that file's own
 * comment. This stub plays the part of invoice-be's
 * POST /api/v1/sandbox/keys (BE Gap 340) so the flag-on rendering path can be
 * exercised without a real FastAPI + Postgres stack, mirroring
 * e2e/fe-proxy-stub.mjs's role for playwright.proxy.config.ts.
 *
 * Deliberately minimal: one canned 201 response with the same shape
 * BE Gap 340's SandboxKeyResponse actually returns (verified against
 * routers/sandbox.py before writing this), no persistence, no real rate
 * limiting -- the relay's own edge limiter and the backend's Redis-backed one
 * are both out of scope for this stub.
 */
import http from "node:http";

const PORT = Number(process.env.SANDBOX_STUB_PORT ?? 8010);

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json",
    "x-sandbox-stub": "gap-350",
    "content-length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

const server = http.createServer((req, res) => {
  const url = req.url?.split("?")[0] ?? "";

  if (url === "/health") {
    json(res, 200, { ok: true });
    return;
  }

  if (url === "/api/v1/sandbox/keys" && req.method === "POST") {
    json(res, 201, {
      api_key: "inv_test_e2e0000000000000000000000000000000000000000",
      tenant_id: "e2e00000-0000-0000-0000-000000000001",
      expires_at: "2026-09-02T10:19:00.000Z",
      chat_message_limit: 25,
      invoice_limit: 5,
    });
    return;
  }

  json(res, 404, { detail: "not found in stub" });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`sandbox-backend-stub listening on http://127.0.0.1:${PORT}`);
});
