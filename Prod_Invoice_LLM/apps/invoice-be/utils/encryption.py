import base64
import hashlib
import logging
from cryptography.fernet import Fernet
from config import settings

logger = logging.getLogger(__name__)

def get_fernet_key() -> bytes:
    """
    Derives a valid 32-byte url-safe base64-encoded Fernet key 
    from settings.TOKEN_ENCRYPTION_KEY using SHA-256.
    """
    raw_key = settings.TOKEN_ENCRYPTION_KEY or "default_fallback_encryption_key"
    key_hash = hashlib.sha256(raw_key.encode()).digest()
    return base64.urlsafe_b64encode(key_hash)

def encrypt_token(token: str) -> str:
    """
    Encrypts a plaintext token using AES-256 Fernet.
    """
    if not token:
        return ""
    try:
        f = Fernet(get_fernet_key())
        return f.encrypt(token.encode()).decode()
    except Exception as e:
        logger.error("Failed to encrypt token: %s", e)
        raise

def decrypt_token(encrypted_token: str) -> str:
    """
    Decrypts an encrypted token back into plaintext.
    """
    if not encrypted_token:
        return ""
    try:
        f = Fernet(get_fernet_key())
        return f.decrypt(encrypted_token.encode()).decode()
    except Exception as e:
        logger.error("Failed to decrypt token: %s", e)
        raise


# Fernet tokens are base64 of a version byte 0x80 -- they always start with "gAAAA".
_FERNET_PREFIX = "gAAAA"


def is_encrypted_token(value: str) -> bool:
    """True when `value` looks like a Fernet token produced by `encrypt_token`."""
    return bool(value) and value.startswith(_FERNET_PREFIX)


def reveal_webhook_secret(stored: str) -> str:
    """BE Gap 564: the signing secret from a `WebhookSubscription.secret` column value.

    Rows written before Gap 564 hold the plaintext secret and are returned as they are (no
    backfill in dev -- add-only rule); rows written after it hold a Fernet token and are
    decrypted. A token that fails to decrypt (rotated TOKEN_ENCRYPTION_KEY) raises, so the
    delivery is logged as failed instead of being signed with garbage.
    """
    if not is_encrypted_token(stored):
        return stored
    return decrypt_token(stored)

