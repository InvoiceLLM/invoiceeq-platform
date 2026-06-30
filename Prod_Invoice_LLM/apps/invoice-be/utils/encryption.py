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
