"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import OutboundBuilder from "@/components/builder/OutboundBuilder";
import { PageHeaderActions, usePageHeader } from "@/components/layout/PageHeaderContext";

/**
 * Feature 20: the Invoice Builder as a page — `?source=<id>`.
 *
 * FE Feature 22 Task 22.2 moved the editor itself into
 * `components/builder/OutboundBuilder.tsx` so Records' `OutboundBuilderDrawer`
 * runs the same form and the same Create handler. This page keeps what is
 * page-specific: the source from the URL, the shared header's title, and its
 * actions portal. With the four surfaces on, this route redirects to
 * `/records?tab=out&source=<id>`, which opens the drawer (lib/navigation.ts);
 * the classic layout (22.21) still renders it here.
 */
function OutboundBuilderContent() {
  const searchParams = useSearchParams();
  const [invoiceNumber, setInvoiceNumber] = useState<string | null>(null);

  usePageHeader({
    title: "Invoice Builder",
    agentIcon: "🛡️",
    agentName: "SENTINEL",
    agentRole: "Audit & Compliance",
    subtitle: invoiceNumber ? `New invoice ${invoiceNumber}` : "New invoice from an existing one",
    backHref: "/invoices",
  });

  return (
    <OutboundBuilder
      sourceId={searchParams.get("source")}
      Actions={PageHeaderActions}
      onInvoiceNumberChange={setInvoiceNumber}
    />
  );
}

export default function OutboundBuilderPage() {
  return (
    <Suspense fallback={<div className="p-8 text-xs text-white">Loading Invoice Builder…</div>}>
      <OutboundBuilderContent />
    </Suspense>
  );
}
