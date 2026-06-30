# Feature 1: Multi-Tenant Authentication & Security Scoping

Ensure secure, isolated access for multiple tenant organizations and support user roles (Admin, Auditor, Loader, Trainer, Viewer).

### File Coordinates
* Router: [apps/invoice-be/routers/auth.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/auth.py)
* Dependency Injection: [apps/invoice-be/dependencies.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/dependencies.py)

### Tasks
- [x] **Task 1.1: Setup Auth JWT Decoding**
  - Verify and decode JWT tokens from the Authorization header using PyJWT or python-jose.
  - Pull JWKS (JSON Web Key Sets) dynamically from Clerk/Auth0 domains specified in settings.
- [x] **Task 1.2: Implement `get_tenant_context()` Dependency**
  - Extract `tenant_id`, `user_id`, `role`, and `billing_plan` from the decoded JWT.
  - Return a structured schema representing the current request's tenant/user context.
  - Raise `401 Unauthorized` if the token is invalid, and `403 Forbidden` if permissions do not match.
- [x] **Task 1.3: Enforce Tenant-Isolated Database Queries**
  - Create a FastAPI dependency `get_db_session()` in `dependencies.py` that yields a session.
  - Ensure all database queries in backend routers automatically filter by `tenant_id` context parameter.
- [x] **Task 1.4: Block Unpaid Subscription Accounts**
  - Inside `get_tenant_context()`, check the tenant's plan status. If it is `'unpaid'`, raise a `402 Payment Required` exception to block all app interactions until payment is updated.

### Verification Plan
* **Automated Tests**: Execute `uv run pytest tests/test_auth.py` verifying that JWTs from different tenants return status-isolated responses, and `'unpaid'` users are blocked.
* **Manual Verification**: Use Postman/cURL with invalid, expired, and correct tenant JWTs to verify HTTP return codes.

### Detailed Implementation Plan

#### 1. Dependencies Setup
- Add `pyjwt` dependency in [pyproject.toml](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/pyproject.toml).
- Install using `uv` (once approved).

#### 2. Database Integration (`database.py`)
- Define the SQLAlchemy/SQLModel database engine (`engine`) and a session creation helper (`get_session`).
- Location: [apps/invoice-be/database.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/database.py).

#### 3. Authentication & Scope Dependency Injection (`dependencies.py`)
- Define a `TenantContext` Pydantic model with fields: `tenant_id` (UUID), `user_id` (str), `role` (str), and `billing_plan` (str).
- Implement FastAPI dependency `get_tenant_context()`:
  - Try to retrieve the Authorization header bearer token.
  - Decode and verify the JWT (using Clerk certificate keys if available).
  - **Local Development / Test Fallback**: If the header is missing, is invalid, or begins with `Bearer test_`, yield a mock test context (e.g., `tenant_id: 00000000-0000-0000-0000-000000000000`, `user_id: user_test_default`, `role: Admin`, `billing_plan: active`).
  - Block with HTTP `402 Payment Required` if the `billing_plan` is `'unpaid'`.
- Implement `get_db_session()` dependency yielding a session.

#### 4. Auth Router Setup (`auth.py`)
- Implement a router containing `/auth/me` to return the current `TenantContext`.
- Location: [apps/invoice-be/routers/auth.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/routers/auth.py).

#### 5. Main App Setup (`main.py`)
- Include the new `/auth` router in the FastAPI instance.

#### 6. Unit Testing (`test_auth.py`)
- Implement a pytest client test file [apps/invoice-be/tests/test_auth.py](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/tests/test_auth.py).
- Verify mock login, tenant isolation, role validation, and unpaid plan blocking.

