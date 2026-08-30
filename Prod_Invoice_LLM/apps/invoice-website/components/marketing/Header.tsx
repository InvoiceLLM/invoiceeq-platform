"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FileText, Menu, X, ArrowRight } from "lucide-react";

interface HeaderProps {
  onOpenFlowsModal?: () => void;
}

/* Active-state treatment shared by every nav link (desktop + mobile drawer) so
   the indicator is computed from the real location, not hardcoded on one link. */
const NAV_ACTIVE = "text-white drop-shadow-[0_0_10px_rgba(59,130,246,0.7)]";
const NAV_IDLE = "hover:text-white hover:drop-shadow-[0_0_8px_rgba(59,130,246,0.5)]";

export function Header({ onOpenFlowsModal }: HeaderProps) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const pathname = usePathname();
  const [hash, setHash] = useState("");
  const loginTargetHref = pathname === "/login" ? "/signup" : "/login";
  const loginLabel = pathname === "/login" ? "Register" : "Login";
  const ctaTargetHref = pathname === "/login" ? "/signup" : "/login";

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

  // Same-page section links (#features/#pricing/#architecture-flows) are only
  // "active" when that section is the current fragment, so exactly one nav item
  // can be highlighted at a time rather than every section link on "/".
  useEffect(() => {
    const syncHash = () => setHash(window.location.hash);
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, [pathname]);

  const isActive = (href: string) => {
    if (href.startsWith("#")) return pathname === "/" && hash === href;
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  const navLinkClass = (href: string, extra = "") =>
    `transition-all duration-200 ${isActive(href) ? NAV_ACTIVE : NAV_IDLE} ${extra}`.trim();

  const drawerLinkClass = (href: string) =>
    `px-3 py-2 rounded-lg transition-all duration-200 ${
      isActive(href) ? "bg-white/10 text-white" : "hover:bg-white/5 hover:text-white"
    }`;

  const navCurrent = (href: string) => (isActive(href) ? ("page" as const) : undefined);

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
          {/* Logotype: serif "Invoice" + "AI" as a cyan-bordered mono tag (Gap 163) */}
          <span className="flex items-baseline gap-1.5">
            <span
              className="text-2xl font-semibold tracking-tight text-white group-hover:drop-shadow-[0_0_12px_rgba(59,130,246,0.6)] transition-all duration-300"
              style={{ fontFamily: 'ui-serif, Georgia, Cambria, "Times New Roman", Times, serif' }}
            >
              Invoice
            </span>
            <span className="font-mono text-[11px] font-bold leading-none tracking-[0.14em] text-[#22D3EE] border border-[#22D3EE]/40 bg-[#22D3EE]/10 rounded px-1.5 py-[3px] group-hover:border-[#22D3EE] group-hover:shadow-[0_0_12px_rgba(34,211,238,0.45)] transition-all duration-300">
              AI
            </span>
          </span>
        </Link>

        {/* Desktop Navigation Links */}
        <nav className="hidden md:flex items-center gap-8 text-[15px] font-semibold text-[#94A3B8]">
          <a
            href={pathname === "/" ? "#architecture-flows" : "/#architecture-flows"}
            onClick={(e) => {
              if (pathname === "/" && onOpenFlowsModal) {
                e.preventDefault();
                onOpenFlowsModal();
              }
            }}
            aria-current={navCurrent("#architecture-flows")}
            className={navLinkClass("#architecture-flows", "flex items-center gap-1.5 cursor-pointer")}
          >
            <span>Architecture Flow</span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-[#22D3EE]/15 border border-[#22D3EE]/30 text-[#22D3EE]">Live</span>
          </a>
          <Link
            href={pathname === "/" ? "#features" : "/#features"}
            onClick={() => {
              if (pathname === "/") setHash("#features");
            }}
            aria-current={navCurrent("#features")}
            className={navLinkClass("#features")}
          >
            Features
          </Link>
          <Link
            href={pathname === "/" ? "#pricing" : "/#pricing"}
            onClick={() => {
              if (pathname === "/") setHash("#pricing");
            }}
            aria-current={navCurrent("#pricing")}
            className={navLinkClass("#pricing")}
          >
            Pricing
          </Link>
          <Link
            href="/contact"
            aria-current={navCurrent("/contact")}
            className={navLinkClass("/contact")}
          >
            Contact Us
          </Link>
          {/* Founder ask, 2026-08-30: the guided "build your own pipeline"
              flow (WorkflowRecipeSelector, id="choose-your-workflow") already
              existed but was only reachable by scrolling past everything
              else. Same active-state/hash pattern as Features/Pricing. */}
          <Link
            href={pathname === "/" ? "#choose-your-workflow" : "/#choose-your-workflow"}
            onClick={() => {
              if (pathname === "/") setHash("#choose-your-workflow");
            }}
            aria-current={navCurrent("#choose-your-workflow")}
            className={navLinkClass("#choose-your-workflow")}
          >
            Build Your Pipeline
          </Link>
          <Link href={loginTargetHref} aria-current={navCurrent(loginTargetHref)} className={navLinkClass(loginTargetHref)}>
            {loginLabel}
          </Link>
        </nav>

        {/* Action Button */}
        <div className="hidden md:flex items-center gap-4">
          <Link href={ctaTargetHref} className="btn-primary-gradient flex items-center gap-2 text-sm">
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
              href={pathname === "/" ? "#features" : "/#features"}
              onClick={() => {
                if (pathname === "/") setHash("#features");
                setMobileMenuOpen(false);
              }}
              aria-current={navCurrent("#features")}
              className={drawerLinkClass("#features")}
            >
              Features
            </Link>
            <Link
              href={pathname === "/" ? "#pricing" : "/#pricing"}
              onClick={() => {
                if (pathname === "/") setHash("#pricing");
                setMobileMenuOpen(false);
              }}
              aria-current={navCurrent("#pricing")}
              className={drawerLinkClass("#pricing")}
            >
              Pricing
            </Link>
            <Link
              href="/contact"
              onClick={() => setMobileMenuOpen(false)}
              aria-current={navCurrent("/contact")}
              className={drawerLinkClass("/contact")}
            >
              Contact Us
            </Link>
            <Link
              href={pathname === "/" ? "#choose-your-workflow" : "/#choose-your-workflow"}
              onClick={() => {
                if (pathname === "/") setHash("#choose-your-workflow");
                setMobileMenuOpen(false);
              }}
              aria-current={navCurrent("#choose-your-workflow")}
              className={drawerLinkClass("#choose-your-workflow")}
            >
              Build Your Pipeline
            </Link>
            <Link
              href={loginTargetHref}
              onClick={() => setMobileMenuOpen(false)}
              aria-current={navCurrent(loginTargetHref)}
              className={drawerLinkClass(loginTargetHref)}
            >
              {loginLabel}
            </Link>
          </nav>
          <div className="pt-2 border-t border-[rgba(255,255,255,0.08)]">
            <Link
              href={ctaTargetHref}
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
