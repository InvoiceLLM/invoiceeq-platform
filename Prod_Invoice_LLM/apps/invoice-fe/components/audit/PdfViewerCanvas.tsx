"use client";

import { ZoomIn, ZoomOut, RotateCw, Maximize2, X } from "lucide-react";
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
  const [isModalOpen, setIsModalOpen] = useState(false);

  const isRotated = rotation % 180 !== 0;
  const pdfUrl = `/api/invoices/${invoiceId}/pdf`;

  const statusBadge: Record<string, string> = {
    COMPLETED: "bg-emerald-500/20 text-emerald-300 border-emerald-600/50",
    AUDIT_REQUIRED: "bg-yellow-500/20 text-yellow-300 border-yellow-600/50",
    PROCESSING: "bg-blue-500/20 text-blue-300 border-blue-600/50",
    DUPLICATE: "bg-orange-500/20 text-orange-300 border-orange-600/50",
    PAID: "bg-emerald-500/20 text-emerald-300 border-emerald-600/50",
    REJECTED: "bg-red-500/20 text-red-300 border-red-600/50",
  };

  const handleZoomIn = () => setZoom((z) => Math.min(z + 15, 250));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 15, 50));
  const handleRotate = () => setRotation((r) => (r + 90) % 360);

  return (
    <div className="flex h-full min-h-[500px] xl:min-h-0 flex-col rounded-xl border border-[#222D3D] bg-[#0F172A]">
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
      <div className="flex items-center gap-2 border-b border-[#222D3D] px-4 py-2 text-slate-400">
        <button
          type="button"
          onClick={handleZoomIn}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200"
        >
          <ZoomIn size={13} /> Zoom In
        </button>
        <button
          type="button"
          onClick={handleZoomOut}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200"
        >
          <ZoomOut size={13} /> Zoom Out
        </button>
        <button
          type="button"
          onClick={handleRotate}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200"
        >
          <RotateCw size={13} /> Rotate
        </button>
        <span className="text-xs text-slate-500 font-mono ml-1">{zoom}%</span>

        {/* Gap 155: Fullscreen Lightbox Modal Button */}
        <button
          type="button"
          onClick={() => setIsModalOpen(true)}
          className="ml-auto flex items-center gap-1 rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-300 transition hover:bg-blue-500/20"
        >
          <Maximize2 size={13} /> Expand PDF
        </button>
      </div>

      {/* PDF + Overlay Container */}
      <div className="relative flex-1 overflow-auto bg-[#08101A] p-4 flex items-start justify-center">
        <div
          className="relative transition-all duration-200"
          style={{
            width: `${zoom}%`,
            minWidth: "100%",
            transform: `rotate(${rotation}deg)`,
            transformOrigin: "center top",
          }}
        >
          {/* PDF iframe */}
          <iframe
            src={pdfUrl}
            className="h-[800px] w-full rounded-md border border-[#222D3D] bg-white shadow-xl"
            title="Invoice PDF"
          />

          {/* Bounding Box Overlays */}
          {coordinates.map((coord, idx) => (
            <div
              key={idx}
              className="pointer-events-none absolute rounded-sm border-2 border-emerald-400 bg-emerald-400/20 shadow-[0_0_12px_rgba(16,185,129,0.5)]"
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

      {/* Gap 155: Lightbox Modal Pop-out */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex flex-col bg-slate-950/95 backdrop-blur-md p-6">
          <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-white">{title || "Invoice PDF Preview"}</span>
              <span className="text-xs font-mono text-slate-400">{zoom}%</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleZoomIn}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
              >
                <ZoomIn size={16} />
              </button>
              <button
                type="button"
                onClick={handleZoomOut}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
              >
                <ZoomOut size={16} />
              </button>
              <button
                type="button"
                onClick={handleRotate}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
              >
                <RotateCw size={16} />
              </button>
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                className="p-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 ml-2"
              >
                <X size={16} />
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-auto flex items-center justify-center p-4">
            <iframe
              src={pdfUrl}
              className="h-full w-full max-w-5xl rounded-xl border border-slate-800 bg-white shadow-2xl"
              title="Expanded Invoice PDF"
            />
          </div>
        </div>
      )}
    </div>
  );
}
