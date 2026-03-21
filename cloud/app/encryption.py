"""
Fernet encryption for sensitive data at rest (OAuth tokens).
Derives a stable Fernet key from SECRET_KEY via HKDF.
"""

import base64
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        from app.config import get_secret_key
        kdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"spotify-auto-skipper-tokens",
            info=b"fernet-key",
        )
        key = kdf.derive(get_secret_key().encode())
        _fernet = Fernet(base64.urlsafe_b64encode(key))
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return a base64-encoded ciphertext."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext back to a string."""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return ""
