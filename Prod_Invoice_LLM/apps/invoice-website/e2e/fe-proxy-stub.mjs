/**
 * Tiny invoice-fe stand-in for playwright.proxy.config.ts.
 *
 * Gap 184: the website's Multi-Zone rewrites for /api/billing/usage and
 * /api/support/* must be proven against a live upstream. The real invoice-fe
 * is not started here (Clerk, BE, shared .next). This stub listens on the
 * same FE_INTERNAL_URL port the proxy config already used (3399).
 */
import http from "node:http";

const PORT = Number(process.env.FE_STUB_PORT ?? 3399);

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json",
    "x-fe-stub": "gap-184",
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

  if (url === "/api/billing/usage" || url.startsWith("/api/billing/usage/")) {
    json(res, 200, { stub: "billing-usage", path: url });
    return;
  }

  if (url.startsWith("/api/support/")) {
    json(res, 200, { stub: "support", path: url, method: req.method });
    return;
  }

  json(res, 404, { stub: "unhandled", path: url });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`fe-proxy-stub listening on http://127.0.0.1:${PORT}`);
});
