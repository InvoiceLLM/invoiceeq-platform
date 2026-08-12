"use client";

import React, { useState, useEffect } from "react";
import { SlidersHorizontal, Save, Check } from "lucide-react";

export interface FilterState {
  vendorName: string;
  dateRange: string;
  tag: string;
  status: string;
}

interface FilterBarProps {
  onFilterChange: (filters: FilterState) => void;
  availableVendors: string[];
  availableTags: string[];
  /** Compact variant: no outer panel/label, meant to share a row with a PageHeader title. */
  compact?: boolean;
  /**
   * Gap 200: a status sub-tab above this bar (e.g. "Rejected") already pins
   * the status server-side, which silently overrides whatever this dropdown
   * is set to. Disable it in that case instead of leaving it looking live.
   */
  statusFilterDisabled?: boolean;
}

const LOCAL_STORAGE_KEY = "invoice_dashboard_filters";

const DATE_RANGES = [
  { value: "all", label: "All Time" },
  { value: "this_month", label: "This Month" },
  { value: "last_30_days", label: "Last 30 Days" },
  { value: "last_90_days", label: "Last 90 Days" },
];

const STATUSES = [
  { value: "", label: "All Statuses" },
  { value: "PROCESSING", label: "Processing" },
  { value: "COMPLETED", label: "Completed" },
  { value: "AUDIT_REQUIRED", label: "Audit Required" },
  { value: "PAID", label: "Paid" },
  { value: "REJECTED", label: "Rejected" },
  { value: "DUPLICATE", label: "Duplicate" },
  { value: "FAILED", label: "Failed" },
];

export default function FilterBar({
  onFilterChange,
  availableVendors = [],
  availableTags = [],
  compact = false,
  statusFilterDisabled = false,
}: FilterBarProps) {
  const [filters, setFilters] = useState<FilterState>({
    vendorName: "",
    dateRange: "all",
    tag: "",
    status: "",
  });
  const [isSaved, setIsSaved] = useState(false);

  // Load saved filters on component mount
  useEffect(() => {
    const saved = localStorage.getItem(LOCAL_STORAGE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as FilterState;
        setFilters(parsed);
        onFilterChange(parsed);
      } catch (e) {
        console.error("Failed to parse saved filters", e);
      }
    }
  }, []);

  const handleChange = (key: keyof FilterState, value: string) => {
    const newFilters = { ...filters, [key]: value };
    setFilters(newFilters);
    onFilterChange(newFilters);
    setIsSaved(false); // Reset saved status on filter modification
  };

  const handleSaveFilters = () => {
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(filters));
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2000);
  };

  return (
    <div
      className={
        compact
          ? "flex items-center gap-2"
          : "glass-panel p-4 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-4"
      }
    >
      {/* Title / Controls Header -- omitted in compact mode: the dropdowns
          ("All Clients/Vendors", "All Time", etc.) already say what they are,
          and compact mode shares a row with the page title, where a second
          "Filters" label would be redundant. */}
      {!compact && (
        <div className="flex items-center gap-2 text-white">
          <SlidersHorizontal className="w-5 h-5 text-accent-blue" />
          <span className="font-semibold text-sm tracking-wide">Filters</span>
        </div>
      )}

      {/* Select Controls */}
      <div className={compact ? "flex flex-wrap items-center gap-2" : "flex flex-wrap items-center gap-3 flex-1 justify-end"}>
        {/* Vendor Selector */}
        <div className="flex flex-col gap-1 min-w-[140px]">
          <select
            value={filters.vendorName}
            onChange={(e) => handleChange("vendorName", e.target.value)}
            className="w-full bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer"
          >
            <option value="">All Clients/Vendors</option>
            {availableVendors.map((vendor) => (
              <option key={vendor} value={vendor}>
                {vendor}
              </option>
            ))}
          </select>
        </div>

        {/* Date Range Selector */}
        <div className="flex flex-col gap-1 min-w-[130px]">
          <select
            value={filters.dateRange}
            onChange={(e) => handleChange("dateRange", e.target.value)}
            className="w-full bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer"
          >
            {DATE_RANGES.map((range) => (
              <option key={range.value} value={range.value}>
                {range.label}
              </option>
            ))}
          </select>
        </div>

        {/* Tag Selector */}
        <div className="flex flex-col gap-1 min-w-[120px]">
          <select
            value={filters.tag}
            onChange={(e) => handleChange("tag", e.target.value)}
            className="w-full bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer"
          >
            <option value="">All Tags</option>
            {availableTags.map((t) => (
              <option key={t} value={t}>
                #{t.replace(/^#/, "")}
              </option>
            ))}
          </select>
        </div>

        {/* Status Selector */}
        <div className="flex flex-col gap-1 min-w-[130px]">
          <select
            value={filters.status}
            onChange={(e) => handleChange("status", e.target.value)}
            disabled={statusFilterDisabled}
            title={statusFilterDisabled ? "Status is already set by the selected tab above" : undefined}
            className="w-full bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-[#222D3D]"
          >
            {STATUSES.map((status) => (
              <option key={status.value} value={status.value}>
                {status.label}
              </option>
            ))}
          </select>
        </div>

        {/* Save Button */}
        <button
          onClick={handleSaveFilters}
          className={`flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold tracking-wide transition-all border ${
            isSaved
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
              : "bg-accent-blue/15 hover:bg-accent-blue/25 border-accent-blue/30 hover:border-accent-blue/50 text-[#3B82F6]"
          }`}
        >
          {isSaved ? (
            <>
              <Check className="w-3.5 h-3.5 animate-bounce" />
              Saved
            </>
          ) : (
            <>
              <Save className="w-3.5 h-3.5" />
              Save Filter
            </>
          )}
        </button>
      </div>
    </div>
  );
}
