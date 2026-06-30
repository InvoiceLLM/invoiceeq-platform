# Feature Website 4: Clerk Auth Gateway & Company Provisioning

Manage user sign-ups, handle automatic email domain-based company/tenant creation, assign roles, and redirect users to the dashboard with role-scoped JWTs.

### File Coordinates
* Website Auth Middleware: [apps/invoice-website/middleware.ts](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-website/middleware.ts)
* Backend Auth Router: [apps/invoice-be/routers/auth.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/auth.py)

### Tasks
- [ ] **Task 4.1: Integrate Clerk/Auth0 SSO Gateway**
  - Integrate Clerk Middleware in `apps/invoice-website` to capture authentication redirects.
  - Retrieve verified user parameters (Email, First Name, Last Name) upon successful Microsoft/Google SSO login.
- [ ] **Task 4.2: Domain-Based Company (Tenant) Creation Flow**
  - On the backend auth callback, parse the user's email domain (e.g. `@acme.com`).
  - **Check database**:
    - **Domain Match Exists**: Bind the joining user to the existing `Tenant` workspace.
    - **New Domain Detected**:
      1. Insert a new record in the `tenants` table.
      2. Set `billing_plan` to `'free'`, and `free_invoices_remaining` to `50`.
      3. Register the user under this new tenant ID.
      4. Automatically assign the first registering user of a domain the role of **`Admin`**. All subsequent sign-ups from that domain default to **`Viewer`** until modified by the Admin.
- [ ] **Task 4.3: Secure JWT Token Issuance & Scoping**
  - Once the tenant scope is resolved, generate a secure JWT signature containing:
    ```json
    {
      "user_id": "uuid",
      "tenant_id": "uuid",
      "role": "Admin | Auditor | Loader | Trainer | Viewer",
      "billing_plan": "free | pro | unpaid"
    }
    ```
  - Redirect the authenticated user to the Next.js frontend application dashboard URL (`app.yourinvoiceai.com`) passing the JWT secure token in cookies or state.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_provisioning.py` verifying that new domains trigger tenant inserts while existing domains join existing groups.
* **Manual Verification**: Register with a new test email account, verify that a fresh tenant workspace is created, and inspect the cookies to check the role is set to `Admin`.
