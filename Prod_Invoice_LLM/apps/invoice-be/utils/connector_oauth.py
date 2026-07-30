"""Shared OAuth plumbing for third-party connectors (Feature 9).

One shared, company-owned OAuth app per provider (not per-tenant) -- each
end-user connects their own Drive/Salesforce account through it. See
routers/connectors.py for the initial auth-url/callback flow that first
populates a TenantConnection row; this module covers what happens after --
keeping that connection's access token valid for as long as the refresh
token remains good, without asking the user to log in again.
"""
import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta

import httpx
from sqlmodel import Session

from models import TenantConnection
from utils.encryption import encrypt_token, decrypt_token

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
SALESFORCE_TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"


def generate_pkce_pair() -> tuple[str, str]:
    """Generates a PKCE code_verifier/code_challenge pair (RFC 7636, S256).

    Salesforce Connected Apps can require PKCE on the authorization code
    flow (some orgs enforce it by default) -- this is only ever needed for
    the initial auth-url/callback exchange, never for a refresh_token grant.
    """
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode("ascii")
    challenge_bytes = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def has_real_credentials(provider: str, settings) -> bool:
    """True once our company's real Client ID has been configured for a
    provider (vs. the shipped empty-string / placeholder default) -- lets
    dev/test keep working with the mock exchange for providers not yet set
    up, while a provider with a real app configured goes through real OAuth.
    """
    if provider == "google_drive":
        return bool(settings.GOOGLE_CLIENT_ID) and "placeholder" not in settings.GOOGLE_CLIENT_ID
    if provider == "salesforce":
        return bool(settings.SALESFORCE_CLIENT_ID) and "placeholder" not in settings.SALESFORCE_CLIENT_ID
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
    elif prov == "salesforce":
        token_url = SALESFORCE_TOKEN_URL
        payload = {
            "client_id": settings.SALESFORCE_CLIENT_ID,
            "client_secret": settings.SALESFORCE_CLIENT_SECRET,
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
    # Salesforce returns instance_url on every token response (including
    # refresh) since its API base is per-org; keep it current in case it
    # ever changes. Google never returns this key, so it's a no-op there.
    if token_data.get("instance_url"):
        connection.instance_url = token_data["instance_url"]
    db_session.add(connection)
    db_session.commit()

    logger.info("Refreshed %s access token for tenant_id=%s", prov, connection.tenant_id)
    return new_access_token
