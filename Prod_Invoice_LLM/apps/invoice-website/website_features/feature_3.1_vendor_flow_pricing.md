# Feature Website 3.1: Vendor Flow Pricing Tier — OPEN DECISION

Extends [feature_3_pricing_stripe.md](feature_3_pricing_stripe.md). **Blocked — requires explicit sign-off before any implementation task is written.** No default is given here on purpose.

### Current tiers (unchanged, for reference)
- **FREE** — ₹0/month, 50 invoices/month, Dashboard + Ingest + Auditor, 1 user.
- **PRO** — ₹4,999/month, unlimited invoices, all screens, up to 10 users, ERP connectors.

### The question
Where does Vendor Flow (outbound Send Invoices, its Dashboard/Auditor split, direction-aware Chat) sit relative to these tiers?

### Option A — Bundled free with any tenant
Vendor Flow ships as part of both FREE and PRO, gated only by the Settings toggle, not billing.
- *For:* simplest to build and support — no new billing logic, no new Stripe price object, `get_tenant_context()`'s existing `billing_plan` check never needs to know Vendor Flow exists.
- *Against:* gives away a materially larger feature (a whole second invoice pipeline direction) for free, including to FREE-tier tenants who today only get 50 invoices/month — no revenue capture for a genuinely new capability.

### Option B — Pro-gated, same treatment as ERP connectors
Send Invoices toggle only enables successfully if `billing_plan == "pro"`; FREE-tier tenants seeing the toggle get an upgrade prompt instead.
- *For:* reuses the exact existing pattern (ERP connectors are already Pro-gated), no new Stripe price object needed, straightforward to enforce in the same place `feature_16_settings.md`'s toggle endpoint already checks role.
- *Against:* bundles a potentially heavy-usage feature (outbound invoices could be higher-volume than inbound for some tenants) into a flat-rate tier with no usage-based ceiling of its own.

### Option C — Separate add-on line item
A third Stripe price object, purchasable independently of FREE/PRO (e.g., "+₹X/month for Vendor Flow"), stackable on either tier.
- *For:* cleanest revenue capture, lets a FREE-tier tenant buy just this one capability without upgrading to full Pro; scales pricing independently as usage patterns become clear post-launch.
- *Against:* most implementation work — a new Stripe product/price, a new webhook-handled entitlement flag separate from `billing_plan`, new UI for a second checkout flow alongside the existing Pro upsell.

### Explicitly not decided here
- Whether any usage cap applies to outbound invoice volume, independent of which option is chosen above.
- Trial/grandfathering terms for tenants who start using Vendor Flow before this decision locks (relevant mainly if Option C is chosen well after initial internal rollout).

### Tasks
- [ ] **Not written yet** — blocked entirely on which option above gets picked. No Stripe/billing code should reference Vendor Flow until this is resolved.
