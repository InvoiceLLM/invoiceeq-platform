"use client";

// =============================================================================
// FILE: app/records/page.tsx
// FEATURE: FE Feature 22 Task 22.2 — Records: "let me look something up".
//
// Four tabs, driven by `?tab=`: Invoices in / Invoices out / Documents / Rules.
// The two invoice tabs render the same ledger the Audit Queue does
// (hooks/useInvoiceLedger.ts + components/records/InvoiceLedger.tsx), with both
// hooks called here so switching tabs keeps each ledger's tab, page and filters.
//
// Service Flow applies exactly as on the Audit Queue: a direction the tenant has
// switched off has no tab, and the outbound ledger does not fetch unless Send is
// on. A `?tab=` naming a hidden tab falls back to the first visible one — but
// only once the flow is known, so a deep link to `out` is not bounced to `in`
// while the settings request is still in flight.
//
// `?tab=out&source=<id>` opens OutboundBuilderDrawer over the outbound ledger —
// both from a row's clone action and from the old `/invoices/outbound-builder`
// URL, which lib/navigation.ts redirects here with its `source` intact.
//
// Rules is RulesTable (22.8). Documents (22.7) is a shell until the backend exposes facts.
// =============================================================================

import React, { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FileStack } from "lucide-react";
import InvoiceLedger from "@/components/records/InvoiceLedger";
import OutboundBuilderDrawer from "@/components/records/OutboundBuilderDrawer";
import RulesTable from "@/components/records/RulesTable";
import { usePageHeader } from "@/components/layout/PageHeaderContext";
import { useAuth } from "@/hooks/useAuth";
import { useInboundLedger, useOutboundLedger } from "@/hooks/useInvoiceLedger";

// Not exported: an App Router page file may export only the page and Next's config names.
type RecordsTab = "in" | "out" | "documents" | "rules";

const RECORDS_TABS: readonly { key: RecordsTab; label: string }[] = [
  { key: "in", label: "Invoices in" },
  { key: "out", label: "Invoices out" },
  { key: "documents", label: "Documents" },
  { key: "rules", label: "Rules" },
];

function PlaceholderPanel({ testId, icon, title, body }: { testId: string; icon: React.ReactNode; title: string; body: string }) {
  return (
    <div
      data-testid={testId}
      className="glass-panel flex flex-col items-center justify-center gap-2 rounded-xl border border-[#222D3D] px-6 py-16 text-center"
    >
      {icon}
      <h3 className="text-sm font-semibold text-white">{title}</h3>
      <p className="max-w-md text-xs text-slate-400">{body}</p>
    </div>
  );
}

function RecordsContent() {
  usePageHeader({ title: "Records" });

  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const sourceId = searchParams.get("source");

  const { loading: authLoading } = useAuth();
  const [receiveEnabled, setReceiveEnabled] = useState(true);
  const [sendEnabled, setSendEnabled] = useState(false);
  const [flowLoaded, setFlowLoaded] = useState(false);

  const inbound = useInboundLedger(!authLoading);
  const outbound = useOutboundLedger(!authLoading && sendEnabled);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/settings/service-flow")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setReceiveEnabled(data.receive_invoices_enabled ?? true);
        setSendEnabled(data.send_invoices_enabled ?? false);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setFlowLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const tabAllowed = (key: RecordsTab) => {
    if (!flowLoaded) return true;
    if (key === "in") return receiveEnabled;
    if (key === "out") return sendEnabled;
    return true;
  };
  const visibleTabs = RECORDS_TABS.filter((tab) => tabAllowed(tab.key));
  const activeTab: RecordsTab =
    visibleTabs.find((tab) => tab.key === requestedTab)?.key ?? visibleTabs[0]?.key ?? "documents";

  const selectTab = (key: RecordsTab) => router.replace(`/records?tab=${key}`);

  return (
    <div className="space-y-6">
      <div role="tablist" aria-label="Records" className="flex w-fit items-center gap-1 rounded-lg border border-[#222D3D] bg-[#0B0F19] p-1">
        {visibleTabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.key}
            onClick={() => selectTab(tab.key)}
            className={`rounded-md px-4 py-1.5 text-xs font-medium transition-colors ${
              activeTab === tab.key ? "bg-[#3B82F6] text-white" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "in" && <InvoiceLedger ledger={inbound} />}

      {activeTab === "out" && (
        <InvoiceLedger
          ledger={outbound}
          onCloneInvoice={(id) => router.push(`/records?tab=out&source=${encodeURIComponent(id)}`)}
        />
      )}

      {activeTab === "documents" && (
        <PlaceholderPanel
          testId="records-documents"
          icon={<FileStack className="h-6 w-6 text-slate-500" />}
          title="Documents"
          body="Every document that left facts behind — and where those facts went — will be listed here."
        />
      )}

      {activeTab === "rules" && <RulesTable />}

      {activeTab === "out" && sourceId && (
        <OutboundBuilderDrawer sourceId={sourceId} onClose={() => router.replace("/records?tab=out")} />
      )}
    </div>
  );
}

export default function RecordsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-xs text-white">Loading Records…</div>}>
      <RecordsContent />
    </Suspense>
  );
}
