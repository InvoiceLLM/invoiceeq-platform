"use client";

import React from "react";
import { cn } from "../../lib/utils";

interface KpiCardProps {
  title: string;
  value: string | number;
  subtext?: string;
  icon?: React.ReactNode;
  trend?: {
    value: string;
    type: "positive" | "negative" | "warning" | "neutral";
  };
  className?: string;
}

export default function KpiCard({
  title,
  value,
  subtext,
  icon,
  trend,
  className,
}: KpiCardProps) {
  return (
    <div
      className={cn(
        "glass-panel p-6 rounded-xl relative overflow-hidden flex flex-col justify-between h-32 transition-all duration-300 hover:shadow-lg hover:shadow-accent-blue/5 hover:translate-y-[-2px] group",
        className
      )}
    >
      {/* Decorative gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-r from-white/0 via-white/[0.01] to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000 ease-out" />

      {/* Top Header Row */}
      <div className="flex items-center justify-between z-10">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          {title}
        </span>
        {icon && (
          <div className="p-2 rounded-lg bg-slate-800/40 border border-[#222D3D] text-slate-400 group-hover:text-white group-hover:border-slate-700 transition-colors">
            {icon}
          </div>
        )}
      </div>

      {/* Value & Trend Row */}
      <div className="flex items-end justify-between mt-2 z-10">
        <div className="flex flex-col">
          <span className="text-2xl md:text-3xl font-bold text-white tracking-tight leading-none">
            {value}
          </span>
          {subtext && (
            <span className="text-[10px] text-slate-400 mt-1 font-medium">
              {subtext}
            </span>
          )}
        </div>

        {trend && (
          <span
            className={cn(
              "text-xs font-semibold px-2 py-0.5 rounded-full flex items-center gap-0.5 border",
              trend.type === "positive" && "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
              trend.type === "negative" && "bg-rose-500/10 border-rose-500/20 text-rose-400",
              trend.type === "warning" && "bg-amber-500/10 border-amber-500/20 text-amber-400",
              trend.type === "neutral" && "bg-slate-500/10 border-slate-500/20 text-slate-400"
            )}
          >
            {trend.value}
          </span>
        )}
      </div>
    </div>
  );
}
