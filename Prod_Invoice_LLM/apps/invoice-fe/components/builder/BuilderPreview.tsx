"use client";

import { useEffect, useRef, useState } from "react";
import { Eye, Loader2, AlertTriangle, FileText } from "lucide-react";
import PdfViewerCanvas from "@/components/audit/PdfViewerCanvas";
import type { BuildRequest } from "@/types/invoice";

/**
 * Feature 20, task 20.4: renders the PDF the backend would produce, before
 * anything is stored.
 *
 * `POST /api/outbound-invoices/build/preview` answers with either a PDF or
 * JSON, so the branching here is on content-type first and status second:
 *
 *   200 + application/pdf  → object URL into `PdfViewerCanvas`
 *   409 + json             → duplicate invoice number (founder decision D5).
 *                            Handed up to the page, which shows it against the
 *                            number field in `BuilderForm`.
 *
 * FE Gap 462 (2026-09-05): the 422 branch is gone. It carried
 * `{"unlocated_fields": [...]}` from the backend's substitution renderer and
 * told the user to revert a field to its source value or add/remove a row to
 * force a re-render — asking them to work around an internal renderer
 * limitation. That renderer is deleted; every clone re-renders, so preview has
 * no refusal path left.
 *
 * The object URL is revoked when it is replaced and on unmount — a preview is
 * a multi-megabyte blob and this screen is used iteratively.
 */

interface BuilderPreviewProps {
  body: BuildRequest;
  /** Bumped by the page when the form changes, so a stale preview can be labelled as such. */
  dirtySinceLastPreview: boolean;
  onDirtyCleared: () => void;
  onDuplicateNumber: (message: string | null) => void;
  disabled?: boolean;
}

export default function BuilderPreview({
  body,
  dirtySinceLastPreview,
  onDirtyCleared,
  onDuplicateNumber,
  disabled,
}: BuilderPreviewProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
          <span>{error}</span>
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
