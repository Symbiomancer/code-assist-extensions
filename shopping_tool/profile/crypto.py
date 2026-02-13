"""Fernet-based encryption for user profile data at rest."""
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet


class ProfileCrypto:
    """Encrypts/decrypts user profile data using Fernet (AES-128-CBC + HMAC)."""

    def __init__(self, key_path: Path | None = None):
        self._key_path = key_path or Path.home() / ".shopping_assistant_key"

    def _get_or_create_key(self) -> bytes:
        """Load existing key or generate a new one."""
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()

        key = Fernet.generate_key()
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._key_path.write_bytes(key)
        os.chmod(self._key_path, 0o600)
        return key

    def encrypt(self, data: dict) -> bytes:
        """Encrypt a dict to bytes."""
        key = self._get_or_create_key()
        f = Fernet(key)
        plaintext = json.dumps(data).encode()
        return f.encrypt(plaintext)

    def decrypt(self, encrypted: bytes) -> dict:
        """Decrypt bytes back to a dict."""
        key = self._get_or_create_key()
        f = Fernet(key)
        plaintext = f.decrypt(encrypted)
        return json.loads(plaintext.decode())
