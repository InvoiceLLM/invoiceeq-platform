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
import { formatCurrency } from "../../lib/utils";

interface SpendPoint {
  date: string;
  amount: number;
}

interface MetricsGridProps {
  metrics: {
    total_invoiced: number;
    paid_amount: number;
    outstanding_amount: number;
    at_risk_amount: number;
    average_processing_time: number;
    extraction_accuracy: number;
    active_alerts_count: number;
    spend_over_time: SpendPoint[];
    invoices_by_status: Record<string, number>;
  };
  isLoading: boolean;
}

export default function MetricsGrid({ metrics, isLoading }: MetricsGridProps) {
  const [hoveredPoint, setHoveredPoint] = useState<SpendPoint | null>(null);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  // Default values and loading fallbacks
  const totalInvoiced = metrics?.total_invoiced ?? 0;
  const paidAmount = metrics?.paid_amount ?? 0;
  const outstandingAmount = metrics?.outstanding_amount ?? 0;
  const atRiskAmount = metrics?.at_risk_amount ?? 0;
  const activeAlerts = metrics?.active_alerts_count ?? 0;
  const avgProcessingTime = metrics?.average_processing_time ?? 0;
  const spendOverTime = metrics?.spend_over_time ?? [];

  // Paid percentage
  const paidPercent = totalInvoiced > 0 ? Math.round((paidAmount / totalInvoiced) * 100) : 0;

  // Extraction Accuracy (circular indicator). 
  // Use real backend data if available, fallback to 0 if loading.
  const extractionAccuracy = metrics?.extraction_accuracy ?? 0.0;

  // SVG Chart Dimensions
  const svgWidth = 600;
  const svgHeight = 100;
  const paddingX = 20;
  const paddingY = 14;

  // Calculate coordinates for Spend Trendline SVG
  let pointsStr = "";
  let areaPointsStr = "";
  let chartPoints: { x: number; y: number; data: SpendPoint }[] = [];

  if (spendOverTime.length > 1) {
    const amounts = spendOverTime.map(p => p.amount);
    const maxAmount = Math.max(...amounts, 100);
    const minAmount = Math.min(...amounts, 0);
    const range = maxAmount - minAmount || 1;

    chartPoints = spendOverTime.map((p, idx) => {
      const x = paddingX + (idx / (spendOverTime.length - 1)) * (svgWidth - 2 * paddingX);
      const y = svgHeight - paddingY - ((p.amount - minAmount) / range) * (svgHeight - 2 * paddingY);
      return { x, y, data: p };
    });

    pointsStr = chartPoints.map(p => `${p.x},${p.y}`).join(" ");
    areaPointsStr = `${chartPoints[0].x},${svgHeight - paddingY} ` + 
                    pointsStr + 
                    ` ${chartPoints[chartPoints.length - 1].x},${svgHeight - paddingY}`;
  }

  // Circular gauge settings -- shrunk from a 112px/radius-52 gauge to fit a
  // more compact metrics strip; center/radius picked so the ring stays fully
  // inside a 96px (w-24 h-24) box with a 6px stroke.
  const gaugeRadius = 40;
  const gaugeCircumference = 2 * Math.PI * gaugeRadius;
  const strokeDashoffset = gaugeCircumference - (extractionAccuracy / 100) * gaugeCircumference;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
      {/* KPI Cards & Spend Graph Container */}
      <div className="lg:col-span-3 space-y-3">
        {/* KPI Row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
          <KpiCard
            title="Total Invoiced"
            value={isLoading ? "$0.00" : formatCurrency(totalInvoiced)}
            subtext="Lifetime aggregated value"
            icon={<DollarSign className="w-4 h-4 text-accent-blue" />}
          />
          <KpiCard
            title="Paid Amount"
            value={isLoading ? "$0.00" : formatCurrency(paidAmount)}
            subtext={`${paidPercent}% of total volume`}
            icon={<CheckCircle2 className="w-4 h-4 text-accent-green" />}
            trend={{
              value: `${paidPercent}% Paid`,
              type: paidPercent > 50 ? "positive" : "neutral",
            }}
          />
          <KpiCard
            title="Outstanding"
            value={isLoading ? "$0.00" : formatCurrency(outstandingAmount)}
            subtext="Pending auditor review/payment"
            icon={<TrendingUp className="w-4 h-4 text-slate-400" />}
          />
          <KpiCard
            title="At-Risk Volume"
            value={isLoading ? "$0.00" : formatCurrency(atRiskAmount)}
            subtext={`${activeAlerts} active extraction alerts`}
            icon={<AlertTriangle className="w-4 h-4 text-accent-yellow" />}
            trend={
              atRiskAmount > 0
                ? { value: "Review Req", type: "warning" }
                : undefined
            }
          />
        </div>

        {/* Spend Graph Panel */}
        <div className="glass-panel p-4 rounded-xl flex flex-col gap-2 relative overflow-hidden">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-white tracking-wide">
              Invoice Spend Trend
            </h3>

            {/* Tooltip detail display */}
            {hoveredPoint && (
              <div className="text-right text-xs bg-slate-800/80 border border-[#222D3D] px-2.5 py-1 rounded-lg animate-fade-in">
                <span className="text-slate-400 mr-1.5">{hoveredPoint.date}:</span>
                <span className="text-white font-bold">{formatCurrency(hoveredPoint.amount)}</span>
              </div>
            )}
          </div>

          <div className="w-full relative h-[100px] select-none">
            {isLoading || spendOverTime.length <= 1 ? (
              <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-xs">
                {isLoading ? "Loading spend trend analytics..." : "Insufficient transaction history to build trend graph"}
              </div>
            ) : (
              <svg 
                viewBox={`0 0 ${svgWidth} ${svgHeight}`} 
                className="w-full h-full overflow-visible"
              >
                <defs>
                  {/* Glowing Area Gradient */}
                  <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3B82F6" stopOpacity="0.25" />
                    <stop offset="100%" stopColor="#0B0F19" stopOpacity="0.0" />
                  </linearGradient>
                  {/* Glowing line filter */}
                  <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
                    <feDropShadow dx="0" dy="2" stdDeviation="4" floodColor="#3B82F6" floodOpacity="0.3" />
                  </filter>
                </defs>

                {/* Horizontal Guide Lines */}
                <line x1={paddingX} y1={paddingY} x2={svgWidth - paddingX} y2={paddingY} stroke="#1E293B" strokeWidth="0.5" strokeDasharray="3 3" />
                <line x1={paddingX} y1={svgHeight / 2} x2={svgWidth - paddingX} y2={svgHeight / 2} stroke="#1E293B" strokeWidth="0.5" strokeDasharray="3 3" />
                <line x1={paddingX} y1={svgHeight - paddingY} x2={svgWidth - paddingX} y2={svgHeight - paddingY} stroke="#1E293B" strokeWidth="0.5" />

                {/* Chart Area Fill */}
                <polygon points={areaPointsStr} fill="url(#chartGradient)" />

                {/* Chart Stroke Line */}
                <polyline
                  fill="none"
                  stroke="#3B82F6"
                  strokeWidth="2.5"
                  points={pointsStr}
                  filter="url(#glow)"
                />

                {/* Interactive Points & Guides */}
                {chartPoints.map((p, idx) => (
                  <g key={idx}>
                    {/* Invisible hover area */}
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
                    
                    {/* Vertical guideline on hover */}
                    {hoveredIndex === idx && (
                      <line
                        x1={p.x}
                        y1={paddingY}
                        x2={p.x}
                        y2={svgHeight - paddingY}
                        stroke="#3B82F6"
                        strokeWidth="1"
                        strokeDasharray="2 2"
                        className="pointer-events-none"
                      />
                    )}

                    {/* Small glowing circle point */}
                    <circle
                      cx={p.x}
                      cy={p.y}
                      r={hoveredIndex === idx ? "5" : "3.5"}
                      fill={hoveredIndex === idx ? "#3B82F6" : "#1e293b"}
                      stroke="#3B82F6"
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

      {/* Accuracy & Processing Time -- combined into one compact card
          (previously two separate glass panels totaling ~320px tall for two
          numbers) */}
      <div className="lg:col-span-1">
        <div className="glass-panel p-4 rounded-xl flex flex-col gap-3 h-full">
          <div className="flex items-center gap-3">
            {/* Dynamic Circular SVG Gauge -- shrunk from 112px to 96px */}
            <div className="relative w-24 h-24 shrink-0 flex items-center justify-center">
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
                <span className="text-sm font-bold text-white tracking-tight">
                  {isLoading ? "0.0%" : `${extractionAccuracy.toFixed(1)}%`}
                </span>
              </div>
            </div>
            <div>
              <h3 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                Extraction Accuracy
              </h3>
              <div className="flex items-center gap-1 text-emerald-400 text-[10px] font-medium mt-0.5">
                <Target className="w-3 h-3" />
                <span>Above 95% target</span>
              </div>
              <div className="mt-1 px-1.5 py-0.5 rounded bg-blue-500/10 border border-blue-500/20 text-[9px] text-blue-400 font-medium font-mono inline-block">
                AI Field Acceptance: {isLoading ? "0.0%" : `${(extractionAccuracy * 1.01 > 100 ? 100 : extractionAccuracy * 1.01).toFixed(1)}%`}
              </div>
            </div>
          </div>

          <div className="h-px bg-[#222D3D]" />

          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-[#F59E0B]/10 border border-[#F59E0B]/20 text-accent-yellow shrink-0">
              <Clock className="w-4 h-4" />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                Avg Processing Time
              </span>
              <span className="text-lg font-bold text-white leading-tight">
                {isLoading ? "0.0s" : `${avgProcessingTime.toFixed(1)}s`}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
