"use client";

import { useState } from "react";
import { Search, Bell, HelpCircle, ChevronDown, User, LogOut, Settings } from "lucide-react";

export default function Header() {
  const [showProfileMenu, setShowProfileMenu] = useState(false);

  return (
    <header className="h-16 border-b border-[#222D3D] bg-[#0B0F19]/80 backdrop-blur-md flex items-center justify-between px-8 text-slate-300 z-10">
      {/* Search Input Container */}
      <div className="relative w-96">
        <span className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
          <Search className="h-4.5 w-4.5 text-slate-400" />
        </span>
        <input
          type="text"
          placeholder="Search invoices, vendors, or batches..."
          className="w-full bg-[#151B26]/50 border border-[#222D3D] rounded-lg py-2 pl-10 pr-4 text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6] transition-all duration-200"
        />
      </div>

      {/* Right Controls Container */}
      <div className="flex items-center gap-6">
        {/* Help Link */}
        <button 
          className="p-1.5 rounded-lg hover:bg-[#1E293B]/50 hover:text-white transition-all text-slate-400 relative"
          title="Help Center"
        >
          <HelpCircle className="h-5 w-5" />
        </button>

        {/* Notifications Tray */}
        <button 
          className="p-1.5 rounded-lg hover:bg-[#1E293B]/50 hover:text-white transition-all text-slate-400 relative"
          title="Notifications"
        >
          <Bell className="h-5 w-5" />
          <span className="absolute top-1 right-1.5 h-2 w-2 rounded-full bg-[#3B82F6] ring-2 ring-[#0B0F19]"></span>
        </button>

        {/* Vertical Divider */}
        <div className="h-6 w-px bg-[#222D3D]"></div>

        {/* User Profile Card Dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowProfileMenu(!showProfileMenu)}
            className="flex items-center gap-3.5 pl-2 py-1.5 pr-3 rounded-lg hover:bg-[#1E293B]/40 transition-all duration-200 group"
          >
            <div className="w-8 h-8 rounded-full bg-[#3B82F6]/10 border border-[#3B82F6]/30 flex items-center justify-center text-[#3B82F6] text-sm font-semibold select-none">
              AR
            </div>
            <div className="text-left hidden md:block">
              <p className="text-xs font-semibold text-white tracking-wide">Alex R.</p>
              <p className="text-[10px] text-slate-400 mt-0.5">Acme Corp. (Admin)</p>
            </div>
            <ChevronDown className="w-4 h-4 text-slate-400 group-hover:text-white transition-colors" />
          </button>

          {/* Profile Menu Dropdown */}
          {showProfileMenu && (
            <div className="absolute right-0 mt-2.5 w-52 bg-[#0F172A] border border-[#222D3D] rounded-xl shadow-xl py-2 z-20 animate-in fade-in slide-in-from-top-2 duration-150">
              <div className="px-4 py-2 border-b border-[#222D3D] mb-1.5">
                <p className="text-xs text-slate-400">Signed in as</p>
                <p className="text-xs font-semibold text-white truncate mt-0.5">alex.r@acme.com</p>
              </div>
              <button 
                onClick={() => setShowProfileMenu(false)}
                className="w-full flex items-center gap-3 px-4 py-2 text-sm text-slate-300 hover:bg-[#1E293B]/70 hover:text-white transition-colors text-left"
              >
                <User className="w-4 h-4 text-slate-400" />
                My Profile
              </button>
              <button 
                onClick={() => setShowProfileMenu(false)}
                className="w-full flex items-center gap-3 px-4 py-2 text-sm text-slate-300 hover:bg-[#1E293B]/70 hover:text-white transition-colors text-left"
              >
                <Settings className="w-4 h-4 text-slate-400" />
                Account Settings
              </button>
              <div className="h-px bg-[#222D3D] my-1.5"></div>
              <button 
                onClick={() => setShowProfileMenu(false)}
                className="w-full flex items-center gap-3 px-4 py-2 text-sm text-red-500 hover:bg-red-500/10 transition-colors text-left"
              >
                <LogOut className="w-4 h-4" />
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
