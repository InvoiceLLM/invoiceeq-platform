"use client";

import React from "react";
import Sidebar from "./Sidebar";
import Header from "./Header";

interface ShellProps {
  children: React.ReactNode;
}

export default function Shell({ children }: ShellProps) {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg-main">
      {/* Sidebar Panel */}
      <Sidebar />

      {/* Main Panel Content Area */}
      <div className="flex flex-col flex-1 h-full overflow-hidden">
        {/* Top Header */}
        <Header />

        {/* Scrollable Children Canvas */}
        <main className="flex-1 overflow-y-auto p-8 bg-gradient-to-b from-[#0B0F19] to-[#080B12]">
          {children}
        </main>
      </div>
    </div>
  );
}
