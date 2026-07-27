"use client";

import React, { useState, useEffect } from "react";
import FilterBar, { FilterState } from "../../components/dashboard/FilterBar";
import MetricsGrid from "../../components/dashboard/MetricsGrid";
import ClientPerformanceChart from "../../components/dashboard/ClientPerformanceChart";
import RecentInvoicesTable from "../../components/dashboard/RecentInvoicesTable";
import TrainerImpactPanel from "../../components/dashboard/TrainerImpactPanel";
import ActionableInsightsPanel from "../../components/dashboard/ActionableInsightsPanel";
import { apiClient } from "../../lib/apiClient";
import { useAuth } from "../../hooks/useAuth";

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
  const [isLoading, setIsLoading] = useState(true);

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

  // 2. Fetch metrics & invoices when filters change
  useEffect(() => {
    if (authLoading) return;

    const fetchData = async () => {
      setIsLoading(true);
      const { startDate, endDate } = getDatesForRange(filters.dateRange);

      const commonParams = {
        start_date: startDate,
        end_date: endDate,
        status: filters.status || undefined,
      };

      try {
        // Query /dashboard/metrics
        const metricsRes = await apiClient.get("/dashboard/metrics", {
          params: {
            ...commonParams,
            vendor_name: filters.vendorName || undefined,
          },
        });

        // Query /invoices list
        const invoicesRes = await apiClient.get("/invoices", {
          params: {
            ...commonParams,
            limit: 20,
            tag: filters.tag || undefined,
          },
        });

        // Filter invoices locally by vendorName if set (backend /invoices has limit/offset/date parameters, local filtering adds extra safety)
        let filteredInvoices = invoicesRes.data || [];
        if (filters.vendorName) {
          filteredInvoices = filteredInvoices.filter(
            (inv: any) => inv.vendor_name === filters.vendorName
          );
        }

        setMetrics(metricsRes.data || defaultMetrics);
        setInvoices(filteredInvoices);
      } catch (err) {
        console.error("Error loading dashboard data", err);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [filters, authLoading]);

  const handleFilterChange = (newFilters: FilterState) => {
    setFilters(newFilters);
  };

  const handleInvoiceDeleted = (id: string) => {
    setInvoices((prev) => prev.filter((inv: any) => inv.id !== id));
    setAllInvoices((prev) => prev.filter((inv: any) => inv.id !== id));
  };

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
      <MetricsGrid metrics={metrics} isLoading={isLoading} />

      {/* Analytics chart and invoice list ledger grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Table list - takes 2 cols on lg screens */}
        <div className="lg:col-span-2">
          <RecentInvoicesTable invoices={invoices} isLoading={isLoading} onDelete={handleInvoiceDeleted} />
        </div>

        {/* Vendors bar chart - takes 1 col on lg screens */}
        <div className="lg:col-span-1 space-y-6">
          <ClientPerformanceChart vendors={metrics.top_vendors} isLoading={isLoading} />
          <ActionableInsightsPanel />
          <TrainerImpactPanel />
        </div>
      </div>
    </div>
  );
}

