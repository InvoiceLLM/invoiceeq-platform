"use client";

import React, { useState, useEffect } from "react";
import InvoiceLedger from "../../components/records/InvoiceLedger";
import { PageHeaderActions, usePageHeader } from "../../components/layout/PageHeaderContext";
import { useAuth } from "../../hooks/useAuth";
import { useInboundLedger, useOutboundLedger } from "../../hooks/useInvoiceLedger";

// Relocated from dashboard/page.tsx (Task 4.9, Dashboard/Audit split) --
// Dashboard is overview-only now; this page is the actual invoice queue.
//
// FE Feature 22 Task 22.2: each direction's fetching, filters and paging moved
// into hooks/useInvoiceLedger.ts and the filter bar + table into
// components/records/InvoiceLedger.tsx, so Records renders the identical ledger.
// Both hooks are called here, above the panes, so toggling Receiving/Sending
// keeps each pane's tab, page and filters (tests/unit/invoices-page-parity.test.tsx).

type InvoicesTab = "receiving" | "sending";

export default function InvoicesPage() {
  // FE Gap 110: title + SENTINEL badge now live in Shell's one shared header.
  usePageHeader({
    title: "Audit Queue",
    agentIcon: "🛡️",
    agentName: "SENTINEL",
    agentRole: "Audit & Compliance",
  });

  const { loading: authLoading } = useAuth();

  // Task 4.1.4/4.1.5 (Service Flow): only shown when both Receive/Send are
  // enabled, mirroring ingestion/page.tsx's tab-visibility rule.
  const [receiveEnabled, setReceiveEnabled] = useState(true);
  const [sendEnabled, setSendEnabled] = useState(false);
  const [invoicesTab, setInvoicesTab] = useState<InvoicesTab>("receiving");

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
        if (!data.receive_invoices_enabled && data.send_invoices_enabled) {
          setInvoicesTab("sending");
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const showTabs = receiveEnabled && sendEnabled;
  const showReceiving = !sendEnabled || invoicesTab === "receiving";
  const showSending = (sendEnabled && !receiveEnabled) || (showTabs && invoicesTab === "sending");

  return (
    <div className="space-y-6">
      {/* FE Gap 110: title + SENTINEL badge moved to Shell's shared header, and
          the Receiving/Sending toggle follows it there via the header's actions
          portal -- same treatment Ingestion gets, so the two screens' tab rows
          stay consistent with each other. */}
      {showTabs && (
        <PageHeaderActions>
          <div className="flex items-center gap-1 bg-[#0B0F19] border border-[#222D3D] rounded-lg p-1 w-fit">
            <button
              onClick={() => setInvoicesTab("receiving")}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                invoicesTab === "receiving" ? "bg-[#3B82F6] text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Receiving
            </button>
            <button
              onClick={() => setInvoicesTab("sending")}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                invoicesTab === "sending" ? "bg-[#3B82F6] text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Sending
            </button>
          </div>
        </PageHeaderActions>
      )}

      {showReceiving && <InvoiceLedger ledger={inbound} />}

      {showSending && <InvoiceLedger ledger={outbound} />}
    </div>
  );
}
