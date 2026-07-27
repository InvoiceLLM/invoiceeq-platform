# Feature 17: Invoice Builder (Logo/Template Invoice Generation)

Placeholder only — deliberately decoupled from Vendor Flow during design review. Not started, not scoped in detail, blocked on its own dedicated scoping conversation before any task list is written.

### Why this is separate from Vendor Flow
Vendor Flow's outbound "Send Invoices" ([feature_2.1_vendor_flow_ingestion.md](feature_2.1_vendor_flow_ingestion.md)) is upload-only: the tenant brings their own already-branded PDF. In-app invoice *generation* — letting a tenant create an outbound invoice from scratch inside this product — was considered and explicitly rejected for that build, because it drags in a materially larger scope: logo upload/storage, a layout/template picker, and a branding settings screen, none of which exist today. Rather than let that scope creep into Vendor Flow's build, it's parked here as its own future feature.

### Known shape (not yet a task list)
- Logo upload + storage (likely Blob Storage, mirroring `services/storage.py`'s existing pattern).
- One or more invoice layout templates, selectable per tenant.
- A generation endpoint producing a PDF from structured line-item input, plausibly feeding into the same `feature_2.1` verification step once generated (self-check the generated document before send).
- A branding section on the Settings screen ([feature_10_settings.md](feature_10_settings.md) FE / [feature_16_settings.md](feature_16_settings.md) BE) to manage the above.

### Explicitly not decided
- Whether this is a Vendor Flow tier feature, a separate add-on, or bundled — tied to the same open pricing question as [feature_3.1_vendor_flow_pricing.md](feature_3.1_vendor_flow_pricing.md), not resolved here.
- Template engine/rendering approach (HTML→PDF, a PDF library, or a third-party document API).

### Tasks
- [ ] Not yet broken into tasks — requires its own scoping pass before implementation planning starts.
