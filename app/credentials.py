"""Fernet encryption helpers for the credentials vault."""

from cryptography.fernet import Fernet

from .config import settings


# ---------------------------------------------------------------------------
# Fernet encrypt / decrypt
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    key = settings.CREDENTIAL_ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def encrypt(plaintext: str | None) -> bytes | None:
    """Encrypt a plaintext string. Returns None if input is None."""
    if plaintext is None:
        return None
    return _get_fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes | None) -> str | None:
    """Decrypt a ciphertext blob. Returns None if input is None."""
    if ciphertext is None:
        return None
    return _get_fernet().decrypt(ciphertext).decode()
