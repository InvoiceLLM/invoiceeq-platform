"use client";

import React, { useState } from "react";
import {
  DollarSign,
  CheckCircle2,
  AlertTriangle,
  CalendarClock,
  Target,
  TrendingUp,
} from "lucide-react";
import KpiCard from "./KpiCard";
import { formatCurrency, normalizeCurrencyCode } from "../../lib/utils";

interface RevenuePoint {
  date: string;
  /** FE Gap 183: ISO-4217 code this point's amount is denominated in. */
  currency?: string | null;
  amount: number;
}

export interface CustomerRevenue {
  customer_name: string;
  /** FE Gap 183: one row per (customer, currency) rather than a summed total. */
  currency?: string | null;
  amount: number;
}

/**
 * FE Gap 183, AR side: one row per currency from
 * GET /outbound-dashboard/metrics. Replaces the old flat total_invoiced_out /
 * amount_collected / outstanding_receivables / at_risk_receivables scalars,
 * which blended every currency into one unlabellable number.
 */
export interface OutboundCurrencyTotals {
  currency: string;
  total_invoiced_out: number;
  amount_collected: number;
  outstanding_receivables: number;
  at_risk_receivables: number;
}

export interface OutboundMetrics {
  totals_by_currency: OutboundCurrencyTotals[];
  average_days_to_payment: number;
  verification_accuracy: number;
  active_alerts_count: number;
  revenue_over_time: RevenuePoint[];
  // Not rendered by this grid -- ClientPerformanceChart consumes it from the
  // same payload (Task 2.1.4), so it belongs on the shared response type.
  top_customers: CustomerRevenue[];
  invoices_by_status: Record<string, number>;
  ai_field_extraction?: number;
  ai_alert_response?: number;
  ai_alerts_missed?: number;
}

interface OutboundMetricsGridProps {
  metrics: OutboundMetrics;
  isLoading: boolean;
}

export const defaultOutboundMetrics: OutboundMetrics = {
  totals_by_currency: [],
  average_days_to_payment: 0,
  verification_accuracy: 0,
  active_alerts_count: 0,
  revenue_over_time: [],
  top_customers: [],
  invoices_by_status: {},
  ai_field_extraction: 100.0,
  ai_alert_response: 100.0,
  ai_alerts_missed: 0.0,
};

const ACCURACY_TARGET = 95.0;

// Green-family palette so the AR chart stays visually distinct from the
// inbound grid's blues when both halves render side by side.
const SERIES_COLORS = ["#10B981", "#34D399", "#0EA5E9", "#A3E635", "#F59E0B"];

/**
 * Feature 2.1, Task 2.1.1 — the AR half of the Dashboard's metrics split.
 *
 * Mirrors MetricsGrid.tsx's layout (4 KPI cards + trend panel, gauge +
 * single-stat tile in the right column) rather than forking it: the underlying
 * fields and labels differ enough (amount_collected vs paid_amount,
 * average_days_to_payment vs average_processing_time) that prop-branching one
 * component two ways would be worse than a clean second one -- see the doc's
 * File Coordinates note.
 *
 * Deliberately carries no combined/net figure of any kind. Both feature docs
 * keep the inbound-vs-outbound comparison Chat-only.
 */
export default function OutboundMetricsGrid({ metrics, isLoading }: OutboundMetricsGridProps) {
  const [hoveredPoint, setHoveredPoint] = useState<RevenuePoint | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);

  const totalsByCurrency = metrics?.totals_by_currency ?? [];
  const activeAlerts = metrics?.active_alerts_count ?? 0;
  const avgDaysToPayment = metrics?.average_days_to_payment ?? 0;
  const revenueOverTime = metrics?.revenue_over_time ?? [];
  const verificationAccuracy = metrics?.verification_accuracy ?? 0.0;
  const aiFieldExtraction = metrics?.ai_field_extraction ?? 100.0;
  const aiAlertResponse = metrics?.ai_alert_response ?? 100.0;
  const aiAlertsMissed = metrics?.ai_alerts_missed ?? 0.0;

  // FE Gap 183: one KPI line per currency billed in. Never a cross-currency
  // sum -- there is no exchange rate anywhere in this system to justify one.
  const emptyValues = [formatCurrency(0)];
  const lines = (pick: (t: OutboundCurrencyTotals) => number) =>
    totalsByCurrency.length === 0
      ? emptyValues
      : totalsByCurrency.map((t) => formatCurrency(pick(t), t.currency));

  // Collection rate computed *within* each currency. The old
  // amountCollected / totalInvoicedOut divided two blended sums.
  const collectedPercents = totalsByCurrency.map((t) => ({
    currency: normalizeCurrencyCode(t.currency),
    percent:
      t.total_invoiced_out > 0
        ? Math.round((t.amount_collected / t.total_invoiced_out) * 100)
        : 0,
  }));
  const collectedSubtext =
    collectedPercents.length === 0
      ? "0% of total billed"
      : collectedPercents.length === 1
      ? `${collectedPercents[0].percent}% of ${collectedPercents[0].currency} billed`
      : collectedPercents.map((c) => `${c.currency} ${c.percent}%`).join(" · ");
  // One badge cannot honestly summarise several currencies' collection rates.
  const collectedTrend =
    collectedPercents.length === 1
      ? {
          value: `${collectedPercents[0].percent}% Collected`,
          type: (collectedPercents[0].percent > 50 ? "positive" : "neutral") as
            | "positive"
            | "neutral",
        }
      : undefined;

  const anyAtRisk = totalsByCurrency.some((t) => t.at_risk_receivables > 0);

  // SVG chart dimensions -- same geometry as MetricsGrid's spend trend so the
  // two halves line up visually when rendered side by side.
  const svgWidth = 600;
  const svgHeight = 160;
  const paddingX = 20;
  const paddingY = 20;

  // FE Gap 183: one polyline per currency, each on its own y scale. A shared
  // scale drew a ₹40,000 day as an order-of-magnitude spike next to a $500
  // day and presented it as a receivables trend. x stays shared (all dates).
  const allDates = Array.from(new Set(revenueOverTime.map((p) => p.date))).sort();
  const dateIndex = new Map(allDates.map((d, i) => [d, i]));

  const currencySeries = Array.from(
    new Set(revenueOverTime.map((p) => normalizeCurrencyCode(p.currency)))
  ).map((currency, seriesIdx) => {
    const points = revenueOverTime
      .filter((p) => normalizeCurrencyCode(p.currency) === currency)
      .sort((a, b) => a.date.localeCompare(b.date));

    const amounts = points.map((p) => p.amount);
    const maxAmount = Math.max(...amounts, 0);
    const minAmount = Math.min(...amounts, 0);
    const range = maxAmount - minAmount || 1;

    const chartPoints = points.map((p) => {
      const idx = dateIndex.get(p.date) ?? 0;
      const x =
        allDates.length > 1
          ? paddingX + (idx / (allDates.length - 1)) * (svgWidth - 2 * paddingX)
          : svgWidth / 2;
      const y = svgHeight - paddingY - ((p.amount - minAmount) / range) * (svgHeight - 2 * paddingY);
      return { x, y, data: p };
    });

    return {
      currency,
      color: SERIES_COLORS[seriesIdx % SERIES_COLORS.length],
      chartPoints,
      pointsStr: chartPoints.map((p) => `${p.x},${p.y}`).join(" "),
    };
  });

  const hasTrendData = currencySeries.some((s) => s.chartPoints.length > 1);

  const gaugeRadius = 40;
  const gaugeCircumference = 2 * Math.PI * gaugeRadius;
  const strokeDashoffset = gaugeCircumference - (aiFieldExtraction / 100) * gaugeCircumference;

  return (
    <div className="space-y-4 w-full">
      {/* KPI Row */}
      <div className="flex flex-wrap gap-3 w-full">
        {/* FE Gap 183: arrays -- one formatted figure per currency, never a
            blended receivables total. KpiCard auto-shrinks to fit them. */}
        <KpiCard
          className="flex-1 min-w-[200px]"
          title="Total Invoiced Out"
          value={isLoading ? emptyValues : lines((t) => t.total_invoiced_out)}
          subtext="Lifetime billed, per currency"
          icon={<DollarSign className="w-4 h-4 text-accent-blue" />}
        />
        <KpiCard
          className="flex-1 min-w-[200px]"
          title="Collected"
          value={isLoading ? emptyValues : lines((t) => t.amount_collected)}
          subtext={isLoading ? "0% of total billed" : collectedSubtext}
          icon={<CheckCircle2 className="w-4 h-4 text-accent-green" />}
          trend={isLoading ? undefined : collectedTrend}
        />
        <KpiCard
          className="flex-1 min-w-[200px]"
          title="Outstanding"
          value={isLoading ? emptyValues : lines((t) => t.outstanding_receivables)}
          subtext="Awaiting send, review, or payment"
          icon={<TrendingUp className="w-4 h-4 text-slate-400" />}
        />
        <KpiCard
          className="flex-1 min-w-[200px]"
          title="At-Risk (Overdue)"
          value={isLoading ? emptyValues : lines((t) => t.at_risk_receivables)}
          subtext={`${activeAlerts} active verification alerts`}
          icon={<AlertTriangle className="w-4 h-4 text-accent-yellow" />}
          trend={!isLoading && anyAtRisk ? { value: "Chase Up", type: "warning" } : undefined}
        />
      </div>

      {/* Revenue Trend Panel */}
      <div className="glass-panel p-6 rounded-xl flex flex-col gap-4 relative overflow-hidden w-full">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-white tracking-wide">
              Receivables Trend
            </h3>
            <p className="text-xs text-slate-400">
              Daily invoiced-out billing trends mapped over time.
            </p>
          </div>

          <div className="flex items-center gap-2 min-w-0 relative h-8">
            {/* FE Gap 183: legend -- each currency is its own line on its own
                y scale, so heights are not comparable between series. */}
            {!isLoading && currencySeries.length > 1 && (
              <div className="flex items-center gap-2 text-[10px] text-slate-400 mr-2">
                {currencySeries.map((s) => (
                  <span key={s.currency} className="inline-flex items-center gap-1">
                    <span
                      className="inline-block w-2 h-2 rounded-full"
                      style={{ backgroundColor: s.color }}
                    />
                    {s.currency}
                  </span>
                ))}
                <span className="text-slate-500">(scaled separately)</span>
              </div>
            )}

            {hoveredPoint && (
              <div className="absolute right-0 top-1/2 -translate-y-1/2 text-right text-xs bg-slate-800/80 border border-[#222D3D] px-2.5 py-1 rounded-lg animate-fade-in z-10 whitespace-nowrap">
                <span className="text-slate-400 mr-1.5">{hoveredPoint.date}:</span>
                <span className="text-white font-bold">
                  {formatCurrency(hoveredPoint.amount, hoveredPoint.currency)}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="w-full relative h-[160px] select-none">
          {isLoading || !hasTrendData ? (
            <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-xs">
              {isLoading
                ? "Loading receivables trend analytics..."
                : "Insufficient invoice history to build trend graph"}
            </div>
          ) : (
            <svg viewBox={`0 0 ${svgWidth} ${svgHeight}`} className="w-full h-full overflow-visible">
              <defs>
                {/* Distinct gradient/filter ids from MetricsGrid's -- both
                    grids render simultaneously in the both-enabled split, and
                    duplicate SVG defs ids collide document-wide. */}
                <linearGradient id="outboundChartGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10B981" stopOpacity="0.25" />
                  <stop offset="100%" stopColor="#0B0F19" stopOpacity="0.0" />
                </linearGradient>
                <filter id="outboundGlow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="2" stdDeviation="4" floodColor="#10B981" floodOpacity="0.3" />
                </filter>
              </defs>

              <line x1={paddingX} y1={paddingY} x2={svgWidth - paddingX} y2={paddingY} stroke="#1E293B" strokeWidth="0.5" strokeDasharray="3 3" />
              <line x1={paddingX} y1={svgHeight / 2} x2={svgWidth - paddingX} y2={svgHeight / 2} stroke="#1E293B" strokeWidth="0.5" strokeDasharray="3 3" />
              <line x1={paddingX} y1={svgHeight - paddingY} x2={svgWidth - paddingX} y2={svgHeight - paddingY} stroke="#1E293B" strokeWidth="0.5" />

              {/* One series per currency. The area fill is only drawn for a
                  single-currency tenant -- overlapping translucent fills read
                  as a stacked cross-currency total, the exact impression this
                  gap exists to remove. */}
              {currencySeries.map((series) => (
                <g key={series.currency}>
                  {currencySeries.length === 1 && series.chartPoints.length > 1 && (
                    <polygon
                      points={
                        `${series.chartPoints[0].x},${svgHeight - paddingY} ` +
                        series.pointsStr +
                        ` ${series.chartPoints[series.chartPoints.length - 1].x},${svgHeight - paddingY}`
                      }
                      fill="url(#outboundChartGradient)"
                    />
                  )}

                  {series.chartPoints.length > 1 && (
                    <polyline
                      fill="none"
                      stroke={series.color}
                      strokeWidth="2.5"
                      points={series.pointsStr}
                      filter="url(#outboundGlow)"
                    />
                  )}

                  {series.chartPoints.map((p, idx) => {
                    const key = `${series.currency}-${idx}`;
                    return (
                      <g key={key}>
                        <circle
                          cx={p.x}
                          cy={p.y}
                          r="12"
                          fill="transparent"
                          className="cursor-pointer"
                          onMouseEnter={() => {
                            setHoveredPoint(p.data);
                            setHoveredKey(key);
                          }}
                          onMouseLeave={() => {
                            setHoveredPoint(null);
                            setHoveredKey(null);
                          }}
                        />

                        {hoveredKey === key && (
                          <line
                            x1={p.x}
                            y1={paddingY}
                            x2={p.x}
                            y2={svgHeight - paddingY}
                            stroke={series.color}
                            strokeWidth="1"
                            strokeDasharray="2 2"
                            className="pointer-events-none"
                          />
                        )}

                        <circle
                          cx={p.x}
                          cy={p.y}
                          r={hoveredKey === key ? "5" : "3.5"}
                          fill={hoveredKey === key ? series.color : "#1e293b"}
                          stroke={series.color}
                          strokeWidth="1.5"
                          className="pointer-events-none transition-all duration-150"
                        />
                      </g>
                    );
                  })}
                </g>
              ))}
            </svg>
          )}
        </div>
      </div>

      {/* Verification Accuracy & Days-to-Payment Column */}
      <div className="glass-panel p-4 rounded-xl w-full">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-center">
          <div className="flex items-center gap-3">
            {/* Dynamic Circular SVG Gauge */}
            <div className="relative w-20 h-20 shrink-0 flex items-center justify-center">
              <svg className="w-full h-full transform -rotate-90" viewBox="0 0 96 96">
                <circle
                  cx="48"
                  cy="48"
                  r={gaugeRadius}
                  className="stroke-[#222D3D]"
                  strokeWidth="6"
                  fill="transparent"
                />
                <circle
                  cx="48"
                  cy="48"
                  r={gaugeRadius}
                  className="stroke-[#10B981] transition-all duration-1000 ease-out"
                  strokeWidth="6"
                  fill="transparent"
                  strokeDasharray={gaugeCircumference}
                  strokeDashoffset={isLoading ? gaugeCircumference : strokeDashoffset}
                  strokeLinecap="round"
                  style={{ filter: "drop-shadow(0px 0px 4px rgba(16, 185, 129, 0.4))" }}
                />
              </svg>
              <div className="absolute flex flex-col items-center justify-center">
                <span className="text-xs font-bold text-white tracking-tight">
                  {isLoading ? "0.0%" : `${aiFieldExtraction.toFixed(1)}%`}
                </span>
                <span className="text-[7px] text-slate-400 font-semibold uppercase tracking-wider mt-0.5">
                  Accuracy
                </span>
              </div>
            </div>
            <div>
              <h3 className="text-xs font-bold text-white tracking-wide">
                AI Score
              </h3>
              <p className="text-[10px] text-slate-400 mt-0.5 leading-relaxed">
                Outbound decision correctness and processing precision.
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-2 bg-slate-900/40 rounded-lg p-2.5 border border-[#222D3D]/50 text-[10px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-400 flex items-center gap-1.5">
                <Target className="w-3.5 h-3.5 text-blue-400" />
                Field Extraction
              </span>
              <span className="font-bold text-white">{isLoading ? "0.0%" : `${aiFieldExtraction.toFixed(1)}%`}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-455 flex items-center gap-1.5 text-slate-400">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                Alert Response
              </span>
              <span className="font-bold text-white">{isLoading ? "0.0%" : `${aiAlertResponse.toFixed(1)}%`}</span>
            </div>
          </div>

          <div className="flex items-center gap-4 justify-center md:justify-start pl-0 md:pl-6 border-t md:border-t-0 md:border-l border-[#222D3D] pt-3 md:pt-0">
            <div className="p-3 rounded-lg bg-[#10B981]/10 border border-[#10B981]/20 text-accent-green shrink-0">
              <CalendarClock className="w-5 h-5" />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                Avg Days to Payment
              </span>
              <span className="text-xl font-bold text-white mt-0.5">
                {isLoading ? "0.0d" : `${avgDaysToPayment.toFixed(1)}d`}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
