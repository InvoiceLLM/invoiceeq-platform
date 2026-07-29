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
import { formatCurrency } from "../../lib/utils";

interface RevenuePoint {
  date: string;
  amount: number;
}

export interface CustomerRevenue {
  customer_name: string;
  amount: number;
}

export interface OutboundMetrics {
  total_invoiced_out: number;
  amount_collected: number;
  outstanding_receivables: number;
  at_risk_receivables: number;
  average_days_to_payment: number;
  verification_accuracy: number;
  active_alerts_count: number;
  revenue_over_time: RevenuePoint[];
  // Not rendered by this grid -- ClientPerformanceChart consumes it from the
  // same payload (Task 2.1.4), so it belongs on the shared response type.
  top_customers: CustomerRevenue[];
  invoices_by_status: Record<string, number>;
}

interface OutboundMetricsGridProps {
  metrics: OutboundMetrics;
  isLoading: boolean;
}

export const defaultOutboundMetrics: OutboundMetrics = {
  total_invoiced_out: 0,
  amount_collected: 0,
  outstanding_receivables: 0,
  at_risk_receivables: 0,
  average_days_to_payment: 0,
  verification_accuracy: 0,
  active_alerts_count: 0,
  revenue_over_time: [],
  top_customers: [],
  invoices_by_status: {},
};

const ACCURACY_TARGET = 95.0;

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
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const totalInvoicedOut = metrics?.total_invoiced_out ?? 0;
  const amountCollected = metrics?.amount_collected ?? 0;
  const outstandingReceivables = metrics?.outstanding_receivables ?? 0;
  const atRiskReceivables = metrics?.at_risk_receivables ?? 0;
  const activeAlerts = metrics?.active_alerts_count ?? 0;
  const avgDaysToPayment = metrics?.average_days_to_payment ?? 0;
  const revenueOverTime = metrics?.revenue_over_time ?? [];
  const verificationAccuracy = metrics?.verification_accuracy ?? 0.0;

  const collectedPercent =
    totalInvoicedOut > 0 ? Math.round((amountCollected / totalInvoicedOut) * 100) : 0;

  // SVG chart dimensions -- same geometry as MetricsGrid's spend trend so the
  // two halves line up visually when rendered side by side.
  const svgWidth = 600;
  const svgHeight = 160;
  const paddingX = 20;
  const paddingY = 20;

  let pointsStr = "";
  let areaPointsStr = "";
  let chartPoints: { x: number; y: number; data: RevenuePoint }[] = [];

  if (revenueOverTime.length > 1) {
    const amounts = revenueOverTime.map((p) => p.amount);
    const maxAmount = Math.max(...amounts, 100);
    const minAmount = Math.min(...amounts, 0);
    const range = maxAmount - minAmount || 1;

    chartPoints = revenueOverTime.map((p, idx) => {
      const x = paddingX + (idx / (revenueOverTime.length - 1)) * (svgWidth - 2 * paddingX);
      const y = svgHeight - paddingY - ((p.amount - minAmount) / range) * (svgHeight - 2 * paddingY);
      return { x, y, data: p };
    });

    pointsStr = chartPoints.map((p) => `${p.x},${p.y}`).join(" ");
    areaPointsStr =
      `${chartPoints[0].x},${svgHeight - paddingY} ` +
      pointsStr +
      ` ${chartPoints[chartPoints.length - 1].x},${svgHeight - paddingY}`;
  }

  const gaugeRadius = 52;
  const gaugeCircumference = 2 * Math.PI * gaugeRadius;
  const strokeDashoffset = gaugeCircumference - (verificationAccuracy / 100) * gaugeCircumference;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
      <div className="lg:col-span-3 space-y-6">
        {/* KPI Row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          <KpiCard
            title="Total Invoiced Out"
            value={isLoading ? "$0.00" : formatCurrency(totalInvoicedOut)}
            subtext="Lifetime billed to customers"
            icon={<DollarSign className="w-4 h-4 text-accent-blue" />}
          />
          <KpiCard
            title="Collected"
            value={isLoading ? "$0.00" : formatCurrency(amountCollected)}
            subtext={`${collectedPercent}% of total billed`}
            icon={<CheckCircle2 className="w-4 h-4 text-accent-green" />}
            trend={{
              value: `${collectedPercent}% Collected`,
              type: collectedPercent > 50 ? "positive" : "neutral",
            }}
          />
          <KpiCard
            title="Outstanding"
            value={isLoading ? "$0.00" : formatCurrency(outstandingReceivables)}
            subtext="Awaiting send, review, or payment"
            icon={<TrendingUp className="w-4 h-4 text-slate-400" />}
          />
          <KpiCard
            title="At-Risk (Overdue)"
            value={isLoading ? "$0.00" : formatCurrency(atRiskReceivables)}
            subtext={`${activeAlerts} active verification alerts`}
            icon={<AlertTriangle className="w-4 h-4 text-accent-yellow" />}
            trend={atRiskReceivables > 0 ? { value: "Chase Up", type: "warning" } : undefined}
          />
        </div>

        {/* Revenue Trend Panel */}
        <div className="glass-panel p-6 rounded-xl flex flex-col gap-4 relative overflow-hidden">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-white tracking-wide">
                Receivables Trend
              </h3>
              <p className="text-xs text-slate-400">
                Daily invoiced-out billing trends mapped over time.
              </p>
            </div>

            {hoveredPoint && (
              <div className="text-right text-xs bg-slate-800/80 border border-[#222D3D] px-2.5 py-1 rounded-lg animate-fade-in">
                <span className="text-slate-400 mr-1.5">{hoveredPoint.date}:</span>
                <span className="text-white font-bold">{formatCurrency(hoveredPoint.amount)}</span>
              </div>
            )}
          </div>

          <div className="w-full relative h-[160px] select-none">
            {isLoading || revenueOverTime.length <= 1 ? (
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

                <polygon points={areaPointsStr} fill="url(#outboundChartGradient)" />

                <polyline
                  fill="none"
                  stroke="#10B981"
                  strokeWidth="2.5"
                  points={pointsStr}
                  filter="url(#outboundGlow)"
                />

                {chartPoints.map((p, idx) => (
                  <g key={idx}>
                    <circle
                      cx={p.x}
                      cy={p.y}
                      r="12"
                      fill="transparent"
                      className="cursor-pointer"
                      onMouseEnter={() => {
                        setHoveredPoint(p.data);
                        setHoveredIndex(idx);
                      }}
                      onMouseLeave={() => {
                        setHoveredPoint(null);
                        setHoveredIndex(null);
                      }}
                    />

                    {hoveredIndex === idx && (
                      <line
                        x1={p.x}
                        y1={paddingY}
                        x2={p.x}
                        y2={svgHeight - paddingY}
                        stroke="#10B981"
                        strokeWidth="1"
                        strokeDasharray="2 2"
                        className="pointer-events-none"
                      />
                    )}

                    <circle
                      cx={p.x}
                      cy={p.y}
                      r={hoveredIndex === idx ? "5" : "3.5"}
                      fill={hoveredIndex === idx ? "#10B981" : "#1e293b"}
                      stroke="#10B981"
                      strokeWidth="1.5"
                      className="pointer-events-none transition-all duration-150"
                    />
                  </g>
                ))}
              </svg>
            )}
          </div>
        </div>
      </div>

      {/* Verification Accuracy & Days-to-Payment Column */}
      <div className="lg:col-span-1 flex flex-col gap-6">
        <div className="glass-panel p-6 rounded-xl flex flex-col items-center justify-between flex-1 min-h-[220px]">
          <div className="text-center w-full">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Verification Accuracy
            </h3>
            <p className="text-[10px] text-slate-500 mt-0.5">
              Outbound invoices verified with no alerts
            </p>
          </div>

          <div className="relative w-28 h-28 my-2 flex items-center justify-center">
            <svg className="w-full h-full transform -rotate-90">
              <circle
                cx="56"
                cy="56"
                r={gaugeRadius}
                className="stroke-[#222D3D]"
                strokeWidth="7"
                fill="transparent"
              />
              <circle
                cx="56"
                cy="56"
                r={gaugeRadius}
                className="stroke-[#10B981] transition-all duration-1000 ease-out"
                strokeWidth="7"
                fill="transparent"
                strokeDasharray={gaugeCircumference}
                strokeDashoffset={isLoading ? gaugeCircumference : strokeDashoffset}
                strokeLinecap="round"
                style={{ filter: "drop-shadow(0px 0px 4px rgba(16, 185, 129, 0.4))" }}
              />
            </svg>
            <div className="absolute flex flex-col items-center justify-center">
              <span className="text-lg font-bold text-white tracking-tight">
                {isLoading ? "0.0%" : `${verificationAccuracy.toFixed(1)}%`}
              </span>
              <span className="text-[8px] uppercase tracking-wider text-slate-400">
                First Pass
              </span>
            </div>
          </div>

          {/* Reports against the target rather than asserting it was met --
              the real number decides which message shows. */}
          <div
            className={`flex items-center gap-1.5 text-xs font-medium ${
              verificationAccuracy >= ACCURACY_TARGET ? "text-emerald-400" : "text-amber-400"
            }`}
          >
            <Target className="w-3.5 h-3.5" />
            <span>
              {verificationAccuracy >= ACCURACY_TARGET
                ? `Target benchmark met (${ACCURACY_TARGET.toFixed(1)}%)`
                : `Below target benchmark (${ACCURACY_TARGET.toFixed(1)}%)`}
            </span>
          </div>
        </div>

        {/* Avg Days to Payment */}
        <div className="glass-panel p-6 rounded-xl flex items-center gap-4 h-24">
          <div className="p-3 rounded-lg bg-[#10B981]/10 border border-[#10B981]/20 text-accent-green">
            <CalendarClock className="w-5 h-5" />
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
              Avg Days to Payment
            </span>
            <span className="text-xl font-bold text-white mt-0.5">
              {isLoading ? "0.0d" : `${avgDaysToPayment.toFixed(1)}d`}
            </span>
            <span className="text-[9px] text-slate-500">
              Real sent-to-paid elapsed time
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
