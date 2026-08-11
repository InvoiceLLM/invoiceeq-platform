"use client";

import React, { useState } from "react";
import { 
  DollarSign, 
  CheckCircle2, 
  AlertTriangle, 
  Clock, 
  Target, 
  TrendingUp, 
  HelpCircle 
} from "lucide-react";
import KpiCard from "./KpiCard";
import { formatCurrency, normalizeCurrencyCode } from "../../lib/utils";

interface SpendPoint {
  date: string;
  /** FE Gap 183: ISO-4217 code this point's amount is denominated in. */
  currency?: string | null;
  amount: number;
}

/**
 * FE Gap 183: one row per currency from GET /dashboard/metrics. Replaces the
 * old flat total_invoiced/paid_amount/outstanding_amount/at_risk_amount
 * scalars, which were blended SUM()s across every currency the tenant had --
 * a $500 invoice plus a ₹40,000 one read as "40500", labelled "$".
 */
export interface CurrencyTotals {
  currency: string;
  total_invoiced: number;
  paid_amount: number;
  outstanding_amount: number;
  at_risk_amount: number;
}

interface MetricsGridProps {
  metrics: {
    totals_by_currency: CurrencyTotals[];
    average_processing_time: number;
    extraction_accuracy: number;
    active_alerts_count: number;
    spend_over_time: SpendPoint[];
    invoices_by_status: Record<string, number>;
    ai_field_extraction?: number;
    ai_alert_response?: number;
    ai_alerts_missed?: number;
  };
  isLoading: boolean;
}

// One colour per currency series on the trendline. Blue-family so the inbound
// chart keeps its identity against the outbound grid's greens.
const SERIES_COLORS = ["#3B82F6", "#8B5CF6", "#06B6D4", "#F59E0B", "#EC4899"];

export default function MetricsGrid({ metrics, isLoading }: MetricsGridProps) {
  const [hoveredPoint, setHoveredPoint] = useState<SpendPoint | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);

  // Default values and loading fallbacks
  const totalsByCurrency = metrics?.totals_by_currency ?? [];
  const activeAlerts = metrics?.active_alerts_count ?? 0;
  const avgProcessingTime = metrics?.average_processing_time ?? 0;
  const spendOverTime = metrics?.spend_over_time ?? [];

  // FE Gap 183: one KPI line per currency. Never a cross-currency sum.
  const emptyValues = [formatCurrency(0)];
  const lines = (pick: (t: CurrencyTotals) => number) =>
    totalsByCurrency.length === 0
      ? emptyValues
      : totalsByCurrency.map((t) => formatCurrency(pick(t), t.currency));

  // Paid percentage, computed *within* each currency. The old
  // paidAmount / totalInvoiced was a ratio of two blended sums, i.e. a number
  // with no meaning at all once more than one currency was present.
  const paidPercents = totalsByCurrency.map((t) => ({
    currency: normalizeCurrencyCode(t.currency),
    percent: t.total_invoiced > 0 ? Math.round((t.paid_amount / t.total_invoiced) * 100) : 0,
  }));
  const paidPercentSubtext =
    paidPercents.length === 0
      ? "0% of total volume"
      : paidPercents.length === 1
      ? `${paidPercents[0].percent}% of ${paidPercents[0].currency} volume`
      : paidPercents.map((p) => `${p.currency} ${p.percent}%`).join(" · ");
  // A single badge cannot honestly summarise several currencies' paid rates,
  // so it is shown only when there is exactly one currency to report.
  const paidTrend =
    paidPercents.length === 1
      ? {
          value: `${paidPercents[0].percent}% Paid`,
          type: (paidPercents[0].percent > 50 ? "positive" : "neutral") as "positive" | "neutral",
        }
      : undefined;

  const anyAtRisk = totalsByCurrency.some((t) => t.at_risk_amount > 0);

  // Extraction Accuracy (circular indicator).
  // Use real backend data if available, fallback to 0 if loading.
  const extractionAccuracy = metrics?.extraction_accuracy ?? 0.0;
  const aiFieldExtraction = metrics?.ai_field_extraction ?? 100.0;
  const aiAlertResponse = metrics?.ai_alert_response ?? 100.0;
  const aiAlertsMissed = metrics?.ai_alerts_missed ?? 0.0;


  // SVG Chart Dimensions
  const svgWidth = 600;
  const svgHeight = 100;
  const paddingX = 20;
  const paddingY = 14;

  // FE Gap 183: one polyline per currency, each scaled to its *own* min/max.
  // Plotting mixed currencies on one shared scale drew a ₹40,000 day 80x
  // taller than a $500 day and called the difference a spend trend. The x
  // axis stays shared (all dates in the range) so the series remain
  // time-comparable; only the y scale is per-currency.
  const allDates = Array.from(new Set(spendOverTime.map((p) => p.date))).sort();
  const dateIndex = new Map(allDates.map((d, i) => [d, i]));

  const currencySeries = Array.from(
    new Set(spendOverTime.map((p) => normalizeCurrencyCode(p.currency)))
  ).map((currency, seriesIdx) => {
    const points = spendOverTime
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

  // Circular gauge settings -- shrunk from a 112px/radius-52 gauge to fit a
  // more compact metrics strip; center/radius picked so the ring stays fully
  // inside a 96px (w-24 h-24) box with a 6px stroke.
  const gaugeRadius = 40;
  const gaugeCircumference = 2 * Math.PI * gaugeRadius;
  const strokeDashoffset = gaugeCircumference - (aiFieldExtraction / 100) * gaugeCircumference;


  return (
    <div className="space-y-4 w-full">
      {/* KPI Row */}
      <div className="flex flex-wrap gap-3 w-full">
        {/* FE Gap 183: every card takes an array -- one formatted figure per
            currency, never a blended total. KpiCard shrinks the font to keep
            them all inside its fixed height. */}
        <KpiCard
          className="flex-1 min-w-[200px]"
          title="Total Invoiced"
          value={isLoading ? emptyValues : lines((t) => t.total_invoiced)}
          subtext="Lifetime value, per currency"
          icon={<DollarSign className="w-4 h-4 text-accent-blue" />}
        />
        <KpiCard
          className="flex-1 min-w-[200px]"
          title="Paid Amount"
          value={isLoading ? emptyValues : lines((t) => t.paid_amount)}
          subtext={isLoading ? "0% of total volume" : paidPercentSubtext}
          icon={<CheckCircle2 className="w-4 h-4 text-accent-green" />}
          trend={isLoading ? undefined : paidTrend}
        />
        <KpiCard
          className="flex-1 min-w-[200px]"
          title="Outstanding"
          value={isLoading ? emptyValues : lines((t) => t.outstanding_amount)}
          subtext="Pending auditor review/payment"
          icon={<TrendingUp className="w-4 h-4 text-slate-400" />}
        />
        <KpiCard
          className="flex-1 min-w-[200px]"
          title="At-Risk Volume"
          value={isLoading ? emptyValues : lines((t) => t.at_risk_amount)}
          subtext={`${activeAlerts} active extraction alerts`}
          icon={<AlertTriangle className="w-4 h-4 text-accent-yellow" />}
          trend={
            !isLoading && anyAtRisk
              ? { value: "Review Req", type: "warning" }
              : undefined
          }
        />
      </div>

      {/* Spend Graph Panel */}
      <div className="glass-panel p-4 rounded-xl flex flex-col gap-2 relative overflow-hidden w-full">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-xs font-semibold text-white tracking-wide shrink-0">
            Invoice Spend Trend
          </h3>

          <div className="flex items-center gap-2 min-w-0">
            {/* FE Gap 183: legend -- each currency is its own line on its own
                y scale, so the reader has to be told which is which and that
                the heights are not comparable between them. */}
            {!isLoading && currencySeries.length > 1 && (
              <div className="flex items-center gap-2 text-[10px] text-slate-400">
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

            {/* Tooltip detail display */}
            {hoveredPoint && (
              <div className="text-right text-xs bg-slate-800/80 border border-[#222D3D] px-2.5 py-1 rounded-lg animate-fade-in">
                <span className="text-slate-400 mr-1.5">{hoveredPoint.date}:</span>
                <span className="text-white font-bold">
                  {formatCurrency(hoveredPoint.amount, hoveredPoint.currency)}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="w-full relative h-[100px] select-none">
          {isLoading || !hasTrendData ? (
            <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-xs">
              {isLoading ? "Loading spend trend analytics..." : "Insufficient transaction history to build trend graph"}
            </div>
          ) : (
            <svg
              viewBox={`0 0 ${svgWidth} ${svgHeight}`}
              className="w-full h-full overflow-visible"
            >
              <defs>
                {/* Glowing line filter */}
                <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="2" stdDeviation="4" floodColor="#3B82F6" floodOpacity="0.3" />
                </filter>
              </defs>

              {/* Horizontal Guide Lines */}
              <line x1={paddingX} y1={paddingY} x2={svgWidth - paddingX} y2={paddingY} stroke="#1E293B" strokeWidth="0.5" strokeDasharray="3 3" />
              <line x1={paddingX} y1={svgHeight / 2} x2={svgWidth - paddingX} y2={svgHeight / 2} stroke="#1E293B" strokeWidth="0.5" strokeDasharray="3 3" />
              <line x1={paddingX} y1={svgHeight - paddingY} x2={svgWidth - paddingX} y2={svgHeight - paddingY} stroke="#1E293B" strokeWidth="0.5" />

              {/* One series per currency. The area fill is only drawn when a
                  single currency is present -- overlapping translucent fills
                  across currencies read as a stacked total, which is exactly
                  the blended-money impression this gap removes. */}
              {currencySeries.map((series) => (
                <g key={series.currency}>
                  {currencySeries.length === 1 && series.chartPoints.length > 1 && (
                    <>
                      <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={series.color} stopOpacity="0.25" />
                        <stop offset="100%" stopColor="#0B0F19" stopOpacity="0.0" />
                      </linearGradient>
                      <polygon
                        points={
                          `${series.chartPoints[0].x},${svgHeight - paddingY} ` +
                          series.pointsStr +
                          ` ${series.chartPoints[series.chartPoints.length - 1].x},${svgHeight - paddingY}`
                        }
                        fill="url(#chartGradient)"
                      />
                    </>
                  )}

                  {series.chartPoints.length > 1 && (
                    <polyline
                      fill="none"
                      stroke={series.color}
                      strokeWidth="2.5"
                      points={series.pointsStr}
                      filter="url(#glow)"
                    />
                  )}

                  {/* Interactive Points & Guides */}
                  {series.chartPoints.map((p, idx) => {
                    const key = `${series.currency}-${idx}`;
                    return (
                      <g key={key}>
                        {/* Invisible hover area */}
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

                        {/* Vertical guideline on hover */}
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

                        {/* Small glowing circle point */}
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

      {/* AI Score & Processing Time -- combined into one compact card */}
      <div className="glass-panel p-4 rounded-xl w-full">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-center">
          <div className="flex items-center gap-3">
            {/* Dynamic Circular SVG Gauge */}
            <div className="relative w-20 h-20 shrink-0 flex items-center justify-center">
              <svg className="w-full h-full transform -rotate-90" viewBox="0 0 96 96">
                <circle cx="48" cy="48" r={gaugeRadius} className="stroke-[#222D3D]" strokeWidth="6" fill="transparent" />
                <circle
                  cx="48"
                  cy="48"
                  r={gaugeRadius}
                  className="stroke-[#3B82F6] transition-all duration-1000 ease-out"
                  strokeWidth="6"
                  fill="transparent"
                  strokeDasharray={gaugeCircumference}
                  strokeDashoffset={isLoading ? gaugeCircumference : strokeDashoffset}
                  strokeLinecap="round"
                  style={{ filter: "drop-shadow(0px 0px 4px rgba(59, 130, 246, 0.4))" }}
                />
              </svg>
              <div className="absolute flex flex-col items-center justify-center">
                <span className="text-xs font-bold text-white tracking-tight">
                  {isLoading ? "0.0%" : `${aiFieldExtraction.toFixed(1)}%`}
                </span>
                <span className="text-[7px] text-slate-400 font-semibold uppercase tracking-wider mt-0.5">Accuracy</span>
              </div>
            </div>
            <div>
              <h3 className="text-xs font-bold text-white tracking-wide">
                AI Score
              </h3>
              <p className="text-[10px] text-slate-400 mt-0.5 leading-relaxed">
                Overall decision correctness and processing precision.
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-2 bg-slate-900/40 rounded-lg p-2.5 border border-[#222D3D]/50 text-[10px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-455 flex items-center gap-1.5 text-slate-400">
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
            <div className="flex items-center justify-between">
              <span className="text-slate-455 flex items-center gap-1.5 text-slate-400">
                <AlertTriangle className="w-3.5 h-3.5 text-yellow-400" />
                Alerts Missed
              </span>
              <span className="font-bold text-white">{isLoading ? "0.0%" : `${aiAlertsMissed.toFixed(1)}%`}</span>
            </div>
          </div>

          <div className="flex items-center gap-3 justify-center md:justify-start pl-0 md:pl-6 border-t md:border-t-0 md:border-l border-[#222D3D] pt-3 md:pt-0">
            <div className="p-2 rounded-lg bg-[#F59E0B]/10 border border-[#F59E0B]/20 text-accent-yellow shrink-0">
              <Clock className="w-4 h-4" />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                Avg Processing Time
              </span>
              <span className="text-base font-bold text-white leading-tight">
                {isLoading ? "0.0s" : `${avgProcessingTime.toFixed(1)}s`}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
