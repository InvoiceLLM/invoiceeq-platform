"use client";

import React, { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import FilterBar, { FilterState } from "../../components/dashboard/FilterBar";
import RecentInvoicesTable, { StatusTab } from "../../components/dashboard/RecentInvoicesTable";
import OutboundFilterBar, { OutboundFilterState } from "../../components/dashboard/OutboundFilterBar";
import OutboundInvoicesTable, { OutboundStatusTab } from "../../components/dashboard/OutboundInvoicesTable";
import { PageHeaderActions, usePageHeader } from "../../components/layout/PageHeaderContext";
import { apiClient } from "../../lib/apiClient";
import { useAuth } from "../../hooks/useAuth";
import { toLocalDateString } from "../../lib/utils";
import { INVOICE_STATUS_PARAM, INVOICE_VENDOR_PARAM } from "../../lib/atlas";

// Relocated from dashboard/page.tsx (Task 4.9, Dashboard/Audit split) --
// Dashboard is overview-only now; this page is the actual invoice queue.
const PAGE_SIZE = 8;

function tabToStatusParams(tab: StatusTab): { status?: string; status_in?: string } {
  if (tab === "paid") return { status: "PAID" };
  if (tab === "rejected") return { status: "REJECTED" };
  if (tab === "audit_required") return { status: "AUDIT_REQUIRED" };
  if (tab === "pending") return { status_in: "PROCESSING,COMPLETED,DUPLICATE,REVIEW_LATER,NEEDS_RESUBMISSION" };
  return {};
}

// Task 4.1.5: outbound's 4-tab shape -- Pending bundles every in-flight
// status, Overdue is the read-time virtual filter (see routers/outbound_dashboard.py).
function outboundTabToStatusParams(tab: OutboundStatusTab): { status?: string; status_in?: string } {
  if (tab === "paid") return { status: "PAID" };
  if (tab === "overdue") return { status: "overdue" };
  if (tab === "pending") return { status_in: "UPLOADED,PROCESSING_OCR,EXTRACTING_DATA,VERIFIED,NEEDS_REVIEW,SENT" };
  return {};
}

type InvoicesTab = "receiving" | "sending";

/**
 * FE Gap 702 — THE OTHER HALF OF THE SEAM. This page now reads the two query
 * parameters `lib/atlas.ts::actionDestination()` sends, and those two functions
 * were changed in the same commit.
 *
 * The gap that produced this was filed rather than worked around precisely
 * because the tempting fix is to append a query string and stop: a parameter one
 * side sends and no page reads is the F33/F22 defect class in miniature -- it
 * looks like the feature works while doing nothing. So the parameter names are
 * imported from `lib/atlas.ts` rather than retyped here; two literals that agree
 * today are how the seam reopens.
 *
 * Only `status` and `vendor` are read, because they are the only two the ATLAS
 * destinations send and the only two `GET /invoices` filters on by a single
 * value. `tag` and the date range stay component state -- lifting them would be
 * a URL-state refactor nobody asked this change for.
 */
function urlFilters(params: ReturnType<typeof useSearchParams>): Partial<FilterState> {
  const seeded: Partial<FilterState> = {};
  const status = params?.get(INVOICE_STATUS_PARAM);
  if (status) seeded.status = status;
  const vendor = params?.get(INVOICE_VENDOR_PARAM);
  if (vendor) seeded.vendorName = vendor;
  return seeded;
}

/**
 * `useSearchParams()` opts a page into client-side rendering and Next 14 requires
 * the boundary to be explicit, so the page body moved down one level rather than
 * the hook being smuggled in through `window.location`.
 */
export default function InvoicesPage() {
  return (
    <Suspense fallback={null}>
      <InvoicesPageBody />
    </Suspense>
  );
}

function InvoicesPageBody() {
  // FE Gap 110: title + SENTINEL badge now live in Shell's one shared header.
  usePageHeader({
    title: "Audit Queue",
    agentIcon: "🛡️",
    agentName: "SENTINEL",
    agentRole: "Audit & Compliance",
  });

  const { loading: authLoading } = useAuth();
  // FE Gap 702: read once, at mount. The seed decides what the first fetch asks
  // for; after that the user's own filter edits own this state, and a later URL
  // change is a navigation, which remounts.
  const searchParams = useSearchParams();
  const [seededFilters] = useState<Partial<FilterState>>(() => urlFilters(searchParams));
  const [filters, setFilters] = useState<FilterState>({
    vendorName: "",
    dateRange: "all",
    tag: "",
    status: "",
    ...seededFilters,
  });

  const [invoices, setInvoices] = useState([]);
  const [allInvoices, setAllInvoices] = useState([]); // for vendor/tag dropdown options only

  const [activeTab, setActiveTab] = useState<StatusTab>("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [isInvoicesLoading, setIsInvoicesLoading] = useState(true);

  // Task 4.1.4/4.1.5 (Service Flow): only shown when both Receive/Send are
  // enabled, mirroring ingestion/page.tsx's tab-visibility rule.
  const [receiveEnabled, setReceiveEnabled] = useState(true);
  const [sendEnabled, setSendEnabled] = useState(false);
  const [invoicesTab, setInvoicesTab] = useState<InvoicesTab>("receiving");

  const [outboundInvoices, setOutboundInvoices] = useState([]);
  const [outboundFilters, setOutboundFilters] = useState<OutboundFilterState>({ customerName: "", dateRange: "all" });
  const [outboundActiveTab, setOutboundActiveTab] = useState<OutboundStatusTab>("all");
  const [outboundCurrentPage, setOutboundCurrentPage] = useState(1);
  const [outboundTotalCount, setOutboundTotalCount] = useState(0);
  const [isOutboundLoading, setIsOutboundLoading] = useState(true);
  const [outboundCustomerOptions, setOutboundCustomerOptions] = useState<string[]>([]);

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

  const getDatesForRange = (range: string) => {
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
  };

  useEffect(() => {
    if (authLoading) return;
    const fetchAllData = async () => {
      try {
        const res = await apiClient.get("/invoices", { params: { limit: 100 } });
        setAllInvoices(res.data || []);
      } catch (err) {
        console.error("Error fetching filter source data", err);
      }
    };
    fetchAllData();
  }, [authLoading]);

  const fetchInvoicesPage = useCallback(async () => {
    if (authLoading) return;
    setIsInvoicesLoading(true);
    const { startDate, endDate } = getDatesForRange(filters.dateRange);

    try {
      const invoicesRes = await apiClient.get("/invoices", {
        params: {
          start_date: startDate,
          end_date: endDate,
          vendor_name: filters.vendorName || undefined,
          tag: filters.tag || undefined,
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE,
          ...(activeTab === "all" ? { status: filters.status || undefined } : tabToStatusParams(activeTab)),
        },
      });

      setInvoices(invoicesRes.data || []);
      const totalHeader = invoicesRes.headers?.["x-total-count"];
      setTotalCount(totalHeader ? parseInt(totalHeader, 10) : (invoicesRes.data || []).length);
    } catch (err) {
      console.error("Error loading invoices page", err);
    } finally {
      setIsInvoicesLoading(false);
    }
  }, [filters, activeTab, currentPage, authLoading]);

  useEffect(() => {
    fetchInvoicesPage();
  }, [fetchInvoicesPage]);

  // Outbound fetch: same server-pagination contract, own endpoint (GET
  // /outbound-dashboard/invoices), completely independent state from the
  // inbound table above.
  useEffect(() => {
    if (authLoading || !sendEnabled) return;
    const fetchCustomers = async () => {
      try {
        const res = await apiClient.get("/outbound-dashboard/invoices", { params: { limit: 100 } });
        const names = (res.data || [])
          .map((inv: any) => inv.customer_name)
          .filter((name: any): name is string => typeof name === "string" && name.trim() !== "");
        setOutboundCustomerOptions(Array.from(new Set(names)));
      } catch (err) {
        console.error("Error fetching outbound customer options", err);
      }
    };
    fetchCustomers();
  }, [authLoading, sendEnabled]);

  const fetchOutboundInvoicesPage = useCallback(async () => {
    if (authLoading || !sendEnabled) return;
    setIsOutboundLoading(true);
    const { startDate, endDate } = getDatesForRange(outboundFilters.dateRange);

    try {
      const res = await apiClient.get("/outbound-dashboard/invoices", {
        params: {
          start_date: startDate,
          end_date: endDate,
          customer_name: outboundFilters.customerName || undefined,
          limit: PAGE_SIZE,
          offset: (outboundCurrentPage - 1) * PAGE_SIZE,
          ...outboundTabToStatusParams(outboundActiveTab),
        },
      });
      setOutboundInvoices(res.data || []);
      const totalHeader = res.headers?.["x-total-count"];
      setOutboundTotalCount(totalHeader ? parseInt(totalHeader, 10) : (res.data || []).length);
    } catch (err) {
      console.error("Error loading outbound invoices page", err);
    } finally {
      setIsOutboundLoading(false);
    }
  }, [outboundFilters, outboundActiveTab, outboundCurrentPage, authLoading, sendEnabled]);

  useEffect(() => {
    fetchOutboundInvoicesPage();
  }, [fetchOutboundInvoicesPage]);

  const handleFilterChange = (newFilters: FilterState) => {
    setFilters(newFilters);
    setCurrentPage(1);
  };

  const handleTabChange = (tab: StatusTab) => {
    setActiveTab(tab);
    setCurrentPage(1);
  };

  const handleOutboundFilterChange = (newFilters: OutboundFilterState) => {
    setOutboundFilters(newFilters);
    setOutboundCurrentPage(1);
  };

  const handleOutboundTabChange = (tab: OutboundStatusTab) => {
    setOutboundActiveTab(tab);
    setOutboundCurrentPage(1);
  };

  const handleInvoiceDeleted = (id: string) => {
    setAllInvoices((prev) => prev.filter((inv: any) => inv.id !== id));
    fetchInvoicesPage();
  };

  // Gap 282: outbound mirror of handleInvoiceDeleted. Drops the row from the
  // customer-dropdown source list and refetches the current outbound page so
  // the count/pagination stay honest, rather than only splicing it locally.
  const handleOutboundInvoiceDeleted = (id: string) => {
    setOutboundInvoices((prev) => prev.filter((inv: any) => inv.id !== id));
    fetchOutboundInvoicesPage();
  };

  // Gap 277: refetches the inbound queue after a status change (e.g. the new
  // Mark-as-Paid action), so the row reflects reality immediately rather than
  // waiting for the next unrelated reload.
  const handleInvoiceStatusChanged = (_id: string, _newStatus: string) => {
    fetchInvoicesPage();
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
  const outboundTotalPages = Math.max(1, Math.ceil(outboundTotalCount / PAGE_SIZE));

  const realVendors = allInvoices
    .map((inv: any) => inv.vendor_name)
    .filter((name): name is string => typeof name === "string" && name.trim() !== "");

  const uniqueVendors = Array.from(new Set(realVendors));

  const realTags = allInvoices
    .flatMap((inv: any) => inv.tags || [])
    .filter((t): t is string => typeof t === "string" && t.trim() !== "");

  const uniqueTags = Array.from(new Set(realTags));

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

      {showReceiving && (
        <>
          <FilterBar
            onFilterChange={handleFilterChange}
            availableVendors={uniqueVendors}
            availableTags={uniqueTags}
            statusFilterDisabled={activeTab !== "all"}
            // FE Gap 702: the bar must SHOW the filter the URL asked for, not
            // just have it applied behind the scenes. A list quietly filtered by
            // something the controls do not display is worse than an unfiltered
            // one -- the user cannot tell why rows are missing, or clear it.
            initialFilters={seededFilters}
          />

          <RecentInvoicesTable
            invoices={invoices}
            isLoading={isInvoicesLoading}
            onDelete={handleInvoiceDeleted}
            onStatusChange={handleInvoiceStatusChanged}
            activeTab={activeTab}
            onTabChange={handleTabChange}
            currentPage={currentPage}
            totalPages={totalPages}
            totalCount={totalCount}
            onPageChange={setCurrentPage}
            isFullPage={true}
          />
        </>
      )}

      {showSending && (
        <>
          <OutboundFilterBar
            onFilterChange={handleOutboundFilterChange}
            availableCustomers={outboundCustomerOptions}
          />

          <OutboundInvoicesTable
            invoices={outboundInvoices}
            isLoading={isOutboundLoading}
            onDelete={handleOutboundInvoiceDeleted}
            activeTab={outboundActiveTab}
            onTabChange={handleOutboundTabChange}
            currentPage={outboundCurrentPage}
            totalPages={outboundTotalPages}
            totalCount={outboundTotalCount}
            onPageChange={setOutboundCurrentPage}
          />
        </>
      )}
    </div>
  );
}
