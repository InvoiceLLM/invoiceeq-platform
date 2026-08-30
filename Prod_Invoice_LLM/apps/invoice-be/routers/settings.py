"""
Feature 16: Settings — Service Flow endpoint.
Gap 184: Settings — programmatic API key (security) endpoints.

Routes
------
GET  /api/v1/settings/vendor-flow              — readable by any authenticated role
PUT  /api/v1/settings/vendor-flow              — Admin only; enforces billing plan + outbound set gate
GET  /api/v1/settings/security/api-key         — key metadata only (never the key itself)
POST /api/v1/settings/security/api-key/rotate  — Admin only; issues a new key, invalidates the old one
GET  /api/v1/settings/security/api-key/verify  — authenticated BY the API key; lets an
                                                 integrator confirm a key works

Feature 25 / Gap 336: Plug & Play workflow policy.

GET  /api/v1/settings/workflow                 — Admin only; the tenant's workflow choices
PUT  /api/v1/settings/workflow                 — Admin only; also writes Tenant.api_key_scope

Feature 25 / Gap 341: embedded chat widget tokens.

GET    /api/v1/settings/security/widget-tokens            — Admin only
POST   /api/v1/settings/security/widget-tokens            — Admin only; shown once
DELETE /api/v1/settings/security/widget-tokens/{token_id} — Admin only; immediate
"""
import logging
import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel

from dependencies import (
    get_api_key_context,
    get_tenant_context,
    get_db_session,
    KEY_SCOPE_ACTIONS,
    KEY_SCOPE_READONLY,
    TenantContext,
)
from models import Tenant, TenantEmailSender, TenantWorkflowConfig
from services.api_keys import (
    generate_api_key,
    generate_salt,
    hash_api_key,
    key_prefix,
    masked_display,
)
# Feature 25 (Gap 339): `email_summary` delivers to the TenantEmailSender
# allowlist, so selecting it is only meaningful when that allowlist is non-empty
# -- validated below via the same reader staff_notify uses, not a second query.
from services.staff_notify import list_registered_emails
# Gap 338: same shape for `drive_archive` -- its recipients are a connected
# Drive account, so selecting it is only meaningful when that connection exists
# AND can write. drive_archive_readiness() is the single implementation of that
# question, shared with the delivery path so the two cannot drift.
from services.workflow_outputs import (
    OUTPUT_DESTINATION_DRIVE_ARCHIVE,
    OUTPUT_DESTINATION_EMAIL_SUMMARY,
    drive_archive_readiness,
)
# Feature 25 (Gap 340): an unclaimed sandbox workspace is pinned to `readonly`
# scope and may not select Full Automation -- see update_workflow_settings().
from services.sandbox import is_sandbox_tenant
# Feature 25 (Gap 341): Admin-only issue/list/revoke for the embedded chat
# widget's tokens. The tokens themselves are used at
# routers/widget.py::post_widget_chat_message and nowhere else.
from services.widget_tokens import (
    MAX_TOKENS_PER_TENANT,
    active_widget_tokens,
    issue_widget_token,
    normalize_origin,
    revoke_widget_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])


class VendorFlowSettings(BaseModel):
    receive_invoices_enabled: bool
    send_invoices_enabled: bool
    outbound_sender_email: str | None
    billing_plan: str
    outbound_authorized_count: int = 0


class VendorFlowUpdateRequest(BaseModel):
    receive_invoices_enabled: bool | None = None
    send_invoices_enabled: bool | None = None
    outbound_sender_email: str | None = None


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


def _outbound_set_count(db_session: Session, tenant_id) -> int:
    rows = db_session.exec(
        select(TenantEmailSender).where(
            TenantEmailSender.tenant_id == tenant_id,
            TenantEmailSender.email_set == "outbound",
        )
    ).all()
    return len(rows)


@router.get("/vendor-flow", response_model=VendorFlowSettings)
async def get_vendor_flow_settings(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    return VendorFlowSettings(
        receive_invoices_enabled=tenant.receive_invoices_enabled,
        send_invoices_enabled=tenant.send_invoices_enabled,
        outbound_sender_email=tenant.outbound_sender_email,
        billing_plan=tenant.billing_plan,
        outbound_authorized_count=_outbound_set_count(db_session, tenant.id),
    )


@router.put("/vendor-flow", response_model=VendorFlowSettings)
async def update_vendor_flow_settings(
    payload: VendorFlowUpdateRequest,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """
    Admin-only. Enabling send_invoices requires:
    - ≥1 TenantEmailSender with email_set=outbound (400 otherwise)
    - billing_plan == pro_combined (402 otherwise)
    """
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can modify Service Flow settings.",
        )

    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    new_receive = (
        payload.receive_invoices_enabled
        if payload.receive_invoices_enabled is not None
        else tenant.receive_invoices_enabled
    )
    new_send = (
        payload.send_invoices_enabled
        if payload.send_invoices_enabled is not None
        else tenant.send_invoices_enabled
    )
    new_email = (
        payload.outbound_sender_email
        if payload.outbound_sender_email is not None
        else tenant.outbound_sender_email
    )

    if new_email is not None and not _valid_email(new_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="outbound_sender_email is not a valid email address.",
        )

    outbound_count = _outbound_set_count(db_session, tenant.id)

    if new_send:
        if outbound_count < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "At least one outbound authorized email must be registered under "
                    "Settings → Email before enabling send_invoices_enabled."
                ),
            )
        if tenant.billing_plan != "pro_combined":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    "Sending invoices requires the Pro Combined plan (₹8,999/month). "
                    "Please upgrade your subscription."
                ),
            )

    tenant.receive_invoices_enabled = new_receive
    tenant.send_invoices_enabled = new_send
    tenant.outbound_sender_email = new_email

    from datetime import datetime
    tenant.updated_at = datetime.utcnow()

    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    logger.info(
        "Service Flow settings updated for tenant=%s by user=%s: receive=%s send=%s outbound_set=%s",
        context.tenant_id, context.user_id,
        tenant.receive_invoices_enabled, tenant.send_invoices_enabled, outbound_count,
    )

    return VendorFlowSettings(
        receive_invoices_enabled=tenant.receive_invoices_enabled,
        send_invoices_enabled=tenant.send_invoices_enabled,
        outbound_sender_email=tenant.outbound_sender_email,
        billing_plan=tenant.billing_plan,
        outbound_authorized_count=outbound_count,
    )


# --- Gap 184: programmatic API key ----------------------------------------


class ApiKeyStatus(BaseModel):
    """
    What the Security settings page is allowed to know about the live key.

    `key_prefix`/`masked_key` are the non-secret leading characters only. There
    is deliberately no field here that could carry the key itself: the raw value
    exists in exactly one response in the whole API (ApiKeyRotateResponse).
    """
    has_key: bool
    key_prefix: str | None = None
    masked_key: str | None = None
    rotated_at: datetime | None = None
    last_used_at: datetime | None = None
    can_rotate: bool = False


class ApiKeyRotateResponse(ApiKeyStatus):
    """The one and only response that carries a raw key. See rotate_api_key()."""
    api_key: str


def _api_key_status(tenant: Tenant, context: TenantContext) -> ApiKeyStatus:
    return ApiKeyStatus(
        has_key=bool(tenant.api_key_hash),
        key_prefix=tenant.api_key_prefix,
        masked_key=masked_display(tenant.api_key_prefix),
        rotated_at=tenant.api_key_rotated_at,
        last_used_at=tenant.api_key_last_used_at,
        can_rotate=context.role == "Admin",
    )


@router.get("/security/api-key", response_model=ApiKeyStatus)
async def get_api_key_status(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """
    Metadata about this tenant's API key. Readable by any authenticated role
    (a non-Admin still needs to see whether an integration key exists and when
    it was last used); `can_rotate` tells the UI whether to offer the button.

    `has_key=False` is a real state, not an error -- a tenant that has never
    rotated has no key. The frontend renders an "issue a key" prompt for it,
    which is what Gap 184's hardcoded `inv_live_9f8a...` string was hiding.
    """
    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return _api_key_status(tenant, context)


@router.post("/security/api-key/rotate", response_model=ApiKeyRotateResponse)
async def rotate_api_key(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """
    Admin-only. Issue a new API key and invalidate the previous one.

    The same endpoint issues the first key and rotates a later one -- there is
    one key per tenant, so "create" and "rotate" are the same write. Overwriting
    hash+salt+prefix in a single commit is what revokes the old key: nothing
    remains to verify the previous digest against, so any request still carrying
    it 401s from the next request onward.

    The raw key in this response is the only time it is ever transmitted. It is
    not stored, not logged, and cannot be re-read -- a caller who loses it has
    to rotate again. The log line below records the prefix only, on purpose.
    """
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can rotate the API key.",
        )

    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    raw_key = generate_api_key()
    salt = generate_salt()

    tenant.api_key_hash = hash_api_key(raw_key, salt)
    tenant.api_key_salt = salt
    tenant.api_key_prefix = key_prefix(raw_key)
    tenant.api_key_rotated_at = datetime.utcnow()
    # A freshly issued key has never authenticated anything; carrying the old
    # key's last-used timestamp forward would misreport the new one as in use.
    tenant.api_key_last_used_at = None
    tenant.updated_at = datetime.utcnow()

    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    logger.info(
        "API key rotated for tenant=%s by user=%s (prefix=%s)",
        context.tenant_id, context.user_id, tenant.api_key_prefix,
    )

    status_payload = _api_key_status(tenant, context)
    return ApiKeyRotateResponse(**status_payload.model_dump(), api_key=raw_key)


# --- Feature 25 (Gap 336): Plug & Play workflow policy ----------------------
#
# The founder's two policies, verbatim:
#   Full Auto-Pilot = full automation -- the API key gets to call
#                     approve/reject/verify/send/mark-paid.
#   Strict Review   = the key stays read/upload-only, a human finalizes in the
#                     web UI.
#
# Working code name for the first is "full_automation", NOT "full_auto_pilot":
# Feature 13 already ships a "Tenant Autopilot" that means scheduled Google Drive
# sync, and both are configured from Settings. The founder has not ruled on the
# user-facing wording -- see docs/feature_25_plug_and_play_workflows.md.

AUDIT_POLICY_FULL_AUTOMATION = "full_automation"
AUDIT_POLICY_STRICT_REVIEW = "strict_review"

# The whole point of this endpoint: the policy the tenant picks IS
# Tenant.api_key_scope (Gap 335), not a second field that could drift from it.
AUDIT_POLICY_TO_KEY_SCOPE = {
    AUDIT_POLICY_FULL_AUTOMATION: KEY_SCOPE_ACTIONS,
    AUDIT_POLICY_STRICT_REVIEW: KEY_SCOPE_READONLY,
}
KEY_SCOPE_TO_AUDIT_POLICY = {v: k for k, v in AUDIT_POLICY_TO_KEY_SCOPE.items()}

# All four work today: email (Feature 14), drive (Feature 13 autopilot sync),
# manual (the upload UI), and api -- which needed Gap 335's key auth and has it.
WORKFLOW_INPUT_CHANNELS = ("email", "drive", "api", "manual")

# Only the destinations that actually deliver something. Anything not in here is
# rejected rather than stored: see _validate_destinations().
#
# `email_summary` moved into this tuple with **Gap 339**, which built the
# delivery (services/workflow_outputs.py, fired from
# routers/audit.py::resolve_audit_invoice on approval). Before that it sat in
# the UNBUILT map below and was 422'd. **Gap 338** did the same for
# `drive_archive`, so all four wizard destinations now deliver something.
WORKFLOW_OUTPUT_DESTINATIONS_AVAILABLE = (
    "webhook", "dashboard_only", "email_summary", "drive_archive",
)

# Designed, named in the wizard, and NOT BUILT. Mapped to the gap that will build
# each so the 422 tells an integrator something actionable instead of "invalid".
#
# **Empty since Gap 338 (2026-08-30)** -- every destination the wizard offers is
# now built. Kept rather than deleted: it is the mechanism that stops a future
# destination being accepted-and-ignored, and re-deriving it later would be a
# strictly worse outcome than an empty dict today. `_validate_destinations()`
# still consults it first.
WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT: dict[str, str] = {}

# Which TenantEmailSender set an `email_summary` recipient must be registered in.
# "inbound", because the only thing that triggers a summary today is the inbound
# audit router's approval, and services/workflow_outputs.py resolves recipients
# from the invoice's own direction. If that trigger is ever widened to outbound
# invoices, this check widens with it.
EMAIL_SUMMARY_SENDER_SET = "inbound"

WORKFLOW_CHAT_ACCESS = ("dashboard", "api", "widget")


class WorkflowConfig(BaseModel):
    input_channels: list[str]
    audit_policy: str
    output_destinations: list[str]
    chat_access: str
    completed_at: datetime | None = None
    # The enforcement primitive this policy maps onto, surfaced so a caller can
    # see what is actually in force rather than inferring it. Read-only here --
    # it is set via audit_policy, never independently.
    api_key_scope: str


class WorkflowConfigUpdate(BaseModel):
    """Partial update, same shape as VendorFlowUpdateRequest: any field left out
    keeps its current value. The wizard sends all four; a later single-field edit
    from the Settings page does not have to."""
    input_channels: list[str] | None = None
    audit_policy: str | None = None
    output_destinations: list[str] | None = None
    chat_access: str | None = None


def _require_admin_for_workflow(context: TenantContext) -> None:
    """Admin gate, matching the inline style the rest of this router uses.

    This is tenant-wide policy, not a per-user preference: it decides whether a
    machine may approve and send this tenant's invoices. Unlike GET
    /vendor-flow (readable by any role), the GET here is Admin-only too -- it
    reports `api_key_scope`, which is security configuration, and its only
    consumer is the Admin-only Settings wizard.
    """
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can view or modify workflow settings.",
        )


def _validate_input_channels(values: list[str]) -> list[str]:
    unknown = [v for v in values if v not in WORKFLOW_INPUT_CHANNELS]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown input channel(s): {', '.join(sorted(unknown))}. "
                f"Allowed: {', '.join(WORKFLOW_INPUT_CHANNELS)}."
            ),
        )
    # De-duplicate while keeping the caller's order -- the wizard can send the
    # same value twice if a checkbox is toggled oddly, and storing it twice would
    # make every later comparison awkward for no gain.
    return list(dict.fromkeys(values))


def _validate_destinations(
    values: list[str], db_session: Session, tenant_id
) -> list[str]:
    """Reject destinations that cannot actually deliver, instead of storing a lie.

    Gap 336's original rule was "reject what is not built": accepting a
    destination nothing delivers to would leave a tenant believing its
    processed invoices are being filed somewhere while nothing sends anything
    -- a silent no-op is strictly worse than a clear rejection, because the
    tenant only finds out by noticing the absence. Both destinations that were
    unbuilt then are built now (`email_summary` -- Gap 339; `drive_archive` --
    Gap 338), so the UNBUILT map is empty and this first check is dormant, not
    gone.

    What replaced it, for each, is a **per-tenant precondition** enforced for
    exactly the same reason:

    * `email_summary` (Gap 339) requires at least one **registered** email
      sender, because that allowlist -- not a free-text address typed into the
      wizard -- is where its recipients come from.
    * `drive_archive` (Gap 338) requires a connected Google Drive whose token
      can actually **write**. A connection made before 2026-08-30 consented to
      `drive.readonly` only, and Google never widens an existing grant, so
      "connected" is not the same question as "writable" -- see
      services/workflow_outputs.py::drive_archive_readiness(). This check is
      one of the two lazy points that detect the old-grant case; the other is
      the write itself.

    Storing either destination without its precondition would produce exactly
    the silent no-op the paragraph above exists to prevent.
    """
    unbuilt = [v for v in values if v in WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT]
    if unbuilt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "These output destinations are not available yet and were not saved: "
                + "; ".join(
                    f"{name} — {WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT[name]}"
                    for name in sorted(unbuilt)
                )
                + ". Available now: "
                + ", ".join(WORKFLOW_OUTPUT_DESTINATIONS_AVAILABLE)
                + "."
            ),
        )
    unknown = [v for v in values if v not in WORKFLOW_OUTPUT_DESTINATIONS_AVAILABLE]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown output destination(s): {', '.join(sorted(unknown))}. "
                f"Allowed: {', '.join(WORKFLOW_OUTPUT_DESTINATIONS_AVAILABLE)}."
            ),
        )
    if OUTPUT_DESTINATION_EMAIL_SUMMARY in values and not list_registered_emails(
        db_session, tenant_id, EMAIL_SUMMARY_SENDER_SET
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "email_summary needs at least one registered email address to "
                "send to. Summaries go only to this workspace's authorized "
                f"{EMAIL_SUMMARY_SENDER_SET} senders -- an arbitrary address "
                "cannot be entered here. Register one under Settings -> Email "
                "first, then select this destination."
            ),
        )
    if OUTPUT_DESTINATION_DRIVE_ARCHIVE in values:
        readiness = drive_archive_readiness(db_session, tenant_id)
        if not readiness["ready"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "drive_archive needs a Google Drive connection that this "
                    f"workspace has authorized for writing. {readiness['detail']}"
                ),
            )
    return list(dict.fromkeys(values))


def _workflow_response(config: TenantWorkflowConfig | None, tenant: Tenant) -> WorkflowConfig:
    """Assemble the response, deriving `audit_policy` from the tenant column.

    Derived, not read back from `config.audit_policy`, on purpose: Gap 335's
    `Tenant.api_key_scope` is the only value the auth layer enforces. If the two
    ever disagree -- an Admin editing the column directly, a partially applied
    write -- this endpoint reports what is actually in force. `or KEY_SCOPE_READONLY`
    is the same fail-closed guard resolve_api_key_context() uses.
    """
    scope = tenant.api_key_scope or KEY_SCOPE_READONLY
    return WorkflowConfig(
        input_channels=list(config.input_channels or []) if config else [],
        audit_policy=KEY_SCOPE_TO_AUDIT_POLICY.get(scope, AUDIT_POLICY_STRICT_REVIEW),
        output_destinations=list(config.output_destinations or []) if config else [],
        chat_access=config.chat_access if config else "dashboard",
        completed_at=config.completed_at if config else None,
        api_key_scope=scope,
    )


@router.get("/workflow", response_model=WorkflowConfig)
async def get_workflow_settings(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """The tenant's Plug & Play workflow choices. Admin only.

    A tenant that has never run the wizard has no row; this returns defaults and
    deliberately **does not create one** -- a GET must not have a side effect,
    and "has this tenant ever configured a workflow" is a real question the
    absence of a row answers (`completed_at` is null either way, but a row would
    also make the FE's "show the wizard" decision ambiguous).
    """
    _require_admin_for_workflow(context)

    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    config = db_session.exec(
        select(TenantWorkflowConfig).where(
            TenantWorkflowConfig.tenant_id == context.tenant_id
        )
    ).first()

    return _workflow_response(config, tenant)


@router.put("/workflow", response_model=WorkflowConfig)
async def update_workflow_settings(
    payload: WorkflowConfigUpdate,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Save the tenant's workflow choices. Admin only.

    Two things worth knowing before changing this:

    1. **`audit_policy` writes through to `Tenant.api_key_scope`** in the same
       commit. That column is what `dependencies.require_key_scope()` enforces;
       this endpoint is simply the supported way to set it. There is deliberately
       no second, independent policy field -- the wizard's answer and the thing
       the auth layer reads are one decision stored in one place, mirrored here
       only for wording.
    2. **Unbuilt output destinations are rejected, not stored.** See
       `_validate_destinations()`.

    Validation runs before any write, so a rejected request changes nothing --
    including `api_key_scope`.
    """
    _require_admin_for_workflow(context)

    tenant = db_session.get(Tenant, context.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    config = db_session.exec(
        select(TenantWorkflowConfig).where(
            TenantWorkflowConfig.tenant_id == context.tenant_id
        )
    ).first()

    # --- validate everything first; no partial writes -----------------------
    new_channels = (
        _validate_input_channels(payload.input_channels)
        if payload.input_channels is not None
        else (list(config.input_channels or []) if config else [])
    )
    new_destinations = (
        _validate_destinations(payload.output_destinations, db_session, context.tenant_id)
        if payload.output_destinations is not None
        else (list(config.output_destinations or []) if config else [])
    )

    if payload.audit_policy is not None:
        if payload.audit_policy not in AUDIT_POLICY_TO_KEY_SCOPE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Unknown audit_policy '{payload.audit_policy}'. Allowed: "
                    f"{AUDIT_POLICY_FULL_AUTOMATION}, {AUDIT_POLICY_STRICT_REVIEW}."
                ),
            )
        # Feature 25 (Gap 340): an unclaimed sandbox workspace is pinned to
        # `readonly` and cannot be widened here.
        #
        # This is already unreachable, and it is written anyway. A sandbox tenant
        # has NO `User` row by design (giving it one would let an anonymous
        # visitor squat a globally-unique email address), so nobody can hold a
        # Clerk session for it, so `get_tenant_context` cannot resolve one, so
        # `_require_admin_for_workflow()` above cannot pass. That is three
        # independent reasons this branch never fires today -- and all three are
        # properties of *other* code, any of which a later change could remove
        # without anyone connecting it to sandbox scope. The pin is stated where
        # the widening happens so it survives that.
        if payload.audit_policy == AUDIT_POLICY_FULL_AUTOMATION:
            sandbox = is_sandbox_tenant(db_session, context.tenant_id)
            if sandbox is not None and sandbox.claimed_at is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "A sandbox workspace is read-only and cannot be switched to "
                        "Full Automation. Claim this sandbox with a real account "
                        "first, then choose a workflow policy."
                    ),
                )
        new_policy = payload.audit_policy
    else:
        # Unchanged means "whatever is actually in force", not "whatever the row
        # last said" -- same derivation as the GET, for the same reason.
        new_policy = KEY_SCOPE_TO_AUDIT_POLICY.get(
            tenant.api_key_scope or KEY_SCOPE_READONLY, AUDIT_POLICY_STRICT_REVIEW
        )

    if payload.chat_access is not None:
        if payload.chat_access not in WORKFLOW_CHAT_ACCESS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Unknown chat_access '{payload.chat_access}'. Allowed: "
                    f"{', '.join(WORKFLOW_CHAT_ACCESS)}."
                ),
            )
        new_chat_access = payload.chat_access
    else:
        new_chat_access = config.chat_access if config else "dashboard"

    now = datetime.utcnow()

    # --- write ---------------------------------------------------------------
    if not config:
        config = TenantWorkflowConfig(tenant_id=context.tenant_id, created_at=now)

    config.input_channels = new_channels
    config.output_destinations = new_destinations
    config.audit_policy = new_policy
    config.chat_access = new_chat_access
    config.updated_at = now
    # Set once, on the first successful save, and never reset by a later edit --
    # it records that this tenant has been through onboarding, not when the row
    # last changed (updated_at is that).
    if config.completed_at is None:
        config.completed_at = now

    # THE write-through. Same commit as the row above, so the policy and the
    # thing that enforces it cannot end up half-applied.
    previous_scope = tenant.api_key_scope
    tenant.api_key_scope = AUDIT_POLICY_TO_KEY_SCOPE[new_policy]
    tenant.updated_at = now

    db_session.add(config)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(config)
    db_session.refresh(tenant)

    logger.info(
        "Workflow settings updated for tenant=%s by user=%s: policy=%s "
        "api_key_scope %s->%s channels=%s destinations=%s chat_access=%s",
        context.tenant_id, context.user_id, new_policy,
        previous_scope, tenant.api_key_scope,
        new_channels, new_destinations, new_chat_access,
    )

    return _workflow_response(config, tenant)


class ApiKeyIdentity(BaseModel):
    tenant_id: str
    tenant_name: str | None = None
    role: str
    billing_plan: str


@router.get("/security/api-key/verify", response_model=ApiKeyIdentity)
async def verify_api_key_endpoint(
    context: TenantContext = Depends(get_api_key_context),
):
    """
    Authenticated by the API key itself (`X-API-Key` or `Authorization: Bearer
    <key>`), not by a Clerk session -- this is the one route that exercises the
    programmatic auth path end to end, so an integrator can confirm a key works
    before wiring it into anything.

    It returns identity only (which tenant the key resolved to, and the role
    key-auth runs as), never tenant data: Gap 184 is about authentication, and
    widening what key-auth can *read* is a separate, deliberate decision.
    """
    return ApiKeyIdentity(
        tenant_id=str(context.tenant_id),
        tenant_name=context.tenant_name,
        role=context.role,
        billing_plan=context.billing_plan,
    )


# --- Feature 25 (Gap 341): embedded chat widget tokens ----------------------
#
# Admin-only management for a credential that is, by design, published: a widget
# token is pasted into the tenant's own website's client-side code. Three
# endpoints, all on the Clerk path -- no API key may manage these, for the same
# reason no API key may rotate the API key (`require_admin` is never satisfiable
# by a key, at any scope; Gap 335).
#
# Unlike `Tenant.api_key_*` there can be several of these per tenant, because a
# tenant may embed the widget on more than one site and revoking one of those
# must not break the others. That is exactly why they are their own table rather
# than a third credential jammed into the one-key-per-tenant columns.


class WidgetTokenSummary(BaseModel):
    """A widget token's metadata. Carries no field that could hold the token."""
    id: str
    label: str
    token_prefix: str
    masked_token: str | None = None
    allowed_origins: list[str] = []
    created_at: datetime | None = None
    last_used_at: datetime | None = None


class WidgetTokenCreateResponse(WidgetTokenSummary):
    """The one and only response that carries a raw widget token."""
    widget_token: str


class WidgetTokenCreateRequest(BaseModel):
    label: str = "Chat widget"
    # The domains the widget will be embedded on. This is a DEFENCE-IN-DEPTH
    # layer -- `Origin`/`Referer` is browser-set and unforgeable by page script,
    # but trivially set by anything that is not a browser. Leaving it empty
    # disables the layer rather than denying everything, so a token is usable
    # the moment it is issued; see services/widget_tokens.py::origin_is_allowed.
    allowed_origins: list[str] = []


def _widget_token_summary(token) -> WidgetTokenSummary:
    return WidgetTokenSummary(
        id=str(token.id),
        label=token.label,
        token_prefix=token.token_prefix,
        masked_token=masked_display(token.token_prefix),
        allowed_origins=list(token.allowed_origins or []),
        created_at=token.created_at,
        last_used_at=token.last_used_at,
    )


@router.get("/security/widget-tokens", response_model=list[WidgetTokenSummary])
async def list_widget_tokens(
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """This workspace's live widget tokens. Admin only.

    Admin-only on the GET as well as the writes -- the same call this router's
    workflow endpoints make, and for the same reason: `allowed_origins` is
    security configuration, and the list of live credentials is not something a
    Trainer needs.
    """
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage chat widget tokens.",
        )
    return [
        _widget_token_summary(t) for t in active_widget_tokens(db_session, context.tenant_id)
    ]


@router.post(
    "/security/widget-tokens",
    response_model=WidgetTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_widget_token(
    body: WidgetTokenCreateRequest,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Issue a chat widget token. Admin only. The raw value is shown once.

    Same shown-once contract as `rotate_api_key()` above: hashed on the way in
    (PBKDF2 + a fresh per-token salt), never stored in plaintext, never logged,
    unrecoverable afterwards. Losing it means issuing another and revoking this
    one -- which is cheap here precisely because a tenant may hold several.

    Read `services/widget_tokens.py`'s module docstring before changing anything
    about what this credential can reach. It is deliberately weaker than an API
    key because it ends up in a customer's public page source.
    """
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage chat widget tokens.",
        )

    existing = active_widget_tokens(db_session, context.tenant_id)
    if len(existing) >= MAX_TOKENS_PER_TENANT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This workspace already has {MAX_TOKENS_PER_TENANT} active chat "
                "widget tokens. Revoke one before issuing another."
            ),
        )

    for origin in body.allowed_origins:
        if normalize_origin(origin) is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"'{origin}' is not a usable website origin. Use the form "
                    "https://example.com (scheme and host, no path)."
                ),
            )

    token, raw = issue_widget_token(
        db_session,
        context.tenant_id,
        label=body.label,
        allowed_origins=body.allowed_origins,
    )
    logger.info(
        "Widget token issued for tenant=%s by user=%s (prefix=%s)",
        context.tenant_id, context.user_id, token.token_prefix,
    )
    summary = _widget_token_summary(token)
    return WidgetTokenCreateResponse(**summary.model_dump(), widget_token=raw)


@router.delete("/security/widget-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_widget_token(
    token_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Revoke a widget token. Admin only. Takes effect on the next request.

    The row is kept and stamped `revoked_at` rather than deleted, so a revoked
    prefix appearing in a log line afterwards is still explainable.
    `resolve_widget_token()` checks that column on every request, so there is no
    TTL to wait out -- which matters for a credential whose realistic
    revocation trigger is "we found it in a paste".
    """
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage chat widget tokens.",
        )

    token = revoke_widget_token(db_session, context.tenant_id, token_id)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat widget token not found.",
        )
