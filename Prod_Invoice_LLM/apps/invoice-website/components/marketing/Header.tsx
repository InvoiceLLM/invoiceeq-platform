"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { FileText, Menu, X, ArrowRight } from "lucide-react";

interface HeaderProps {
  onOpenFlowsModal?: () => void;
}

export function Header({ onOpenFlowsModal }: HeaderProps) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      if (window.scrollY > 20) {
        setScrolled(true);
      } else {
        setScrolled(false);
      }
    };

    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <header
      className={`sticky top-0 z-50 w-full border-b border-[rgba(255,255,255,0.08)] transition-all duration-300 ${
        scrolled
          ? "bg-[#050816]/95 backdrop-blur-[20px] shadow-lg shadow-black/50"
          : "bg-[#050816]/75 backdrop-blur-[20px]"
      }`}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand Logo */}
        <Link href="/" className="flex items-center gap-3 group">
          <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-[#3B82F6] to-[#22D3EE] p-0.5 flex items-center justify-center group-hover:scale-105 group-hover:shadow-[0_0_20px_rgba(34,211,238,0.6)] transition-all duration-300">
            <div className="h-full w-full bg-[#050816] rounded-[10px] flex items-center justify-center">
              <FileText className="h-5 w-5 text-[#22D3EE] group-hover:text-white transition-colors" />
            </div>
          </div>
          <span className="text-xl font-bold tracking-tight text-white group-hover:drop-shadow-[0_0_12px_rgba(59,130,246,0.6)] transition-all duration-300">
            Invoice<span className="text-[#22D3EE]">.AI</span>
          </span>
        </Link>

        {/* Desktop Navigation Links */}
        <nav className="hidden md:flex items-center gap-8 text-[15px] font-semibold text-[#94A3B8]">
          <a
            href="#architecture-flows"
            onClick={(e) => {
              if (onOpenFlowsModal) {
                e.preventDefault();
                onOpenFlowsModal();
              }
            }}
            className="hover:text-white text-[#22D3EE] hover:drop-shadow-[0_0_8px_rgba(34,211,238,0.5)] transition-all duration-200 flex items-center gap-1.5 cursor-pointer"
          >
            <span>Architecture Flow</span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-[#22D3EE]/15 border border-[#22D3EE]/30">Live</span>
          </a>
          <Link
            href="#features"
            className="hover:text-white hover:drop-shadow-[0_0_8px_rgba(59,130,246,0.5)] transition-all duration-200"
          >
            Features
          </Link>
          <Link
            href="/login"
            className="hover:text-white hover:drop-shadow-[0_0_8px_rgba(59,130,246,0.5)] transition-all duration-200"
          >
            Login
          </Link>
        </nav>

        {/* Action Button */}
        <div className="hidden md:flex items-center gap-4">
          <Link href="/login" className="btn-primary-gradient flex items-center gap-2 text-sm">
            <span>Get Started Free</span>
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>

        {/* Mobile Menu Button */}
        <div className="md:hidden flex items-center">
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-white/5 transition-colors"
            aria-label="Toggle Navigation Menu"
          >
            {mobileMenuOpen ? (
              <X className="w-6 h-6" />
            ) : (
              <Menu className="w-6 h-6" />
            )}
          </button>
        </div>
      </div>

      {/* Mobile Navigation Drawer */}
      {mobileMenuOpen && (
        <div className="md:hidden border-b border-[rgba(255,255,255,0.08)] bg-[#050816]/95 backdrop-blur-[20px] px-4 pt-2 pb-6 space-y-4">
          <nav className="flex flex-col gap-3 font-medium text-[#94A3B8]">
            <Link
              href="#features"
              onClick={() => setMobileMenuOpen(false)}
              className="px-3 py-2 rounded-lg hover:bg-white/5 hover:text-white"
            >
              Features
            </Link>
            <Link
              href="/login"
              onClick={() => setMobileMenuOpen(false)}
              className="px-3 py-2 rounded-lg hover:bg-white/5 hover:text-white"
            >
              Login
            </Link>
          </nav>
          <div className="pt-2 border-t border-[rgba(255,255,255,0.08)]">
            <Link
              href="/login"
              onClick={() => setMobileMenuOpen(false)}
              className="btn-primary-gradient w-full flex items-center justify-center gap-2 text-sm"
            >
              <span>Get Started Free</span>
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      )}
    </header>
  );
}
