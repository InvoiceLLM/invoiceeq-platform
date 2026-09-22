"use client";

import React, { useState, useEffect, useRef } from "react";
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
  /**
   * Gap 316: which flow this instance filters. Swaps the party-field label
   * ("Clients/Vendors" vs "Customers") and the status option list to that
   * direction's real vocabulary -- inbound's PAID/REJECTED/AUDIT_REQUIRED
   * set is meaningless for outbound's UPLOADED/VERIFIED/NEEDS_REVIEW/SENT
   * lifecycle, and vice versa. Also namespaces the saved-filter localStorage
   * key so an inbound and outbound bar rendered side by side (a tenant with
   * both flows on) don't clobber each other's saved state.
   */
  direction?: "inbound" | "outbound";
  /**
   * FE Gap 702: filter values this bar must open with, supplied by the page
   * because they came off the URL.
   *
   * **They beat the saved filters, on purpose.** A user who arrived here by
   * clicking "Put these back in the queue" on an ATLAS line asked for the stuck
   * list *now*; a filter set they saved last Tuesday is a weaker statement of
   * intent than the click they just made, and silently restoring it would make
   * the destination look broken in exactly the way FE Gap 702 recorded.
   *
   * Nothing is written to `localStorage` by this: the Save button is still the
   * only thing that persists a filter set, so a one-off arrival from a link does
   * not quietly become the user's default.
   */
  initialFilters?: Partial<FilterState>;
}

const LOCAL_STORAGE_KEY = "invoice_dashboard_filters";

const DATE_RANGES = [
  { value: "all", label: "All Time" },
  { value: "this_month", label: "This Month" },
  { value: "last_30_days", label: "Last 30 Days" },
  { value: "last_90_days", label: "Last 90 Days" },
];

const INBOUND_STATUSES = [
  { value: "", label: "All Statuses" },
  { value: "PROCESSING", label: "Processing" },
  { value: "COMPLETED", label: "Completed" },
  { value: "AUDIT_REQUIRED", label: "Audit Required" },
  { value: "REVIEW_LATER", label: "Review Later" },
  { value: "NEEDS_RESUBMISSION", label: "Needs Resubmission" },
  { value: "PAID", label: "Paid" },
  { value: "REJECTED", label: "Rejected" },
  { value: "DUPLICATE", label: "Duplicate" },
  { value: "FAILED", label: "Failed" },
];

// Gap 316: outbound's real status lifecycle (routers/outbound_invoices.py,
// outbound_handlers.py) -- distinct from inbound's, never PAID/REJECTED-only.
const OUTBOUND_STATUSES = [
  { value: "", label: "All Statuses" },
  { value: "UPLOADED", label: "Uploaded" },
  { value: "VERIFIED", label: "Verified" },
  { value: "NEEDS_REVIEW", label: "Needs Review" },
  { value: "SENT", label: "Sent" },
  { value: "PAID", label: "Paid" },
];

export default function FilterBar({
  onFilterChange,
  availableVendors = [],
  availableTags = [],
  compact = false,
  statusFilterDisabled = false,
  direction = "inbound",
  initialFilters,
}: FilterBarProps) {
  const isOutbound = direction === "outbound";
  const statusOptions = isOutbound ? OUTBOUND_STATUSES : INBOUND_STATUSES;
  const partyLabel = isOutbound ? "All Customers" : "All Clients/Vendors";
  const storageKey = `${LOCAL_STORAGE_KEY}_${direction}`;

  const [filters, setFilters] = useState<FilterState>({
    vendorName: "",
    dateRange: "all",
    tag: "",
    status: "",
    ...(initialFilters || {}),
  });
  const [isSaved, setIsSaved] = useState(false);

  // FE Gap 702: an explicit arrival ("open the stuck list") outranks a saved
  // filter set. Read once, not on every render, because the point is what this
  // bar MOUNTED with -- a later edit by the user must not re-trigger it.
  const seededFromUrlRef = useRef(
    Boolean(initialFilters && Object.values(initialFilters).some((value) => value))
  );

  // Load saved filters on component mount
  useEffect(() => {
    if (seededFromUrlRef.current) return;
    const saved = localStorage.getItem(storageKey);
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
    localStorage.setItem(storageKey, JSON.stringify(filters));
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
      {compact ? (
        <div className="flex flex-col gap-2 w-full">
          {/* Row 1: Vendor + Date */}
          <div className="flex items-center gap-2 w-full">
            {/* Vendor Selector */}
            <div className="flex-1 min-w-0">
              <select
                value={filters.vendorName}
                onChange={(e) => handleChange("vendorName", e.target.value)}
                className="w-full truncate bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer"
              >
                <option value="">{partyLabel}</option>
                {filters.vendorName && !availableVendors.includes(filters.vendorName) && (
                  <option value={filters.vendorName}>{filters.vendorName}</option>
                )}
                {availableVendors.map((vendor) => (
                  <option key={vendor} value={vendor}>
                    {vendor}
                  </option>
                ))}
              </select>
            </div>

            {/* Date Range Selector */}
            <div className="flex-1 min-w-0">
              <select
                value={filters.dateRange}
                onChange={(e) => handleChange("dateRange", e.target.value)}
                className="w-full truncate bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer"
              >
                {DATE_RANGES.map((range) => (
                  <option key={range.value} value={range.value}>
                    {range.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Row 2: Tag + Status + Save Filter */}
          <div className="flex items-center gap-2 w-full">
            {/* Tag Selector */}
            <div className="flex-1 min-w-0">
              <select
                value={filters.tag}
                onChange={(e) => handleChange("tag", e.target.value)}
                className="w-full truncate bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer"
              >
                <option value="">All Tags</option>
                {filters.tag && !availableTags.includes(filters.tag) && (
                  <option value={filters.tag}>#{filters.tag.replace(/^#/, "")}</option>
                )}
                {availableTags.map((t) => (
                  <option key={t} value={t}>
                    #{t.replace(/^#/, "")}
                  </option>
                ))}
              </select>
            </div>

            {/* Status Selector */}
            <div className="flex-1 min-w-0">
              <select
                value={filters.status}
                onChange={(e) => handleChange("status", e.target.value)}
                disabled={statusFilterDisabled}
                title={statusFilterDisabled ? "Status is already set by the selected tab above" : undefined}
                className="w-full truncate bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-[#222D3D]"
              >
                {statusOptions.map((status) => (
                  <option key={status.value} value={status.value}>
                    {status.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Save Button */}
            <button
              onClick={handleSaveFilters}
              className={`shrink-0 flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold tracking-wide transition-all border whitespace-nowrap ${
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
      ) : (
        <div className="flex flex-wrap items-center gap-3 flex-1 justify-end">
          {/* Vendor Selector */}
          <div className="flex flex-col gap-1 min-w-[140px]">
            <select
              value={filters.vendorName}
              onChange={(e) => handleChange("vendorName", e.target.value)}
              className="w-full bg-[#1A2230] border border-[#222D3D] hover:border-[#3B82F6]/50 rounded-lg py-2 px-3 text-xs text-slate-300 focus:outline-none focus:border-[#3B82F6] transition-all cursor-pointer"
            >
              <option value="">{partyLabel}</option>
              {filters.vendorName && !availableVendors.includes(filters.vendorName) && (
                <option value={filters.vendorName}>{filters.vendorName}</option>
              )}
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
              {filters.tag && !availableTags.includes(filters.tag) && (
                <option value={filters.tag}>#{filters.tag.replace(/^#/, "")}</option>
              )}
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
              {statusOptions.map((status) => (
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
      )}
    </div>
  );
}
