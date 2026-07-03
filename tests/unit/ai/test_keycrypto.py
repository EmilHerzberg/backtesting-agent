"""Account-settings Phase 1 — keycrypto (encryption-at-rest for AI keys)."""

from __future__ import annotations

from cryptography.fernet import Fernet

from src.backend.ai import keycrypto


def _enable(monkeypatch):
    monkeypatch.setattr(keycrypto, "_fernet", Fernet(Fernet.generate_key()))


def test_roundtrip_and_prefix(monkeypatch):
    _enable(monkeypatch)
    e = keycrypto.encrypt_key("sk-abc-1234567890")
    assert keycrypto.is_encrypted(e) and e.startswith("enc::v1::")
    assert keycrypto.decrypt_key(e) == "sk-abc-1234567890"


def test_double_encrypt_guard(monkeypatch):
    _enable(monkeypatch)
    e = keycrypto.encrypt_key("sk-abc-1234567890")
    assert keycrypto.encrypt_key(e) == e  # already-encrypted is not re-wrapped


def test_mask(monkeypatch):
    _enable(monkeypatch)
    e = keycrypto.encrypt_key("sk-abc-1234567890")
    assert keycrypto.mask_key(e) == "sk-a...7890"  # masks the *plaintext*
    assert keycrypto.mask_key(keycrypto.encrypt_key("short")) == "****"


def test_legacy_plaintext_passthrough(monkeypatch):
    _enable(monkeypatch)
    assert keycrypto.decrypt_key("plain-legacy-key") == "plain-legacy-key"
    assert keycrypto.mask_key("plain-legacy-key") == "plai...-key"


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(keycrypto, "_fernet", None)
    assert keycrypto.encryption_enabled() is False
    assert keycrypto.encrypt_key("sk-x-1234567890") == "sk-x-1234567890"  # no-op
    assert keycrypto.decrypt_key("sk-x-1234567890") == "sk-x-1234567890"
    assert keycrypto.mask_key("sk-x-1234567890") == "sk-x...7890"
