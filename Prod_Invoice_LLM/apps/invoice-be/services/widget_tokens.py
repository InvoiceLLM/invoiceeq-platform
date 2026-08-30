"""
Feature 25 (Gap 341): issuing, verifying and revoking embedded chat widget tokens.

WHAT A WIDGET TOKEN IS, AND WHAT IT DELIBERATELY IS NOT
-------------------------------------------------------
It is a chat-only credential a tenant pastes into **their own website's
client-side code**, so their visitors can ask the assistant a question without
signing in to this product. It is therefore visible in page source to anybody
who opens dev tools, and every design decision here follows from that one fact:

* It does **not** live in `Tenant.api_key_hash` / `api_key_salt` /
  `api_key_prefix`. Those columns are one-key-per-tenant by design
  (`services/api_keys.py`'s module docstring), and putting a third credential
  type through them would mean every reader of those columns has to ask "which
  kind of credential is this" -- a question that only has to be got wrong once.
  Widget tokens get their own table, and a tenant may hold several.
* It does **not** resolve to a `TenantContext`. It resolves to
  `dependencies.WidgetContext`, which has no role, no scope and no permission
  booleans, so the codebase's permission gates structurally cannot be satisfied
  by it. See that class's docstring.
* Its dependency is mounted on **one** route -- the widget chat send -- and
  nowhere else.

Storage is identical to Gap 184's API keys and reuses that module's primitives
verbatim: PBKDF2-HMAC-SHA256 over the raw token with a fresh per-token salt,
`hmac.compare_digest` verification, and the raw value transmitted exactly once
by the response that created it. Nothing here re-implements hashing.

ORIGIN PINNING IS ONE LAYER. IT IS NOT THE CONTROL.
---------------------------------------------------
`origin_is_allowed()` checks the request's `Origin`/`Referer` against the
token's registered list. That raises the cost of casually reusing a scraped
token from another page, and it is worth having. It is also **trivially
bypassable outside a real browser** -- `curl -H 'Origin: https://acme.com'` is
the entire attack -- so it is a defence-in-depth layer stacked on top of the
structural containment above, never a substitute for it. Nothing in this module,
its callers, or the product documentation may describe it as a guarantee.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlmodel import Session, select

from models import WidgetToken
from services.api_keys import (
    generate_salt,
    generate_widget_token,
    hash_api_key,
    key_prefix,
    verify_api_key,
)

logger = logging.getLogger(__name__)

# How many tokens one tenant may hold at once. Not a security boundary -- an
# Admin issuing them is already authenticated -- but an unbounded list is a
# list nobody prunes, and each row is a live credential.
MAX_TOKENS_PER_TENANT = 10


# A syntactically usable `host[:port]`. Deliberately strict: `urlsplit()` alone
# happily returns a netloc of "not a url at all" for that input, which would
# then be stored as an allowed origin that no browser can ever send -- i.e. a
# token silently pinned to nothing, discovered as a 403 by the customer's
# visitors. Letters, digits, dots and hyphens, with an optional numeric port.
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?(:\d{1,5})?$")


def normalize_origin(value: str | None) -> str | None:
    """Reduce a URL or Origin header to bare `scheme://host[:port]`, lowercased.

    Both sides of the comparison go through this, so an Admin registering
    `https://Acme.com/chat` and a browser sending `https://acme.com` match. The
    path is discarded because an `Origin` header never carries one -- keeping it
    would mean a registered value copied out of a browser address bar could
    never match anything.

    Returns None for anything that is not a usable origin, which is what the
    Settings endpoint 422s on. Only `http` and `https` are accepted: an `Origin`
    header can carry other schemes (`file:`, an extension scheme) and none of
    them describe a website a tenant can meaningfully register.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if "//" not in raw:
        # Bare host ("acme.com") -- assume https, which is the only scheme a
        # widget on a real site should be served over anyway.
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    if not parts.netloc or not _HOST_RE.match(parts.netloc):
        return None
    return f"{scheme}://{parts.netloc.lower()}"


def origin_is_allowed(token: WidgetToken, origin: str | None) -> bool:
    """Defence-in-depth only -- see the module docstring before relying on this.

    An empty `allowed_origins` list means the layer is not applied for this
    token (an Admin who registered no origins gets no origin check), which is a
    deliberate opt-in rather than a default-deny: defaulting to deny with an
    empty list would make every freshly issued token dead on arrival, and the
    fix a support ticket rather than a setting.
    """
    allowed = [normalize_origin(o) for o in (token.allowed_origins or [])]
    allowed = [o for o in allowed if o]
    if not allowed:
        return True
    return normalize_origin(origin) in allowed


def issue_widget_token(
    db_session: Session,
    tenant_id: UUID,
    label: str = "Chat widget",
    allowed_origins: list[str] | None = None,
) -> tuple[WidgetToken, str]:
    """Mint a token for `tenant_id`. Returns `(row, raw_token)`.

    The raw token is the only moment the value exists outside the caller's
    memory -- same shown-once contract as `ApiKeyRotateResponse` and
    `WebhookSubscription.secret`. It is hashed on the way in and never logged;
    the log line below records the non-secret prefix only.
    """
    raw = generate_widget_token()
    salt = generate_salt()

    normalized: list[str] = []
    for origin in allowed_origins or []:
        cleaned = normalize_origin(origin)
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)

    token = WidgetToken(
        id=uuid4(),
        tenant_id=tenant_id,
        token_hash=hash_api_key(raw, salt),
        token_salt=salt,
        token_prefix=key_prefix(raw),
        label=(label or "Chat widget").strip()[:100] or "Chat widget",
        allowed_origins=normalized,
        created_at=datetime.utcnow(),
    )
    db_session.add(token)
    db_session.commit()
    db_session.refresh(token)

    logger.info(
        "widget token issued for tenant=%s (prefix=%s, origins=%s)",
        tenant_id, token.token_prefix, normalized or "none registered",
    )
    return token, raw


def active_widget_tokens(db_session: Session, tenant_id: UUID) -> list[WidgetToken]:
    """This tenant's un-revoked tokens, newest first."""
    rows = db_session.exec(
        select(WidgetToken).where(
            WidgetToken.tenant_id == tenant_id,
            WidgetToken.revoked_at.is_(None),  # type: ignore[union-attr]
        )
    ).all()
    return sorted(rows, key=lambda t: t.created_at or datetime.min, reverse=True)


def revoke_widget_token(
    db_session: Session, tenant_id: UUID, token_id: UUID
) -> WidgetToken | None:
    """Revoke one of this tenant's tokens. Returns None if it is not theirs.

    The row is kept, not deleted: a revoked token that turns up in a log line
    should still be explainable, and `resolve_widget_token()` checks
    `revoked_at` on every request, so revocation takes effect immediately rather
    than at some TTL boundary.
    """
    token = db_session.exec(
        select(WidgetToken).where(
            WidgetToken.id == token_id,
            WidgetToken.tenant_id == tenant_id,
        )
    ).first()
    if token is None:
        return None
    if token.revoked_at is None:
        token.revoked_at = datetime.utcnow()
        db_session.add(token)
        db_session.commit()
        db_session.refresh(token)
        logger.info(
            "widget token revoked for tenant=%s (prefix=%s)", tenant_id, token.token_prefix
        )
    return token


def resolve_widget_token(db_session: Session, raw_token: str) -> WidgetToken | None:
    """Verify a raw widget token, or return None.

    Same shape as `dependencies.resolve_api_key_context()`'s lookup: find the
    single candidate by the indexed non-secret prefix, then decide with a
    constant-time digest comparison. A wrong token, an unknown prefix and a
    revoked token are all the same None -- the caller turns all three into one
    401, because telling an anonymous visitor which of the three it was is free
    reconnaissance.
    """
    if not raw_token:
        return None

    token = db_session.exec(
        select(WidgetToken).where(WidgetToken.token_prefix == key_prefix(raw_token))
    ).first()
    if token is None or token.revoked_at is not None:
        return None
    if not verify_api_key(raw_token, token.token_salt, token.token_hash):
        return None

    token.last_used_at = datetime.utcnow()
    db_session.add(token)
    db_session.commit()
    db_session.refresh(token)
    return token
