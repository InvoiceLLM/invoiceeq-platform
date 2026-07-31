# Website (invoice-website) Test Suite — Index

This document is an index into the per-feature test suites for the public marketing website, billing, and auth gateway pages. Each linked file follows the same 4-part structure:

1. **Screen Alignment Check** — visual/spec conformance (colors, layout, responsive behavior).
2. **Functionality Check** — user actions and their expected UI/API behavior.
3. **Database Validation** — what should (and should not) change in Postgres as a result of each flow.
4. **Flow Validation via Log Files** — what `invoice-be` should log, and at what level, for each flow. Note: `invoice-be` has no file-based log handler configured yet (`main.py` only calls `logging.getLogger(__name__)`, stdout only) — every suite below flags this and treats log checks as console/stdout checks, not literal file tails.

## Suites

| Feature | Suite | Build status |
|---|---|---|
| 1: Landing Page & Core Shell | [feature_1_landing_tests.md](website/feature_1_landing_tests.md) | Built |
| 2: Multi-Tenant Workspace Showcase | [feature_2_showcase_tests.md](website/feature_2_showcase_tests.md) | Built |
| 3 / 3.1: Pricing Table & PayU Checkout (incl. Combined Pro upgrade) | [feature_3_pricing_payu_tests.md](website/feature_3_pricing_payu_tests.md) | **Backend router exists (uncommitted); frontend pricing page not built** — see suite for what's actually runnable today |
| 4: Clerk Auth Gateway & Company Provisioning | [feature_4_auth_gateway_tests.md](website/feature_4_auth_gateway_tests.md) | Built, on placeholder Clerk keys (Gap 2/9 open) |

See `apps/invoice-website/website_features/website_features_tracker.md` for the underlying feature build status and open gaps referenced throughout these suites (Gap 2, 4, 9, 10, 11 in particular are cited directly in test cases above).
