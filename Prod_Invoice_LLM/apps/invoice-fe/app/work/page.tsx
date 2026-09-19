"use client";
// =============================================================================
// FILE: app/work/page.tsx
// FEATURE: FE Feature 23 — the work screen's route.
//
// WHY A NEW ROUTE AND NOT A REPLACED LANDING PAGE: spec §9 task 1 ("delete
// PrimaryNav, the redirect table and the flag; restore the sidebar") is a
// **no-op** — FE Feature 22 was never built, so there is no navigation shell to
// remove and no redirect to restore (see spec §11.2, the additive amendment).
// Re-homing the app's landing page is a navigation change nobody asked this
// build for, and §1.2 is explicit that Records and Settings are not re-homed.
// So the screen gets its own route beside the existing ten-item sidebar, and
// where a user lands stays a founder decision.
//
// "use client" because the whole screen is one authenticated read performed in
// the browser through `lib/apiClient` -> the app's own route handler, exactly
// like `/chat` and `/documents`.
// =============================================================================

import WorkScreen from "@/components/atlas/WorkScreen";
import { usePageHeader } from "@/components/layout/PageHeaderContext";

export default function WorkPage() {
  usePageHeader({
    title: "Your work",
    agentIcon: "🧭",
    agentName: "ATLAS",
    agentRole: "Recommends, and shows its working",
  });

  return <WorkScreen />;
}
