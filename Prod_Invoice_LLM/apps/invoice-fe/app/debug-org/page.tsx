"use client";

import { useUser, useOrganization } from "@clerk/nextjs";

export default function DebugOrgPage() {
  const { user } = useUser();
  // Clerk v5 replaced the v4 `membershipList` option with the paginated
  // `memberships` resource; the old name no longer exists on the return type
  // and was failing `next build` type-check, which blocked the Docker image
  // build in CI.
  const { organization, memberships } = useOrganization({
    memberships: true,
  });
  const membershipList = memberships?.data;

  return (
    <div style={{ padding: "40px", fontFamily: "monospace", background: "#0B0F19", color: "#E2E8F0", minHeight: "100vh" }}>
      <h1 style={{ marginBottom: "30px" }}>🔍 Organization Debug Page</h1>

      <div style={{ background: "#1a1f2e", border: "1px solid #222d3d", borderRadius: "12px", padding: "20px", marginBottom: "20px" }}>
        <h2 style={{ marginBottom: "15px" }}>👤 Current User</h2>
        <pre style={{ background: "#0f141e", padding: "15px", borderRadius: "8px", overflow: "auto" }}>
          {JSON.stringify({
            userId: user?.id,
            email: user?.primaryEmailAddress?.emailAddress,
            unsafeMetadata: user?.unsafeMetadata,
            orgMemberships: user?.organizationMemberships?.map(m => ({
              orgId: m.organization.id,
              orgName: m.organization.name,
              role: m.role,
            })),
          }, null, 2)}
        </pre>
      </div>

      <div style={{ background: "#1a1f2e", border: "1px solid #222d3d", borderRadius: "12px", padding: "20px", marginBottom: "20px" }}>
        <h2 style={{ marginBottom: "15px" }}>🏢 Active Organization</h2>
        <pre style={{ background: "#0f141e", padding: "15px", borderRadius: "8px", overflow: "auto" }}>
          {JSON.stringify({
            hasOrg: !!organization,
            orgId: organization?.id,
            orgName: organization?.name,
            slug: organization?.slug,
          }, null, 2)}
        </pre>
      </div>

      <div style={{ background: "#1a1f2e", border: "1px solid #222d3d", borderRadius: "12px", padding: "20px" }}>
        <h2 style={{ marginBottom: "15px" }}>👥 Organization Members</h2>
        <pre style={{ background: "#0f141e", padding: "15px", borderRadius: "8px", overflow: "auto" }}>
          {JSON.stringify({
            memberCount: membershipList?.length || 0,
            members: membershipList?.map(m => ({
              userId: m.publicUserData?.userId,
              name: `${m.publicUserData?.firstName || ''} ${m.publicUserData?.lastName || ''}`.trim(),
              email: m.publicUserData?.identifier,
              role: m.role,
            })) || [],
          }, null, 2)}
        </pre>
      </div>

      <div style={{ marginTop: "30px", padding: "20px", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.3)", borderRadius: "12px" }}>
        <h3 style={{ marginBottom: "10px" }}>💡 What to check:</h3>
        <ul style={{ lineHeight: "1.8" }}>
          <li>✅ <strong>Active Organization</strong> should show <code>hasOrg: true</code> and a valid <code>orgId</code></li>
          <li>✅ <strong>Organization Members</strong> should list all users you've created</li>
          <li>❌ If <code>hasOrg: false</code>, you need to <strong>sign out and sign back in</strong></li>
          <li>❌ If members list is empty, the create-user API isn't adding users to the org</li>
        </ul>
      </div>

      <div style={{ marginTop: "20px" }}>
        <a href="/admin" style={{ padding: "12px 24px", background: "#3b82f6", color: "#fff", borderRadius: "8px", textDecoration: "none", display: "inline-block" }}>
          ← Back to Admin Console
        </a>
      </div>
    </div>
  );
}
