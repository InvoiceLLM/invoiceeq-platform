"use client";

import React, { useState } from "react";
import { SlidersHorizontal } from "lucide-react";

export interface OutboundFilterState {
  customerName: string;
  dateRange: string;
}

interface OutboundFilterBarProps {
  onFilterChange: (filters: OutboundFilterState) => void;
  availableCustomers: string[];
}

const DATE_RANGES = [
  { value: "all", label: "All Time" },
  { value: "this_month", label: "This Month" },
  { value: "last_30_days", label: "Last 30 Days" },
  { value: "last_90_days", label: "Last 90 Days" },
];

/**
 * Task 4.1.5 (feature_4.1_vendor_flow_auditor.md): customer-name mirror of
 * FilterBar.tsx, scoped to the outbound tab of /invoices. No tag filter --
 * outbound invoices don't carry FilterBar's tags field. No localStorage
 * persistence in v1 (matches inbound's FilterBar too, so this stays symmetric).
 */
export default function OutboundFilterBar({ onFilterChange, availableCustomers = [] }: OutboundFilterBarProps) {
  const [filters, setFilters] = useState<OutboundFilterState>({ customerName: "", dateRange: "all" });

  const handleChange = (key: keyof OutboundFilterState, value: string) => {
    const next = { ...filters, [key]: value };
    setFilters(next);
    onFilterChange(next);
  };

  return (
    <div className="glass-panel p-4 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div className="flex items-center gap-2 text-white">
        <SlidersHorizontal className="w-5 h-5 text-accent-blue" />
        <span className="font-semibold text-sm tracking-wide">Filters</span>
      </div>

      <div className="flex flex-wrap items-center gap-3 flex-1 justify-end">
        <div className="flex flex-col gap-1 min-w-[140px]">
          <select
            value={filters.customerName}
            onChange={(e) => handleChange("customerName", e.target.value)}
            className="w-full bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer"
          >
            <option value="">All Customers</option>
            {availableCustomers.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1 min-w-[130px]">
          <select
            value={filters.dateRange}
            onChange={(e) => handleChange("dateRange", e.target.value)}
            className="w-full bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer"
          >
            {DATE_RANGES.map((range) => (
              <option key={range.value} value={range.value}>{range.label}</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
