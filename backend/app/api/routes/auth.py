"""Authentication endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import AuthSvc, CurrentUser, get_user_agent
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserPublic,
)
from app.schemas.common import Message

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, service: AuthSvc) -> AuthResponse:
    """Create an account, its player profile and all 16 skill rows."""
    return await service.register(payload)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    service: AuthSvc,
    user_agent: Annotated[str | None, Depends(get_user_agent)] = None,
) -> AuthResponse:
    return await service.login(payload, user_agent=user_agent)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshRequest,
    service: AuthSvc,
    user_agent: Annotated[str | None, Depends(get_user_agent)] = None,
) -> TokenPair:
    """Rotate a refresh token. The old one is revoked; reuse revokes everything."""
    return await service.refresh(payload.refresh_token, user_agent=user_agent)


@router.post("/logout", response_model=Message)
async def logout(
    user: CurrentUser,
    service: AuthSvc,
    payload: RefreshRequest | None = None,
    all_sessions: bool = False,
) -> Message:
    count = await service.logout(
        payload.refresh_token if payload else None, user.id, all_sessions=all_sessions
    )
    return Message(message=f"Signed out of {count} session(s).")


@router.get("/me", response_model=UserPublic)
async def me(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)


@router.post("/change-password", response_model=Message)
async def change_password(
    payload: ChangePasswordRequest, user: CurrentUser, service: AuthSvc
) -> Message:
    await service.change_password(user.id, payload.current_password, payload.new_password)
    return Message(message="Password changed. All other sessions have been signed out.")
