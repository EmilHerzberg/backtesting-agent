from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class UserRegisterRequest(BaseModel):
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=8)
    # Phase 1 (Q3): optionally provide an AI provider key at registration.
    provider_type: str | None = None
    api_key: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class DeleteAccountRequest(BaseModel):
    current_password: str = Field(..., min_length=1)


class UserLoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    is_verified: bool


class MessageResponse(BaseModel):
    message: str


class RegisterResponse(BaseModel):
    message: str
    verify_url: str | None = None
