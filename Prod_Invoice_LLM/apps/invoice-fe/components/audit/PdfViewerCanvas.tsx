"use client";

import { ZoomIn, ZoomOut, RotateCw } from "lucide-react";
import { useState } from "react";

interface Coordinate {
  x: number;       // percentage-based left offset (0-100)
  y: number;       // percentage-based top offset (0-100)
  width: number;   // percentage-based width (0-100)
  height: number;  // percentage-based height (0-100)
  label?: string;
}

interface PdfViewerCanvasProps {
  invoiceId: string;
  title?: string;
  status?: string;
  coordinates?: Coordinate[];
}

export default function PdfViewerCanvas({
  invoiceId,
  title,
  status,
  coordinates = [],
}: PdfViewerCanvasProps) {
  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);

  const pdfUrl = `/api/invoices/${invoiceId}/pdf`;

  const statusBadge: Record<string, string> = {
    COMPLETED: "bg-emerald-500/20 text-emerald-300 border-emerald-600/50",
    AUDIT_REQUIRED: "bg-yellow-500/20 text-yellow-300 border-yellow-600/50",
    PROCESSING: "bg-blue-500/20 text-blue-300 border-blue-600/50",
    DUPLICATE: "bg-orange-500/20 text-orange-300 border-orange-600/50",
    PAID: "bg-emerald-500/20 text-emerald-300 border-emerald-600/50",
    REJECTED: "bg-red-500/20 text-red-300 border-red-600/50",
  };

  return (
    <div className="flex h-full flex-col rounded-xl border border-[#222D3D] bg-[#0F172A]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#222D3D] px-4 py-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
            Invoice PDF Viewer
          </p>
          {title && (
            <p className="mt-0.5 text-sm font-medium text-slate-200">{title}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {status && (
            <span
              className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
                statusBadge[status] ?? "bg-slate-700 text-slate-300 border-slate-600"
              }`}
            >
              {status.replace("_", " ")}
            </span>
          )}
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 border-b border-[#222D3D] px-4 py-2 text-slate-400">
        <button
          onClick={() => setZoom((z) => Math.min(z + 10, 200))}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200"
        >
          <ZoomIn size={13} /> Zoom In
        </button>
        <button
          onClick={() => setZoom((z) => Math.max(z - 10, 50))}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200"
        >
          <ZoomOut size={13} /> Zoom Out
        </button>
        <button
          onClick={() => setRotation((r) => (r + 90) % 360)}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200"
        >
          <RotateCw size={13} /> Rotate
        </button>
        <span className="ml-auto text-xs text-slate-500">{zoom}%</span>
      </div>

      {/* PDF + Overlay Container */}
      <div className="relative flex-1 overflow-auto bg-[#08101A] p-4">
        <div
          className="relative mx-auto origin-top transition-transform"
          style={{
            width: `${zoom}%`,
            transform: `rotate(${rotation}deg)`,
          }}
        >
          {/* PDF iframe */}
          <iframe
            src={pdfUrl}
            className="h-[800px] w-full rounded-md border border-[#222D3D] bg-white"
            title="Invoice PDF"
          />

          {/* Bounding Box Overlays */}
          {coordinates.map((coord, idx) => (
            <div
              key={idx}
              className="pointer-events-none absolute rounded-sm border border-emerald-400 bg-emerald-400/10 shadow-[0_0_10px_rgba(16,185,129,0.4)]"
              style={{
                left: `${coord.x}%`,
                top: `${coord.y}%`,
                width: `${coord.width}%`,
                height: `${coord.height}%`,
              }}
              title={coord.label}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
