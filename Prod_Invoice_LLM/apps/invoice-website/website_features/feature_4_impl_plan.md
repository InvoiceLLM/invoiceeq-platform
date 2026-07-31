# Feature 4: Auth Gateway - Implementation Plan

**Feature:** Clerk Auth Gateway & Company Provisioning  
**Document Version:** 1.0  
**Last Updated:** July 27, 2026  
**Status:** Frontend Complete, Backend Phase 2 In Progress (Schema Done)

---

## 📋 Executive Summary

This document outlines the complete implementation plan for Feature 4: Clerk Auth Gateway & Company Provisioning. It covers what has been developed, architectural decisions made, and the roadmap for remaining work.

### Current State
- ✅ **Frontend:** 100% Complete (Signup, Login, Org Management)
- ✅ **Clerk Integration:** 100% Complete (Organizations, Metadata, Sessions)
- ✅ **Schema Update:** 100% Complete (`clerk_org_id` column added to tenant table)
- ✅ **Auth Provision Router:** 100% Complete (POST /auth/provision)
- ✅ **JWT Middleware:** 100% Complete (tenant resolved by clerk_org_id)
- ⏳ **Backend:** 90% Complete (Webhook optional, frontend integration pending)

### Key Achievement
Successfully implemented a **multi-tenant authentication system** using Clerk Organizations with role-based access control, eliminating the need for custom domain-parsing logic on the backend.

---

## 🏗️ Architecture Overview

### **Design Decision: Clerk Organizations as Tenant Identifier**

**Original Plan (from feature_4_auth_gateway.md):**
- Parse email domain (e.g., `@acme.com`)
- Match domain to `tenants` table
- Create tenant if domain is new

**Implemented Approach:**
- Use **Clerk Organizations** as the primary tenant entity
- Store `clerk_org_id` in `tenants` table
- Organization name provided by user during signup
- No email domain parsing required

**Rationale:**
1. ✅ **User Control:** Users choose their organization name (not constrained by email domain)
2. ✅ **Freelancers/Consultants:** Supports users with generic emails (@gmail.com) who need separate orgs
3. ✅ **Multi-Org Support:** Users can belong to multiple organizations
4. ✅ **Clerk Native:** Leverages built-in Clerk Organizations feature
5. ✅ **Reduced Complexity:** No custom domain-to-tenant mapping logic needed

---

## 🎯 Phase 1: Frontend Implementation (COMPLETE)

### **1.1 User Signup Flow** ✅

**File:** `apps/invoice-website/pages/admin/signup.jsx`

**Implementation Steps:**
1. **Form Design:**
   - Organization fields: name, type, country
   - Account fields: email, password, confirm password
   - Validation: password match, required fields

2. **Clerk User Creation:**
   ```javascript
   const result = await signUp.create({
     emailAddress: email,
     password,
     unsafeMetadata: { orgType, country, role: 'admin' }
   });
   ```

3. **Organization Creation:**
   ```javascript
   const org = await window.Clerk.createOrganization({ name: orgName });
   await window.Clerk.setActive({ organization: org.id });
   ```

4. **Metadata Update:**
   ```javascript
   await window.Clerk.user.update({
     unsafeMetadata: {
       orgId: org.id,
       orgName,
       orgType,
       country,
       role: 'admin'
     }
   });
   ```

5. **Redirect:** Navigate to `/admin/login`

**Key Features:**
- Glassmorphism UI with gradient backgrounds
- Real-time form validation
- Error handling for duplicate emails
- Password strength requirements
- Success state with auto-redirect

---

### **1.2 User Login Flow** ✅

**File:** `apps/invoice-website/pages/admin/login.jsx`

**Implementation Steps:**
1. **Role Selection UI:**
   - Toggle between Admin and User roles
   - Visual distinction (different colors/icons)

2. **Clerk Sign-In:**
   ```javascript
   let result = await signIn.create({
     identifier: email,
     password
   });
   ```

3. **Role Verification:**
   ```javascript
   const registeredRole = clerkUser?.unsafeMetadata?.role;
   if (registeredRole !== selectedRole) {
     setAccessDenied(true);
     return;
   }
   ```

4. **Active Organization Selection (Critical):**
   ```javascript
   const memberships = clerkUser?.organizationMemberships || [];
   const adminMembership = memberships.find(m => m.role === 'org:admin');
   await window.Clerk.setActive({
     organization: adminMembership.organization.id
   });
   ```

5. **Role-Based Redirect:**
   - Admin → `http://localhost:3001/admin`
   - User → `http://localhost:3001/dashboard`

**Key Features:**
- Session conflict handling (auto sign-out if exists)
- Email verification fallback (OTP form)
- "Forgot password" link
- Access denied banner
- Active session indicator

---

### **1.3 Create User API** ✅

**File:** `apps/invoice-fe/app/api/admin/create-user/route.js`

**Implementation Steps:**
1. **Receive orgId from Frontend Request Body:**
   ```javascript
   const { firstName, lastName, email, password, orgId } = body;
   // orgId comes from useOrganization().organization.id on the client
   ```

2. **Validate orgId is present:**
   ```javascript
   if (!orgId) {
     return NextResponse.json({ error: 'orgId is required.' }, { status: 400 });
   }
   ```

3. **Create Clerk User (Direct REST API):**
   ```javascript
   const createRes = await fetch('https://api.clerk.com/v1/users', {
     method: 'POST',
     headers: {
       Authorization: `Bearer ${CLERK_SECRET_KEY}`,
       'Content-Type': 'application/json'
     },
     body: JSON.stringify({
       first_name, last_name,
       email_address: [email],
       password,
       skip_password_checks: true,
       unsafe_metadata: { role: 'user', orgId }
     })
   });
   ```

4. **Verify Email Immediately:**
   ```javascript
   await fetch(`https://api.clerk.com/v1/email_addresses/${emailId}`, {
     method: 'PATCH',
     body: JSON.stringify({ verified: true })
   });
   ```

5. **Add User to Organization:**
   ```javascript
   await fetch(`https://api.clerk.com/v1/organizations/${orgId}/memberships`, {
     method: 'POST',
     body: JSON.stringify({
       user_id: user.id,
       role: 'org:member'
     })
   });
   ```

**Why Direct REST API?**
- Avoids Clerk SDK version compatibility issues
- Explicit control over email verification
- Better error handling and debugging

**Why orgId from request body (not `auth().orgId`)?**
- Clerk's server-side `auth()` does NOT reliably reflect active org set client-side
- Session token refresh is asynchronous and not guaranteed
- Frontend `useOrganization()` hook always has the correct active org
- This pattern is more reliable and explicit

---

### **1.4 Admin Console** ✅

**File:** `apps/invoice-fe/app/admin/page.tsx`

**Implementation Steps:**
1. **Fetch Organization Context:**
   ```typescript
   const { organization, membershipList } = useOrganization({
     membershipList: {}
   });
   ```

2. **Display Organization Details:**
   - Organization name, type, country
   - Clerk Organization ID badge
   - Member statistics (admin count, user count)

3. **Member List Table:**
   - User avatar (first letter)
   - Name and email
   - Role badge (Admin vs Member)
   - Join date
   - Remove action (for non-admins)

4. **Add User Modal:**
   - Form with validation
   - Real-time API call
   - Success state with auto-refresh

---

### **1.5 Middleware Configuration** ✅

**Files:**
- `apps/invoice-website/middleware.ts`
- `apps/invoice-fe/middleware.ts`

**Critical Fix Applied:**
```typescript
export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|robots.txt|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)).*)',
    '/api/(.*)',  // ← CRITICAL: ensures auth() works in API routes
    '/trpc/(.*)'
  ]
};
```

**Problem Solved:**
- Old regex excluded `.js` files
- API routes weren't getting auth context
- `auth()` helper failed with "can't detect clerkMiddleware"

---

## 🔄 Phase 2: Backend Integration (IN PROGRESS)

### **2.1 Database Schema Update** ✅ COMPLETE

**File:** `apps/invoice-be/models.py`  
**Migration:** `apps/invoice-be/alembic/versions/a1b2c3d4e5f6_add_clerk_org_id_to_tenant.py`  
**Date Completed:** July 27, 2026

**Table Changed:** `tenant`

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| **`clerk_org_id`** | **VARCHAR(255)** | **UNIQUE, INDEXED, NULLABLE** | **Maps Clerk Organization ID (e.g., `org_2xyz...`) to internal tenant record** |

**Model Change:**
```python
class Tenant(SQLModel, table=True):
    # ... existing fields ...
    clerk_org_id: str | None = Field(default=None, max_length=255, unique=True, index=True)
```

**Migration (a1b2c3d4e5f6):**
```python
def upgrade() -> None:
    op.add_column('tenant', sa.Column('clerk_org_id', sa.String(255), nullable=True))
    op.create_index('ix_tenant_clerk_org_id', 'tenant', ['clerk_org_id'], unique=True)

def downgrade() -> None:
    op.drop_index('ix_tenant_clerk_org_id', table_name='tenant')
    op.drop_column('tenant', 'clerk_org_id')
```

**Design Decisions:**
- **Nullable:** Existing tenants (if any) won't break. Can be backfilled later.
- **Unique:** One Clerk org maps to exactly one tenant. Prevents duplicates.
- **Indexed:** Fast O(1) lookup when resolving tenant from JWT `org_id` claim.

**To Run Migration:**
```bash
cd apps/invoice-be
alembic upgrade head
```

---

### **2.2 Auth Provisioning Router** ✅ COMPLETE

**File:** `apps/invoice-be/routers/auth.py`  
**Date Completed:** July 27, 2026

**Endpoint:** `POST /auth/provision`

**Purpose:** Called by frontend after admin signup to register the Clerk Organization as a backend tenant.

**Request Schema:**
```python
class TenantProvisionRequest(BaseModel):
    clerk_org_id: str          # "org_2abc..."
    org_name: str              # Display name
    admin_email: str           # Admin email
    clerk_user_id: str         # "user_2xyz..."
    first_name: str | None = None
    last_name: str | None = None
```

**Response Schema:**
```python
class TenantProvisionResponse(BaseModel):
    tenant_id: str             # Internal UUID as string
    clerk_org_id: str
    org_name: str
    billing_plan: str          # "free"
    free_invoices_remaining: int  # 50
    is_new: bool               # Was this just created?
```

**Logic Flow:**
1. Look up tenant by `clerk_org_id` → if exists, return it (idempotent)
2. Look up by email domain → if legacy tenant found, link `clerk_org_id` to it
3. Otherwise → create new tenant + admin User row

**Integration Point (frontend signup.jsx):**
```javascript
// After Clerk org is created in signup
await fetch('http://localhost:8000/auth/provision', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    clerk_org_id: org.id,
    org_name: orgName,
    admin_email: email,
    clerk_user_id: clerkUser.id,
    first_name: firstName,
    last_name: lastName,
  })
});
```

---

### **2.3 JWT Middleware Enhancement** ✅ COMPLETE

**File:** `apps/invoice-be/dependencies.py`  
**Date Completed:** July 27, 2026

**What was fixed:**

The original code tried to UUID-parse Clerk's `org_id` (which is a string like `"org_2abc..."`), causing a crash. Now it uses string matching:

**Tenant Resolution Priority (in `get_tenant_context()`):**
```
1. clerk_org_id → SELECT * FROM tenant WHERE clerk_org_id = 'org_2abc...'
2. tenant_id    → SELECT * FROM tenant WHERE id = UUID(...)
3. domain       → SELECT * FROM tenant WHERE domain = 'acme.com'
```

**Key Changes:**
```python
# Extract from JWT (no UUID parsing!)
clerk_org_id = payload.get("org_id")  # String: "org_2abc..."

# Tenant lookup: clerk_org_id first
if clerk_org_id:
    tenant = db_session.exec(
        select(Tenant).where(Tenant.clerk_org_id == clerk_org_id)
    ).first()
```

**Clerk JWT Structure (with Organizations active):**
```json
{
  "sub": "user_2abc...",
  "org_id": "org_2xyz...",
  "org_role": "org:admin",
  "org_slug": "test-company",
  "email": "admin@testcompany.com",
  "iat": 1674567890,
  "exp": 1674571490
}
```

---

### **2.4 Webhook Integration (Optional)** ⏳

**File:** `apps/invoice-be/routers/webhooks.py`

**Purpose:** Auto-sync Clerk org events to backend

**Webhook Events to Handle:**
1. `organization.created` → Create tenant record
2. `organizationMembership.created` → Track user-tenant associations
3. `organization.deleted` → Mark tenant as inactive

**Implementation:**
```python
@router.post("/webhooks/clerk")
async def clerk_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    # Verify Clerk webhook signature
    payload = await request.json()
    signature = request.headers.get("svix-signature")
    
    if not verify_webhook_signature(payload, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    event_type = payload.get("type")
    
    if event_type == "organization.created":
        org_data = payload.get("data")
        tenant = Tenant(
            clerk_org_id=org_data["id"],
            name=org_data["name"],
            billing_plan="free",
            free_invoices_remaining=50
        )
        db.add(tenant)
        await db.commit()
    
    return {"status": "processed"}
```

**Setup in Clerk Dashboard:**
1. Go to Webhooks → Add Endpoint
2. URL: `https://your-api.com/api/webhooks/clerk`
3. Subscribe to events:
   - `organization.created`
   - `organization.deleted`
   - `organizationMembership.created`

**Estimated Time:** 4-5 hours

---

## 🧪 Phase 3: Testing & Validation (PENDING)

### **3.1 Unit Tests**

**File:** `apps/invoice-be/tests/test_auth.py`

**Test Cases:**
```python
async def test_provision_new_tenant():
    """Test creating a new tenant from Clerk org"""
    response = await client.post("/api/auth/provision", json={
        "clerk_org_id": "org_test123",
        "org_name": "Test Company",
        "user_id": "user_test456"
    })
    assert response.status_code == 200
    assert response.json()["billing_plan"] == "free"

async def test_provision_existing_tenant():
    """Test linking to existing tenant"""
    # Pre-create tenant
    # Then provision again with same clerk_org_id
    # Should return existing tenant, not create duplicate

async def test_tenant_context_resolution():
    """Test JWT middleware resolves tenant correctly"""
    # Mock Clerk JWT with org_id
    # Call protected endpoint
    # Verify tenant_id injected into context
```

**Estimated Time:** 6-8 hours

---

### **3.2 Integration Tests**

**File:** `apps/invoice-fe/tests/auth-flow.test.ts`

**Test Cases:**
```typescript
test('Full signup flow creates org and redirects', async () => {
  // Fill signup form
  // Submit
  // Verify Clerk org created
  // Verify redirect to login
});

test('Login sets active org in session', async () => {
  // Login as admin
  // Verify auth().orgId is set
  // Verify create-user API can add members
});

test('Create user adds to organization', async () => {
  // Login as admin
  // Create new user
  // Verify user appears in membershipList
  // Verify user visible in Clerk Dashboard
});
```

**Estimated Time:** 8-10 hours

---

### **3.3 E2E Tests**

**Tool:** Playwright or Cypress

**Test Scenarios:**
1. New user signup → org creation → login → dashboard
2. Admin creates user → user logs in → sees correct org data
3. Multiple orgs: user switches between organizations
4. Role enforcement: user tries to access admin routes (should fail)

**Estimated Time:** 10-12 hours

---

## 🚀 Phase 4: Production Readiness (PENDING)

### **4.1 Environment Configuration**

**Replace Hard-Coded URLs:**

**Create:** `apps/invoice-website/.env.production`
```env
NEXT_PUBLIC_FRONTEND_URL=https://app.yourinvoiceai.com
NEXT_PUBLIC_BACKEND_URL=https://api.yourinvoiceai.com
```

**Update:** `login.jsx`
```javascript
const ROLE_REDIRECT = {
  admin: `${process.env.NEXT_PUBLIC_FRONTEND_URL}/admin`,
  user: `${process.env.NEXT_PUBLIC_FRONTEND_URL}/dashboard`,
};
```

---

### **4.2 Security Hardening**

**Tasks:**
- [ ] Enable HTTPS-only cookies
- [ ] Add CSRF protection
- [ ] Implement rate limiting on signup/login
- [ ] Add security headers (HSTS, CSP)
- [ ] Validate Clerk webhook signatures
- [ ] Sanitize user inputs

---

### **4.3 Monitoring & Logging**

**Implementation:**
- [ ] Log all auth events (signup, login, failures)
- [ ] Track org creation metrics
- [ ] Alert on failed auth attempts (potential attacks)
- [ ] Monitor API latency for auth endpoints

**Tools:**
- Datadog / New Relic for APM
- Sentry for error tracking
- CloudWatch for AWS logs

---

### **4.4 Documentation**

**Required Docs:**
- [ ] User guide: How to sign up
- [ ] Admin guide: How to manage team members
- [ ] API documentation: Auth endpoints
- [ ] Troubleshooting guide: Common issues

---

## 📅 Implementation Timeline

| Phase | Tasks | Estimated Time | Priority |
|-------|-------|----------------|----------|
| **Phase 1** | Frontend (Complete) | ✅ Done | - |
| **Phase 2.1** | Schema Update (Complete) | ✅ Done | - |
| **Phase 2.2** | Auth Provision Router (Complete) | ✅ Done | - |
| **Phase 2.3** | JWT Middleware (Complete) | ✅ Done | - |
| **Phase 2.4** | Webhooks (Optional) | 4-5 hours | Medium |
| **Phase 2.5** | Frontend → Backend Integration | 2-3 hours | High |
| **Phase 3** | Testing | 24-30 hours | High |
| **Phase 4** | Production Prep | 8-12 hours | Medium |
| **Total Remaining** | | **38-50 hours** | |

**Sprint Breakdown:**
- **Sprint 1 (Current):** Phase 2 - Backend Integration (2 weeks)
- **Sprint 2:** Phase 3 - Testing (2 weeks)
- **Sprint 3:** Phase 4 - Production Readiness (1 week)

---

## 🎯 Success Metrics

**Technical Metrics:**
- [ ] 100% auth flow test coverage
- [ ] < 500ms average auth API response time
- [ ] 99.9% uptime for auth endpoints
- [ ] Zero security vulnerabilities in auth code

**Business Metrics:**
- [ ] < 30 seconds signup time
- [ ] < 10 seconds login time
- [ ] < 5% signup abandonment rate
- [ ] 90%+ successful first-time logins

---

## 🔗 Dependencies

**Internal:**
- Feature 1: Landing Page (redirects after signup)
- Feature 3: Pricing/Stripe (billing plan enforcement)
- Backend Database: PostgreSQL with Alembic

**External:**
- Clerk (Authentication provider)
- Next.js 13+ (App Router)
- FastAPI (Backend framework)

---

## 📚 References

- [Clerk Organizations Documentation](https://clerk.com/docs/organizations/overview)
- [Clerk JWT Claims](https://clerk.com/docs/backend-requests/making/jwt-templates)
- [Next.js Middleware](https://nextjs.org/docs/app/building-your-application/routing/middleware)
- [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)

---

## 📞 Contact & Support

**Technical Lead:** [Your Name]  
**Slack Channel:** #invoice-ai-auth  
**Issue Tracker:** GitHub Issues (tag: `feature-4`)

---

**Document Status:** Living Document - Updated as implementation progresses  
**Next Review:** After Phase 2 completion
