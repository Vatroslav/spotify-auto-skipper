import os
from cryptography.fernet import Fernet, InvalidToken

from spotify_auto_skipper.utils import get_appdata_dir


class CredentialEncryption:
    """
    Handles encryption/decryption of sensitive config values using Fernet.
    Key is stored in %APPDATA%/SpotifyAutoSkipper/key.bin.
    Auto-generates a key on first use.
    """

    def __init__(self):
        self._key_path = os.path.join(get_appdata_dir(), "key.bin")
        self._fernet = None

    def _ensure_key(self):
        """Load or generate the Fernet key."""
        if self._fernet is not None:
            return

        if os.path.exists(self._key_path):
            with open(self._key_path, "rb") as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            with open(self._key_path, "wb") as f:
                f.write(key)

        self._fernet = Fernet(key)

    def encrypt(self, plaintext):
        """Encrypt a string, returns base64-encoded Fernet token string."""
        if not plaintext:
            return plaintext
        self._ensure_key()
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext):
        """Decrypt a Fernet token string back to plaintext."""
        if not ciphertext:
            return ciphertext
        self._ensure_key()
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except (InvalidToken, Exception):
            # Not encrypted or corrupted — return as-is (graceful migration)
            return ciphertext

    @staticmethod
    def is_encrypted(value):
        """Heuristic: Fernet tokens start with 'gAAAAA'."""
        return isinstance(value, str) and value.startswith("gAAAAA")
