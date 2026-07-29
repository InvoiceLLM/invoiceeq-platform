"use client";

import React, { useState, useEffect, useCallback } from "react";
import FilterBar, { FilterState } from "../../components/dashboard/FilterBar";
import RecentInvoicesTable, { StatusTab } from "../../components/dashboard/RecentInvoicesTable";
import { apiClient } from "../../lib/apiClient";
import { useAuth } from "../../hooks/useAuth";

// Relocated from dashboard/page.tsx (Task 4.9, Dashboard/Audit split) --
// Dashboard is overview-only now; this page is the actual invoice queue.
const PAGE_SIZE = 8;

const DEFAULT_VENDORS = ["Hardware Depot", "Cloud Hosting Inc", "Office Supply Corp", "Consulting LLC", "Telco Giants"];
const DEFAULT_TAGS = ["Hardware", "Software", "Services", "Marketing", "Travel"];

function tabToStatusParams(tab: StatusTab): { status?: string; status_in?: string } {
  if (tab === "paid") return { status: "PAID" };
  if (tab === "rejected") return { status: "REJECTED" };
  if (tab === "pending") return { status_in: "PROCESSING,COMPLETED,AUDIT_REQUIRED,DUPLICATE" };
  return {};
}

export default function InvoicesPage() {
  const { loading: authLoading } = useAuth();
  const [filters, setFilters] = useState<FilterState>({
    vendorName: "",
    dateRange: "all",
    tag: "",
    status: "",
  });

  const [invoices, setInvoices] = useState([]);
  const [allInvoices, setAllInvoices] = useState([]); // for vendor/tag dropdown options only

  const [activeTab, setActiveTab] = useState<StatusTab>("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [isInvoicesLoading, setIsInvoicesLoading] = useState(true);

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

  useEffect(() => {
    if (authLoading) return;
    const fetchAllData = async () => {
      try {
        const res = await apiClient.get("/invoices", { params: { limit: 100 } });
        setAllInvoices(res.data || []);
      } catch (err) {
        console.error("Error fetching filter source data", err);
      }
    };
    fetchAllData();
  }, [authLoading]);

  const fetchInvoicesPage = useCallback(async () => {
    if (authLoading) return;
    setIsInvoicesLoading(true);
    const { startDate, endDate } = getDatesForRange(filters.dateRange);

    try {
      const invoicesRes = await apiClient.get("/invoices", {
        params: {
          start_date: startDate,
          end_date: endDate,
          vendor_name: filters.vendorName || undefined,
          tag: filters.tag || undefined,
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE,
          ...(activeTab === "all" ? { status: filters.status || undefined } : tabToStatusParams(activeTab)),
        },
      });

      setInvoices(invoicesRes.data || []);
      const totalHeader = invoicesRes.headers?.["x-total-count"];
      setTotalCount(totalHeader ? parseInt(totalHeader, 10) : (invoicesRes.data || []).length);
    } catch (err) {
      console.error("Error loading invoices page", err);
    } finally {
      setIsInvoicesLoading(false);
    }
  }, [filters, activeTab, currentPage, authLoading]);

  useEffect(() => {
    fetchInvoicesPage();
  }, [fetchInvoicesPage]);

  const handleFilterChange = (newFilters: FilterState) => {
    setFilters(newFilters);
    setCurrentPage(1);
  };

  const handleTabChange = (tab: StatusTab) => {
    setActiveTab(tab);
    setCurrentPage(1);
  };

  const handleInvoiceDeleted = (id: string) => {
    setAllInvoices((prev) => prev.filter((inv: any) => inv.id !== id));
    fetchInvoicesPage();
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const uniqueVendors = Array.from(
    new Set([
      ...allInvoices
        .map((inv: any) => inv.vendor_name)
        .filter((name): name is string => typeof name === "string" && name.trim() !== ""),
      ...DEFAULT_VENDORS,
    ])
  );

  const uniqueTags = Array.from(
    new Set([
      ...allInvoices
        .flatMap((inv: any) => inv.tags || [])
        .filter((t): t is string => typeof t === "string" && t.trim() !== ""),
      ...DEFAULT_TAGS,
    ])
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-white tracking-wide">Invoices</h1>
        <p className="text-xs text-slate-400">
          Full invoice queue -- browse, filter, and open any invoice for audit review.
        </p>
      </div>

      <FilterBar
        onFilterChange={handleFilterChange}
        availableVendors={uniqueVendors}
        availableTags={uniqueTags}
      />

      <RecentInvoicesTable
        invoices={invoices}
        isLoading={isInvoicesLoading}
        onDelete={handleInvoiceDeleted}
        activeTab={activeTab}
        onTabChange={handleTabChange}
        currentPage={currentPage}
        totalPages={totalPages}
        totalCount={totalCount}
        onPageChange={setCurrentPage}
      />
    </div>
  );
}
