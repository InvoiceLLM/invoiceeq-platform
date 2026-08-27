"use client";

import React, { useState, useEffect } from "react";
import FilterBar, { FilterState } from "../../components/dashboard/FilterBar";
import MetricsGrid, { CurrencyTotals } from "../../components/dashboard/MetricsGrid";
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
import { toLocalDateString } from "../../lib/utils";

interface SpendPoint {
  date: string;
  /** FE Gap 183: ISO-4217 code this point's amount is denominated in. */
  currency?: string | null;
  amount: number;
}

interface VendorSpend {
  vendor_name: string;
  /** FE Gap 183: one row per (vendor, currency), never a summed total. */
  currency?: string | null;
  amount: number;
}

interface DashboardMetrics {
  /**
   * FE Gap 183: replaces the flat total_invoiced/paid_amount/
   * outstanding_amount/at_risk_amount scalars, which the backend no longer
   * returns at all -- they were blended cross-currency sums with no correct
   * label.
   */
  totals_by_currency: CurrencyTotals[];
  average_processing_time: number;
  extraction_accuracy: number;
  active_alerts_count: number;
  spend_over_time: SpendPoint[];
  top_vendors: VendorSpend[];
  invoices_by_status: Record<string, number>;
}

const defaultMetrics: DashboardMetrics = {
  totals_by_currency: [],
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
  // Gap 316: independent from `filters` above -- inbound's vendor_name/
  // PAID/REJECTED/AUDIT_REQUIRED vocabulary would silently mis-filter or
  // zero out the outbound half if shared. See the outbound FilterBar below
  // and its own fetch effect.
  const [outboundFilters, setOutboundFilters] = useState<FilterState>({
    vendorName: "",
    dateRange: "all",
    tag: "",
    status: "",
  });

  const [metrics, setMetrics] = useState<DashboardMetrics>(defaultMetrics);
  const [allInvoices, setAllInvoices] = useState([]); // Kept to dynamically extract vendors/tags for FilterBar
  const [allOutboundInvoices, setAllOutboundInvoices] = useState([]); // Same, for the outbound FilterBar's customer/tag dropdowns
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

  // 1b. Gap 316: same as above, for the outbound FilterBar's customer/tag
  // dropdown options -- inbound's `allInvoices` has no customer_name on it.
  useEffect(() => {
    if (authLoading || !sendEnabled) return;

    const fetchAllOutboundData = async () => {
      try {
        const res = await apiClient.get("/outbound-dashboard/invoices", {
          params: { limit: 100 },
        });
        setAllOutboundInvoices(res.data || []);
      } catch (err) {
        console.error("Error fetching outbound filter source data", err);
      }
    };
    fetchAllOutboundData();
  }, [authLoading, sendEnabled]);

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
  // receive-only tenant makes no extra request at all.
  //
  // Gap 316: now sends customer_name/status from its own `outboundFilters`
  // state, not the inbound `filters` state -- GET /dashboard/outbound-metrics
  // already accepted customer_name/status server-side
  // (routers/outbound_dashboard.py), the frontend just never sent them.
  useEffect(() => {
    if (authLoading || !sendEnabled) return;

    const fetchOutboundMetrics = async () => {
      setIsOutboundMetricsLoading(true);
      const { startDate, endDate } = getDatesForRange(outboundFilters.dateRange);

      try {
        const res = await apiClient.get("/dashboard/outbound-metrics", {
          params: {
            start_date: startDate,
            end_date: endDate,
            customer_name: outboundFilters.vendorName || undefined,
            status: outboundFilters.status || undefined,
          },
        });
        setOutboundMetrics(res.data || defaultOutboundMetrics);
      } catch (err) {
        console.error("Error loading outbound dashboard metrics", err);
      } finally {
        setIsOutboundMetricsLoading(false);
      }
    };

    fetchOutboundMetrics();
  }, [outboundFilters, authLoading, sendEnabled]);

  const handleFilterChange = (newFilters: FilterState) => {
    setFilters(newFilters);
  };

  const handleOutboundFilterChange = (newFilters: FilterState) => {
    setOutboundFilters(newFilters);
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

  // Gap 316: same, for the outbound FilterBar. GET /outbound-dashboard/invoices
  // doesn't return a `tags` field today, so uniqueOutboundTags is expected to
  // stay empty (an "All Tags"-only dropdown) until that endpoint gains one --
  // a known, separate, smaller gap, not silently claimed fixed here.
  const realOutboundCustomers = allOutboundInvoices
    .map((inv: any) => inv.customer_name)
    .filter((name): name is string => typeof name === "string" && name.trim() !== "");

  const uniqueOutboundCustomers = Array.from(new Set(realOutboundCustomers));

  const realOutboundTags = allOutboundInvoices
    .flatMap((inv: any) => inv.tags || [])
    .filter((t): t is string => typeof t === "string" && t.trim() !== "");

  const uniqueOutboundTags = Array.from(new Set(realOutboundTags));

  const dynamicTabs = [
    ...(receiveEnabled ? [{ id: "vendors", label: "Top Vendors & Clients" } as const] : []),
    ...(sendEnabled ? [{ id: "customers", label: "Top Customers" } as const] : []),
    { id: "insights", label: "Insights" } as const,
    { id: "trainer", label: "Trainer Impact" } as const,
  ];
  const [activeTab, setActiveTab] = useState<string>("insights");

  // Task 2.1.4: ClientPerformanceChart already renders any {name, amount}
  // ranking, so top_customers is mapped onto its existing prop shape rather
  // than forking the component. FE Gap 183: currency rides along, otherwise
  // the outbound ranking would fall back to USD for every row.
  const topCustomersAsVendorShape: VendorSpend[] = (outboundMetrics?.top_customers ?? []).map(
    (c: { customer_name: string; currency?: string | null; amount: number }) => ({
      vendor_name: c.customer_name,
      currency: c.currency,
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
          shared header (declared above via usePageHeader).

          Gap 316: previously one FilterBar sat here, gated on receiveEnabled
          only, using inbound vocabulary (vendor_name,
          PAID/REJECTED/AUDIT_REQUIRED) even when both flows were on -- it
          silently never filtered the outbound half, and a send-only tenant
          got no filter bar at all. Each FilterBar now renders scoped to, and
          physically positioned above, the metrics half it actually controls
          -- a filter sitting above the panel it filters needs no label
          explaining scope, there's nothing else to assume it does. */}

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
            <FilterBar
              compact
              direction="inbound"
              onFilterChange={handleFilterChange}
              availableVendors={uniqueVendors}
              availableTags={uniqueTags}
            />
            <MetricsGrid metrics={metrics} isLoading={isMetricsLoading} />
          </section>

          <section aria-labelledby="sending-metrics-heading" className="space-y-3">
            <h2
              id="sending-metrics-heading"
              className="text-sm font-semibold text-white tracking-wide"
            >
              Sending
            </h2>
            <FilterBar
              compact
              direction="outbound"
              onFilterChange={handleOutboundFilterChange}
              availableVendors={uniqueOutboundCustomers}
              availableTags={uniqueOutboundTags}
            />
            <OutboundMetricsGrid metrics={outboundMetrics} isLoading={isOutboundMetricsLoading} />
          </section>
        </div>
      ) : (
        <>
          {showInboundMetrics && (
            <>
              <FilterBar
                compact
                direction="inbound"
                onFilterChange={handleFilterChange}
                availableVendors={uniqueVendors}
                availableTags={uniqueTags}
              />
              <MetricsGrid metrics={metrics} isLoading={isMetricsLoading} />
            </>
          )}
          {showOutboundMetrics && !showInboundMetrics && (
            <>
              <FilterBar
                compact
                direction="outbound"
                onFilterChange={handleOutboundFilterChange}
                availableVendors={uniqueOutboundCustomers}
                availableTags={uniqueOutboundTags}
              />
              <OutboundMetricsGrid metrics={outboundMetrics} isLoading={isOutboundMetricsLoading} />
            </>
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
