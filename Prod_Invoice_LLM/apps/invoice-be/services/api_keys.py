"""
Gap 184: issuing, hashing and verifying a tenant's programmatic API key.

The rules this module exists to enforce, in one place rather than at each call
site:

* The raw key is generated server-side only (never accepted from a client) and
  is returned by exactly one response -- the rotate call that created it. It is
  not recoverable afterwards, by us or by anyone with the database.
* Storage is a PBKDF2-HMAC-SHA256 digest over the raw key with a fresh 16-byte
  random salt per issuance, so two tenants who somehow ended up with the same
  key would still not share a digest, and a stolen database dump is not a set
  of usable credentials.
* Comparison is `hmac.compare_digest`, not `==`, so verification time does not
  depend on how many leading bytes of the digest an attacker guessed right.
* Rotation overwrites hash *and* salt *and* prefix together. There is one key
  per tenant by design (this is not a key-management product), so writing the
  new triple is what invalidates the old key -- there is nothing left to verify
  the previous digest against.

Only `cryptography`/`hashlib` primitives from the stdlib are used; no new
dependency is added for this.
"""
import hashlib
import hmac
import secrets

# Everything the platform issues carries this prefix, so a leaked key is
# recognisable as ours in a log or a paste. `inv_live_` is the literal the
# frontend Security page has always displayed (as a hardcoded fake); keeping it
# means the shape users have seen is now the shape they actually get.
API_KEY_PREFIX = "inv_live_"

# Feature 25 (Gap 340): a sandbox key, issued to an anonymous website visitor
# with no login, resolving to a throwaway-but-real Tenant row. Same hashing,
# same storage columns, same one-key-per-tenant rule -- what differs is the
# tenant behind it (see services/sandbox.py), not the credential format. The
# distinct prefix is what makes a sandbox key recognisable as such in a log, a
# paste, or a support conversation without looking anything up.
SANDBOX_KEY_PREFIX = "inv_test_"

# Feature 25 (Gap 341): a chat-only widget token. This is deliberately NOT an
# API key and must never resolve to a TenantContext -- it is meant to be pasted
# into a customer's own website's client-side code, i.e. it is visible in page
# source to anybody who opens dev tools, so it cannot carry the trust level of
# a real key. It lives in its own table (`widget_tokens`), resolves to its own
# narrow `WidgetContext`, and reaches exactly one route. See
# services/widget_tokens.py.
WIDGET_TOKEN_PREFIX = "inv_widget_"

# Every prefix this platform mints. Used only to answer "is this bearer value
# one of ours rather than a Clerk session JWT" -- see
# looks_like_platform_credential(). Keeping it as one tuple is what stops a new
# credential type silently falling through to the Clerk verifier and 401ing
# with an unrelated message about token signatures.
PLATFORM_CREDENTIAL_PREFIXES = (
    API_KEY_PREFIX,
    SANDBOX_KEY_PREFIX,
    WIDGET_TOKEN_PREFIX,
)

# 32 URL-safe bytes -> ~43 characters of entropy after the prefix.
_SECRET_BYTES = 32

# Number of characters of the *secret* portion of a raw key that are safe to
# persist and display. 6 leaves ~37 characters unknown, which is not a
# meaningful reduction in brute-force cost, while still letting an Admin tell
# two credentials apart in the UI.
_DISPLAY_SECRET_CHARS = 6

# Retained for the `inv_live_` case so the stored prefix length is byte-identical
# to what Gap 184 has always written: 9 ("inv_live_") + 6 = 15.
_DISPLAY_PREFIX_LEN = len(API_KEY_PREFIX) + _DISPLAY_SECRET_CHARS

# PBKDF2 iteration count. Deliberately lower than a password KDF's: an API key
# is 256 bits of machine-generated entropy, not a guessable human secret, so the
# work factor is about slowing digest-cracking of a dump, not defeating a
# dictionary attack -- and this runs on every authenticated API request, where a
# password-grade cost would be a self-inflicted throughput ceiling.
_PBKDF2_ITERATIONS = 100_000


def generate_api_key() -> str:
    """Return a fresh raw API key. The only place raw keys come into existence."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(_SECRET_BYTES)}"


def generate_sandbox_key() -> str:
    """Gap 340: a fresh raw sandbox key -- identical entropy, different prefix.

    Deliberately the same `_SECRET_BYTES`: a sandbox tenant is a *real* tenant
    with real rows in it, so its credential is not a weaker one. What limits it
    is the tenant (readonly-pinned, TTL'd, chat-capped), not the key's strength.
    """
    return f"{SANDBOX_KEY_PREFIX}{secrets.token_urlsafe(_SECRET_BYTES)}"


def generate_widget_token() -> str:
    """Gap 341: a fresh raw widget chat token.

    Same entropy as the two above even though this credential lives in public
    page source. Being guessable and being published are different problems;
    this function only solves the first, and nothing about the token's storage
    or verification should be read as a claim that the second is solved -- the
    containment for that is how narrow the token's reach is (one route, its own
    context type), not its length.
    """
    return f"{WIDGET_TOKEN_PREFIX}{secrets.token_urlsafe(_SECRET_BYTES)}"


def generate_salt() -> str:
    """Return a fresh per-key salt, hex-encoded for plain-text column storage."""
    return secrets.token_hex(16)


def hash_api_key(raw_key: str, salt: str) -> str:
    """Derive the stored digest for `raw_key` under `salt` (hex-encoded)."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        raw_key.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    ).hex()


def verify_api_key(raw_key: str, salt: str | None, expected_hash: str | None) -> bool:
    """
    Constant-time check of `raw_key` against a stored (salt, hash) pair.

    A tenant that has never issued a key has NULL for both, which is a plain
    False here rather than an exception -- "no key issued" and "wrong key" are
    the same answer to the caller, and distinguishing them in the response would
    tell an unauthenticated caller which tenants have keys.
    """
    if not raw_key or not salt or not expected_hash:
        return False
    return hmac.compare_digest(hash_api_key(raw_key, salt), expected_hash)


def key_prefix(raw_key: str) -> str:
    """The non-secret leading slice of `raw_key` that is safe to store/display.

    Gap 340/341: computed from whichever platform prefix the value actually
    carries, so every credential type keeps exactly `_DISPLAY_SECRET_CHARS`
    characters of its secret visible rather than a number that happens to fall
    out of `inv_live_`'s length. For an `inv_live_` key the result is
    byte-identical to what Gap 184 has always stored (9 + 6 = 15) -- a test
    asserts that, because `Tenant.api_key_prefix` is an indexed lookup column
    and changing its width for existing rows would silently 401 every live key.
    """
    for prefix in PLATFORM_CREDENTIAL_PREFIXES:
        if raw_key.startswith(prefix):
            return raw_key[: len(prefix) + _DISPLAY_SECRET_CHARS]
    return raw_key[:_DISPLAY_PREFIX_LEN]


def masked_display(prefix: str | None) -> str | None:
    """
    Render a stored prefix the way the UI shows it: `inv_live_ab12cd...`.

    Returns None when the tenant has no key, so the caller can render an
    "issue a key" state instead of a fake-looking placeholder -- which is the
    exact failure Gap 184 was opened for.
    """
    if not prefix:
        return None
    return f"{prefix}{'.' * 3}"


def looks_like_api_key(candidate: str | None) -> bool:
    """
    True when a bearer value is a tenant API key rather than a Clerk session JWT.

    Used by the auth path to decide which verifier a given `Authorization:
    Bearer ...` belongs to. A Clerk JWT is three base64url segments separated by
    dots and never starts with one of our prefixes, so the prefix alone
    separates them unambiguously.

    Gap 340 widened this to `inv_test_` as well. A sandbox key is verified by
    exactly the same code path against exactly the same columns -- the tenant
    behind it is what makes it a sandbox, not the credential -- so treating it
    as a different *kind* of thing here would mean two verifiers to keep in
    step. `inv_widget_` is deliberately NOT included: see
    looks_like_widget_token().
    """
    return bool(candidate) and candidate.startswith((API_KEY_PREFIX, SANDBOX_KEY_PREFIX))


def looks_like_sandbox_key(candidate: str | None) -> bool:
    """True when a raw credential is a Gap 340 sandbox key."""
    return bool(candidate) and candidate.startswith(SANDBOX_KEY_PREFIX)


def looks_like_widget_token(candidate: str | None) -> bool:
    """
    True when a bearer value is a Gap 341 widget chat token.

    Kept separate from looks_like_api_key() on purpose. A widget token must
    never reach resolve_api_key_context() and become a TenantContext -- it is a
    published credential, and the whole containment story is that the type it
    resolves to has no permission fields for a scope check to get wrong.
    """
    return bool(candidate) and candidate.startswith(WIDGET_TOKEN_PREFIX)


def looks_like_platform_credential(candidate: str | None) -> bool:
    """
    True when a bearer value is any credential this platform minted.

    This is the dispatch question -- "is this ours, or is it a Clerk JWT" --
    asked once for every prefix. Gap 341 added it because the alternative was a
    widget token in the shared `Authorization` header falling through to the
    Clerk verifier and 401ing with a message about an invalid token signature,
    while the same token in `X-API-Key` 401'd with something else entirely. One
    credential, two headers, two unrelated errors is how an integrator loses an
    afternoon.
    """
    return bool(candidate) and candidate.startswith(PLATFORM_CREDENTIAL_PREFIXES)
