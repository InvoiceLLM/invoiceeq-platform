import React from "react";
import Link from "next/link";
import { FileText, Shield, Lock, ExternalLink } from "lucide-react";

export function Footer() {
  return (
    <footer className="border-t border-[rgba(255,255,255,0.08)] bg-[#050816]/80 backdrop-blur-[20px] text-[#94A3B8] py-12 relative z-10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-3 group">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-[#3B82F6] to-[#22D3EE] p-0.5 shadow-md shadow-blue-500/20">
              <div className="h-full w-full bg-[#050816] rounded-[6px] flex items-center justify-center">
                <FileText className="h-4 w-4 text-[#22D3EE]" />
              </div>
            </div>
            <span className="text-lg font-bold text-white tracking-tight">
              Invoice<span className="text-[#22D3EE]">.AI</span>
            </span>
          </div>

          <p className="text-xs sm:text-sm text-[#94A3B8] text-center">
            © {new Date().getFullYear()} Invoice AI Platform. All rights reserved. Enterprise multi-tenant AI processing on Azure.
          </p>

          <div className="flex items-center gap-6 text-xs sm:text-sm">
            <Link
              href="/privacy"
              className="hover:text-[#22D3EE] hover:drop-shadow-[0_0_8px_rgba(34,211,238,0.6)] transition-all duration-200"
            >
              Privacy Policy
            </Link>
            <Link
              href="/terms"
              className="hover:text-[#22D3EE] hover:drop-shadow-[0_0_8px_rgba(34,211,238,0.6)] transition-all duration-200"
            >
              Terms of Service
            </Link>
            <Link
              href="#security"
              className="hover:text-[#22D3EE] hover:drop-shadow-[0_0_8px_rgba(34,211,238,0.6)] transition-all duration-200 flex items-center gap-1"
            >
              <Shield className="w-3 h-3 text-[#10B981]" />
              <span>SOC2 Security</span>
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
