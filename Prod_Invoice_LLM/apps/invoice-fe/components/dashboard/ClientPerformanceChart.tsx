"use client";

import React, { useState } from "react";
import { Users, BarChart3 } from "lucide-react";
import { formatCurrency } from "../../lib/utils";

interface VendorSpend {
  vendor_name: string;
  amount: number;
}

interface ClientPerformanceChartProps {
  vendors: VendorSpend[];
  isLoading: boolean;
}

export default function ClientPerformanceChart({
  vendors = [],
  isLoading,
}: ClientPerformanceChartProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  // Take top 5 vendors
  const topVendors = (vendors || []).slice(0, 5);
  
  // Find maximum billing amount to scale progress bars
  const maxAmount = topVendors.length > 0 ? Math.max(...topVendors.map((v) => v.amount)) : 1;

  return (
    <div className="glass-panel p-6 rounded-xl flex flex-col gap-6 h-full min-h-[340px]">
      {/* Component Title Header */}
      <div className="flex items-center justify-between border-b border-[#222D3D] pb-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-accent-blue" />
          <div>
            <h3 className="text-sm font-semibold text-white tracking-wide">
              Top Clients & Vendors
            </h3>
            <p className="text-xs text-slate-400">
              Ranking by aggregated billing volumes.
            </p>
          </div>
        </div>
        <Users className="w-5 h-5 text-slate-500" />
      </div>

      {/* Vendors Ranking Bars */}
      <div className="flex-1 flex flex-col justify-center gap-4">
        {isLoading ? (
          <div className="flex flex-col gap-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="space-y-2 animate-pulse">
                <div className="flex justify-between text-xs">
                  <div className="h-3 w-24 bg-slate-800 rounded"></div>
                  <div className="h-3 w-12 bg-slate-800 rounded"></div>
                </div>
                <div className="h-2 w-full bg-slate-800 rounded-full"></div>
              </div>
            ))}
          </div>
        ) : topVendors.length === 0 ? (
          <div className="text-center text-slate-500 text-xs py-8">
            No client data found for this range.
          </div>
        ) : (
          <div className="space-y-4">
            {topVendors.map((vendor, index) => {
              const percentage = Math.max(5, (vendor.amount / maxAmount) * 100);
              const isHovered = hoveredIndex === index;

              return (
                <div
                  key={vendor.vendor_name}
                  className="space-y-1.5 cursor-pointer group"
                  onMouseEnter={() => setHoveredIndex(index)}
                  onMouseLeave={() => setHoveredIndex(null)}
                >
                  {/* Vendor Details Text Row */}
                  <div className="flex justify-between text-xs font-semibold select-none">
                    <span className="text-slate-300 group-hover:text-white transition-colors duration-150 truncate max-w-[200px]">
                      {index + 1}. {vendor.vendor_name}
                    </span>
                    <span className="text-slate-400 group-hover:text-[#3B82F6] transition-colors duration-150 font-mono">
                      {formatCurrency(vendor.amount)}
                    </span>
                  </div>

                  {/* Horizontal Bar Graphic */}
                  <div className="relative w-full h-2.5 bg-slate-800/40 border border-[#222D3D] rounded-full overflow-hidden">
                    <div
                      className="absolute top-0 left-0 bottom-0 rounded-full transition-all duration-500 ease-out"
                      style={{
                        width: `${percentage}%`,
                        backgroundColor: isHovered ? "#3B82F6" : "#94A3B8",
                        boxShadow: isHovered
                          ? "0 0 8px rgba(59, 130, 246, 0.4)"
                          : "none",
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
