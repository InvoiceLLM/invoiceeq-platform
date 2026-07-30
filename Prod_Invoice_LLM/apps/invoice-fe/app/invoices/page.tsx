"use client";

import React, { useState, useEffect, useCallback } from "react";
import FilterBar, { FilterState } from "../../components/dashboard/FilterBar";
import RecentInvoicesTable, { StatusTab } from "../../components/dashboard/RecentInvoicesTable";
import OutboundFilterBar, { OutboundFilterState } from "../../components/dashboard/OutboundFilterBar";
import OutboundInvoicesTable, { OutboundStatusTab } from "../../components/dashboard/OutboundInvoicesTable";
import PageHeader from "../../components/layout/PageHeader";
import { apiClient } from "../../lib/apiClient";
import { useAuth } from "../../hooks/useAuth";

// Relocated from dashboard/page.tsx (Task 4.9, Dashboard/Audit split) --
// Dashboard is overview-only now; this page is the actual invoice queue.
const PAGE_SIZE = 8;

const DEFAULT_VENDORS = ["Hardware Depot", "Cloud Hosting Inc", "Office Supply Corp", "Consulting LLC", "Telco Giants"];
const DEFAULT_TAGS = ["Hardware", "Software", "Services", "Marketing", "Travel"];

function tabToStatusParams(tab: StatusTab): { status?: string; status_in?: string } {
  if (tab === "paid") return { status: "PAID" };
  if (tab === "rejected") return { status: "REJECTED" };
  if (tab === "pending") return { status_in: "PROCESSING,COMPLETED,AUDIT_REQUIRED,DUPLICATE" };
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

export default function InvoicesPage() {
  const { loading: authLoading } = useAuth();
  const [filters, setFilters] = useState<FilterState>({
    vendorName: "",
    dateRange: "all",
    tag: "",
    status: "",
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
    let endDate: string | undefined = today.toISOString().split("T")[0];

    if (range === "this_month") {
      const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
      startDate = firstDay.toISOString().split("T")[0];
    } else if (range === "last_30_days") {
      const prior = new Date();
      prior.setDate(today.getDate() - 30);
      startDate = prior.toISOString().split("T")[0];
    } else if (range === "last_90_days") {
      const prior = new Date();
      prior.setDate(today.getDate() - 90);
      startDate = prior.toISOString().split("T")[0];
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

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
  const outboundTotalPages = Math.max(1, Math.ceil(outboundTotalCount / PAGE_SIZE));

  const uniqueVendors = Array.from(
    new Set([
      ...allInvoices
        .map((inv: any) => inv.vendor_name)
        .filter((name): name is string => typeof name === "string" && name.trim() !== ""),
      ...DEFAULT_VENDORS,
    ])
  );

  const uniqueTags = Array.from(
    new Set([
      ...allInvoices
        .flatMap((inv: any) => inv.tags || [])
        .filter((t): t is string => typeof t === "string" && t.trim() !== ""),
      ...DEFAULT_TAGS,
    ])
  );

  const showTabs = receiveEnabled && sendEnabled;
  const showReceiving = !sendEnabled || invoicesTab === "receiving";
  const showSending = (sendEnabled && !receiveEnabled) || (showTabs && invoicesTab === "sending");

  return (
    <div className="space-y-6">
      <PageHeader title="Audit Queue" agentIcon="🛡️" agentName="SENTINEL" agentRole="Audit & Compliance" />

      {showTabs && (
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
      )}

      {showReceiving && (
        <>
          <FilterBar
            onFilterChange={handleFilterChange}
            availableVendors={uniqueVendors}
            availableTags={uniqueTags}
          />

          <RecentInvoicesTable
            invoices={invoices}
            isLoading={isInvoicesLoading}
            onDelete={handleInvoiceDeleted}
            activeTab={activeTab}
            onTabChange={handleTabChange}
            currentPage={currentPage}
            totalPages={totalPages}
            totalCount={totalCount}
            onPageChange={setCurrentPage}
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
