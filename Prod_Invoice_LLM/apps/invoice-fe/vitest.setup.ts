// =============================================================================
// FILE: vitest.setup.ts
// FEATURE: FE Feature 21 (task 21.1) — jsdom gaps the chat components rely on.
// =============================================================================
// `toBeDisabled()` / `toBeEnabled()` — DOM matchers, so a disabled-button
// assertion reads as one line instead of an `hasAttribute("disabled")` poke.
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// MessageStream calls this on every render; jsdom does not implement it.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
