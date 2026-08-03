"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useUser } from "@clerk/nextjs";

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
  created_at: string;
  last_login: string | null;
}

/** The three grantable permissions, in the order they render. */
const PERMISSIONS = [
  { key: "canTrain" as const, field: "can_train" as const, label: "Trainer" },
  { key: "canAudit" as const, field: "can_audit" as const, label: "Auditor" },
  { key: "canLoad" as const, field: "can_load" as const, label: "Loader" },
];

export type PermissionState = { canTrain: boolean; canAudit: boolean; canLoad: boolean };

/** PUT the 3 flags for a user. `userRef` is a backend UUID or a Clerk user ID. */
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
      if (perms.canTrain || perms.canAudit || perms.canLoad) {
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
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [permError, setPermError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);

  // Feature 1.1 Task 1.1.6: the user list used to be ephemeral client state
  // that vanished on reload, which left the edit-time permission checkboxes
  // with nothing real to edit. It now comes from the backend.
  // The signed-in Admin is filtered out -- they already render as their own
  // row below, and Admin implies all three permissions anyway.
  const loadUsers = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/users", { cache: "no-store" });
      if (!res.ok) return;
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
          }))
      );
    } catch {
      // Non-blocking: the org/stat cards above still render without the list.
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const handleTogglePermission = async (target: OrgUser, key: keyof PermissionState) => {
    const next: PermissionState = {
      canTrain: target.canTrain,
      canAudit: target.canAudit,
      canLoad: target.canLoad,
      [key]: !target[key],
    };
    // Optimistic: the checkbox flips immediately, and is rolled back if the
    // PUT fails, so a rejected grant can't look like it succeeded.
    setUsers((prev) => prev.map((u) => (u.id === target.id ? { ...u, ...next } : u)));
    setSavingId(target.id);
    setPermError(null);
    try {
      await savePermissions(target.id, next, { email: target.email });
    } catch (err: any) {
      setUsers((prev) => prev.map((u) => (u.id === target.id ? target : u)));
      setPermError(err.message || "Failed to save permissions");
    } finally {
      setSavingId(null);
    }
  };

  // Extract org metadata from Clerk user
  const orgName = (user?.unsafeMetadata?.orgName as string) || "Your Organisation";
  const orgType = (user?.unsafeMetadata?.orgType as string) || "—";
  const country = (user?.unsafeMetadata?.country as string) || "—";
  const adminEmail = user?.primaryEmailAddress?.emailAddress || "—";

  const handleUserCreated = (newUser: OrgUser) => {
    setUsers((prev) => [newUser, ...prev]);
  };

  const handleRemoveUser = (id: string) => {
    setUsers((prev) => prev.filter((u) => u.id !== id));
  };

  if (!isLoaded) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "200px", color: T.textDim }}>
        Loading…
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

        {/* Admin row (always shown) */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 2fr 1fr 1fr 1.6fr auto", padding: "14px 24px", borderBottom: `1px solid ${T.border}`, alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <div style={{ width: "32px", height: "32px", borderRadius: "8px", background: "rgba(59,130,246,0.15)", border: "1px solid rgba(59,130,246,0.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "14px" }}>
              {(user?.firstName || adminEmail).charAt(0).toUpperCase()}
            </div>
            <div>
              <div style={{ fontSize: "14px", fontWeight: "600", color: T.textPrimary }}>{user?.firstName ? `${user.firstName} ${user.lastName || ""}` : "You"}</div>
              <div style={{ fontSize: "12px", color: T.textDim }}>Organisation Owner</div>
            </div>
          </div>
          <div style={{ fontSize: "14px", color: T.textMuted }}>{adminEmail}</div>
          <div>
            <span style={{ background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)", borderRadius: "6px", padding: "3px 10px", fontSize: "12px", color: T.blue, fontWeight: "600" }}>Admin</span>
          </div>
          <div>
            <span style={{ background: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", borderRadius: "6px", padding: "3px 10px", fontSize: "12px", color: T.green, fontWeight: "600" }}>● Active</span>
          </div>
          {/* Admin is a role, not a 4th permission -- it implies all three
              (dependencies.resolve_permissions), so there is nothing to tick. */}
          <div style={{ fontSize: "12px", color: T.textDim }}>All (Admin)</div>
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
                <span style={{ background: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", borderRadius: "6px", padding: "3px 10px", fontSize: "12px", color: T.green, fontWeight: "600" }}>User</span>
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
                onClick={() => handleRemoveUser(u.id)}
                style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: "6px", padding: "4px 10px", fontSize: "12px", color: T.red, cursor: "pointer", fontFamily: "inherit" }}
              >
                Remove
              </button>
            </div>
          ))
        )}

        {permError && (
          <div style={{ padding: "10px 24px", background: "rgba(239,68,68,0.08)", borderTop: `1px solid ${T.border}`, fontSize: "13px", color: T.red }}>
            ⚠️ {permError}
          </div>
        )}
      </div>

      {/* Info banner */}
      <div style={{ background: "rgba(59,130,246,0.06)", border: "1px solid rgba(59,130,246,0.15)", borderRadius: "12px", padding: "14px 20px", display: "flex", gap: "12px", alignItems: "flex-start", fontSize: "13px", color: T.textMuted }}>
        <span style={{ fontSize: "18px", flexShrink: 0 }}>💡</span>
        <span>
          Users created here are synced to <strong style={{ color: T.textPrimary }}>Clerk</strong> and assigned the <strong style={{ color: T.green }}>user</strong> role.
          They can log in at <strong style={{ color: T.blue }}>localhost:3000/admin/login</strong> → select <em>User</em> → access the <strong style={{ color: T.textPrimary }}>User Dashboard</strong>.
        </span>
      </div>

      {showModal && <CreateUserModal onClose={() => setShowModal(false)} onCreated={handleUserCreated} />}
    </div>
  );
}
