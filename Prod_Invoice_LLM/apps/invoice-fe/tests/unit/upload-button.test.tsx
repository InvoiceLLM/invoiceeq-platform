/**
 * FE Feature 22 Task 22.24 — Today's Upload button.
 *
 * Spec §6: "the Attach control is a REAL native <input type="file"> (asserted on
 * the element, not a mock) posting to the EXISTING endpoint; no request to any
 * new upload path". The picker offers Ingest's accept list and 25 MB cap, and
 * the button exists only for users who may ingest.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { AxiosError, AxiosHeaders } from "axios";

const auth = vi.hoisted(() => ({ current: { canLoad: true, loading: false } }));
const api = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }));

vi.mock("@/hooks/useAuth", () => ({ useAuth: () => auth.current }));
vi.mock("@/lib/apiClient", () => ({ apiClient: api }));
vi.mock("@/lib/featureFlags", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/featureFlags")>();
  return { ...actual, loadFeatureFlags: vi.fn(async () => ({})) };
});

import UploadButton, { MAX_UPLOAD_BYTES } from "@/components/today/UploadButton";
import { acceptedUploadExtensions, invalidFormatMessage } from "@/lib/featureFlags";
import { uploadErrorMessage } from "@/lib/today";

function httpError(status: number, detail?: string) {
  return new AxiosError(`Request failed with status code ${status}`, "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    statusText: "",
    data: detail ? { detail } : {},
    headers: {},
    config: { headers: new AxiosHeaders() },
  });
}

function pdf(name: string, bytes = 10) {
  return new File([new Uint8Array(bytes)], name, { type: "application/pdf" });
}

async function pick(files: File[]) {
  const input = screen.getByTestId("today-upload-input") as HTMLInputElement;
  await act(async () => {
    fireEvent.change(input, { target: { files } });
  });
}

beforeEach(() => {
  auth.current = { canLoad: true, loading: false };
  api.post.mockReset();
});

describe("UploadButton (22.24)", () => {
  it("is a real native file input with Ingest's accept list, opened by the button", () => {
    render(<UploadButton />);
    const input = screen.getByTestId("today-upload-input") as HTMLInputElement;
    expect(input.tagName).toBe("INPUT");
    expect(input.type).toBe("file");
    expect(input.multiple).toBe(true);
    expect(input.accept).toBe(acceptedUploadExtensions({}).join(","));
    const clicked = vi.spyOn(input, "click");
    fireEvent.click(screen.getByTestId("today-upload"));
    expect(clicked).toHaveBeenCalledTimes(1);
  });

  it("is absent for a user without the ingest permission", () => {
    auth.current = { canLoad: false, loading: false };
    render(<UploadButton />);
    expect(screen.queryByTestId("today-upload")).toBeNull();
  });

  it("posts the picked files once to the existing Ingest endpoint and confirms", async () => {
    api.post.mockResolvedValue({ data: { batch_id: "b1", job_ids: ["j1", "j2"] } });
    const onUploaded = vi.fn();
    render(<UploadButton onUploaded={onUploaded} />);
    await pick([pdf("RAJ-2008.pdf"), pdf("BH-11.pdf")]);

    expect(api.post).toHaveBeenCalledTimes(1);
    const [url, body] = api.post.mock.calls[0] as [string, FormData];
    expect(url).toBe("/invoices/upload");
    expect((body.getAll("files") as File[]).map((f) => f.name)).toEqual(["RAJ-2008.pdf", "BH-11.pdf"]);
    expect(screen.getByRole("status")).toHaveTextContent("2 documents uploaded");
    expect(onUploaded).toHaveBeenCalledTimes(1);
  });

  it("refuses a format Ingest would refuse, before uploading", async () => {
    render(<UploadButton />);
    await pick([pdf("notes.docx")]);
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(invalidFormatMessage(acceptedUploadExtensions({})));
  });

  it("refuses a file over 25 MB, before uploading", async () => {
    render(<UploadButton />);
    const big = pdf("huge.pdf");
    Object.defineProperty(big, "size", { value: MAX_UPLOAD_BYTES + 1 });
    await pick([big]);
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("huge.pdf is larger than 25 MB");
  });

  it("explains a billing refusal", async () => {
    api.post.mockRejectedValue(httpError(402));
    render(<UploadButton />);
    await pick([pdf("RAJ-2008.pdf")]);
    expect(screen.getByRole("alert")).toHaveTextContent("Billing limit reached");
  });
});

describe("uploadErrorMessage", () => {
  it("uses the billing sentence for 402, the backend's words otherwise, and a generic fallback", () => {
    expect(uploadErrorMessage(httpError(402))).toMatch(/Billing limit reached/);
    expect(uploadErrorMessage(httpError(415, "Unsupported file type: .docx"))).toBe("Unsupported file type: .docx");
    expect(uploadErrorMessage(httpError(500))).toMatch(/The upload failed/);
    expect(uploadErrorMessage(new Error("boom"))).toMatch(/The upload failed/);
  });
});
