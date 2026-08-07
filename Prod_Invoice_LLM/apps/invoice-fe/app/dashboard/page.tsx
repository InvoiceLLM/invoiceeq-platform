"use client";

import React, { useState, useEffect } from "react";
import FilterBar, { FilterState } from "../../components/dashboard/FilterBar";
import MetricsGrid from "../../components/dashboard/MetricsGrid";
import OutboundMetricsGrid, {
  OutboundMetrics,
  defaultOutboundMetrics,
} from "../../components/dashboard/OutboundMetricsGrid";
import ClientPerformanceChart from "../../components/dashboard/ClientPerformanceChart";
import NeedsAttentionWidget from "../../components/dashboard/NeedsAttentionWidget";
import TrainerImpactPanel from "../../components/dashboard/TrainerImpactPanel";
import ActionableInsightsPanel from "../../components/dashboard/ActionableInsightsPanel";
import { usePageHeader } from "../../components/layout/PageHeaderContext";
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
  // FE Gap 110: feeds Shell's one shared header instead of rendering a title
  // block of this page's own.
  usePageHeader({ title: "Command Center" });

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

  // Feature 2.1 (Task 2.1.2): Service Flow gating. Defaults match the Tenant
  // model's own defaults (receive on, send off), so a tenant that never
  // touched Settings -- or a failed settings fetch -- renders exactly today's
  // inbound-only Dashboard rather than flashing an empty outbound half.
  const [receiveEnabled, setReceiveEnabled] = useState(true);
  const [sendEnabled, setSendEnabled] = useState(false);
  const [outboundMetrics, setOutboundMetrics] = useState<OutboundMetrics>(defaultOutboundMetrics);
  const [isOutboundMetricsLoading, setIsOutboundMetricsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/settings/service-flow")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setReceiveEnabled(data.receive_invoices_enabled ?? true);
        setSendEnabled(data.send_invoices_enabled ?? false);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

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
    if (authLoading || !receiveEnabled) return;

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
  }, [authLoading, receiveEnabled]);

  // 2. Fetch inbound dashboard metrics whenever filters change.
  useEffect(() => {
    if (authLoading || !receiveEnabled) return;

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
  }, [filters, authLoading, receiveEnabled]);

  // 3. Fetch outbound (AR) metrics -- only when Send is actually enabled, so a
  // receive-only tenant makes no extra request at all. Only the date range is
  // shared with the inbound half: FilterBar's vendor/status/tag values are
  // inbound vocabulary (vendor_name, PAID/REJECTED/AUDIT_REQUIRED) and would
  // silently mis-filter or zero out the outbound aggregates.
  useEffect(() => {
    if (authLoading || !sendEnabled) return;

    const fetchOutboundMetrics = async () => {
      setIsOutboundMetricsLoading(true);
      const { startDate, endDate } = getDatesForRange(filters.dateRange);

      try {
        const res = await apiClient.get("/dashboard/outbound-metrics", {
          params: { start_date: startDate, end_date: endDate },
        });
        setOutboundMetrics(res.data || defaultOutboundMetrics);
      } catch (err) {
        console.error("Error loading outbound dashboard metrics", err);
      } finally {
        setIsOutboundMetricsLoading(false);
      }
    };

    fetchOutboundMetrics();
  }, [filters.dateRange, authLoading, sendEnabled]);

  const handleFilterChange = (newFilters: FilterState) => {
    setFilters(newFilters);
  };

  // Build unique lists of client/vendor names and tags from real tenant invoice data (Gap 141)
  const realVendors = allInvoices
    .map((inv: any) => inv.vendor_name)
    .filter((name): name is string => typeof name === "string" && name.trim() !== "");

  const uniqueVendors = Array.from(new Set(realVendors));

  const realTags = allInvoices
    .flatMap((inv: any) => inv.tags || [])
    .filter((t): t is string => typeof t === "string" && t.trim() !== "");

  const uniqueTags = Array.from(new Set(realTags));

  const dynamicTabs = [
    ...(receiveEnabled ? [{ id: "vendors", label: "Top Vendors & Clients" } as const] : []),
    ...(sendEnabled ? [{ id: "customers", label: "Top Customers" } as const] : []),
    { id: "insights", label: "Insights" } as const,
    { id: "trainer", label: "Trainer Impact" } as const,
  ];
  const [activeTab, setActiveTab] = useState<string>("insights");

  // Task 2.1.4: ClientPerformanceChart already renders any {name, amount}
  // ranking, so top_customers is mapped onto its existing prop shape rather
  // than forking the component.
  const topCustomersAsVendorShape: VendorSpend[] = (outboundMetrics?.top_customers ?? []).map(
    (c: { customer_name: string; amount: number }) => ({
      vendor_name: c.customer_name,
      amount: c.amount,
    })
  );

  // Split-screen, not a tab: when both services are on, both halves are
  // visible at once (feature_8.1's design note -- Dashboard is a passive
  // overview, so seeing both totals together is the useful default).
  const showSplit = receiveEnabled && sendEnabled;
  const showInboundMetrics = receiveEnabled;
  const showOutboundMetrics = sendEnabled;

  return (
    <div className="space-y-4">
      {/* FE Gap 110: the title moved out of the page body into Shell's one
          shared header (declared above via usePageHeader). The filter row is
          deliberately NOT portalled up there with it: FilterBar's compact
          variant is still four selects plus a Save button (~660px of minimum
          widths), which cannot share a 64px header row with the title and the
          profile block at 1024-1280px without pushing controls off-screen --
          the exact failure Gap 85 exists to prevent. It keeps the row the
          title used to occupy, so no vertical space is lost either way.

          Filters are inbound-only vocabulary (vendor_name,
          PAID/REJECTED/AUDIT_REQUIRED), so hidden entirely for a send-only
          tenant rather than silently mis-filtering/zeroing the outbound half. */}
      {receiveEnabled && (
        <FilterBar
          compact
          onFilterChange={handleFilterChange}
          availableVendors={uniqueVendors}
          availableTags={uniqueTags}
        />
      )}

      {/* Metrics half. One undivided grid when only one service is active;
          two side-by-side halves when both are. No combined/net figure in
          any branch -- that comparison is Chat-only. */}
      {showSplit ? (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6" data-testid="dashboard-metrics-split">
          <section aria-labelledby="receiving-metrics-heading" className="space-y-3">
            <h2
              id="receiving-metrics-heading"
              className="text-sm font-semibold text-white tracking-wide"
            >
              Receiving
            </h2>
            <MetricsGrid metrics={metrics} isLoading={isMetricsLoading} />
          </section>

          <section aria-labelledby="sending-metrics-heading" className="space-y-3">
            <h2
              id="sending-metrics-heading"
              className="text-sm font-semibold text-white tracking-wide"
            >
              Sending
            </h2>
            <OutboundMetricsGrid metrics={outboundMetrics} isLoading={isOutboundMetricsLoading} />
          </section>
        </div>
      ) : (
        <>
          {showInboundMetrics && <MetricsGrid metrics={metrics} isLoading={isMetricsLoading} />}
          {showOutboundMetrics && !showInboundMetrics && (
            <OutboundMetricsGrid metrics={outboundMetrics} isLoading={isOutboundMetricsLoading} />
          )}
        </>
      )}

      {/* Always visible, no tab/click needed -- direction-aware: merges
          inbound+outbound flagged rows, shows whichever ranking(s) are
          enabled. */}
      <NeedsAttentionWidget receiveEnabled={receiveEnabled} sendEnabled={sendEnabled} />

      {/* Tabbed panel: only the genuinely supplementary panels share space
          here -- fits on screen without scrolling, and each gets the full
          page width when it's the one showing. */}
      <div className="glass-panel rounded-xl">
        <div className="flex items-center gap-1 border-b border-[#222D3D] px-3 pt-2">
          {dynamicTabs.map((tab) => (
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
          {activeTab === "vendors" && (
            <ClientPerformanceChart vendors={metrics.top_vendors} isLoading={isMetricsLoading} />
          )}
          {activeTab === "customers" && (
            <ClientPerformanceChart
              vendors={topCustomersAsVendorShape}
              isLoading={isOutboundMetricsLoading}
              title="Top Customers"
              subtitle="Ranking by aggregated invoiced-out value."
            />
          )}
          {activeTab === "insights" && <ActionableInsightsPanel />}
          {activeTab === "trainer" && <TrainerImpactPanel />}
        </div>
      </div>
    </div>
  );
}
