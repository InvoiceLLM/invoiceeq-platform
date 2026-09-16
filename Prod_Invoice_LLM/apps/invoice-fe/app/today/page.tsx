"use client";

// =============================================================================
// FILE: app/today/page.tsx
// FEATURE: FE Feature 22 Task 22.4 — Today: "what needs me".
//
// GET /today (via hooks/useToday.ts, polled until the backend emits a live
// event) -> pre-onboarding progress, the empty state, or the sections. Role and
// clearance are resolved server-side; this page filters nothing.
// =============================================================================

import React from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import EmptyToday, { PreOnboardingToday } from "@/components/today/EmptyToday";
import QuestionnaireCard from "@/components/today/QuestionnaireCard";
import RunNowButton from "@/components/today/RunNowButton";
import UploadButton from "@/components/today/UploadButton";
import TodayList from "@/components/today/TodayList";
import { usePageHeader } from "@/components/layout/PageHeaderContext";
import { useAuth } from "@/hooks/useAuth";
import { useToday } from "@/hooks/useToday";
import { isPreOnboarding, todaySections } from "@/lib/today";

export default function TodayPage() {
  usePageHeader({ title: "Today", subtitle: "What needs you" });

  const { loading: authLoading, role } = useAuth();
  const { data, loading, error, refresh } = useToday(!authLoading);

  let body: React.ReactNode = null;
  if (!data) {
    if (loading) {
      body = (
        <div data-testid="today-loading" className="flex justify-center py-16 text-slate-400">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      );
    }
  } else if (isPreOnboarding(data)) {
    body = <PreOnboardingToday docsSeen={data.docs_seen} docsRequired={data.docs_required} onUploaded={refresh} />;
  } else {
    const sections = todaySections(data);
    const list = sections.length > 0 ? <TodayList sections={sections} /> : <EmptyToday />;
    // 22.22: the routine questionnaire, for the workspace owner. Shown on Today once
    // documents are in (the Ingest path); the Setup path starts from FirstRun (22.14).
    body =
      data.next_question && role === "Admin" ? (
        <div className="flex flex-col gap-4">
          <QuestionnaireCard initialQuestion={data.next_question} path="ingest" onComplete={refresh} />
          {list}
        </div>
      ) : (
        list
      );
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      {/* 22.24 Upload (needs can_load) and 22.23 Run now (Admin only); each renders nothing
          for a role it is not for. Not shown before onboarding, which has its own drop zone. */}
      {data && !isPreOnboarding(data) && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <UploadButton onUploaded={refresh} />
          <RunNowButton onQueued={refresh} />
        </div>
      )}
      {error && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-lg border border-rose-600/40 bg-rose-950/20 px-3 py-2 text-xs text-rose-200"
        >
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {data ? `Could not refresh Today (${error}). Showing the last loaded list.` : error}
        </div>
      )}
      {body}
    </div>
  );
}
