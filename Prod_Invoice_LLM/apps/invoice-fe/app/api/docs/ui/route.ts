import { NextRequest, NextResponse } from "next/server";
import { backendRootUrl, forwardedHeaders } from "@/lib/backendProxy";

export const dynamic = "force-dynamic";

/** Same-origin path this app serves the OpenAPI document from (see ../openapi/route.ts). */
const PROXIED_SCHEMA_PATH = "/api/docs/openapi";

/**
 * Matches the schema URL FastAPI writes into its own Swagger UI page:
 * `SwaggerUIBundle({ url: '/openapi.json', ... })`. Only that one literal is
 * rewritten — the CSS/JS/favicon URLs in the same document are absolute CDN
 * links and already resolve from the browser.
 */
const SCHEMA_URL_PATTERN = /url:\s*'[^']*'/;

/**
 * Gap 184 (Docs Hub) — serves the backend's own Swagger UI page, same-origin.
 *
 * This deliberately proxies FastAPI's existing `/docs` HTML rather than
 * building a second Swagger UI in the frontend: the goal is that developers see
 * exactly the document the backend publishes, and there is nothing to keep in
 * sync when routes change. FastAPI's page already loads swagger-ui from a CDN,
 * so proxying it adds no dependency that was not already there.
 *
 * One rewrite is required. The backend's page points Swagger UI at
 * `/openapi.json` on whatever origin loaded it — which, inside an iframe on the
 * frontend origin, is a frontend URL that does not exist (and in deployed
 * environments the browser cannot reach the backend origin at all, since
 * BACKEND_API_URL is an internal container address). Repointing it at
 * `/api/docs/openapi` makes both the page and its schema same-origin.
 */
export async function GET(request: NextRequest) {
  const response = await fetch(backendRootUrl("/docs"), {
    headers: await forwardedHeaders(request),
    cache: "no-store",
  });

  if (!response.ok) {
    return new NextResponse(
      renderUnavailable(
        `The backend returned HTTP ${response.status} for /docs.`,
      ),
      { status: 502, headers: { "Content-Type": "text/html; charset=utf-8" } },
    );
  }

  const html = await response.text();

  // If the expected literal is absent, the upstream page shape changed and a
  // blind pass-through would render a Swagger UI that silently fails to load
  // any schema. Fail visibly with a link to the raw document instead.
  if (!SCHEMA_URL_PATTERN.test(html)) {
    return new NextResponse(
      renderUnavailable(
        "The backend's Swagger UI page no longer contains the expected schema URL, " +
          "so it could not be re-pointed at this app's proxied copy.",
      ),
      { status: 502, headers: { "Content-Type": "text/html; charset=utf-8" } },
    );
  }

  const rewritten = html.replace(SCHEMA_URL_PATTERN, `url: '${PROXIED_SCHEMA_PATH}'`);

  return new NextResponse(rewritten, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      // Only this app may frame it, which is what the Docs Hub tab does.
      "Content-Security-Policy": "frame-ancestors 'self'",
    },
  });
}

/** Minimal in-iframe error page — the tab must explain itself, not go blank. */
function renderUnavailable(reason: string): string {
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>API documentation unavailable</title></head>
<body style="font-family:system-ui,sans-serif;background:#0B0F19;color:#94a3b8;padding:24px">
<h2 style="color:#e2e8f0;font-size:15px">API documentation is unavailable</h2>
<p style="font-size:13px">${reason}</p>
<p style="font-size:13px">The raw OpenAPI document may still be readable at
<a style="color:#38bdf8" href="${PROXIED_SCHEMA_PATH}">${PROXIED_SCHEMA_PATH}</a>.</p>
</body></html>`;
}
