"""Account-settings Phase 1 — encryption-at-rest for stored AI provider API keys.

Symmetric (Fernet). Keys are encrypted on write, decrypted only for use, masked on display.
If ``settings.ai_key_encryption_key`` is unset the helpers are a **graceful no-op** (plaintext),
so the site keeps working — with a loud one-time warning — and prod must set the key. Values are
tagged with a version prefix so legacy plaintext and encrypted values coexist during migration.
"""

from __future__ import annotations

import logging

from src.backend.shared.config import settings

logger = logging.getLogger(__name__)

_PREFIX = "enc::v1::"

_fernet = None
try:
    if settings.ai_key_encryption_key:
        from cryptography.fernet import Fernet

        _fernet = Fernet(settings.ai_key_encryption_key.encode())
    else:
        logger.warning(
            "AI_KEY_ENCRYPTION_KEY is not set — AI provider keys are stored in PLAINTEXT. "
            "Set a Fernet key in the environment for encryption-at-rest."
        )
except Exception:  # noqa: BLE001 — a bad key must not crash boot; fall back to plaintext + warn
    logger.exception("AI_KEY_ENCRYPTION_KEY invalid — falling back to plaintext storage")
    _fernet = None


def encryption_enabled() -> bool:
    return _fernet is not None


def is_encrypted(stored: str) -> bool:
    return bool(stored) and stored.startswith(_PREFIX)


def encrypt_key(plain: str) -> str:
    """Encrypt a plaintext key for storage. No-op (returns plain) if encryption is disabled."""
    if not plain or _fernet is None:
        return plain
    if is_encrypted(plain):  # already encrypted — don't double-wrap
        return plain
    return _PREFIX + _fernet.encrypt(plain.encode()).decode()


def decrypt_key(stored: str) -> str:
    """Return the plaintext key. Passes legacy/plaintext values through unchanged."""
    if not stored or not is_encrypted(stored):
        return stored
    if _fernet is None:  # encrypted at rest but no key available now — can't recover
        logger.error("Encountered an encrypted AI key but AI_KEY_ENCRYPTION_KEY is unset")
        return stored
    try:
        from cryptography.fernet import InvalidToken

        return _fernet.decrypt(stored[len(_PREFIX):].encode()).decode()
    except Exception:  # noqa: BLE001 — never crash on a bad token; surface the raw value
        logger.exception("Failed to decrypt an AI key")
        return stored


def mask_key(stored: str) -> str:
    """Mask for display: first 4 + last 4 of the *plaintext* value."""
    plain = decrypt_key(stored)
    return plain[:4] + "..." + plain[-4:] if len(plain) > 8 else "****"
