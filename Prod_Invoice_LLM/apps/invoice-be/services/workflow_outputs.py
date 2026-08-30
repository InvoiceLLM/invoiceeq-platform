"""Feature 25 (Gaps 339/338): delivery for `TenantWorkflowConfig.output_destinations`.

Gap 336 built the column and deliberately made it inert — a tenant could *choose*
a destination and nothing read the choice, which is why the two undelivered
values were rejected with a 422 rather than stored. This module is the first
thing that actually reads `output_destinations` and does something with it.

Today it implements exactly one destination, `email_summary`: when an invoice is
approved (reaches PAID via `routers/audit.py::resolve_audit_invoice`), the
tenant's registered addresses receive a short human summary with the invoice's
extracted fields attached as a CSV and a JSON.

**Recipients are pre-registered, never free text — this is the load-bearing
decision here.** The addresses come from `TenantEmailSender`, the same allowlist
`routers/email_ingestion.py` uses to decide whether an *inbound* mail may become
an invoice and that `services/staff_notify.py` validates its notify lists
against. The alternative — letting the Settings wizard collect an arbitrary
address — would have turned a workflow setting into an unauthenticated
"send mail to anyone, from our domain, on a schedule we control" primitive, i.e.
reopened precisely the outbound-spam control those two modules exist to enforce.
There is intentionally no way to add a summary recipient here that is not
already an authorized sender for the tenant.

`webhook` and `dashboard_only`, the other two accepted destinations, need
nothing from this module: webhooks are dispatched by `services/webhooks.py` off
subscriptions (already wired into the same resolve handler), and
`dashboard_only` means "no delivery" by construction.

**Gap 338 (2026-08-30) added the second destination, `drive_archive`**, in this
same file and on the same contract — read from the same column, fired from the
same single point in `routers/audit.py::resolve_audit_invoice()`, never raising,
returning the same `{"…": bool, …}` shape. It writes the *same* CSV and JSON
`services/invoice_export.py` builds for the email summary, plus the invoice's
original source PDF, into the tenant's connected Google Drive.

Its one genuinely new problem is **scope**: the Drive connection Feature 9 built
asks for `drive.readonly`, and reading is not writing. New connections now ask
for `drive.file` as well, but Google does not widen an existing grant when an
app starts asking for more — every tenant connected before 2026-08-30 holds a
read-only token that will refuse to create a file. `drive_archive_readiness()`
is the detector for that state, and it is deliberately *lazy*: it runs when the
tenant selects the destination and again when a write is attempted, so an
already-connected tenant is told to reconnect at the moment it matters instead
of being dragged through a forced re-auth for a feature it may never use.
"""
from __future__ import annotations

import logging

import httpx
from sqlmodel import Session, select

from config import get_settings
from models import Invoice, TenantConnection, TenantWorkflowConfig
from services.invoice_export import (
    build_invoice_csv,
    build_invoice_json,
    export_filenames,
    export_pdf_filename,
)
from services.outbound_email import EmailAttachment, send_email, sendgrid_configured
from services.staff_notify import email_set_for_invoice, list_registered_emails
from services.storage import download_pdf_from_storage
from utils.connector_files import (
    find_or_create_google_drive_folder,
    upload_google_drive_file,
)
from utils.connector_oauth import (
    get_valid_access_token,
    has_real_credentials,
    token_has_drive_write_scope,
)

logger = logging.getLogger(__name__)

OUTPUT_DESTINATION_EMAIL_SUMMARY = "email_summary"
OUTPUT_DESTINATION_DRIVE_ARCHIVE = "drive_archive"

CSV_MIME_TYPE = "text/csv"
JSON_MIME_TYPE = "application/json"
PDF_MIME_TYPE = "application/pdf"

# The one provider `drive_archive` writes to. Named rather than inlined because
# `TenantConnection.provider` is a free-text column and this string has to match
# routers/connectors.py's exactly.
DRIVE_PROVIDER = "google_drive"

# The app-owned folder every archived invoice lands in. It is created by this
# app on first use rather than chosen by the tenant, and that is a direct
# consequence of asking for the narrow `drive.file` scope instead of full
# `drive` access -- see utils/connector_files.py
# ::find_or_create_google_drive_folder() for the full reasoning.
DRIVE_ARCHIVE_FOLDER_NAME = "InvoiceEQ Archive"

# Readiness codes. These are returned to the caller (and end up in the resolve
# endpoint's JSON), so they are part of the contract an integration reads --
# "why did nothing get archived" has to be answerable without reading logs.
DRIVE_OK = "ok"
DRIVE_NOT_CONNECTED = "not_connected"
DRIVE_RECONNECT_REQUIRED = "reconnect_required"
DRIVE_TOKEN_UNUSABLE = "token_unusable"
DRIVE_SCOPE_UNKNOWN = "scope_unknown"
DRIVE_OAUTH_NOT_CONFIGURED = "oauth_not_configured"

RECONNECT_INSTRUCTION = (
    "Reconnect Google Drive under Settings -> Connectors and approve the "
    "access request; the existing connection was authorized for read-only "
    "access, which cannot write files back."
)


def tenant_output_destinations(db_session: Session, tenant_id) -> list[str]:
    """The tenant's stored destinations, or `[]` if it never ran the wizard.

    No row is the normal state for most tenants (the GET endpoint deliberately
    does not create one), so absence has to be an empty list, not an error.
    """
    config = db_session.exec(
        select(TenantWorkflowConfig).where(TenantWorkflowConfig.tenant_id == tenant_id)
    ).first()
    if not config:
        return []
    destinations = config.output_destinations or []
    if not isinstance(destinations, list):
        return []
    return [str(d) for d in destinations]


def email_summary_enabled(db_session: Session, tenant_id) -> bool:
    return OUTPUT_DESTINATION_EMAIL_SUMMARY in tenant_output_destinations(db_session, tenant_id)


def email_summary_recipients(db_session: Session, invoice: Invoice) -> list[str]:
    """The pre-registered addresses this invoice's summary goes to.

    Keyed on the invoice's own direction via `email_set_for_invoice()` — the
    same rule `services/staff_notify.py` applies — so an OUTBOUND invoice's
    summary can never land in the inbound AP set and vice versa. In practice
    everything reaching this module today is INBOUND (it fires from the inbound
    audit router), but keying it on the invoice rather than hardcoding
    `"inbound"` is what keeps that true if the trigger is ever widened.
    """
    return list_registered_emails(db_session, invoice.tenant_id, email_set_for_invoice(invoice))


def _summary_body(invoice: Invoice) -> str:
    """Short, human-readable: vendor, amount, invoice #, status — plus the two
    attachments for anything more detailed. Plain text only, matching every
    other notifier in this codebase (`services/staff_notify.py` sends no HTML
    part either); a second HTML template would be a second thing to keep
    truthful for no stated benefit."""
    inv_ref = invoice.invoice_number or str(invoice.id)
    party = (
        invoice.customer_name
        if email_set_for_invoice(invoice) == "outbound"
        else invoice.vendor_name
    ) or "unknown"
    currency = (invoice.currency or "").strip()
    amount = "unknown" if invoice.grand_total is None else f"{currency} {invoice.grand_total}".strip()

    lines = [
        f"Invoice {inv_ref} has been approved.",
        "",
        f"Vendor:       {party}",
        f"Invoice #:    {inv_ref}",
        f"Amount:       {amount}",
        f"Status:       {invoice.status}",
    ]
    if invoice.invoice_date:
        lines.append(f"Invoice date: {invoice.invoice_date.isoformat()}")
    lines += [
        "",
        "The full extracted data is attached twice — a CSV (one row per line "
        "item) and a JSON, so it can be read by a person or by a machine "
        "without either having to reformat the other's copy.",
        "",
        "This summary was sent because your workspace selected the "
        "'email_summary' output destination in Settings → Workflow. It goes "
        "only to addresses already registered in this workspace's authorized "
        "email set — never to customers.",
    ]
    return "\n".join(lines) + "\n"


def deliver_email_summary(db_session: Session, invoice: Invoice) -> dict | None:
    """Send the approved-invoice summary, if this tenant asked for one.

    Returns `None` when the destination is not selected — the overwhelmingly
    common case, and not a failure. Otherwise returns a `{"sent": bool, ...}`
    dict in the same shape `services/staff_notify.py`'s notifiers return, so the
    resolve endpoint can surface the outcome without a second convention.

    **Never raises.** This runs after the invoice's status transition has
    already committed; a mail problem must not turn a successful approval into a
    500 for the caller, and must not be able to roll anything back. Every
    failure mode below is logged and returned, not raised.
    """
    try:
        if not email_summary_enabled(db_session, invoice.tenant_id):
            return None

        recipients = email_summary_recipients(db_session, invoice)
        if not recipients:
            # This state should be unreachable: `PUT /settings/workflow`
            # refuses to store `email_summary` for a tenant with no registered
            # sender (routers/settings.py::_validate_destinations), and Gap 342
            # seeds one at provisioning. It is still handled rather than
            # asserted, because the allowlist can be emptied *after* the
            # destination was saved — deleting the last sender row is a
            # perfectly ordinary thing for an Admin to do, and it must not
            # start 500-ing every approval.
            logger.warning(
                "Gap 339: tenant %s selected email_summary but has no registered "
                "%s sender — nothing sent for invoice %s. Add an address in "
                "Settings → Email, or remove the destination.",
                invoice.tenant_id, email_set_for_invoice(invoice), invoice.id,
            )
            return {"sent": False, "error": "No registered email sender for this workspace."}

        if not sendgrid_configured():
            logger.info(
                "Gap 339: skipping email summary for invoice %s — SENDGRID_API_KEY not set",
                invoice.id,
            )
            return {
                "sent": False,
                "error": "SENDGRID_API_KEY is not configured.",
                "to": recipients,
            }

        csv_name, json_name = export_filenames(invoice)
        attachments = [
            EmailAttachment(csv_name, build_invoice_csv(invoice).encode("utf-8"), CSV_MIME_TYPE),
            EmailAttachment(json_name, build_invoice_json(invoice).encode("utf-8"), JSON_MIME_TYPE),
        ]

        inv_ref = invoice.invoice_number or str(invoice.id)
        result = send_email(
            to_addresses=recipients,
            subject=f"[InvoiceEQ] Approved — {inv_ref}",
            plain_body=_summary_body(invoice),
            attachments=attachments,
        )
        return {"sent": True, "attachments": [csv_name, json_name], **result}
    except Exception as e:  # noqa: BLE001 - see docstring: this must never raise
        logger.error("Gap 339: email summary failed for invoice %s: %s", getattr(invoice, "id", None), e)
        return {"sent": False, "error": str(e)}


# ===========================================================================
# Gap 338 -- the `drive_archive` output destination
# ===========================================================================


def drive_archive_enabled(db_session: Session, tenant_id) -> bool:
    return OUTPUT_DESTINATION_DRIVE_ARCHIVE in tenant_output_destinations(db_session, tenant_id)


def tenant_drive_connection(db_session: Session, tenant_id) -> TenantConnection | None:
    """The tenant's active Google Drive connection row, or None.

    `status != "active"` counts as no connection: that is the same test
    `routers/connectors.py`'s list/import endpoints apply, and a disconnected
    row must not read as a usable destination.
    """
    connection = db_session.exec(
        select(TenantConnection).where(
            TenantConnection.tenant_id == tenant_id,
            TenantConnection.provider == DRIVE_PROVIDER,
        )
    ).first()
    if not connection or connection.status != "active":
        return None
    return connection


def drive_archive_readiness(db_session: Session, tenant_id) -> dict:
    """Can this tenant's Drive connection actually receive a file right now?

    **This is the re-consent detector, and it is the reason this gap is a
    migration and not just a feature.** Feature 9's OAuth flow requested
    `drive.readonly`. Gap 338 changed that request to
    `drive.readonly + drive.file`, but a scope is a property of the *grant*: an
    access (or refresh) token minted under the old consent screen keeps exactly
    the scopes the user approved then, forever, and Google will never widen it
    silently. So "the tenant has a connected Drive" and "we may write to it"
    are two different questions, and every tenant connected before 2026-08-30
    answers yes to the first and no to the second.

    Rather than force a re-auth on everyone (most tenants will never turn this
    destination on), the check runs **lazily** at the two moments it matters:
    when `PUT /settings/workflow` is asked to store `drive_archive`, and again
    before each write. Both surface `reconnect_required` with an instruction,
    instead of an opaque 403 from Google arriving inside an approval.

    Returns `{"ready", "code", "detail", "access_token"}`. `ready` answers "may
    this destination be selected / is it worth attempting a write", which is
    **not** the same as `code == "ok"`:

    * `not_connected` / `token_unusable` / `reconnect_required` -> ready False.
      A definite no, each with a different fix.
    * `oauth_not_configured` -> ready False. This deployment has no Google OAuth
      app at all (`has_real_credentials()` is false and the stored tokens are
      the mock exchange's), so nothing can be written by anyone.
    * `scope_unknown` -> **ready True.** Google's tokeninfo endpoint could not
      be reached, so the grant is undetermined. Refusing on an indeterminate
      answer would let a blip on Google's side block a tenant's configuration;
      the write is attempted and a real 403 is translated back into
      `reconnect_required` by `deliver_drive_archive()`. Fail-open here,
      fail-loud there.
    """
    connection = tenant_drive_connection(db_session, tenant_id)
    if connection is None:
        return {
            "ready": False,
            "code": DRIVE_NOT_CONNECTED,
            "detail": (
                "Google Drive is not connected for this workspace. Connect it "
                "under Settings -> Connectors first."
            ),
            "access_token": None,
        }

    settings = get_settings()
    if not has_real_credentials(DRIVE_PROVIDER, settings):
        # The connector is running its mock exchange, so the stored token is a
        # `mock_access_token_...` string. Probing or uploading with it would
        # produce a confusing 401 from Google; say what is actually wrong.
        return {
            "ready": False,
            "code": DRIVE_OAUTH_NOT_CONFIGURED,
            "detail": (
                "This deployment has no Google OAuth application configured, "
                "so nothing can be written to Drive."
            ),
            "access_token": None,
        }

    try:
        access_token = get_valid_access_token(connection, settings, db_session)
    except Exception as e:  # noqa: BLE001 - refresh failure is a user-visible state
        # get_valid_access_token() raises RuntimeError for the two conditions
        # that mean "reconnect": no refresh token stored, and a refresh the
        # provider rejected (revoked/expired). Anything else (a network error
        # on the refresh POST) lands here too and is equally un-writable now.
        return {
            "ready": False,
            "code": DRIVE_TOKEN_UNUSABLE,
            "detail": f"Google Drive connection needs to be reconnected: {e}",
            "access_token": None,
        }

    has_write = token_has_drive_write_scope(access_token)
    if has_write is False:
        return {
            "ready": False,
            "code": DRIVE_RECONNECT_REQUIRED,
            "detail": (
                "The connected Google Drive account granted read-only access. "
                + RECONNECT_INSTRUCTION
            ),
            "access_token": access_token,
        }
    if has_write is None:
        return {
            "ready": True,
            "code": DRIVE_SCOPE_UNKNOWN,
            "detail": (
                "Could not confirm the Google Drive permissions on this "
                "connection; the write will be attempted."
            ),
            "access_token": access_token,
        }
    return {"ready": True, "code": DRIVE_OK, "detail": "", "access_token": access_token}


def _invoice_source_pdf(invoice: Invoice) -> tuple[str, bytes] | None:
    """The invoice's original PDF, or None if it could not be fetched.

    A missing blob must not cost the tenant the CSV and the JSON as well, so
    this failure is isolated from the rest of the archive rather than aborting
    it — an archive with two of three files and a logged reason is strictly
    better than no archive.
    """
    if not invoice.file_path:
        return None
    try:
        return export_pdf_filename(invoice), download_pdf_from_storage(invoice.file_path)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Gap 338: could not read the source PDF for invoice %s (%s): %s",
            invoice.id, invoice.file_path, e,
        )
        return None


def deliver_drive_archive(db_session: Session, invoice: Invoice) -> dict | None:
    """Write this invoice's results into the tenant's connected Google Drive.

    Returns `None` when the destination is not selected — the common case, not
    a failure. Otherwise a `{"uploaded": bool, "code": str, …}` dict, mirroring
    `deliver_email_summary()`'s shape so the resolve endpoint reports both
    destinations the same way.

    **Never raises**, for the same reason as the email summary: this runs after
    the invoice's status transition has already committed, and a Drive outage,
    a revoked token or an inadequate scope must not turn a successful approval
    into a 500 or roll anything back. Every failure below is logged and
    returned.

    Three files, all named off the same sanitised stem: the CSV and the JSON
    that `services/invoice_export.py` builds (the *same* builders the email
    summary uses — there is deliberately no second serialiser), and the
    original source PDF.
    """
    try:
        if not drive_archive_enabled(db_session, invoice.tenant_id):
            return None

        readiness = drive_archive_readiness(db_session, invoice.tenant_id)
        if not readiness["ready"]:
            # Reachable even though `PUT /settings/workflow` refuses to store
            # this destination without a write-scoped connection: the tenant
            # can disconnect Drive, or revoke the grant on Google's side, at
            # any time after saving. Same defensive posture Gap 339 takes when
            # the last email sender is deleted after the fact.
            logger.warning(
                "Gap 338: tenant %s selected drive_archive but the connection is "
                "not usable (%s) — nothing archived for invoice %s. %s",
                invoice.tenant_id, readiness["code"], invoice.id, readiness["detail"],
            )
            return {
                "uploaded": False,
                "code": readiness["code"],
                "error": readiness["detail"],
            }

        access_token = readiness["access_token"]
        folder_id = find_or_create_google_drive_folder(
            access_token, DRIVE_ARCHIVE_FOLDER_NAME
        )

        csv_name, json_name = export_filenames(invoice)
        payloads: list[tuple[str, bytes, str]] = [
            (csv_name, build_invoice_csv(invoice).encode("utf-8"), CSV_MIME_TYPE),
            (json_name, build_invoice_json(invoice).encode("utf-8"), JSON_MIME_TYPE),
        ]
        source_pdf = _invoice_source_pdf(invoice)
        if source_pdf is not None:
            payloads.append((source_pdf[0], source_pdf[1], PDF_MIME_TYPE))

        uploaded: list[str] = []
        for filename, content, mime_type in payloads:
            upload_google_drive_file(access_token, folder_id, filename, content, mime_type)
            uploaded.append(filename)

        return {
            "uploaded": True,
            "code": readiness["code"],
            "folder": DRIVE_ARCHIVE_FOLDER_NAME,
            "folder_id": folder_id,
            "files": uploaded,
            # True only when all three landed; a missing source PDF is reported
            # rather than hidden behind an otherwise-successful archive.
            "source_pdf_included": source_pdf is not None,
        }
    except httpx.HTTPStatusError as e:
        # The other half of the re-consent story. If tokeninfo was unreachable
        # (`scope_unknown`, fail-open above) and the grant really was read-only,
        # Drive answers the create with 403 insufficientPermissions — and a
        # revoked grant answers 401. Both are the same actionable state as a
        # detected read-only scope, so they are reported with the same code
        # rather than as a raw HTTP error the tenant cannot act on.
        code = e.response.status_code if e.response is not None else None
        if code in (401, 403):
            logger.warning(
                "Gap 338: Drive rejected the write for invoice %s with %s — "
                "treating as reconnect-required for tenant %s",
                invoice.id, code, invoice.tenant_id,
            )
            return {
                "uploaded": False,
                "code": DRIVE_RECONNECT_REQUIRED,
                "error": (
                    f"Google Drive refused the upload ({code}). "
                    + RECONNECT_INSTRUCTION
                ),
            }
        logger.error("Gap 338: Drive archive failed for invoice %s: %s", invoice.id, e)
        return {"uploaded": False, "code": "http_error", "error": str(e)}
    except Exception as e:  # noqa: BLE001 - see docstring: this must never raise
        logger.error(
            "Gap 338: Drive archive failed for invoice %s: %s",
            getattr(invoice, "id", None), e,
        )
        return {"uploaded": False, "code": "error", "error": str(e)}
