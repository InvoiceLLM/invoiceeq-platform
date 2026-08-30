"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  MonitorCheck,
  BarChart3,
  Users,
  Mail,
  FolderSync,
  Plug,
  Webhook,
  ArrowRight,
} from "lucide-react";

/**
 * Feature 7 / Gap 345 — two-mode hero switcher.
 *
 * Sits directly under Hero's eyebrow badge and above the interactive
 * pipeline demo. Two audiences, one hero, no new page: teams who want the
 * whole workspace, and teams who already run their own AP tooling and only
 * want the engine behind it.
 *
 * Marketing surface only. Both panels are static fixtures -- no network
 * calls, nothing here reaches invoice-be (see feature_7 spec section 7).
 * Extracted rather than inlined because Hero.tsx is already 627 lines with
 * 9 useState hooks and this owns exactly one piece of state of its own.
 *
 * Colour tokens are taken from Hero.tsx so this reads as part of the same
 * surface: #050816 console, #3B82F6/#22D3EE/#8B5CF6/#10B981 accents,
 * rgba(255,255,255,0.08) borders, backdrop-blur-md glass.
 */

type HeroMode = "app" | "plug";

interface ModeCapability {
  title: string;
  blurb: string;
  icon: React.ElementType;
  accent: string;
  iconBg: string;
  /** When set, the tile becomes a menu item -- clicking it starts that
   * setup path instead of only describing it. `intent` is carried as a
   * query param into /signup so the real wizard (FE Feature 17, not yet
   * built) can eventually deep-link straight to that step; until then it
   * lands on signup like every other conversion path in this hero. */
  href?: string;
}

/** "Complete Web Application" -- what the hosted workspace gives you. */
const WEB_APP_CAPABILITIES: ModeCapability[] = [
  {
    title: "SENTINEL Review Console",
    blurb: "Flagged invoices side by side with the source document, resolved in one screen.",
    icon: MonitorCheck,
    accent: "text-[#22D3EE]",
    iconBg: "bg-[#22D3EE]/10 border-[#22D3EE]/30",
  },
  {
    title: "Spend Analytics",
    blurb: "Vendor trends, monthly totals and KPI dashboards, exportable as CSV.",
    icon: BarChart3,
    accent: "text-[#3B82F6]",
    iconBg: "bg-[#3B82F6]/10 border-[#3B82F6]/30",
  },
  {
    title: "Team Roles",
    blurb: "Admin, Auditor and Trainer scopes, so each teammate sees only their own work.",
    icon: Users,
    accent: "text-[#8B5CF6]",
    iconBg: "bg-[#8B5CF6]/10 border-[#8B5CF6]/30",
  },
];

/** "Plug & Play Engine" -- the 4 primitives you can wire into your own stack.
 * Each links out to /signup?intent=... so this reads as a menu you can act
 * on, not just a description -- see the `href` note on ModeCapability. */
const PLUG_PLAY_PRIMITIVES: ModeCapability[] = [
  {
    title: "Email In",
    blurb: "Forward invoices to your own inbound address. No integration work at all.",
    icon: Mail,
    accent: "text-[#22D3EE]",
    iconBg: "bg-[#22D3EE]/10 border-[#22D3EE]/30",
    href: "/signup?intent=email",
  },
  {
    title: "Drive Sync",
    blurb: "Point us at a Google Drive folder and we pick up whatever lands in it.",
    icon: FolderSync,
    accent: "text-[#3B82F6]",
    iconBg: "bg-[#3B82F6]/10 border-[#3B82F6]/30",
    href: "/signup?intent=drive",
  },
  {
    title: "REST API",
    blurb: "Push a document, poll its status, approve it — all against your API key.",
    icon: Plug,
    accent: "text-[#8B5CF6]",
    iconBg: "bg-[#8B5CF6]/10 border-[#8B5CF6]/30",
    href: "/signup?intent=api",
  },
  {
    title: "Webhooks",
    blurb: "A signed JSON payload arrives at your endpoint the moment a document clears.",
    icon: Webhook,
    accent: "text-[#10B981]",
    iconBg: "bg-[#10B981]/10 border-[#10B981]/30",
    href: "/signup?intent=webhook",
  },
];

function CapabilityTile({ item }: { item: ModeCapability }) {
  const Icon = item.icon;
  const body = (
    <>
      <div className="flex items-start justify-between">
        <div className={`inline-flex p-2 rounded-lg border ${item.iconBg}`}>
          <Icon className={`w-4 h-4 ${item.accent}`} />
        </div>
        {item.href && (
          <ArrowRight className="w-3.5 h-3.5 text-[#64748B] opacity-0 -translate-x-1 transition-all duration-200 group-hover:opacity-100 group-hover:translate-x-0" />
        )}
      </div>
      <div className="mt-2.5 text-xs font-bold text-white">{item.title}</div>
      <p className="mt-1 text-[11px] leading-relaxed text-[#64748B]">{item.blurb}</p>
    </>
  );

  if (item.href) {
    return (
      <Link
        href={item.href}
        className="group p-3.5 rounded-xl border border-[rgba(255,255,255,0.08)] bg-white/[0.03] backdrop-blur-md text-left transition-all duration-300 hover:border-[#3B82F6]/40 hover:bg-white/[0.06] block"
      >
        {body}
      </Link>
    );
  }

  return (
    <div className="p-3.5 rounded-xl border border-[rgba(255,255,255,0.08)] bg-white/[0.03] backdrop-blur-md text-left transition-all duration-300 hover:border-white/20 hover:bg-white/[0.05]">
      {body}
    </div>
  );
}

export function HeroModeTabs() {
  const [mode, setMode] = useState<HeroMode>("app");

  const tabClass = (active: boolean) =>
    `text-xs sm:text-[13px] font-bold px-4 sm:px-5 py-2.5 rounded-[9px] transition-all duration-200 ${
      active
        ? "bg-gradient-to-br from-[#3B82F6]/25 to-[#8B5CF6]/25 text-white shadow-[inset_0_0_0_1px_rgba(59,130,246,0.4)]"
        : "text-[#94A3B8] hover:text-white"
    }`;

  return (
    <div className="mt-6">
      <div
        role="tablist"
        aria-label="Choose how you want to use Invoice AI"
        className="inline-flex gap-1 p-1 rounded-xl border border-[rgba(255,255,255,0.08)] bg-white/[0.03] backdrop-blur-md"
      >
        <button
          type="button"
          role="tab"
          id="hero-mode-tab-app"
          aria-selected={mode === "app"}
          aria-controls="hero-mode-panel-app"
          onClick={() => setMode("app")}
          className={tabClass(mode === "app")}
        >
          Complete Web Application
        </button>
        <button
          type="button"
          role="tab"
          id="hero-mode-tab-plug"
          aria-selected={mode === "plug"}
          aria-controls="hero-mode-panel-plug"
          onClick={() => setMode("plug")}
          className={tabClass(mode === "plug")}
        >
          Plug &amp; Play Engine
        </button>
      </div>

      {mode === "app" && (
        <div
          role="tabpanel"
          id="hero-mode-panel-app"
          aria-labelledby="hero-mode-tab-app"
          className="mt-5 grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-3xl mx-auto"
        >
          {WEB_APP_CAPABILITIES.map((item) => (
            <CapabilityTile key={item.title} item={item} />
          ))}
        </div>
      )}

      {mode === "plug" && (
        <div className="mt-5 max-w-3xl mx-auto">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[#64748B] text-left">
            Pick where to start
          </p>
          <div
            role="tabpanel"
            id="hero-mode-panel-plug"
            aria-labelledby="hero-mode-tab-plug"
            className="grid grid-cols-2 lg:grid-cols-4 gap-3"
          >
            {PLUG_PLAY_PRIMITIVES.map((item) => (
              <CapabilityTile key={item.title} item={item} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
