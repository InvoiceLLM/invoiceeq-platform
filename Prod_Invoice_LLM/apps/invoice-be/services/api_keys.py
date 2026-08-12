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

# 32 URL-safe bytes -> ~43 characters of entropy after the prefix.
_SECRET_BYTES = 32

# Number of characters of the *raw* key (prefix included) that are safe to
# persist and display. 9 ("inv_live_") + 6 leaves ~37 characters of the secret
# unknown, which is not a meaningful reduction in brute-force cost, while still
# letting an Admin tell two keys apart in the UI.
_DISPLAY_PREFIX_LEN = len(API_KEY_PREFIX) + 6

# PBKDF2 iteration count. Deliberately lower than a password KDF's: an API key
# is 256 bits of machine-generated entropy, not a guessable human secret, so the
# work factor is about slowing digest-cracking of a dump, not defeating a
# dictionary attack -- and this runs on every authenticated API request, where a
# password-grade cost would be a self-inflicted throughput ceiling.
_PBKDF2_ITERATIONS = 100_000


def generate_api_key() -> str:
    """Return a fresh raw API key. The only place raw keys come into existence."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(_SECRET_BYTES)}"


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
    """The non-secret leading slice of `raw_key` that is safe to store/display."""
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
    True when a bearer value is one of ours rather than a Clerk session JWT.

    Used by the auth path to decide which verifier a given `Authorization:
    Bearer ...` belongs to. A Clerk JWT is three base64url segments separated by
    dots and never starts with `inv_live_`, so the prefix alone separates them
    unambiguously.
    """
    return bool(candidate) and candidate.startswith(API_KEY_PREFIX)
