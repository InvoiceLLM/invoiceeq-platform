"use client";

// =============================================================================
// FILE: hooks/useInvoiceLedger.ts
// FEATURE: FE Feature 22 Task 22.2 — one invoice ledger's state and fetching,
//          for either direction.
//
// WHY A HOOK, NOT A COMPONENT: this logic used to live inline in
// app/invoices/page.tsx. Records needs the identical ledger, but the Audit Queue
// shows its two directions as panes the user toggles between, and it keeps each
// pane's tab, page and filters across that toggle. A self-fetching component per
// pane would lose that state on every toggle and refetch on every return. State
// in a hook, called by whichever page owns the panes, keeps both behaviours —
// pinned by tests/unit/invoices-page-parity.test.tsx, whose snapshots were
// recorded against the page before this extraction.
//
// Moved verbatim: FE Gap 29 (real server pagination via X-Total-Count), FE Gap 5
// / Task 4.1.5 (status-tab -> query params), Gap 282 (outbound delete refetch),
// Gap 277 (refetch after a status change).
// =============================================================================

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/apiClient";
import { toLocalDateString } from "@/lib/utils";
import type { FilterState } from "@/components/dashboard/FilterBar";
import type { OutboundFilterState } from "@/components/dashboard/OutboundFilterBar";
import type {
  InvoiceRecord,
  OutboundInvoiceRecord,
  OutboundStatusTab,
  StatusTab,
} from "@/components/records/InvoiceTable";

export const LEDGER_PAGE_SIZE = 8;

function tabToStatusParams(tab: StatusTab): { status?: string; status_in?: string } {
  if (tab === "paid") return { status: "PAID" };
  if (tab === "rejected") return { status: "REJECTED" };
  if (tab === "audit_required") return { status: "AUDIT_REQUIRED" };
  if (tab === "pending") return { status_in: "PROCESSING,COMPLETED,DUPLICATE,REVIEW_LATER,NEEDS_RESUBMISSION" };
  return {};
}

// Task 4.1.5: Pending bundles every in-flight status; Overdue is the read-time
// virtual filter (see routers/outbound_dashboard.py).
function outboundTabToStatusParams(tab: OutboundStatusTab): { status?: string; status_in?: string } {
  if (tab === "paid") return { status: "PAID" };
  if (tab === "overdue") return { status: "overdue" };
  if (tab === "pending") return { status_in: "UPLOADED,PROCESSING_OCR,EXTRACTING_DATA,VERIFIED,NEEDS_REVIEW,SENT" };
  return {};
}

function getDatesForRange(range: string) {
  const today = new Date();
  let startDate: string | undefined = undefined;
  let endDate: string | undefined = toLocalDateString(today);

  if (range === "this_month") {
    const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
    startDate = toLocalDateString(firstDay);
  } else if (range === "last_30_days") {
    const prior = new Date();
    prior.setDate(today.getDate() - 30);
    startDate = toLocalDateString(prior);
  } else if (range === "last_90_days") {
    const prior = new Date();
    prior.setDate(today.getDate() - 90);
    startDate = toLocalDateString(prior);
  } else {
    endDate = undefined;
  }
  return { startDate, endDate };
}

interface LedgerPaging {
  isLoading: boolean;
  currentPage: number;
  setCurrentPage: (page: number) => void;
  totalCount: number;
  totalPages: number;
}

export interface InboundLedger extends LedgerPaging {
  direction: "in";
  invoices: InvoiceRecord[];
  activeTab: StatusTab;
  onTabChange: (tab: StatusTab) => void;
  onFilterChange: (filters: FilterState) => void;
  onDelete: (id: string) => void;
  onStatusChange: (id: string, newStatus: string) => void;
  /** Dropdown options, from a separate 100-row read, as before. */
  vendorOptions: string[];
  tagOptions: string[];
  statusFilterDisabled: boolean;
}

export interface OutboundLedger extends LedgerPaging {
  direction: "out";
  invoices: OutboundInvoiceRecord[];
  activeTab: OutboundStatusTab;
  onTabChange: (tab: OutboundStatusTab) => void;
  onFilterChange: (filters: OutboundFilterState) => void;
  onDelete: (id: string) => void;
  customerOptions: string[];
}

export type InvoiceLedger = InboundLedger | OutboundLedger;

/**
 * Inbound ledger (`GET /invoices`). `enabled` is the caller's gate — identity
 * resolved — and no request is made until it is true.
 */
export function useInboundLedger(enabled: boolean): InboundLedger {
  const [filters, setFilters] = useState<FilterState>({
    vendorName: "",
    dateRange: "all",
    tag: "",
    status: "",
  });
  const [invoices, setInvoices] = useState<InvoiceRecord[]>([]);
  const [allInvoices, setAllInvoices] = useState<InvoiceRecord[]>([]); // for vendor/tag dropdown options only
  const [activeTab, setActiveTab] = useState<StatusTab>("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!enabled) return;
    const fetchAllData = async () => {
      try {
        const res = await apiClient.get("/invoices", { params: { limit: 100 } });
        setAllInvoices(res.data || []);
      } catch (err) {
        console.error("Error fetching filter source data", err);
      }
    };
    fetchAllData();
  }, [enabled]);

  const fetchPage = useCallback(async () => {
    if (!enabled) return;
    setIsLoading(true);
    const { startDate, endDate } = getDatesForRange(filters.dateRange);

    try {
      const res = await apiClient.get("/invoices", {
        params: {
          start_date: startDate,
          end_date: endDate,
          vendor_name: filters.vendorName || undefined,
          tag: filters.tag || undefined,
          limit: LEDGER_PAGE_SIZE,
          offset: (currentPage - 1) * LEDGER_PAGE_SIZE,
          ...(activeTab === "all" ? { status: filters.status || undefined } : tabToStatusParams(activeTab)),
        },
      });

      setInvoices(res.data || []);
      const totalHeader = res.headers?.["x-total-count"];
      setTotalCount(totalHeader ? parseInt(totalHeader, 10) : (res.data || []).length);
    } catch (err) {
      console.error("Error loading invoices page", err);
    } finally {
      setIsLoading(false);
    }
  }, [filters, activeTab, currentPage, enabled]);

  useEffect(() => {
    fetchPage();
  }, [fetchPage]);

  const vendorOptions = Array.from(
    new Set(
      allInvoices
        .map((inv) => inv.vendor_name)
        .filter((name): name is string => typeof name === "string" && name.trim() !== "")
    )
  );
  const tagOptions = Array.from(
    new Set(
      allInvoices
        .flatMap((inv) => inv.tags || [])
        .filter((t): t is string => typeof t === "string" && t.trim() !== "")
    )
  );

  return {
    direction: "in",
    invoices,
    isLoading,
    activeTab,
    onTabChange: (tab) => {
      setActiveTab(tab);
      setCurrentPage(1);
    },
    onFilterChange: (next) => {
      setFilters(next);
      setCurrentPage(1);
    },
    onDelete: (id) => {
      setAllInvoices((prev) => prev.filter((inv) => inv.id !== id));
      fetchPage();
    },
    // Gap 277: refetch after a status change so the row reflects reality immediately.
    onStatusChange: () => {
      fetchPage();
    },
    currentPage,
    setCurrentPage,
    totalCount,
    totalPages: Math.max(1, Math.ceil(totalCount / LEDGER_PAGE_SIZE)),
    vendorOptions,
    tagOptions,
    statusFilterDisabled: activeTab !== "all",
  };
}

/**
 * Outbound ledger (`GET /outbound-dashboard/invoices`) — same pagination
 * contract, own endpoint. `enabled` must also require Send to be switched on.
 */
export function useOutboundLedger(enabled: boolean): OutboundLedger {
  const [invoices, setInvoices] = useState<OutboundInvoiceRecord[]>([]);
  const [filters, setFilters] = useState<OutboundFilterState>({ customerName: "", dateRange: "all" });
  const [activeTab, setActiveTab] = useState<OutboundStatusTab>("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [customerOptions, setCustomerOptions] = useState<string[]>([]);

  useEffect(() => {
    if (!enabled) return;
    const fetchCustomers = async () => {
      try {
        const res = await apiClient.get("/outbound-dashboard/invoices", { params: { limit: 100 } });
        const names = (res.data || [])
          .map((inv: OutboundInvoiceRecord) => inv.customer_name)
          .filter((name: unknown): name is string => typeof name === "string" && name.trim() !== "");
        setCustomerOptions(Array.from(new Set<string>(names)));
      } catch (err) {
        console.error("Error fetching outbound customer options", err);
      }
    };
    fetchCustomers();
  }, [enabled]);

  const fetchPage = useCallback(async () => {
    if (!enabled) return;
    setIsLoading(true);
    const { startDate, endDate } = getDatesForRange(filters.dateRange);

    try {
      const res = await apiClient.get("/outbound-dashboard/invoices", {
        params: {
          start_date: startDate,
          end_date: endDate,
          customer_name: filters.customerName || undefined,
          limit: LEDGER_PAGE_SIZE,
          offset: (currentPage - 1) * LEDGER_PAGE_SIZE,
          ...outboundTabToStatusParams(activeTab),
        },
      });
      setInvoices(res.data || []);
      const totalHeader = res.headers?.["x-total-count"];
      setTotalCount(totalHeader ? parseInt(totalHeader, 10) : (res.data || []).length);
    } catch (err) {
      console.error("Error loading outbound invoices page", err);
    } finally {
      setIsLoading(false);
    }
  }, [filters, activeTab, currentPage, enabled]);

  useEffect(() => {
    fetchPage();
  }, [fetchPage]);

  return {
    direction: "out",
    invoices,
    isLoading,
    activeTab,
    onTabChange: (tab) => {
      setActiveTab(tab);
      setCurrentPage(1);
    },
    onFilterChange: (next) => {
      setFilters(next);
      setCurrentPage(1);
    },
    // Gap 282: drop the row, then refetch so the count and paging stay honest.
    onDelete: (id) => {
      setInvoices((prev) => prev.filter((inv) => inv.id !== id));
      fetchPage();
    },
    currentPage,
    setCurrentPage,
    totalCount,
    totalPages: Math.max(1, Math.ceil(totalCount / LEDGER_PAGE_SIZE)),
    customerOptions,
  };
}
