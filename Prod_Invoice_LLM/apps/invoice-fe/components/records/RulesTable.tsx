"use client";

// =============================================================================
// FILE: components/records/RulesTable.tsx
// FEATURE: FE Feature 22 Task 22.8 — Records › Rules: the extraction rules the
//          tenant has taught, grouped by scope (Global, then each vendor).
//
// EXTRACTION RULES ONLY. Chat rules live on one page — /settings/chat-rules
// (FE Gap 478) — and this tab links there exactly once instead of keeping a
// second list with a second delete. It makes no `GET /chat/rules` call.
//
// DATA — built from existing endpoints only; there is no "list all templates"
// route (plan open item #21):
//   GET /trainer/vendors                                   -> vendor names
//   GET /trainer/templates/history?scope=global            -> Global versions
//   GET /trainer/templates/history?scope=vendor&vendor_name -> per vendor
// A group shows its CURRENT version's rules. A template with no rules — or a
// vendor with no template — is absent. Limitation: `/trainer/vendors` only knows
// vendors with an inbound invoice, so a template for any other vendor is not
// listed until the backend offers a template list.
//
// "History" opens the Trainer's own RuleHistoryDrawer (BE Gap 514) with that
// group's versions; its rollback is the Trainer's existing call.
// =============================================================================

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { BookOpen, History, Loader2, MessageSquareQuote } from "lucide-react";
import RuleHistoryDrawer from "@/components/trainer/RuleHistoryDrawer";
import { trainerService, type RuleVersion } from "@/lib/trainer-service";

export interface RuleGroup {
  key: string;
  title: string;
  scope: "global" | "existing_vendor";
  vendorName?: string;
  current: RuleVersion;
  history: RuleVersion[];
}

/** One group per template that currently holds rules; Global first, vendors in the order given. */
export function ruleGroupsFrom(
  globalHistory: RuleVersion[],
  vendorHistories: { vendorName: string; history: RuleVersion[] }[]
): RuleGroup[] {
  const groups: RuleGroup[] = [];
  const currentOf = (history: RuleVersion[]) => history.find((v) => v.isCurrent) ?? null;

  const globalCurrent = currentOf(globalHistory);
  if (globalCurrent && globalCurrent.rules.length > 0) {
    groups.push({ key: "global", title: "Global", scope: "global", current: globalCurrent, history: globalHistory });
  }
  for (const { vendorName, history } of vendorHistories) {
    const current = currentOf(history);
    if (current && current.rules.length > 0) {
      groups.push({
        key: `vendor-${vendorName}`,
        title: vendorName,
        scope: "existing_vendor",
        vendorName,
        current,
        history,
      });
    }
  }
  return groups;
}

async function loadRuleGroups(): Promise<RuleGroup[]> {
  const [vendors, globalHistory] = await Promise.all([
    trainerService.getTenantVendors(),
    trainerService.getRuleHistory("global"),
  ]);
  const vendorHistories = await Promise.all(
    vendors.map(async (vendor) => ({
      vendorName: vendor.name,
      history: await trainerService.getRuleHistory("existing_vendor", vendor.name),
    }))
  );
  return ruleGroupsFrom(globalHistory, vendorHistories);
}

export default function RulesTable() {
  const [groups, setGroups] = useState<RuleGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openGroup, setOpenGroup] = useState<RuleGroup | null>(null);
  const [rollingBack, setRollingBack] = useState(false);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const next = await loadRuleGroups();
      setGroups(next);
      return next;
    } catch {
      setError("Could not load extraction rules. Try again.");
      setGroups((previous) => previous ?? []);
      return null;
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const rollback = async (version: RuleVersion) => {
    if (!openGroup || !version.templateId) return;
    setRollingBack(true);
    try {
      await trainerService.rollbackTemplate(version.templateId, version.version);
      const next = await reload();
      const refreshed = next?.find((g) => g.key === openGroup.key) ?? null;
      setOpenGroup(refreshed);
    } catch {
      setError("Rollback failed. The current rules are unchanged.");
    } finally {
      setRollingBack(false);
    }
  };

  return (
    <div data-testid="records-rules" className="flex flex-col gap-4">
      <Link
        href="/settings/chat-rules"
        data-testid="records-rules-chat-link"
        className="flex items-center gap-2 rounded-lg border border-[#1E293B] bg-[#0F172A]/60 px-4 py-3 text-xs text-slate-300 transition-colors hover:border-slate-500 hover:text-white"
      >
        <MessageSquareQuote className="h-4 w-4 text-sky-400" aria-hidden="true" />
        Chat answering rules are managed in Settings › Chat Rules →
      </Link>

      {error && (
        <p role="alert" className="text-xs text-rose-300">
          {error}
        </p>
      )}

      {groups === null ? (
        <div className="flex justify-center py-12 text-slate-400">
          <Loader2 className="h-5 w-5 animate-spin" aria-label="Loading rules" />
        </div>
      ) : groups.length === 0 ? (
        !error && (
          <div className="flex flex-col items-center gap-2 rounded-xl border border-[#222D3D] px-6 py-14 text-center">
            <BookOpen className="h-6 w-6 text-slate-500" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-white">No extraction rules yet</h3>
            <p className="max-w-md text-xs text-slate-400">
              Rules taught in the AI Trainer — for all invoices or for one vendor — will be listed here.
            </p>
          </div>
        )
      ) : (
        groups.map((group) => (
          <section
            key={group.key}
            data-testid="records-rule-group"
            aria-labelledby={`${group.key}-title`}
            className="overflow-hidden rounded-xl border border-[#1E293B] bg-[#0F172A]/60"
          >
            <header className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1E293B] px-5 py-3">
              <div className="min-w-0">
                <h3 id={`${group.key}-title`} className="text-sm font-semibold text-white">
                  {group.title}
                </h3>
                <p className="text-[11px] text-slate-500">
                  Version {group.current.version}
                  {group.current.changedBy ? ` · ${group.current.changedBy}` : ""}
                  {group.current.changedAt ? ` · ${group.current.changedAt}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpenGroup(group)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#222D3D] px-2.5 py-1 text-xs text-slate-300 transition-colors hover:border-slate-500 hover:text-white"
              >
                <History className="h-3.5 w-3.5" aria-hidden="true" />
                History
              </button>
            </header>
            <ul className="divide-y divide-[#1E293B]">
              {group.current.rules.map((rule, index) => (
                <li key={`${group.key}-${index}`} className="px-5 py-2.5 text-xs text-slate-200">
                  {rule}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}

      <RuleHistoryDrawer
        isOpen={openGroup !== null}
        onClose={() => setOpenGroup(null)}
        history={openGroup?.history ?? []}
        scope={openGroup?.scope ?? "global"}
        vendorName={openGroup?.vendorName}
        onRollback={rollback}
        isLoading={rollingBack}
      />
    </div>
  );
}
