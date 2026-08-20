# Feature 16: Admin Console & Organization Debug Tooling

Documentation for the Admin Console and Clerk organization-membership debug tooling, which provides user administration, role-based permission settings, inbound email drop auditing, and session state inspection.

### File Coordinates (as built)
* **Admin Console Page:** [apps/invoice-fe/app/admin/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/admin/page.tsx)
* **Create User API Route:** [apps/invoice-fe/app/api/admin/create-user/route.js](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/admin/create-user/route.js)
* **Delete User API Route:** [apps/invoice-fe/app/api/admin/users/[userRef]/route.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/api/admin/users/%5BuserRef%5D/route.ts)
* **Permissions API Client Helper:** `savePermissions()` and `removeUser()` in [app/admin/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/admin/page.tsx)
* **Clerk Debug Org Page:** [apps/invoice-fe/app/debug-org/page.tsx](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/app/debug-org/page.tsx)

---

### Functionality

#### 1. Admin Console & Gating
* **Access Control Gate:** Role-honesty is strictly enforced. The Admin Console is gated at route-level. If a user is not an `Admin` or the backend API calls return `401`/`403` status codes, the page renders an `Access Restricted` panel using `useAuth()` metadata, explaining that only organisation Administrators can manage users, roles, and permissions.
* **Viewer Row Identity:** The active signed-in Admin viewer's own row displays role/permission properties (e.g. "Organisation Owner", "Admin", "All (Admin)") sourced directly from the backend context `useAuth()` to prevent layout drift from hardcoded assumptions.
* **Workspace Metrics:** Displays total user counts, active users, and pending invitations via stat cards matching the project's glassmorphic design system.

#### 2. User Management
* **List Users:** Fetches the list of tenant members from `GET /api/admin/users` (mapping `AdminUserDto` structures into row entries). The logged-in admin viewer is filtered out from this list since they render on a dedicated top row.
* **Permissions Checkboxes:** Provides interactive checkboxes ("Trainer", "Auditor", "Loader") for each user. Checking or unchecking immediately calls `PUT /api/admin/users/{userRef}/permissions` (`savePermissions()`) using optimistic state updates. The state rolls back to its previous value if the network call fails.
* **Create User Modal:** Clicking `+ Add User` opens the `CreateUserModal` form:
  * Collects `firstName`, `lastName`, `email`, and `password`.
  * Allows assigning permissions ("Trainer", "Auditor", "Loader") at creation time.
  * Sends a `POST` request to `/api/admin/create-user` which creates the Clerk account, adds them to the caller's organization as `org:member`, patches the primary email address as verified (so they can sign in immediately), and then saves their custom permissions.
* **Remove User Flow:** Clicking `Remove` prompts for confirmation and calls `DELETE /api/admin/users/{userRef}`:
  * **Step 1:** Next.js API deletes the user's tenant database row first via backend `DELETE /api/v1/admin/users/{userRef}` (this is the real authorization boundary; a non-admin request fails here before touching Clerk).
  * **Step 2:** Next.js API then deletes the Clerk account via `DELETE https://api.clerk.com/v1/users/{clerkUserId}` using `CLERK_SECRET_KEY` to revoke sign-in.
  * If the Clerk deletion fails or is skipped (e.g. Clerk is offline or not configured), the API returns HTTP 200 with `clerkDeleted: false` and a warning, which is displayed in the UI banner (honoring partial success since tenant data is gone).

#### 3. Dropped Inbound Emails Auditing
* **Audit Panel:** Renders dropped inbound email logs fetched from `GET /api/admin/dropped-emails` (`DroppedEmailDto[]`) to monitor emails that failed validation.
* **Reason Mapping:** Maps technical reasons into descriptive labels (e.g., failed authentication, oversized payload, missing workspace) via `DROP_REASON_LABELS`.
* **Attributed Flag:** Unregistered domain-matched senders display a `(unregistered)` tag to prevent admins from assuming the sender email belongs to their tenant.
* **Refresh Action:** Includes a `Refresh` button to reload dropped email logs.

#### 4. Clerk Org Debug Page (`/debug-org`)
* A developer-only inspection screen that prints JSON metadata for:
  * **Current User:** Clerk ID, primary email, unsafe metadata, and organization memberships.
  * **Active Organization:** ID, name, slug, and active status.
  * **Organization Members:** Count and list of users.
* Excluded from marketing website proxy routing rule lists.

---

### Explicitly out of scope
* **Self-Demotion Gating:** The Admin cannot demote themselves or remove another Admin from the UI. Admin adjustments must be done via Clerk's central organization settings.
* **No-Company Signup:** Users created here are strictly bound to the caller's active organization tenant. There is no route for signing up without an organization context.

---

### Tasks
- [x] **Task 16.1: Admin Console Layout:** Implement `/admin` console UI, listing users, status cards, and security gating.
- [x] **Task 16.2: User Creation Endpoint:** Build `/api/admin/create-user` to automate Clerk account creation, organization mapping, and email verification.
- [x] **Task 16.3: Permissions Synchronisation:** Build optimistic permission toggling and permissions pre-provisioning for newly created users.
- [x] **Task 16.4: Deletion Flow:** Build `/api/admin/users/[userRef]/route.ts` implementing the two-step backend detach + Clerk delete revocation flow.
- [x] **Task 16.5: Debug Tooling:** Implement `/debug-org` to inspect Clerk session and membership state.

---

### Verification Plan

#### Automated Tests
* None. (Manual inspection and visual styling checks only; no Playwright tests cover this console, and it is excluded from default E2E rewrites).

#### Manual Verification
* **Access Gating:**
  1. Sign in as a `Viewer` or `Auditor` and navigate to `/admin`. Verify that the page blocks access and displays the `Access Restricted` message detailing your current role.
  2. Sign in as an `Admin` and confirm the page loads cleanly, displaying organization statistics and the users table.
* **Permissions Toggle:**
  1. Toggle the "Trainer" checkbox on a user. Confirm the checkbox stays checked and is successfully saved.
  2. Simulate a backend network failure. Confirm the checkbox rolls back to its original state and displays a warning banner.
* **User Provisioning:**
  1. Click `+ Add User`, fill out the form, tick "Auditor", and submit.
  2. Confirm the user appears in the table with "Invited" status and the "Auditor" permission checked.
* **Remove User:**
  1. Click "Remove" on a user. Verify the confirmation popup appears.
  2. Confirm the user is deleted from both the database and Clerk, and their row is removed from the table.
