"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { 
  LayoutDashboard, 
  UploadCloud, 
  ClipboardList, 
  MessageSquare, 
  Settings, 
  HelpCircle,
  FileText
} from "lucide-react";

export default function Sidebar() {
  const pathname = usePathname();

  const menuItems = [
    { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { name: "Ingest", href: "/ingestion", icon: UploadCloud },
    { name: "Invoices", href: "/audit", icon: ClipboardList },
    { name: "Chat", href: "/chat", icon: MessageSquare },
    { name: "Settings", href: "/settings", icon: Settings },
    { name: "Help", href: "/help", icon: HelpCircle },
  ];

  return (
    <aside className="w-64 border-r border-[#222D3D] bg-[#0F172A]/40 backdrop-blur-md flex flex-col h-full text-slate-300">
      {/* Brand Header */}
      <div className="h-16 flex items-center px-6 border-b border-[#222D3D] gap-3">
        <FileText className="w-6 h-6 text-accent-blue" />
        <span className="font-semibold text-lg text-white tracking-wide">Invoice AI</span>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-4 py-6 space-y-1.5">
        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");

          return (
            <Link
              key={item.name}
              href={item.href}
              className={`flex items-center gap-3.5 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 hover:text-white hover:bg-[#1E293B]/50 ${
                isActive 
                  ? "bg-[#1E293B] text-white border-l-2 border-[#3B82F6] rounded-l-none" 
                  : "text-slate-400"
              }`}
            >
              <Icon className={`w-5 h-5 ${isActive ? "text-[#3B82F6]" : "text-slate-400"}`} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* Tenant Context Footer */}
      <div className="p-4 border-t border-[#222D3D] flex flex-col gap-1.5 text-xs text-slate-500 bg-[#070A13]/20">
        <span>Tenant Isolation ID:</span>
        <span className="font-mono text-[10px] text-slate-400 break-all select-all bg-[#0F172A]/50 p-1.5 rounded border border-[#222D3D]">
          00000000-0000-0000-0000-000000000000
        </span>
      </div>
    </aside>
  );
}
