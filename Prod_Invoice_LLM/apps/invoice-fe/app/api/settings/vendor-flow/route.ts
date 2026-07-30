// Renamed to service-flow — kept for backward compatibility only.
// Use /api/settings/service-flow instead.
export { GET, PUT } from "../service-flow/route";

// Route segment config is not inherited through a re-export -- only GET/PUT
// cross the module boundary above, so without this the alias was treated as a
// static route and `next build` failed prerendering it (the proxied handler
// reads request headers, which don't exist at build time). Declared here to
// match the force-dynamic setting on the route it aliases.
export const dynamic = "force-dynamic";
