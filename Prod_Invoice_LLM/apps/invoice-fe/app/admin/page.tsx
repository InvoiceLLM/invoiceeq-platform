"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useUser } from "@clerk/nextjs";
import { useAuth, refreshAuth } from "@/hooks/useAuth";

/**
 * FE Gap 169: new users log in through the marketing site's /login page, not a
 * `/admin/login` route — that route has never existed in this app (Gap 66).
 * Same env var, same localhost fallback as every other cross-app link here
 * (`components/layout/Header.tsx`, `app/trainer/page.tsx`).
 */
const WEBSITE_URL = process.env.NEXT_PUBLIC_WEBSITE_URL || "http://localhost:3000";

/* ─── Types ─── */
export interface OrgUser {
  id: string;
  /** Clerk user ID. Used as the permissions ref for a user who has not signed
   *  in yet and therefore has no backend `users` row to key off. */
  clerkUserId?: string;
  name: string;
  email: string;
  role: string;
  createdAt: string;
  status: "active" | "invited";
  /* Feature 1.1 Task 1.1.6 — granular permissions, default off. */
  canTrain: boolean;
  canAudit: boolean;
  canLoad: boolean;
  /** Gap 369: per-user Send Invoices visibility. */
  canSendInvoices: boolean;
}

/** Shape of a row from GET /api/admin/users (backend AdminUserOut). */
interface AdminUserDto {
  id: string;
  clerk_user_id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  role: string;
  can_train: boolean;
  can_audit: boolean;
  can_load: boolean;
  can_send_invoices: boolean;
  created_at: string;
  last_login: string | null;
}

/**
 * Shape of a row from GET /api/admin/dropped-emails (backend DroppedEmailOut).
 * BE Gap 124 item 6.
 */
interface DroppedEmailDto {
  id: string;
  reason: string;
  detail: string;
  from_email: string | null;
  to_email: string | null;
  filename: string | null;
  content_length: number | null;
  /** False when the row is shown only because the sender's domain matches. */
  attributed: boolean;
  created_at: string;
}

/**
 * Human wording for `DroppedInboundEmail.reason`, whose values are a fixed
 * vocabulary defined in `services/inbound_mail_security.py::DROP_REASONS`.
 * An unknown code falls back to the raw string rather than being hidden, so a
 * reason added backend-side still shows up here instead of rendering blank.
 */
const DROP_REASON_LABELS: Record<string, string> = {
  secret_unconfigured: "Mail authentication not configured",
  unverified_secret: "Failed authentication",
  oversized: "Too large (over 25 MB)",
  malformed: "Malformed request",
  unknown_sender: "Sender not registered",
  missing_tenant: "Workspace missing",
  no_pdf_attachment: "No PDF attached",
  quota_exhausted: "Free quota exhausted",
  ingest_rejected: "Refused by settings",
  ingest_failed: "Processing failed",
};

/** The four grantable permissions, in the order they render. */
const PERMISSIONS = [
  { key: "canTrain" as const, field: "can_train" as const, label: "Trainer" },
  { key: "canAudit" as const, field: "can_audit" as const, label: "Auditor" },
  { key: "canLoad" as const, field: "can_load" as const, label: "Loader" },
  // Gap 369: Admin-config-panel visibility control for Send Invoices.
  { key: "canSendInvoices" as const, field: "can_send_invoices" as const, label: "Send Invoices" },
];

export type PermissionState = {
  canTrain: boolean;
  canAudit: boolean;
  canLoad: boolean;
  canSendInvoices: boolean;
};

/** PUT the 4 flags for a user. `userRef` is a backend UUID or a Clerk user ID. */
async function savePermissions(
  userRef: string,
  perms: PermissionState,
  identity?: { email: string; firstName?: string; lastName?: string }
): Promise<void> {
  const res = await fetch(`/api/admin/users/${encodeURIComponent(userRef)}/permissions`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      can_train: perms.canTrain,
      can_audit: perms.canAudit,
      can_load: perms.canLoad,
      can_send_invoices: perms.canSendInvoices,
      ...(identity
        ? { email: identity.email, first_name: identity.firstName, last_name: identity.lastName }
        : {}),
    }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || data.error || "Failed to save permissions");
  }
}

/** Result of a real user removal — see DELETE /api/admin/users/[userRef]. */
interface RemoveUserResult {
  /** False when the backend row was detached but the Clerk account survived. */
  clerkDeleted: boolean;
  /** Present only when `clerkDeleted` is false: why sign-in access may remain. */
  warning?: string;
}

/**
 * FE Gap 168: really remove a user, rather than dropping them from local state.
 * The FE route deletes the Clerk account (the thing that actually grants
 * sign-in) after the backend has detached/deleted their tenant row, and the
 * backend's `require_admin` is the authorization boundary for both halves.
 */
async function removeUser(userRef: string): Promise<RemoveUserResult> {
  const res = await fetch(`/api/admin/users/${encodeURIComponent(userRef)}`, {
    method: "DELETE",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || "Failed to remove user");
  }
  return { clerkDeleted: data.clerkDeleted !== false, warning: data.warning };
}

interface StatCardProps {
  icon: string;
  label: string;
  value: string | number;
  color?: string;
  subtitle?: string;
}

interface CreateUserModalProps {
  onClose: () => void;
  onCreated: (user: OrgUser) => void;
}

/* ─── Inline styles matching project design system ─── */
const T = {
  bg: "#0B0F19",
  panel: "rgba(21, 27, 38, 0.75)",
  border: "#222D3D",
  textPrimary: "#E2E8F0",
  textMuted: "#94A3B8",
  textDim: "#64748B",
  green: "#10B981",
  blue: "#3B82F6",
  red: "#EF4444",
  yellow: "#F59E0B",
};

/* ─── Stat card ─── */
function StatCard({ icon, label, value, color = T.green, subtitle }: StatCardProps) {
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: "14px",
        padding: "20px 24px",
        backdropFilter: "blur(12px)",
        display: "flex",
        flexDirection: "column",
        gap: "6px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
        <span style={{ fontSize: "20px" }}>{icon}</span>
        <span style={{ fontSize: "12px", fontWeight: "600", letterSpacing: "0.8px", textTransform: "uppercase", color: T.textDim }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: "32px", fontWeight: "800", color, letterSpacing: "-1px" }}>{value}</div>
      {subtitle && <div style={{ fontSize: "12px", color: T.textDim }}>{subtitle}</div>}
    </div>
  );
}

/* ─── Create User Modal ─── */
function CreateUserModal({ onClose, onCreated }: CreateUserModalProps) {
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  // Feature 1.1: least privilege -- a new user starts with nothing beyond
  // Dashboard/Chat/Help. The Admin opts them into each area explicitly.
  const [perms, setPerms] = useState<PermissionState>({
    canTrain: false,
    canAudit: false,
    canLoad: false,
    canSendInvoices: false,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/admin/create-user", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ firstName, lastName, email, password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to create user");

      // Persist the ticked permissions against the brand-new Clerk user. The
      // backend pre-provisions a `users` row for them (they have none yet --
      // get_tenant_context only writes one on their first API call), so the
      // grant survives until they first sign in. Only attempted when at least
      // one box is ticked, so the default path stays a single request.
      if (perms.canTrain || perms.canAudit || perms.canLoad || perms.canSendInvoices) {
        await savePermissions(data.userId, perms, { email: data.email, firstName, lastName });
      }

      setSuccess(true);
      onCreated({
        id: data.userId,
        clerkUserId: data.userId,
        name: data.name,
        email: data.email,
        role: "user",
        createdAt: new Date().toLocaleDateString(),
        status: "active",
        ...perms,
      });
      setTimeout(onClose, 1500);
    } catch (err: any) {
      setError(err.message || "Failed to create user");
    } finally {
      setLoading(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    boxSizing: "border-box",
    background: "rgba(15,20,30,0.6)",
    border: `1px solid ${T.border}`,
    borderRadius: "10px",
    padding: "11px 14px",
    fontSize: "14px",
    color: T.textPrimary,
    outline: "none",
    fontFamily: "inherit",
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}>
      <div style={{ width: "100%", maxWidth: "440px", background: "#141926", border: `1px solid ${T.border}`, borderRadius: "20px", padding: "36px", boxShadow: "0 24px 64px rgba(0,0,0,0.5)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "24px" }}>
          <h3 style={{ fontSize: "18px", fontWeight: "700", color: T.textPrimary, margin: 0 }}>👤 Create New User</h3>
          <button onClick={onClose} style={{ background: "none", border: "none", color: T.textDim, cursor: "pointer", fontSize: "20px" }}>✕</button>
        </div>

        {success ? (
          <div style={{ textAlign: "center", padding: "24px 0" }}>
            <div style={{ fontSize: "48px", marginBottom: "12px" }}>✅</div>
            <div style={{ color: T.green, fontWeight: "700", fontSize: "16px" }}>User created successfully!</div>
            <div style={{ color: T.textDim, fontSize: "13px", marginTop: "6px" }}>They can now log in using their credentials.</div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
              <div>
                <div style={{ fontSize: "11px", fontWeight: "700", letterSpacing: "0.8px", textTransform: "uppercase", color: T.textDim, marginBottom: "6px" }}>First Name</div>
                <input style={inputStyle} type="text" placeholder="John" value={firstName} onChange={(e) => setFirstName(e.target.value)} required />
              </div>
              <div>
                <div style={{ fontSize: "11px", fontWeight: "700", letterSpacing: "0.8px", textTransform: "uppercase", color: T.textDim, marginBottom: "6px" }}>Last Name</div>
                <input style={inputStyle} type="text" placeholder="Doe" value={lastName} onChange={(e) => setLastName(e.target.value)} required />
              </div>
            </div>
            <div>
              <div style={{ fontSize: "11px", fontWeight: "700", letterSpacing: "0.8px", textTransform: "uppercase", color: T.textDim, marginBottom: "6px" }}>Work Email</div>
              <input style={inputStyle} type="email" placeholder="john@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div>
              <div style={{ fontSize: "11px", fontWeight: "700", letterSpacing: "0.8px", textTransform: "uppercase", color: T.textDim, marginBottom: "6px" }}>Temporary Password</div>
              <input style={inputStyle} type="password" placeholder="Min. 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
            </div>

            {/* Feature 1.1 Task 1.1.6 — permission checkboxes at create time */}
            <div>
              <div style={{ fontSize: "11px", fontWeight: "700", letterSpacing: "0.8px", textTransform: "uppercase", color: T.textDim, marginBottom: "6px" }}>Permissions</div>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", background: "rgba(15,20,30,0.6)", border: `1px solid ${T.border}`, borderRadius: "10px", padding: "12px 14px" }}>
                {PERMISSIONS.map(({ key, label }) => (
                  <label key={key} style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "13px", color: T.textMuted, cursor: "pointer" }}>
                    <input
                      id={`create-perm-${key}`}
                      type="checkbox"
                      checked={perms[key]}
                      onChange={(e) => setPerms((p) => ({ ...p, [key]: e.target.checked }))}
                      style={{ accentColor: T.green, width: "15px", height: "15px", cursor: "pointer" }}
                    />
                    {label}
                  </label>
                ))}
                <div style={{ fontSize: "11px", color: T.textDim, marginTop: "2px" }}>
                  Everyone gets Dashboard, Chat and Help. Leave all unticked for view-only access.
                </div>
              </div>
            </div>

            {error && (
              <div style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: "8px", padding: "10px 14px", fontSize: "13px", color: T.red }}>
                ⚠️ {error}
              </div>
            )}

            <div style={{ display: "flex", gap: "10px", marginTop: "8px" }}>
              <button type="button" onClick={onClose} style={{ flex: 1, background: "transparent", border: `1px solid ${T.border}`, borderRadius: "10px", padding: "11px", fontSize: "14px", color: T.textMuted, cursor: "pointer", fontFamily: "inherit" }}>
                Cancel
              </button>
              <button type="submit" disabled={loading} style={{ flex: 2, background: "linear-gradient(135deg, #10B981 0%, #059669 100%)", border: "none", borderRadius: "10px", padding: "11px", fontSize: "14px", fontWeight: "600", color: "#fff", cursor: "pointer", opacity: loading ? 0.7 : 1, fontFamily: "inherit" }}>
                {loading ? "⏳ Creating…" : "✓ Create User"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

/* ─── Main Admin Dashboard Page ─── */
export default function AdminDashboardPage() {
  const { user, isLoaded } = useUser();
  // FE Gap 167: the real, backend-resolved identity of whoever is looking at
  // this page. This screen used to describe the viewer as the org's Admin
  // unconditionally; every role/permission label below now comes from here.
  const { role, canTrain, canAudit, canLoad, canSendInvoices, tenantName, loading: authLoading, userId } = useAuth();
  const isAdmin = role === "Admin";

  const [users, setUsers] = useState<OrgUser[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [permError, setPermError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  // FE Gap 167: a 403 from GET /api/admin/users used to be swallowed, leaving a
  // non-Admin on a page that looked like an empty but legitimate console.
  const [accessDenied, setAccessDenied] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  // BE Gap 124 item 6: inbound mail that never became an invoice.
  const [droppedEmails, setDroppedEmails] = useState<DroppedEmailDto[]>([]);
  const [droppedError, setDroppedError] = useState<string | null>(null);
  const [droppedLoaded, setDroppedLoaded] = useState(false);

  // Feature 1.1 Task 1.1.6: the user list used to be ephemeral client state
  // that vanished on reload, which left the edit-time permission checkboxes
  // with nothing real to edit. It now comes from the backend.
  // The signed-in Admin is filtered out -- they already render as their own
  // row below, and Admin implies all three permissions anyway.
  const loadUsers = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/users", { cache: "no-store" });
      if (!res.ok) {
        // Gap 167: a 401/403 is not a "no users yet" state -- it means the
        // viewer is not this tenant's Admin and must be told so, not shown an
        // empty console. Anything else is a genuine load failure and gets a
        // visible error rather than a silently blank table.
        if (res.status === 401 || res.status === 403) {
          setAccessDenied(true);
        } else {
          setListError("Could not load the user list. Please try again.");
        }
        return;
      }
      setAccessDenied(false);
      setListError(null);
      const rows: AdminUserDto[] = await res.json();
      setUsers(
        rows
          .filter((r) => r.role !== "Admin")
          .map((r) => ({
            id: r.id,
            clerkUserId: r.clerk_user_id,
            name: [r.first_name, r.last_name].filter(Boolean).join(" ") || r.email,
            email: r.email,
            role: r.role,
            createdAt: new Date(r.created_at).toLocaleDateString(),
            status: r.last_login ? "active" : "invited",
            canTrain: r.can_train,
            canAudit: r.can_audit,
            canLoad: r.can_load,
            canSendInvoices: r.can_send_invoices,
          }))
      );
    } catch {
      setListError("Could not load the user list. Please try again.");
    }
  }, []);

  /**
   * BE Gap 124 item 6. Inbound mail the mailintegration webhook rejected or
   * skipped used to end at a `logger.warning` inside the container -- a vendor
   * could email an invoice, the webhook could refuse it for any of eight
   * reasons, and nobody with access to this console would ever find out. This
   * is the read side of the record that fixes that.
   *
   * A failure here is reported in its own panel and never touches
   * `setAccessDenied`/`setListError`: this is a secondary list, and it must not
   * be able to blank out the user table it renders below.
   */
  const loadDroppedEmails = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/dropped-emails", { cache: "no-store" });
      if (!res.ok) {
        setDroppedError("Could not load dropped inbound emails.");
        return;
      }
      setDroppedError(null);
      setDroppedEmails(await res.json());
    } catch {
      setDroppedError("Could not load dropped inbound emails.");
    } finally {
      setDroppedLoaded(true);
    }
  }, []);

  useEffect(() => {
    // Gap 167: don't fire an Admin-only call for a viewer we already know is
    // not an Admin -- the same shape `app/settings/webhooks/page.tsx` uses.
    if (authLoading || !isAdmin) return;
    void loadUsers();
    void loadDroppedEmails();
  }, [loadUsers, loadDroppedEmails, authLoading, isAdmin]);

  const handleTogglePermission = async (target: OrgUser, key: keyof PermissionState) => {
    const next: PermissionState = {
      canTrain: target.canTrain,
      canAudit: target.canAudit,
      canLoad: target.canLoad,
      canSendInvoices: target.canSendInvoices,
      [key]: !target[key],
    };
    // Optimistic: the checkbox flips immediately, and is rolled back if the
    // PUT fails, so a rejected grant can't look like it succeeded.
    setUsers((prev) => prev.map((u) => (u.id === target.id ? { ...u, ...next } : u)));
    setSavingId(target.id);
    setPermError(null);
    try {
      await savePermissions(target.id, next, { email: target.email });
      // Gap 138: if an Admin edited their own grants, refresh the shell cache.
      if (target.id === userId || (target.clerkUserId && target.clerkUserId === user?.id)) {
        void refreshAuth();
      }
    } catch (err: any) {
      setUsers((prev) => prev.map((u) => (u.id === target.id ? target : u)));
      setPermError(err.message || "Failed to save permissions");
    } finally {
      setSavingId(null);
    }
  };

  // BE Gap 133: the workspace name is the backend's resolved tenant, same fix as
  // Header.tsx -- Clerk's `unsafeMetadata.orgName` is written at sign-up and
  // never reconciled with the tenant the data actually lives in, so this console
  // could confidently name an organisation that owns none of the users listed
  // below it. Metadata is only the pre-resolution placeholder now.
  // (orgType/country below have no backend equivalent and stay on metadata.)
  const orgName =
    (authLoading
      ? (user?.unsafeMetadata?.orgName as string)
      : tenantName || (user?.unsafeMetadata?.orgName as string)) || "Your Organisation";
  const orgType = (user?.unsafeMetadata?.orgType as string) || "—";
  const country = (user?.unsafeMetadata?.country as string) || "—";
  const adminEmail = user?.primaryEmailAddress?.emailAddress || "—";

  // FE Gap 167: how the viewer's own row describes them. "Organisation Owner"
  // and "All (Admin)" used to be literals in the markup regardless of role.
  const selfSubtitle = isAdmin ? "Organisation Owner" : "Workspace member";
  const grantedAreas = [
    canTrain ? "Trainer" : null,
    canAudit ? "Auditor" : null,
    canLoad ? "Loader" : null,
    canSendInvoices ? "Send Invoices" : null,
  ].filter(Boolean) as string[];
  const selfPermissions = isAdmin
    ? "All (Admin)"
    : grantedAreas.length > 0
    ? grantedAreas.join(", ")
    : "View only";

  const handleUserCreated = (newUser: OrgUser) => {
    setUsers((prev) => [newUser, ...prev]);
  };

  /**
   * FE Gap 168: this used to be `setUsers(prev => prev.filter(...))` and
   * nothing else -- the row vanished, the user kept every bit of their access,
   * and the next page load brought them back. It now calls the real
   * DELETE /api/admin/users/{ref}, and only drops the row once that succeeds.
   */
  const handleRemoveUser = async (target: OrgUser) => {
    const confirmed = window.confirm(
      `Remove ${target.email}? Their sign-in account is deleted and they lose access to this workspace immediately.`
    );
    if (!confirmed) return;

    setRemovingId(target.id);
    setPermError(null);
    try {
      const { clerkDeleted, warning } = await removeUser(target.id);
      setUsers((prev) => prev.filter((u) => u.id !== target.id));
      if (!clerkDeleted) {
        // Partial success is stated plainly rather than shown as a clean
        // removal -- the whole point of this gap was false confidence.
        setPermError(
          warning ||
            "Removed from this workspace, but their sign-in account could not be deleted. Remove it in Clerk to fully revoke access."
        );
      }
    } catch (err: any) {
      setPermError(err.message || "Failed to remove user");
    } finally {
      setRemovingId(null);
    }
  };

  if (!isLoaded || authLoading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "200px", color: T.textDim }}>
        Loading…
      </div>
    );
  }

  /**
   * FE Gap 167: the route's own gate. The Settings tile is hidden from
   * non-Admins, but the URL is still typeable, and the backend's `require_admin`
   * (the actual boundary) 403s every call this page makes -- so say that,
   * instead of rendering an Admin console that describes the viewer as the
   * organisation's owner. `accessDenied` covers the case where the client-side
   * role says Admin but the backend disagrees.
   */
  if (!isAdmin || accessDenied) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "14px", padding: "64px 24px", textAlign: "center" }}>
        <div style={{ width: "56px", height: "56px", borderRadius: "16px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "26px" }}>
          🛡️
        </div>
        <h1 style={{ fontSize: "20px", fontWeight: "800", color: T.textPrimary, margin: 0 }}>Access Restricted</h1>
        <p style={{ fontSize: "13px", color: T.textDim, maxWidth: "420px", margin: 0 }}>
          Only organisation Administrators can manage users, roles and permissions.
          {role ? ` You are signed in as ${role}.` : ""}
        </p>
        <Link
          href="/settings"
          style={{ marginTop: "6px", background: "transparent", border: `1px solid ${T.border}`, borderRadius: "10px", padding: "10px 18px", fontSize: "13px", color: T.textMuted, textDecoration: "none" }}
        >
          Return to Settings
        </Link>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
      {/* Page header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: "24px", fontWeight: "800", color: T.textPrimary, letterSpacing: "-0.5px", marginBottom: "4px" }}>
            🛡️ Admin Console
          </h1>
          <p style={{ fontSize: "13px", color: T.textDim }}>
            Manage your organisation, users, and access control.
          </p>
        </div>
        <button
          id="btn-create-user"
          onClick={() => setShowModal(true)}
          style={{ background: "linear-gradient(135deg, #10B981 0%, #059669 100%)", border: "none", borderRadius: "10px", padding: "10px 20px", fontSize: "14px", fontWeight: "600", color: "#fff", cursor: "pointer", boxShadow: "0 4px 16px rgba(16,185,129,0.25)", display: "flex", alignItems: "center", gap: "6px" }}
        >
          + Add User
        </button>
      </div>

      {/* Org info card */}
      <div style={{ background: "linear-gradient(135deg, rgba(16,185,129,0.07) 0%, rgba(59,130,246,0.07) 100%)", border: `1px solid ${T.border}`, borderRadius: "14px", padding: "24px 28px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "14px", marginBottom: "16px" }}>
          <div style={{ width: "48px", height: "48px", borderRadius: "12px", background: "linear-gradient(135deg, #10B981 0%, #3B82F6 100%)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "22px", fontWeight: "700", color: "#fff" }}>
            {orgName.charAt(0).toUpperCase()}
          </div>
          <div>
            <div style={{ fontSize: "18px", fontWeight: "700", color: T.textPrimary }}>{orgName}</div>
            <div style={{ fontSize: "13px", color: T.textDim }}>{orgType} · {country}</div>
          </div>
          <div style={{ marginLeft: "auto", background: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", borderRadius: "20px", padding: "4px 12px", fontSize: "12px", color: T.green, fontWeight: "600" }}>
            ● Active
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "16px", borderTop: `1px solid ${T.border}`, paddingTop: "16px" }}>
          {[
            { label: "Admin", value: adminEmail },
            { label: "Plan", value: "Free Trial" },
            { label: "Joined", value: user?.createdAt ? new Date(user.createdAt).toLocaleDateString() : "Today" },
          ].map(({ label, value }) => (
            <div key={label}>
              <div style={{ fontSize: "11px", color: T.textDim, fontWeight: "600", letterSpacing: "0.6px", textTransform: "uppercase", marginBottom: "2px" }}>{label}</div>
              <div style={{ fontSize: "14px", color: T.textPrimary, fontWeight: "500" }}>{value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Stats row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "16px" }}>
        <StatCard icon="👥" label="Total Users" value={users.length + 1} subtitle="Including you (admin)" color={T.blue} />
        <StatCard icon="✅" label="Active Users" value={users.filter((u) => u.status === "active").length + 1} color={T.green} />
        <StatCard icon="📋" label="Pending Invites" value={users.filter((u) => u.status === "invited").length} color={T.yellow} />
      </div>

      {/* Users table */}
      <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: "14px", overflow: "hidden" }}>
        {/* Table header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 24px", borderBottom: `1px solid ${T.border}` }}>
          <div>
            <div style={{ fontSize: "15px", fontWeight: "700", color: T.textPrimary }}>Users</div>
            <div style={{ fontSize: "12px", color: T.textDim, marginTop: "2px" }}>Users created here sync to Clerk and can log in to the dashboard</div>
          </div>
        </div>

        {/* Column headers */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 2fr 1fr 1fr 1.6fr auto", padding: "10px 24px", borderBottom: `1px solid ${T.border}`, fontSize: "11px", fontWeight: "700", letterSpacing: "0.8px", textTransform: "uppercase", color: T.textDim }}>
          <span>Name</span>
          <span>Email</span>
          <span>Role</span>
          <span>Status</span>
          <span>Permissions</span>
          <span>Action</span>
        </div>

        {/* The signed-in viewer's own row.
            FE Gap 167: every label here was hardcoded ("Organisation Owner",
            "Admin", "All (Admin)") and was shown to whoever loaded the page,
            so a permission-less user who reached /admin was told they were the
            org's Admin.
            The role badge, the subtitle and the permissions cell now all come
            from GET /auth/me. Only an Admin gets this far now, but the values
            are read rather than asserted so this row can never drift from the
            backend's answer again. */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 2fr 1fr 1fr 1.6fr auto", padding: "14px 24px", borderBottom: `1px solid ${T.border}`, alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <div style={{ width: "32px", height: "32px", borderRadius: "8px", background: "rgba(59,130,246,0.15)", border: "1px solid rgba(59,130,246,0.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "14px" }}>
              {(user?.firstName || adminEmail).charAt(0).toUpperCase()}
            </div>
            <div>
              <div style={{ fontSize: "14px", fontWeight: "600", color: T.textPrimary }}>{user?.firstName ? `${user.firstName} ${user.lastName || ""}` : "You"}</div>
              <div style={{ fontSize: "12px", color: T.textDim }}>{selfSubtitle}</div>
            </div>
          </div>
          <div style={{ fontSize: "14px", color: T.textMuted }}>{adminEmail}</div>
          <div>
            <span style={{ background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)", borderRadius: "6px", padding: "3px 10px", fontSize: "12px", color: T.blue, fontWeight: "600" }}>{role || "Unknown"}</span>
          </div>
          <div>
            <span style={{ background: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", borderRadius: "6px", padding: "3px 10px", fontSize: "12px", color: T.green, fontWeight: "600" }}>● Active</span>
          </div>
          {/* Admin is a role, not a 4th permission -- it implies all three
              (dependencies.resolve_permissions), so there is nothing to tick. */}
          <div style={{ fontSize: "12px", color: T.textDim }}>{selfPermissions}</div>
          <div style={{ fontSize: "12px", color: T.textDim }}>—</div>
        </div>

        {/* Created users */}
        {users.length === 0 ? (
          <div style={{ padding: "40px 24px", textAlign: "center", color: T.textDim, fontSize: "14px" }}>
            <div style={{ fontSize: "32px", marginBottom: "10px" }}>👥</div>
            No users yet. Click <strong style={{ color: T.green }}>+ Add User</strong> to invite someone.
          </div>
        ) : (
          users.map((u) => (
            <div key={u.id} style={{ display: "grid", gridTemplateColumns: "2fr 2fr 1fr 1fr 1.6fr auto", padding: "14px 24px", borderBottom: `1px solid ${T.border}`, alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <div style={{ width: "32px", height: "32px", borderRadius: "8px", background: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "14px" }}>
                  {u.name.charAt(0).toUpperCase()}
                </div>
                <div style={{ fontSize: "14px", fontWeight: "600", color: T.textPrimary }}>{u.name}</div>
              </div>
              <div style={{ fontSize: "14px", color: T.textMuted }}>{u.email}</div>
              <div>
                {/* Gap 167: the stored role, not a literal "User" -- this cell
                    claimed "User" even for a row the backend returned as, say,
                    Auditor. */}
                <span style={{ background: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", borderRadius: "6px", padding: "3px 10px", fontSize: "12px", color: T.green, fontWeight: "600" }}>{u.role || "User"}</span>
              </div>
              <div>
                <span style={{ background: u.status === "active" ? "rgba(16,185,129,0.1)" : "rgba(245,158,11,0.1)", border: `1px solid ${u.status === "active" ? "rgba(16,185,129,0.2)" : "rgba(245,158,11,0.2)"}`, borderRadius: "6px", padding: "3px 10px", fontSize: "12px", color: u.status === "active" ? T.green : T.yellow, fontWeight: "600" }}>
                  {u.status === "active" ? "● Active" : "⏳ Invited"}
                </span>
              </div>
              {/* Feature 1.1 Task 1.1.6 — edit-time permission checkboxes.
                  Each toggle PUTs immediately; the backend reads the flags off
                  this row on the user's next request, so no re-login. */}
              <div style={{ display: "flex", gap: "12px", alignItems: "center", opacity: savingId === u.id ? 0.5 : 1 }}>
                {PERMISSIONS.map(({ key, label }) => (
                  <label key={key} title={label} style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "12px", color: T.textDim, cursor: "pointer" }}>
                    <input
                      id={`perm-${key}-${u.id}`}
                      aria-label={`${label} permission for ${u.email}`}
                      type="checkbox"
                      checked={u[key]}
                      disabled={savingId === u.id}
                      onChange={() => handleTogglePermission(u, key)}
                      style={{ accentColor: T.green, width: "14px", height: "14px", cursor: "pointer" }}
                    />
                    {label}
                  </label>
                ))}
              </div>
              <button
                onClick={() => void handleRemoveUser(u)}
                disabled={removingId === u.id}
                aria-label={`Remove ${u.email}`}
                style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: "6px", padding: "4px 10px", fontSize: "12px", color: T.red, cursor: removingId === u.id ? "wait" : "pointer", opacity: removingId === u.id ? 0.5 : 1, fontFamily: "inherit" }}
              >
                {removingId === u.id ? "Removing…" : "Remove"}
              </button>
            </div>
          ))
        )}

        {(permError || listError) && (
          <div style={{ padding: "10px 24px", background: "rgba(239,68,68,0.08)", borderTop: `1px solid ${T.border}`, fontSize: "13px", color: T.red }}>
            ⚠️ {permError || listError}
          </div>
        )}
      </div>

      {/* Dropped inbound emails — BE Gap 124 item 6.
          Same panel/table shape as the Users table above. Deliberately placed
          in the Admin console rather than under Settings → Email Setup: the
          rows that matter most are the ones nobody's email settings explain
          (failed authentication, oversized payloads), and the Admin is the
          only role that can act on them. */}
      <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: "14px", overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 24px", borderBottom: `1px solid ${T.border}` }}>
          <div>
            <div style={{ fontSize: "15px", fontWeight: "700", color: T.textPrimary }}>📥 Dropped inbound emails</div>
            <div style={{ fontSize: "12px", color: T.textDim, marginTop: "2px" }}>
              Mail sent to your workspace mailbox that did not become an invoice, and why.
            </div>
          </div>
          <button
            id="btn-refresh-dropped-emails"
            onClick={() => void loadDroppedEmails()}
            style={{ background: "transparent", border: `1px solid ${T.border}`, borderRadius: "8px", padding: "6px 14px", fontSize: "12px", color: T.textMuted, cursor: "pointer", fontFamily: "inherit" }}
          >
            ↻ Refresh
          </button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 2fr 2.6fr 1.2fr", padding: "10px 24px", borderBottom: `1px solid ${T.border}`, fontSize: "11px", fontWeight: "700", letterSpacing: "0.8px", textTransform: "uppercase", color: T.textDim }}>
          <span>Reason</span>
          <span>From</span>
          <span>Detail</span>
          <span>When</span>
        </div>

        {droppedEmails.length === 0 ? (
          <div style={{ padding: "32px 24px", textAlign: "center", color: T.textDim, fontSize: "14px" }}>
            <div style={{ fontSize: "28px", marginBottom: "8px" }}>✅</div>
            {droppedLoaded ? "No inbound email has been dropped." : "Loading…"}
          </div>
        ) : (
          droppedEmails.map((d) => (
            <div key={d.id} style={{ display: "grid", gridTemplateColumns: "1.4fr 2fr 2.6fr 1.2fr", padding: "12px 24px", borderBottom: `1px solid ${T.border}`, alignItems: "center", gap: "8px" }}>
              <div>
                <span style={{ background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.2)", borderRadius: "6px", padding: "3px 8px", fontSize: "11px", color: T.yellow, fontWeight: "600" }}>
                  {DROP_REASON_LABELS[d.reason] || d.reason}
                </span>
              </div>
              <div style={{ fontSize: "13px", color: T.textMuted, overflowWrap: "anywhere" }}>
                {d.from_email || "—"}
                {/* An unattributed row is shown because the sender's DOMAIN
                    matches this workspace, not because the address is
                    registered to it. Saying so keeps the Admin from reading a
                    domain match as proof the mail was meant for them. */}
                {!d.attributed && (
                  <span style={{ marginLeft: "6px", fontSize: "11px", color: T.textDim }} title="Sender is not in this workspace's authorized email set; matched on domain only.">
                    (unregistered)
                  </span>
                )}
              </div>
              <div style={{ fontSize: "12px", color: T.textDim, overflowWrap: "anywhere" }}>
                {d.filename ? `${d.filename} — ` : ""}
                {d.detail}
              </div>
              <div style={{ fontSize: "12px", color: T.textDim }}>
                {new Date(d.created_at).toLocaleString()}
              </div>
            </div>
          ))
        )}

        {droppedError && (
          <div style={{ padding: "10px 24px", background: "rgba(239,68,68,0.08)", borderTop: `1px solid ${T.border}`, fontSize: "13px", color: T.red }}>
            ⚠️ {droppedError}
          </div>
        )}
      </div>

      {/* Info banner */}
      <div style={{ background: "rgba(59,130,246,0.06)", border: "1px solid rgba(59,130,246,0.15)", borderRadius: "12px", padding: "14px 20px", display: "flex", gap: "12px", alignItems: "flex-start", fontSize: "13px", color: T.textMuted }}>
        <span style={{ fontSize: "18px", flexShrink: 0 }}>💡</span>
        {/* FE Gap 169: this used to point new users at
            `localhost:3000/admin/login`, a route that has never existed in this
            app (Gap 66) -- and a hardcoded localhost host, so it was wrong in
            every deployed environment too. Sign-in happens on the marketing
            site's /login page, which then lands them on this dashboard. */}
        <span>
          Users created here are synced to <strong style={{ color: T.textPrimary }}>Clerk</strong> and assigned the <strong style={{ color: T.green }}>user</strong> role.
          They sign in at{" "}
          <a
            href={`${WEBSITE_URL}/login`}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: T.blue, fontWeight: "700", textDecoration: "underline" }}
          >
            {`${WEBSITE_URL}/login`}
          </a>{" "}
          with the email and temporary password set above, and land straight on the <strong style={{ color: T.textPrimary }}>Dashboard</strong> with whatever permissions you grant here.
        </span>
      </div>

      {showModal && <CreateUserModal onClose={() => setShowModal(false)} onCreated={handleUserCreated} />}
    </div>
  );
}
