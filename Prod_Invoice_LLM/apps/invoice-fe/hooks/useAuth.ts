"use client";

import { useEffect, useState } from "react";

/**
 * Real identity for the app shell — FE Gap 99 / Feature 1.1 Task 1.1.4.
 *
 * This hook used to be a pure `localStorage` mock that defaulted everyone to
 * `role: "Admin"`, so every permission decision made from it was meaningless.
 * It now reads the backend's authoritative context from `GET /api/auth/me`,
 * which proxies to `GET /auth/me` -> `dependencies.py::get_tenant_context()`.
 * There is no `localStorage` read left in this file, deliberately: the client
 * must not be able to grant itself a role by editing browser storage.
 *
 * Permissions (`canTrain`/`canAudit`/`canLoad`) come from the `User` row, not
 * from the Clerk JWT, so an Admin's grant applies on the next request without
 * a re-login.
 *
 * Caching: `useAuth` is called from several components that can render on the
 * same page (Sidebar, Header-adjacent screens, page bodies). A module-level
 * cache plus a shared in-flight promise means one request per page load rather
 * than one per consumer, and every consumer re-renders when it resolves.
 *
 * Gap 138: the module cache used to live for the whole tab JS lifetime with
 * nothing calling `refreshAuth()`, so a server-side plan/role change was
 * invisible until a hard reload. We now (a) re-fetch on tab focus/visibility
 * (debounced), (b) export `clearAuth` for sign-out, and (c) expect call sites
 * that mutate identity (billing checkout, admin permission saves) to call
 * `refreshAuth()` themselves.
 */
export interface AuthContextType {
  tenantId: string;
  userId: string;
  role: string;
  canTrain: boolean;
  canAudit: boolean;
  canLoad: boolean;
  billingPlan: string;
  loading: boolean;
}

/** Backend TenantContext, snake_case as FastAPI serialises it. */
interface AuthMeResponse {
  tenant_id?: string;
  user_id?: string;
  role?: string;
  billing_plan?: string;
  can_train?: boolean;
  can_audit?: boolean;
  can_load?: boolean;
}

/**
 * What we assume when identity cannot be established (network error, 401, 402,
 * backend down). Least privilege: no role, no permissions. A failed identity
 * lookup must never open the Trainer/Auditor/Ingest surfaces — the backend
 * would 403 those calls anyway, and showing nav items that 403 on click is
 * worse UX than hiding them.
 */
const ANONYMOUS: AuthContextType = {
  tenantId: "",
  userId: "",
  role: "",
  canTrain: false,
  canAudit: false,
  canLoad: false,
  billingPlan: "",
  loading: false,
};

const LOADING: AuthContextType = { ...ANONYMOUS, loading: true };

/** Debounce window for focus/visibility re-fetch (Gap 138). */
const FOCUS_REFRESH_DEBOUNCE_MS = 2000;

let cached: AuthContextType | null = null;
let inFlight: Promise<AuthContextType> | null = null;
const subscribers = new Set<(auth: AuthContextType) => void>();
let focusListenersAttached = false;
let lastFocusRefreshAt = 0;
let focusRefreshTimer: ReturnType<typeof setTimeout> | null = null;

function normalise(data: AuthMeResponse): AuthContextType {
  return {
    tenantId: data.tenant_id ?? "",
    userId: data.user_id ?? "",
    role: data.role ?? "",
    canTrain: data.can_train === true,
    canAudit: data.can_audit === true,
    canLoad: data.can_load === true,
    billingPlan: data.billing_plan ?? "",
    loading: false,
  };
}

function publish(auth: AuthContextType) {
  cached = auth;
  subscribers.forEach((fn) => fn(auth));
}

function fetchAuth(): Promise<AuthContextType> {
  if (inFlight) return inFlight;

  inFlight = (async () => {
    try {
      const res = await fetch("/api/auth/me", { cache: "no-store" });
      if (!res.ok) return ANONYMOUS;
      return normalise((await res.json()) as AuthMeResponse);
    } catch {
      return ANONYMOUS;
    }
  })()
    .then((auth) => {
      publish(auth);
      return auth;
    })
    .finally(() => {
      inFlight = null;
    });

  return inFlight;
}

function scheduleFocusRefresh() {
  const now = Date.now();
  const since = now - lastFocusRefreshAt;
  const wait = Math.max(0, FOCUS_REFRESH_DEBOUNCE_MS - since);
  if (focusRefreshTimer) clearTimeout(focusRefreshTimer);
  focusRefreshTimer = setTimeout(() => {
    focusRefreshTimer = null;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      return;
    }
    lastFocusRefreshAt = Date.now();
    void refreshAuth();
  }, wait);
}

function onVisibilityOrFocus() {
  if (typeof document !== "undefined" && document.visibilityState === "hidden") {
    return;
  }
  scheduleFocusRefresh();
}

function attachFocusListeners() {
  if (focusListenersAttached || typeof window === "undefined") return;
  focusListenersAttached = true;
  window.addEventListener("focus", onVisibilityOrFocus);
  document.addEventListener("visibilitychange", onVisibilityOrFocus);
}

function detachFocusListeners() {
  if (!focusListenersAttached || typeof window === "undefined") return;
  focusListenersAttached = false;
  window.removeEventListener("focus", onVisibilityOrFocus);
  document.removeEventListener("visibilitychange", onVisibilityOrFocus);
  if (focusRefreshTimer) {
    clearTimeout(focusRefreshTimer);
    focusRefreshTimer = null;
  }
}

/**
 * Force a re-read of `/api/auth/me`, e.g. after an Admin changes permissions
 * in the Admin console, so the sidebar updates without a full reload.
 */
export async function refreshAuth(): Promise<AuthContextType> {
  cached = null;
  inFlight = null;
  return fetchAuth();
}

/**
 * Gap 138: drop the module cache on sign-out so the next session cannot
 * inherit the previous user's role/plan from a surviving JS runtime.
 */
export function clearAuth(): void {
  cached = null;
  inFlight = null;
  if (focusRefreshTimer) {
    clearTimeout(focusRefreshTimer);
    focusRefreshTimer = null;
  }
  publish(ANONYMOUS);
}

/**
 * Gap 138: when a gated API returns 402/403 that contradicts the cached plan
 * or permissions, re-fetch identity once so a stale cache is not trusted to
 * the end of a dead-end error screen.
 */
export async function refreshAuthOnAuthError(
  status: number
): Promise<AuthContextType | null> {
  if (status !== 402 && status !== 403) return null;
  return refreshAuth();
}

export function useAuth(): AuthContextType {
  const [auth, setAuth] = useState<AuthContextType>(() => cached ?? LOADING);

  useEffect(() => {
    subscribers.add(setAuth);
    if (subscribers.size === 1) attachFocusListeners();
    if (cached) {
      setAuth(cached);
    } else {
      void fetchAuth();
    }
    return () => {
      subscribers.delete(setAuth);
      if (subscribers.size === 0) detachFocusListeners();
    };
  }, []);

  return auth;
}
