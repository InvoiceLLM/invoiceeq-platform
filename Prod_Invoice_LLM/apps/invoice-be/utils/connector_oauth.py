"""Shared OAuth plumbing for third-party connectors (Feature 9).

One shared, company-owned OAuth app per provider (not per-tenant) -- each
end-user connects their own Google Drive account through it. See
routers/connectors.py for the initial auth-url/callback flow that first
populates a TenantConnection row; this module covers what happens after --
keeping that connection's access token valid for as long as the refresh
token remains good, without asking the user to log in again.

Salesforce (`SALESFORCE_TOKEN_URL`, `generate_pkce_pair()`, and this
module's Salesforce credential/refresh arms) was removed 2026-08-28 -- see
Gap 334. Google Drive is now the only provider, but the per-provider shape
below is deliberately kept rather than collapsed to a single hardcoded
path, so adding a second provider stays a local change.
"""
import logging
from datetime import datetime, timedelta

import httpx
from sqlmodel import Session

from models import TenantConnection
from utils.encryption import encrypt_token, decrypt_token

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Google's OAuth2 token introspection endpoint. It reports the scopes actually
# granted to a token, which is the only way to tell an old readonly-only
# connection apart from a new read+write one -- see google_granted_scopes().
GOOGLE_TOKENINFO_URL = "https://www.googleapis.com/oauth2/v3/tokeninfo"

GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
# `drive.file`, NOT the bare `drive` scope. `drive` grants access to everything
# in the user's Drive; `drive.file` grants access only to files this app itself
# created (or that the user explicitly opened with this app), which is the
# minimum that "write our processed results into Drive" actually needs. The
# bare `drive` scope is still *accepted* below when detecting an existing
# grant -- it is a superset, so a token that carries it can write -- but this
# app never asks for it.
GOOGLE_DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_DRIVE_FULL_SCOPE = "https://www.googleapis.com/auth/drive"

# What a *new* connection asks for (Gap 338). Both, deliberately: drive.file
# cannot read the tenant's pre-existing invoice PDFs (Features 9/13's import
# and Autopilot sync), and drive.readonly cannot write. Space-separated is
# Google's format for a multi-scope request.
GOOGLE_DRIVE_OAUTH_SCOPE = f"{GOOGLE_DRIVE_READONLY_SCOPE} {GOOGLE_DRIVE_FILE_SCOPE}"

# Either of these on a token means it can create files.
GOOGLE_DRIVE_WRITE_SCOPES = frozenset({GOOGLE_DRIVE_FILE_SCOPE, GOOGLE_DRIVE_FULL_SCOPE})


def has_real_credentials(provider: str, settings) -> bool:
    """True once our company's real Client ID has been configured for a
    provider (vs. the shipped empty-string / placeholder default) -- lets
    dev/test keep working with the mock exchange for providers not yet set
    up, while a provider with a real app configured goes through real OAuth.
    """
    if provider == "google_drive":
        return bool(settings.GOOGLE_CLIENT_ID) and "placeholder" not in settings.GOOGLE_CLIENT_ID
    return False


def get_valid_access_token(connection: TenantConnection, settings, db_session: Session) -> str:
    """Returns a usable access token for this connection, transparently
    refreshing it via the stored refresh_token when expired -- this is what
    makes "connect once" actually mean "never ask again" instead of just
    being schema support with nothing wired to it.
    """
    if connection.token_expiry > datetime.utcnow():
        return decrypt_token(connection.encrypted_access_token)

    if not connection.encrypted_refresh_token:
        raise RuntimeError(
            f"Access token expired for provider '{connection.provider}' and no "
            "refresh token is stored; the user must reconnect."
        )

    refresh_token = decrypt_token(connection.encrypted_refresh_token)
    prov = connection.provider.lower()

    if prov == "google_drive":
        token_url = GOOGLE_TOKEN_URL
        payload = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    else:
        raise ValueError(f"Unknown connector provider '{connection.provider}'")

    response = httpx.post(token_url, data=payload, timeout=10.0)
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to refresh {prov} access token: {response.status_code} {response.text}"
        )

    token_data = response.json()
    new_access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", 3600)

    connection.encrypted_access_token = encrypt_token(new_access_token)
    connection.token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
    db_session.add(connection)
    db_session.commit()

    logger.info("Refreshed %s access token for tenant_id=%s", prov, connection.tenant_id)
    return new_access_token


def google_granted_scopes(access_token: str) -> set[str] | None:
    """The scopes Google says this access token actually carries.

    Gap 338. Scope is a property of the *grant*, not of what we asked for
    today: every connection minted before 2026-08-30 consented to
    `drive.readonly` alone, and Google does not silently widen an existing
    grant when the app starts requesting more -- the user has to consent
    again. The token itself is the only honest source for what it may do, and
    this endpoint is how the token is asked.

    Three outcomes, kept distinct on purpose:

    * a `set` -- Google answered; this is exactly what was granted.
    * an **empty set** on HTTP 400, Google's answer for a token that is invalid,
      expired or revoked. That token cannot write (it cannot do anything), so
      an empty set is the truthful answer rather than a special case.
    * `None` -- we could not reach Google or it answered unexpectedly, i.e.
      *unknown*. Callers must not read `None` as "no write scope"; blocking a
      tenant because a Google endpoint blipped would be a worse failure than
      attempting an upload that then fails with a clear API error.
    """
    try:
        response = httpx.get(
            GOOGLE_TOKENINFO_URL, params={"access_token": access_token}, timeout=10.0
        )
    except httpx.HTTPError as e:
        logger.warning("Google tokeninfo request failed: %s", e)
        return None

    if response.status_code == 400:
        # Google's documented response for an invalid/expired/revoked token.
        logger.info("Google tokeninfo reports the access token is not valid.")
        return set()
    if response.status_code != 200:
        logger.warning(
            "Google tokeninfo returned %s: %s", response.status_code, response.text[:200]
        )
        return None

    try:
        scope_value = response.json().get("scope") or ""
    except ValueError:
        logger.warning("Google tokeninfo returned a non-JSON body.")
        return None
    return {s for s in scope_value.split(" ") if s}


def token_has_drive_write_scope(access_token: str) -> bool | None:
    """True/False when Google answered, `None` when it could not be determined.

    `None` is deliberately not folded into `False`: "this token definitely
    cannot write" and "we could not ask" lead to different behaviour at the
    call site (a hard reconnect-required state vs. attempting the write
    anyway). See services/workflow_outputs.py::drive_archive_readiness().
    """
    scopes = google_granted_scopes(access_token)
    if scopes is None:
        return None
    return bool(scopes & GOOGLE_DRIVE_WRITE_SCOPES)
