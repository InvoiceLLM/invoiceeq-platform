"use client";

import React, { useState, useEffect, useCallback } from "react";
import FilterBar, { FilterState } from "../../components/dashboard/FilterBar";
import MetricsGrid from "../../components/dashboard/MetricsGrid";
import ClientPerformanceChart from "../../components/dashboard/ClientPerformanceChart";
import RecentInvoicesTable, { StatusTab } from "../../components/dashboard/RecentInvoicesTable";
import TrainerImpactPanel from "../../components/dashboard/TrainerImpactPanel";
import ActionableInsightsPanel from "../../components/dashboard/ActionableInsightsPanel";
import { apiClient } from "../../lib/apiClient";
import { useAuth } from "../../hooks/useAuth";

// FE Gap 29: real server-side page size for the Recent Invoices table (was
// previously a client-side re-slice of one already-fetched 20-row batch,
// which could never reach invoices past that fixed window).
const PAGE_SIZE = 8;

// "Pending" spans several raw statuses (matches the AP mental model of
// "still in the pipeline" vs. closed-out, same reasoning as the original
// Gap 5 tabs) so it needs the backend's status_in filter rather than the
// single-value status param used by "paid"/"rejected"/the FilterBar dropdown.
function tabToStatusParams(tab: StatusTab): { status?: string; status_in?: string } {
  if (tab === "paid") return { status: "PAID" };
  if (tab === "rejected") return { status: "REJECTED" };
  if (tab === "pending") return { status_in: "PROCESSING,COMPLETED,AUDIT_REQUIRED,DUPLICATE" };
  return {};
}

interface SpendPoint {
  date: string;
  amount: number;
}

interface VendorSpend {
  vendor_name: string;
  amount: number;
}

interface DashboardMetrics {
  total_invoiced: number;
  paid_amount: number;
  outstanding_amount: number;
  at_risk_amount: number;
  average_processing_time: number;
  extraction_accuracy: number;
  active_alerts_count: number;
  spend_over_time: SpendPoint[];
  top_vendors: VendorSpend[];
  invoices_by_status: Record<string, number>;
}

// Fallback mock vendor list & tags if backend returns empty datasets
const DEFAULT_VENDORS = ["Hardware Depot", "Cloud Hosting Inc", "Office Supply Corp", "Consulting LLC", "Telco Giants"];
const DEFAULT_TAGS = ["Hardware", "Software", "Services", "Marketing", "Travel"];

const defaultMetrics: DashboardMetrics = {
  total_invoiced: 0,
  paid_amount: 0,
  outstanding_amount: 0,
  at_risk_amount: 0,
  average_processing_time: 0,
  extraction_accuracy: 0,
  active_alerts_count: 0,
  spend_over_time: [],
  top_vendors: [],
  invoices_by_status: {},
};

export default function DashboardPage() {
  const { tenantId, loading: authLoading } = useAuth();
  const [filters, setFilters] = useState<FilterState>({
    vendorName: "",
    dateRange: "all",
    tag: "",
    status: "",
  });

  const [metrics, setMetrics] = useState<DashboardMetrics>(defaultMetrics);
  const [invoices, setInvoices] = useState([]);
  const [allInvoices, setAllInvoices] = useState([]); // Kept to dynamically extract vendors/tags
  const [isMetricsLoading, setIsMetricsLoading] = useState(true);

  // FE Gap 29: pagination state now lives here (server-backed) rather than
  // inside RecentInvoicesTable re-slicing one fixed fetched batch.
  const [activeTab, setActiveTab] = useState<StatusTab>("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [isInvoicesLoading, setIsInvoicesLoading] = useState(true);

  // Dynamically extract date range values
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

  // 1. Initial Load of all invoices to extract drop-down filter options
  useEffect(() => {
    if (authLoading) return;

    const fetchAllData = async () => {
      try {
        const res = await apiClient.get("/invoices", {
          params: { limit: 100 },
        });
        setAllInvoices(res.data || []);
      } catch (err) {
        console.error("Error fetching filter source data", err);
      }
    };
    fetchAllData();
  }, [authLoading]);

  // 2. Fetch dashboard metrics whenever filters change. Independent of
  // pagination -- these are tenant-wide aggregates, not tied to a page.
  useEffect(() => {
    if (authLoading) return;

    const fetchMetrics = async () => {
      setIsMetricsLoading(true);
      const { startDate, endDate } = getDatesForRange(filters.dateRange);

      try {
        const metricsRes = await apiClient.get("/dashboard/metrics", {
          params: {
            start_date: startDate,
            end_date: endDate,
            status: filters.status || undefined,
            vendor_name: filters.vendorName || undefined,
          },
        });
        setMetrics(metricsRes.data || defaultMetrics);
      } catch (err) {
        console.error("Error loading dashboard metrics", err);
      } finally {
        setIsMetricsLoading(false);
      }
    };

    fetchMetrics();
  }, [filters, authLoading]);

  // 3. Fetch one real server-paginated page of invoices for the Recent
  // Invoices table. FE Gap 29: previously fetched one fixed batch (limit 20)
  // and re-sliced/re-filtered it entirely client-side, so invoices past that
  // fixed window were unreachable no matter how many times "Next" was
  // clicked. Now every page turn and every tab switch is a real backend call
  // with the matching limit/offset/status, and X-Total-Count drives the
  // page count instead of the length of whatever happened to be fetched.
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

  const handleFilterChange = (newFilters: FilterState) => {
    setFilters(newFilters);
    setCurrentPage(1);
  };

  const handleTabChange = (tab: StatusTab) => {
    setActiveTab(tab);
    setCurrentPage(1);
  };

  const handleInvoiceDeleted = (id: string) => {
    // Re-fetch the current page rather than splicing the local array --
    // totalCount/totalPages need to reflect the backend's new count too.
    setAllInvoices((prev) => prev.filter((inv: any) => inv.id !== id));
    fetchInvoicesPage();
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  // Build unique lists of client/vendor names and tags from historical data
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

  return (
    <div className="space-y-6">
      {/* Dashboard Top Header Title */}
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-white tracking-wide">Command Center</h1>
        <p className="text-xs text-slate-400">
          Real-time metrics, audit status ledger, and client rankings dashboard.
        </p>
      </div>

      {/* Filter Control Bar */}
      <FilterBar
        onFilterChange={handleFilterChange}
        availableVendors={uniqueVendors}
        availableTags={uniqueTags}
      />

      {/* Bento box metrics panel */}
      <MetricsGrid metrics={metrics} isLoading={isMetricsLoading} />

      {/* Analytics chart and invoice list ledger grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Table list - takes 2 cols on lg screens */}
        <div className="lg:col-span-2">
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
        </div>

        {/* Vendors bar chart - takes 1 col on lg screens */}
        <div className="lg:col-span-1 space-y-6">
          <ClientPerformanceChart vendors={metrics.top_vendors} isLoading={isMetricsLoading} />
          <ActionableInsightsPanel />
          <TrainerImpactPanel />
        </div>
      </div>
    </div>
  );
}

