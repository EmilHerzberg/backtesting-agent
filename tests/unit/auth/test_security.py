from datetime import timedelta

from src.backend.auth.security import (
    create_access_token,
    decode_access_token,
    generate_verification_token,
    hash_password,
    verify_password,
)


class TestPassword:
    def test_hash_and_verify(self):
        hashed = hash_password("mypassword123")
        assert hashed != "mypassword123"
        assert verify_password("mypassword123", hashed)

    def test_wrong_password(self):
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)


class TestJWT:
    def test_create_and_decode(self):
        token = create_access_token({"sub": "42", "email": "test@example.com"})
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "42"
        assert payload["email"] == "test@example.com"

    def test_expired_token(self):
        token = create_access_token(
            {"sub": "1"}, expires_delta=timedelta(seconds=-1)
        )
        assert decode_access_token(token) is None

    def test_invalid_token(self):
        assert decode_access_token("garbage.token.here") is None


class TestVerificationToken:
    def test_generates_unique(self):
        t1 = generate_verification_token()
        t2 = generate_verification_token()
        assert t1 != t2
        assert len(t1) > 20
