/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    if (process.env.ENABLE_FE_PROXY !== "true") return [];

    const feUrl = process.env.FE_INTERNAL_URL;
    if (!feUrl) throw new Error("FE_INTERNAL_URL is not set but ENABLE_FE_PROXY=true");

    const fePages = ["dashboard", "chat", "ingestion", "invoices", "trainer", "settings", "admin", "flows", "help"];
    const feApiPrefixes = ["admin", "audit", "chat", "connectors", "dashboard", "email", "invoices", "outbound-audit", "outbound-dashboard", "outbound-invoices", "settings", "trainer"];

    return [
      ...fePages.flatMap((p) => [
        { source: `/${p}`, destination: `${feUrl}/${p}` },
        { source: `/${p}/:path*`, destination: `${feUrl}/${p}/:path*` },
      ]),
      ...feApiPrefixes.map((p) => ({
        source: `/api/${p}/:path*`,
        destination: `${feUrl}/api/${p}/:path*`,
      })),
      { source: "/fe-static/:path*", destination: `${feUrl}/_next/:path*` },
    ];
  },
};

module.exports = nextConfig;
