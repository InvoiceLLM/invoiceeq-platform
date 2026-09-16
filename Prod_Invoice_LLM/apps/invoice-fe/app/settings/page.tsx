"use client";

/**
 * Feature 10: Settings Page — /settings
 *
 * FE Feature 22 Task 22.3: with the four surfaces on
 * (`NEXT_PUBLIC_FOUR_SURFACES`, lib/navigation.ts) this is the single scrolling
 * page — People / Inbox / Checks / Notify / Plan / Security — and the old
 * sub-routes redirect to its anchors. With them off it is the tile grid it has
 * always been, moved verbatim to components/settings/SettingsTileGrid.tsx
 * (parity: tests/unit/settings-page.test.tsx).
 */

import SettingsSections from "@/components/settings/SettingsSections";
import SettingsTileGrid from "@/components/settings/SettingsTileGrid";
import { fourSurfacesEnabled } from "@/lib/navigation";

export default function SettingsPage() {
  return fourSurfacesEnabled() ? <SettingsSections /> : <SettingsTileGrid />;
}
