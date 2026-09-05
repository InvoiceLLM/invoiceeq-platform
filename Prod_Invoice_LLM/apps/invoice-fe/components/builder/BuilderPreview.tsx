"use client";

import { useEffect, useRef, useState } from "react";
import { Eye, Loader2, AlertTriangle, FileText } from "lucide-react";
import PdfViewerCanvas from "@/components/audit/PdfViewerCanvas";
import type { BuildRequest } from "@/types/invoice";

/**
 * Feature 20, task 20.4: renders the PDF the backend would produce, before
 * anything is stored.
 *
 * `POST /api/outbound-invoices/build/preview` is the one route in this feature
 * that can answer with either a PDF or JSON on the same status-code family, so
 * the branching here is on content-type first and status second:
 *
 *   200 + application/pdf  → object URL into `PdfViewerCanvas`
 *   409 + json             → duplicate invoice number (founder decision D5).
 *                            Handed up to the page, which shows it against the
 *                            number field in `BuilderForm`.
 *   422 + json             → `{"unlocated_fields": [...]}` from the substitute
 *                            path. Handed up so the affected fields can be
 *                            marked with a "revert to source" action; also
 *                            listed here so the user can see all of them at
 *                            once without hunting the form.
 *
 * The object URL is revoked when it is replaced and on unmount — a preview is
 * a multi-megabyte blob and this screen is used iteratively.
 */

interface BuilderPreviewProps {
  body: BuildRequest;
  /** Bumped by the page when the form changes, so a stale preview can be labelled as such. */
  dirtySinceLastPreview: boolean;
  onDirtyCleared: () => void;
  onUnlocatedFields: (fields: string[]) => void;
  onDuplicateNumber: (message: string | null) => void;
  disabled?: boolean;
}

export default function BuilderPreview({
  body,
  dirtySinceLastPreview,
  onDirtyCleared,
  onUnlocatedFields,
  onDuplicateNumber,
  disabled,
}: BuilderPreviewProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unlocated, setUnlocated] = useState<string[]>([]);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  const swapUrl = (next: string | null) => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = next;
    setPreviewUrl(next);
  };

  const handlePreview = async () => {
    setLoading(true);
    setError(null);
    setUnlocated([]);
    onUnlocatedFields([]);
    onDuplicateNumber(null);
    try {
      const response = await fetch("/api/outbound-invoices/build/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const contentType = response.headers.get("content-type") || "";

      if (response.ok && contentType.includes("application/pdf")) {
        const blob = await response.blob();
        swapUrl(URL.createObjectURL(blob));
        onDirtyCleared();
        return;
      }

      const payload = await response.json().catch(() => null);

      if (response.status === 409) {
        const message =
          (payload && (payload.detail as string)) || "Invoice number already used for this customer";
        onDuplicateNumber(message);
        setError(message);
        return;
      }

      if (response.status === 422 && payload && Array.isArray(payload.unlocated_fields)) {
        const fields: string[] = payload.unlocated_fields;
        setUnlocated(fields);
        onUnlocatedFields(fields);
        setError(
          "Some changed values could not be found in the source PDF, so they cannot be substituted in place."
        );
        return;
      }

      setError(
        (payload && ((payload.detail as string) || (payload.message as string))) ||
          `Preview failed (${response.status}).`
      );
    } catch {
      setError("Preview failed — the server could not be reached.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section data-testid="builder-preview" className="flex h-full min-h-[520px] flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handlePreview}
          disabled={disabled || loading}
          data-testid="preview-button"
          className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/50 bg-blue-600/20 px-3 py-1.5 text-xs font-semibold text-blue-200 transition hover:bg-blue-600/40 disabled:opacity-50"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Eye size={13} />}
          {loading ? "Rendering…" : "Preview PDF"}
        </button>
        {previewUrl && dirtySinceLastPreview && (
          <span data-testid="preview-stale" className="text-[11px] text-amber-300">
            Edited since this preview — render again to see the change.
          </span>
        )}
      </div>

      {error && (
        <div
          data-testid="preview-error"
          className="flex items-start gap-2 rounded-lg border border-rose-600/40 bg-rose-950/20 px-3 py-2 text-xs text-rose-200"
        >
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <div className="flex flex-col gap-1">
            <span>{error}</span>
            {unlocated.length > 0 && (
              <span data-testid="unlocated-fields" className="text-rose-300/90">
                Fields: {unlocated.join(", ")} — revert them to the source value on the left, or change
                the layout by adding/removing a row so the invoice is re-rendered instead.
              </span>
            )}
          </div>
        </div>
      )}

      {previewUrl ? (
        <div className="min-h-[500px] flex-1">
          <PdfViewerCanvas srcUrl={previewUrl} title="Preview — not yet created" status="PREVIEW" />
        </div>
      ) : (
        <div
          data-testid="preview-placeholder"
          className="flex flex-1 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-[#222D3D] bg-[#0B1220] text-xs text-slate-500"
        >
          <FileText size={22} />
          <p>Preview renders the real PDF the backend will produce. Nothing is saved.</p>
        </div>
      )}
    </section>
  );
}
