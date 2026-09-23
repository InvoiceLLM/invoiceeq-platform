"use client";

import { ZoomIn, ZoomOut, RotateCw, Maximize2, X } from "lucide-react";
import { useState, useRef, useEffect } from "react";

interface PdfViewerCanvasProps {
  /** Stored invoice to display. Omit when passing `srcUrl` instead. */
  invoiceId?: string;
  /**
   * Feature 20: an explicit PDF URL, used by the Invoice Builder's preview.
   * That PDF is the response body of a `POST` and has never been stored, so it
   * has no invoice id to fetch by — the builder hands over an object URL for a
   * blob it already holds. When set it wins over `invoiceId`; everything else
   * about this viewer (zoom, rotate, expand modal) is unchanged.
   */
  srcUrl?: string;
  title?: string;
  status?: string;
}

export default function PdfViewerCanvas({
  invoiceId,
  srcUrl,
  title,
  status,
}: PdfViewerCanvasProps) {
  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);
  const [isModalOpen, setIsModalOpen] = useState(false);
  // Gap 154/155: isolated modal transform state — these are completely separate from
  // the inline viewer state so that rotating in the modal does not leak back into
  // the background viewer and vice-versa.
  const [modalZoom, setModalZoom] = useState(100);
  const [modalRotation, setModalRotation] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(480);

  const modalContainerRef = useRef<HTMLDivElement>(null);
  const [modalContainerWidth, setModalContainerWidth] = useState(800);
  const [modalContainerHeight, setModalContainerHeight] = useState(600);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        if (w > 0) {
          setContainerWidth(Math.floor(w));
        }
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!isModalOpen) return;
    const el = modalContainerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0) setModalContainerWidth(Math.floor(width));
        if (height > 0) setModalContainerHeight(Math.floor(height));
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [isModalOpen]);

  const isRotated = rotation % 180 !== 0;
  const isModalRotated = modalRotation % 180 !== 0;
  const pdfUrl = srcUrl ?? `/api/invoices/${invoiceId}/pdf`;

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

  // Gap 154/155: isolated modal controls — only affect modalZoom / modalRotation.
  const handleModalZoomIn = () => setModalZoom((z) => Math.min(z + 15, 250));
  const handleModalZoomOut = () => setModalZoom((z) => Math.max(z - 15, 50));
  const handleModalRotate = () => setModalRotation((r) => (r + 90) % 360);

  const handleOpenModal = () => {
    // Reset modal to default view on open so it starts clean regardless of inline viewer state.
    setModalZoom(100);
    setModalRotation(0);
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
    // Explicitly reset so reopening starts fresh and inline viewer is unaffected.
    setModalZoom(100);
    setModalRotation(0);
  };

  // Base canvas dimensions
  const BASE_HEIGHT = 760;
  const effectiveWidth = Math.max(containerWidth - 32, 280);

  const modalBaseHeight = Math.max(modalContainerHeight - 40, 500);
  const modalBaseWidth = Math.max(Math.min(modalContainerWidth - 40, modalBaseHeight * 0.75), 320);

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
      <div className="flex items-center gap-1 sm:gap-1.5 2xl:gap-2 border-b border-[#222D3D] px-2 sm:px-2.5 2xl:px-4 py-2 text-slate-400 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <button
          type="button"
          onClick={handleZoomIn}
          title="Zoom In"
          aria-label="Zoom In"
          className="flex items-center gap-1 rounded p-1 sm:px-1.5 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200 shrink-0 whitespace-nowrap"
        >
          <ZoomIn size={13} className="shrink-0" />
          <span className="hidden 2xl:inline">Zoom In</span>
        </button>
        <button
          type="button"
          onClick={handleZoomOut}
          title="Zoom Out"
          aria-label="Zoom Out"
          className="flex items-center gap-1 rounded p-1 sm:px-1.5 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200 shrink-0 whitespace-nowrap"
        >
          <ZoomOut size={13} className="shrink-0" />
          <span className="hidden 2xl:inline">Zoom Out</span>
        </button>
        <button
          type="button"
          onClick={handleRotate}
          title="Rotate"
          aria-label="Rotate"
          className="flex items-center gap-1 rounded p-1 sm:px-1.5 py-1 text-xs transition hover:bg-[#1E293B] hover:text-slate-200 shrink-0 whitespace-nowrap"
        >
          <RotateCw size={13} className="shrink-0" />
          <span className="hidden 2xl:inline">Rotate</span>
        </button>
        <span className="text-xs text-slate-500 font-mono ml-0.5 sm:ml-1 shrink-0">{zoom}%</span>

        {/* Gap 155: Fullscreen Lightbox Modal Button */}
        <button
          type="button"
          onClick={handleOpenModal}
          title="Expand PDF"
          aria-label="Expand PDF"
          data-testid="expand-pdf-btn"
          className="expand-pdf-btn ml-auto flex items-center gap-1 rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs font-medium text-blue-300 transition hover:bg-blue-500/20 shrink-0 whitespace-nowrap"
        >
          <Maximize2 size={13} className="shrink-0" />
          <span>Expand PDF</span>
        </button>
      </div>

      {/* PDF + Overlay Container */}
      <div
        ref={containerRef}
        className="relative flex-1 overflow-auto bg-[#08101A] p-2 sm:p-4 flex min-h-[400px]"
      >
        {!isRotated ? (
          <div
            className="m-auto transition-all duration-200 shrink-0"
            style={{
              width: `${zoom}%`,
              minWidth: "100%",
              height: `${BASE_HEIGHT}px`,
              transform: rotation === 180 ? "rotate(180deg)" : undefined,
              transformOrigin: "center center",
            }}
          >
            {!isModalOpen ? (
              <iframe
                src={pdfUrl}
                className="h-full w-full rounded-md border border-[#222D3D] bg-white shadow-xl"
                title="Invoice PDF"
              />
            ) : (
              <div className="h-full w-full rounded-md border border-[#222D3D] bg-[#0F172A] flex items-center justify-center text-xs text-slate-500 italic">
                PDF expanded in modal view
              </div>
            )}
          </div>
        ) : (
          <div
            className="m-auto relative transition-all duration-200 shrink-0"
            style={{
              width: `${BASE_HEIGHT * (zoom / 100)}px`,
              height: `${effectiveWidth * (zoom / 100)}px`,
              minWidth: `${BASE_HEIGHT * (zoom / 100)}px`,
              minHeight: `${effectiveWidth * (zoom / 100)}px`,
            }}
          >
            {!isModalOpen ? (
              <iframe
                src={pdfUrl}
                style={{
                  position: "absolute",
                  left: "50%",
                  top: "50%",
                  width: `${effectiveWidth}px`,
                  height: `${BASE_HEIGHT}px`,
                  transform: `translate(-50%, -50%) rotate(${rotation}deg) scale(${zoom / 100})`,
                  transformOrigin: "center center",
                }}
                className="rounded-md border border-[#222D3D] bg-white shadow-xl"
                title="Invoice PDF"
              />
            ) : (
              <div
                style={{
                  position: "absolute",
                  left: "50%",
                  top: "50%",
                  width: `${effectiveWidth}px`,
                  height: `${BASE_HEIGHT}px`,
                  transform: `translate(-50%, -50%) rotate(${rotation}deg) scale(${zoom / 100})`,
                  transformOrigin: "center center",
                }}
                className="rounded-md border border-[#222D3D] bg-[#0F172A] flex items-center justify-center text-xs text-slate-500 italic"
              >
                PDF expanded in modal view
              </div>
            )}
          </div>
        )}
      </div>

      {/* Gap 154/155: Lightbox Modal Pop-out — with isolated zoom/rotation state */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex flex-col bg-slate-950/95 backdrop-blur-md p-6">
          <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-white">{title || "Invoice PDF Preview"}</span>
              {/* Gap 154: show modal-specific zoom level, not inline viewer's */}
              <span className="text-xs font-mono text-slate-400">{modalZoom}%</span>
              {modalRotation > 0 && (
                <span className="text-xs font-mono text-slate-500">{modalRotation}°</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {/* Gap 154: modal zoom/rotate controls use isolated handlers */}
              <button
                type="button"
                onClick={handleModalZoomIn}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
                title="Zoom In (modal)"
              >
                <ZoomIn size={16} />
              </button>
              <button
                type="button"
                onClick={handleModalZoomOut}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
                title="Zoom Out (modal)"
              >
                <ZoomOut size={16} />
              </button>
              <button
                type="button"
                onClick={handleModalRotate}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300"
                title="Rotate (modal only — does not affect background viewer)"
              >
                <RotateCw size={16} />
              </button>
              <button
                type="button"
                onClick={handleCloseModal}
                className="p-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 ml-2"
              >
                <X size={16} />
              </button>
            </div>
          </div>
          <div
            ref={modalContainerRef}
            className="flex-1 overflow-auto flex p-4"
          >
            {!isModalRotated ? (
              <div
                style={{
                  width: `${modalZoom}%`,
                  minWidth: "300px",
                  maxWidth: "100%",
                  transform: modalRotation === 180 ? "rotate(180deg)" : undefined,
                  transformOrigin: "center center",
                  transition: "transform 0.2s ease, width 0.2s ease",
                }}
                className="h-full m-auto"
              >
                <iframe
                  src={pdfUrl}
                  className="h-full w-full min-h-[70vh] rounded-xl border border-slate-800 bg-white shadow-2xl"
                  title="Expanded Invoice PDF"
                />
              </div>
            ) : (
              <div
                style={{
                  width: `${modalBaseHeight * (modalZoom / 100)}px`,
                  height: `${modalBaseWidth * (modalZoom / 100)}px`,
                  minWidth: `${modalBaseHeight * (modalZoom / 100)}px`,
                  minHeight: `${modalBaseWidth * (modalZoom / 100)}px`,
                  position: "relative",
                  margin: "auto",
                }}
                className="shrink-0"
              >
                <iframe
                  src={pdfUrl}
                  style={{
                    position: "absolute",
                    left: "50%",
                    top: "50%",
                    width: `${modalBaseWidth}px`,
                    height: `${modalBaseHeight}px`,
                    transform: `translate(-50%, -50%) rotate(${modalRotation}deg) scale(${modalZoom / 100})`,
                    transformOrigin: "center center",
                  }}
                  className="rounded-xl border border-slate-800 bg-white shadow-2xl"
                  title="Expanded Invoice PDF"
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
