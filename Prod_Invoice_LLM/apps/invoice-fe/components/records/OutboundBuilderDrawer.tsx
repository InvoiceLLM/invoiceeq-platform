"use client";

// =============================================================================
// FILE: components/records/OutboundBuilderDrawer.tsx
// FEATURE: FE Feature 22 Task 22.2 — Feature 20's Invoice Builder, opened in
//          place over Records' "Invoices out" tab.
//
// WHY A DRAWER AND STILL A FORM: spec §7 Q3 — the builder is the one screen
// that stays a form. The drawer wraps `components/builder/OutboundBuilder.tsx`,
// the same editor the `/invoices/outbound-builder` page renders, so Create goes
// through Feature 20's one existing handler; nothing about building is
// re-implemented here.
//
// The builder draws its controls (source link, Create) into an `Actions` slot.
// The page portals them into Shell's header; this drawer portals them into its
// own header bar, which sits above the dimmed page and its header.
// =============================================================================

import React, { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import OutboundBuilder from "@/components/builder/OutboundBuilder";

const DrawerActionsSlot = createContext<HTMLElement | null>(null);

/** Module-level so its identity is stable — a component created per render would remount the builder's controls. */
function DrawerActions({ children }: { children: ReactNode }) {
  const slot = useContext(DrawerActionsSlot);
  return slot ? createPortal(children, slot) : null;
}

interface OutboundBuilderDrawerProps {
  sourceId: string;
  onClose: () => void;
}

export default function OutboundBuilderDrawer({ sourceId, onClose }: OutboundBuilderDrawerProps) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const [invoiceNumber, setInvoiceNumber] = useState<string | null>(null);
  const handleInvoiceNumber = useCallback((value: string | null) => setInvoiceNumber(value), []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="outbound-builder-drawer-title"
        data-testid="outbound-builder-drawer"
        onClick={(event) => event.stopPropagation()}
        className="flex h-full w-full max-w-6xl flex-col border-l border-[#222D3D] bg-[#0B0F19] shadow-2xl"
      >
        <div className="flex h-16 shrink-0 items-center gap-3 border-b border-[#222D3D] px-6">
          <div className="min-w-0 flex-1">
            <h2 id="outbound-builder-drawer-title" className="text-sm font-semibold text-white">
              Invoice Builder
            </h2>
            <p className="truncate text-xs text-slate-400">
              {invoiceNumber ? `New invoice ${invoiceNumber}` : "New invoice from an existing one"}
            </p>
          </div>
          <div ref={setSlot} className="flex items-center gap-2" />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close invoice builder"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1">
          <DrawerActionsSlot.Provider value={slot}>
            <OutboundBuilder
              sourceId={sourceId}
              Actions={DrawerActions}
              onInvoiceNumberChange={handleInvoiceNumber}
              onClose={onClose}
            />
          </DrawerActionsSlot.Provider>
        </div>
      </div>
    </div>
  );
}
