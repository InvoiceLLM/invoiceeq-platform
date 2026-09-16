"use client";

// =============================================================================
// FILE: components/records/InvoiceLedger.tsx
// FEATURE: FE Feature 22 Task 22.2 — one direction's filter bar + InvoiceTable,
//          driven by a ledger from hooks/useInvoiceLedger.ts.
//
// Rendered by the Audit Queue's Receiving / Sending panes and by Records'
// "Invoices in" / "Invoices out" tabs. The state is passed in, not owned here,
// so a host that toggles panes keeps each ledger's tab, page and filters.
// =============================================================================

import React from "react";
import FilterBar from "@/components/dashboard/FilterBar";
import OutboundFilterBar from "@/components/dashboard/OutboundFilterBar";
import InvoiceTable from "@/components/records/InvoiceTable";
import type { InvoiceLedger as Ledger } from "@/hooks/useInvoiceLedger";

interface InvoiceLedgerProps {
  ledger: Ledger;
  /** Outbound only: open the Invoice Builder in place instead of navigating to its page. */
  onCloneInvoice?: (sourceId: string) => void;
}

export default function InvoiceLedger({ ledger, onCloneInvoice }: InvoiceLedgerProps) {
  if (ledger.direction === "in") {
    return (
      <>
        <FilterBar
          onFilterChange={ledger.onFilterChange}
          availableVendors={ledger.vendorOptions}
          availableTags={ledger.tagOptions}
          statusFilterDisabled={ledger.statusFilterDisabled}
        />

        <InvoiceTable
          direction="in"
          invoices={ledger.invoices}
          isLoading={ledger.isLoading}
          onDelete={ledger.onDelete}
          onStatusChange={ledger.onStatusChange}
          activeTab={ledger.activeTab}
          onTabChange={ledger.onTabChange}
          currentPage={ledger.currentPage}
          totalPages={ledger.totalPages}
          totalCount={ledger.totalCount}
          onPageChange={ledger.setCurrentPage}
          isFullPage={true}
        />
      </>
    );
  }

  return (
    <>
      <OutboundFilterBar onFilterChange={ledger.onFilterChange} availableCustomers={ledger.customerOptions} />

      <InvoiceTable
        direction="out"
        invoices={ledger.invoices}
        isLoading={ledger.isLoading}
        onDelete={ledger.onDelete}
        activeTab={ledger.activeTab}
        onTabChange={ledger.onTabChange}
        currentPage={ledger.currentPage}
        totalPages={ledger.totalPages}
        totalCount={ledger.totalCount}
        onPageChange={ledger.setCurrentPage}
        onCloneInvoice={onCloneInvoice}
      />
    </>
  );
}
