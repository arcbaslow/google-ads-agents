"""Fernet encryption with append-only key versioning.

`keys` is ordered oldest -> newest. The newest key encrypts; the stored integer
version is the key's index, stable across future appends. Rotation = append a
new key; existing ciphertext still decrypts under its stored version.
"""

from __future__ import annotations

from cryptography.fernet import Fernet


class Crypto:
    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("Crypto requires at least one key")
        self._fernets = [Fernet(k.encode()) for k in keys]

    def encrypt(self, plaintext: str) -> tuple[bytes, int]:
        version = len(self._fernets) - 1
        return self._fernets[version].encrypt(plaintext.encode()), version

    def decrypt(self, token: bytes, version: int) -> str:
        return self._fernets[version].decrypt(token).decode()
