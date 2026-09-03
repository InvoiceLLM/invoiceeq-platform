"use client";

/**
 * Gap 423: block a route the signed-in user has no permission for.
 *
 * Before this, permissions filtered nav *links* but nothing guarded the routes
 * — `middleware.ts` only calls `auth().protect()`, which asserts a session
 * exists and checks nothing else. Typing a URL reached any screen in the app.
 *
 * Deliberately generalises the pattern FE Gap 232 already established with
 * `TrainerPermissionPrompt` (a full-page "this route is not for you" state)
 * rather than inventing a second one. A dismissable overlay was rejected there
 * for the same reason it would be wrong here: it reveals a screen whose every
 * API call 403s.
 *
 * NOT A SECURITY BOUNDARY. The backend gates every write with
 * `require_can_*` / `require_admin` and 403s regardless of how the request
 * arrives. This exists so a user is told plainly instead of landing on a
 * screen that silently fails.
 */

import React from "react";
import { usePathname, useRouter } from "next/navigation";
import { ShieldAlert, Loader2 } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { canAccessRoute, ruleForPath } from "@/lib/routePermissions";

export function RouteGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "";
  const router = useRouter();
  const { role, canLoad, canAudit, canTrain, loading } = useAuth();

  // FE Gap 324's lesson, applied: "identity still loading" and "genuinely not
  // allowed" must never share a screen. Rendering the denial while the
  // /auth/me call is in flight would flash Access Restricted at users who are
  // perfectly entitled to be here — and `useAuth` resolves to a
  // least-privilege anonymous identity on failure, so every permission reads
  // false until it lands.
  if (loading) {
    return (
      <div className="flex h-full min-h-[60vh] items-center justify-center text-slate-400">
        <Loader2 size={22} className="animate-spin" />
      </div>
    );
  }

  if (canAccessRoute(pathname, { role, canLoad, canAudit, canTrain })) {
    return <>{children}</>;
  }

  const rule = ruleForPath(pathname);
  const area = rule?.label ?? "this area";

  return (
    <div
      id="route-access-restricted"
      className="flex h-full min-h-[60vh] flex-col items-center justify-center gap-4 p-6 text-center"
    >
      <div className="rounded-2xl border border-amber-600/40 bg-amber-950/20 p-4 text-amber-300">
        <ShieldAlert size={26} />
      </div>
      <div className="max-w-md space-y-1.5">
        <h2 className="text-lg font-bold text-white">Access restricted</h2>
        <p className="text-sm text-slate-400">
          Your account does not have permission to open {area}.
        </p>
        {/* Deep links are the whole reason this needs a real destination: someone
            follows an emailed link to a specific invoice and would otherwise hit
            a dead end with no way onward. */}
        <p className="text-xs text-slate-500">
          Ask an Admin in your workspace to grant it, then reload this page.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={() => router.push("/dashboard")}
          className="rounded-lg border border-[#222D3D] bg-[#1E293B] px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:bg-[#243044]"
        >
          Go to Dashboard
        </button>
        <button
          onClick={() => router.push("/help")}
          className="rounded-lg border border-[#222D3D] px-3 py-1.5 text-xs font-semibold text-slate-400 transition hover:text-white"
        >
          Help Center
        </button>
      </div>
    </div>
  );
}
