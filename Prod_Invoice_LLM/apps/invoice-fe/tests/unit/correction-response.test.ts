import { describe, expect, it } from "vitest";
import { AxiosError } from "axios";
import { correctionErrorMessage, resolveNotice, savedValues } from "@/lib/correctionResponse";

describe("FE Gap 717 / correctionResponse", () => {
  it("returns specific message for dropped connection without response (ECONNABORTED)", () => {
    const err = new AxiosError("timeout of 30000ms exceeded");
    err.code = "ECONNABORTED";
    const msg = correctionErrorMessage(err);
    expect(msg).toContain("Save request timed out waiting for server confirmation");
    expect(msg).toContain("check Rule History before retrying");
  });

  it("returns specific message for socket hang up / no response", () => {
    const err = new AxiosError("socket hang up");
    // no err.response
    const msg = correctionErrorMessage(err);
    expect(msg).toContain("Save request timed out waiting for server confirmation");
  });

  it("preserves backend detail message when detail string is returned", () => {
    const err = new AxiosError("Bad Request");
    err.response = {
      data: { detail: "Cannot change a PAID invoice to 'REJECTED' directly — reopen it first." },
      status: 400,
      statusText: "Bad Request",
      headers: {},
      config: {} as any,
    };
    const msg = correctionErrorMessage(err);
    expect(msg).toBe("Not saved — Cannot change a PAID invoice to 'REJECTED' directly — reopen it first.");
  });

  it("formats invalid_corrections array properly", () => {
    const err = new AxiosError("Unprocessable Entity");
    err.response = {
      data: {
        detail: {
          invalid_corrections: [
            { field: "grand_total", reason: "Cannot be empty" },
            { field: "currency", reason: "Invalid ISO code" },
          ],
        },
      },
      status: 422,
      statusText: "Unprocessable Entity",
      headers: {},
      config: {} as any,
    };
    const msg = correctionErrorMessage(err);
    expect(msg).toBe("Not saved — grand_total: Cannot be empty; currency: Invalid ISO code");
  });

  it("handles non-axios generic errors cleanly", () => {
    const msg = correctionErrorMessage(new Error("Unknown failure"));
    expect(msg).toBe("Not saved — the server did not accept this change. Please try again.");
  });
});
