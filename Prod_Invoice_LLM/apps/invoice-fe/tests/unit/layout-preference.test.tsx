// =============================================================================
// FILE: tests/unit/layout-preference.test.tsx
// FEATURE: FE Feature 22 Task 22.21 — Classic layout preference toggle
// =============================================================================

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import React from "react";
import * as todayApi from "@/lib/today";
import { LayoutPreferenceProvider, useLayoutPreference } from "@/components/layout/LayoutPreferenceContext";
import LayoutPreference from "@/components/settings/LayoutPreference";

describe("LayoutPreference & Context (Task 22.21)", () => {
  let getPreferencesSpy: any;
  let updatePreferencesSpy: any;
  let localStorageSetSpy: any;
  let localStorageGetSpy: any;

  beforeEach(() => {
    localStorageSetSpy = vi.spyOn(Storage.prototype, "setItem");
    localStorageGetSpy = vi.spyOn(Storage.prototype, "getItem");

    getPreferencesSpy = vi.spyOn(todayApi, "getPreferences").mockResolvedValue({
      layout: "surfaces",
      first_run_seen: false,
      tour_seen: false,
      questionnaire_progress: null,
    });

    updatePreferencesSpy = vi.spyOn(todayApi, "updatePreferences").mockImplementation(async (updates) => ({
      layout: (updates.layout ?? "surfaces") as todayApi.LayoutPreference,
      first_run_seen: false,
      tour_seen: false,
      questionnaire_progress: null,
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads layout preference from GET /auth/me/preferences and NEVER touches localStorage", async () => {
    render(
      <LayoutPreferenceProvider>
        <LayoutPreference variant="header" />
      </LayoutPreferenceProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole("switch", { name: /classic layout/i })).toBeInTheDocument();
    });

    expect(getPreferencesSpy).toHaveBeenCalledTimes(1);
    expect(localStorageGetSpy).not.toHaveBeenCalledWith("layout");
    expect(localStorageSetSpy).not.toHaveBeenCalled();

    const toggle = screen.getByRole("switch", { name: /classic layout/i });
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  it("toggles to classic via PATCH /auth/me/preferences without touching localStorage", async () => {
    render(
      <LayoutPreferenceProvider>
        <LayoutPreference variant="header" />
      </LayoutPreferenceProvider>
    );

    const toggle = await screen.findByRole("switch", { name: /classic layout/i });
    expect(toggle).toHaveAttribute("aria-checked", "false");

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(updatePreferencesSpy).toHaveBeenCalledWith({ layout: "classic" });
      expect(toggle).toHaveAttribute("aria-checked", "true");
    });

    expect(localStorageSetSpy).not.toHaveBeenCalled();
  });

  it("toggles back from classic to surfaces when clicked again", async () => {
    getPreferencesSpy.mockResolvedValueOnce({
      layout: "classic",
      first_run_seen: false,
      tour_seen: false,
      questionnaire_progress: null,
    });

    render(
      <LayoutPreferenceProvider>
        <LayoutPreference variant="header" />
      </LayoutPreferenceProvider>
    );

    const toggle = await screen.findByRole("switch", { name: /classic layout/i });
    expect(toggle).toHaveAttribute("aria-checked", "true");

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(updatePreferencesSpy).toHaveBeenCalledWith({ layout: "surfaces" });
      expect(toggle).toHaveAttribute("aria-checked", "false");
    });
  });

  it("renders the settings row variant with description and title", async () => {
    render(
      <LayoutPreferenceProvider>
        <LayoutPreference variant="settings" />
      </LayoutPreferenceProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("layout-preference-row")).toBeInTheDocument();
    });

    expect(screen.getByText("Classic layout")).toBeInTheDocument();
    expect(screen.getByText(/Saved for your account on every device/i)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /classic layout/i })).toBeInTheDocument();
  });

  it("displays error alert if updatePreferences fails", async () => {
    updatePreferencesSpy.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 500, data: { detail: "Database unreachable" } },
    });

    render(
      <LayoutPreferenceProvider>
        <LayoutPreference variant="header" />
      </LayoutPreferenceProvider>
    );

    const toggle = await screen.findByRole("switch", { name: /classic layout/i });
    fireEvent.click(toggle);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Database unreachable");
    expect(toggle).not.toBeDisabled();
  });
});
