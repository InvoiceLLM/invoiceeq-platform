import React from "react";
import { CheckCircle2, Zap, ShieldCheck, Search, Lock } from "lucide-react";

interface Benefit {
  title: string;
  icon: React.ElementType;
  accent: string;
}

const BENEFITS: Benefit[] = [
  {
    title: "Less Manual Data Entry",
    icon: Zap,
    accent: "text-[#22D3EE]",
  },
  {
    title: "Earlier Error Detection",
    icon: ShieldCheck,
    accent: "text-[#10B981]",
  },
  {
    title: "Faster Invoice Search",
    icon: Search,
    accent: "text-[#8B5CF6]",
  },
  {
    title: "Secure Company Isolation",
    icon: Lock,
    accent: "text-[#3B82F6]",
  },
];

export function BenefitsStrip() {
  return (
    <section className="py-10 border-t border-b border-[rgba(255,255,255,0.08)] bg-[#050816]/90 relative z-10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 sm:gap-6">
          {BENEFITS.map((item) => {
            const Icon = item.icon;
            return (
              <div
                key={item.title}
                className="flex items-center justify-center gap-3 p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.07] hover:border-white/20 transition-all duration-300 group"
              >
                <div className="p-2 rounded-lg bg-white/5 border border-white/10 group-hover:scale-110 transition-transform">
                  <Icon className={`w-4 h-4 ${item.accent}`} />
                </div>
                <span className="text-xs sm:text-sm font-semibold text-[#CBD5E1] group-hover:text-white transition-colors">
                  {item.title}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
