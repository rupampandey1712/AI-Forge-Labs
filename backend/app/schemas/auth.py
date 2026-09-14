"""Auth request/response contracts.

The password policy lives here rather than in the service because Pydantic is
the first thing a request touches: rejecting a weak password at the schema
boundary means the service can assume it is dealing with a valid one. That is
the practical meaning of "parse, don't validate".
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import Schema

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]{2,29}$")


class RegisterRequest(Schema):
    email: EmailStr
    username: Annotated[str, Field(min_length=3, max_length=30)]
    password: Annotated[str, Field(min_length=8, max_length=128)]
    display_name: Annotated[str | None, Field(max_length=60)] = None

    @field_validator("username")
    @classmethod
    def _valid_username(cls, v: str) -> str:
        if not USERNAME_RE.match(v):
            raise ValueError(
                "Username must be 3-30 chars: letters, digits, underscore, dot or hyphen, "
                "and must not start with a dot or hyphen."
            )
        return v

    @field_validator("password")
    @classmethod
    def _strong_enough(cls, v: str) -> str:
        # Deliberately composition-based rather than a regex wall: length is the
        # dominant factor in password strength, so long passphrases pass on
        # length alone rather than being forced to bolt on a "!" at the end.
        if len(v) >= 16:
            return v
        classes = sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]"))
        if classes < 3:
            raise ValueError(
                "Password needs 16+ characters, or at least 3 of: lowercase, uppercase, digit, symbol."
            )
        return v


class LoginRequest(Schema):
    # Accepts either — players remember one or the other, not reliably both.
    identifier: Annotated[str, Field(min_length=3, max_length=320)]
    password: Annotated[str, Field(min_length=1, max_length=128)]


class RefreshRequest(Schema):
    refresh_token: str


class TokenPair(Schema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserPublic(Schema):
    id: uuid.UUID
    email: EmailStr
    username: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class AuthResponse(Schema):
    user: UserPublic
    tokens: TokenPair


class ChangePasswordRequest(Schema):
    current_password: str
    new_password: Annotated[str, Field(min_length=8, max_length=128)]
