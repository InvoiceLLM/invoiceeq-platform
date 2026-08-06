"use client";

/**
 * Per-browser "default browse folder" for a connector provider + direction.
 *
 * FE Gap 165 — what this is, and deliberately is not:
 *
 * Settings > Connectors used to present this as "Folder Mappings", with copy
 * promising folders would be "automatically imported"/"exported". Nothing of
 * the sort existed: the chosen folder was written to `localStorage` as a bare
 * display string, no backend ever heard about it, there is no connector
 * auto-pull on the backend to honour it (`routers/connectors.py` only exposes
 * browse + explicit per-file import), and Ingestion's own browse bar never read
 * the value, so every browse session still opened at Root.
 *
 * Rather than half-build persistence for a sync feature that does not exist,
 * this is now an honest local convenience: a saved starting folder that the
 * folder explorer actually opens at, wherever it is launched from (Settings or
 * the Ingestion tab's browse bar). It is per browser, per user, and it changes
 * nothing about how files are processed once imported. Making it a real
 * tenant-wide auto-pull mapping is a backend feature (persisted mapping +
 * scheduled pull), tracked separately if it is ever wanted.
 *
 * Storage keys are unchanged from the previous implementation so a value saved
 * before this change still resolves (as a name-only shortcut, see `read`).
 */

export type ConnectorProvider = "google_drive" | "salesforce";
export type ConnectorDirection = "inbound" | "outbound";

export interface FolderShortcut {
  /** Provider folder id. `null` means the provider's root. */
  id: string | null;
  /** Human-readable folder name, for display. */
  name: string;
}

const STORAGE_KEYS: Record<ConnectorProvider, Record<ConnectorDirection, string>> = {
  google_drive: { inbound: "map_gdrive_in", outbound: "map_gdrive_out" },
  salesforce: { inbound: "map_sf_in", outbound: "map_sf_out" },
};

export function readFolderShortcut(
  provider: ConnectorProvider,
  direction: ConnectorDirection
): FolderShortcut | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(STORAGE_KEYS[provider][direction]);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.name === "string") {
      return { id: typeof parsed.id === "string" ? parsed.id : null, name: parsed.name };
    }
  } catch {
    // Legacy value: a plain folder name (or, before the breadcrumb fix, a raw
    // folder id shown as if it were a name). Usable for display only -- there
    // is no id to navigate to, so it resolves to root on the next browse.
  }
  return { id: null, name: raw };
}

export function writeFolderShortcut(
  provider: ConnectorProvider,
  direction: ConnectorDirection,
  shortcut: FolderShortcut | null
): void {
  if (typeof window === "undefined") return;
  const key = STORAGE_KEYS[provider][direction];
  if (!shortcut) {
    window.localStorage.removeItem(key);
    return;
  }
  window.localStorage.setItem(key, JSON.stringify(shortcut));
}

/** Drops both directions for a provider — used when it is disconnected. */
export function clearFolderShortcuts(provider: ConnectorProvider): void {
  writeFolderShortcut(provider, "inbound", null);
  writeFolderShortcut(provider, "outbound", null);
}
