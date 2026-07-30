"use client";

import React, { useState, useEffect } from "react";
import FilterBar, { FilterState } from "../../components/dashboard/FilterBar";
import MetricsGrid from "../../components/dashboard/MetricsGrid";
import ClientPerformanceChart from "../../components/dashboard/ClientPerformanceChart";
import NeedsAttentionWidget from "../../components/dashboard/NeedsAttentionWidget";
import TrainerImpactPanel from "../../components/dashboard/TrainerImpactPanel";
import ActionableInsightsPanel from "../../components/dashboard/ActionableInsightsPanel";
import PageHeader from "../../components/layout/PageHeader";
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
  const { loading: authLoading } = useAuth();
  const [filters, setFilters] = useState<FilterState>({
    vendorName: "",
    dateRange: "all",
    tag: "",
    status: "",
  });

  const [metrics, setMetrics] = useState<DashboardMetrics>(defaultMetrics);
  const [allInvoices, setAllInvoices] = useState([]); // Kept to dynamically extract vendors/tags for FilterBar
  const [isMetricsLoading, setIsMetricsLoading] = useState(true);

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

  // 2. Fetch dashboard metrics whenever filters change.
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

  const handleFilterChange = (newFilters: FilterState) => {
    setFilters(newFilters);
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

  const TABS = [
    { id: "attention", label: "Needs Attention" },
    { id: "vendors", label: "Top Vendors" },
    { id: "insights", label: "Insights" },
    { id: "trainer", label: "Trainer Impact" },
  ] as const;
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]["id"]>("attention");

  return (
    <div className="space-y-4">
      {/* Title + filters share one row -- no subtitle line, no separate filter panel */}
      <PageHeader
        title="Command Center"
        actions={
          <FilterBar
            compact
            onFilterChange={handleFilterChange}
            availableVendors={uniqueVendors}
            availableTags={uniqueTags}
          />
        }
      />

      {/* Bento box metrics panel */}
      <MetricsGrid metrics={metrics} isLoading={isMetricsLoading} />

      {/* Tabbed panel: one wide view at a time instead of 4 panels squeezed
          into a 3-column grid -- fits on screen without scrolling, and each
          panel gets the full page width when it's the one showing. */}
      <div className="glass-panel rounded-xl">
        <div className="flex items-center gap-1 border-b border-[#222D3D] px-3 pt-2">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-2 text-xs font-medium rounded-t-lg transition-colors ${
                activeTab === tab.id
                  ? "bg-[#1E293B] text-white border-b-2 border-[#3B82F6]"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="p-4">
          {activeTab === "attention" && <NeedsAttentionWidget />}
          {activeTab === "vendors" && (
            <ClientPerformanceChart vendors={metrics.top_vendors} isLoading={isMetricsLoading} />
          )}
          {activeTab === "insights" && <ActionableInsightsPanel />}
          {activeTab === "trainer" && <TrainerImpactPanel />}
        </div>
      </div>
    </div>
  );
}
