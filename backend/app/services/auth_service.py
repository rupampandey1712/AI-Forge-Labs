"""Registration, login, refresh and logout.

SECURITY decisions worth naming, because the game teaches them:

* **Uniform failure.** Wrong username and wrong password return the identical
  error. Anything else is a user-enumeration oracle.
* **Constant work on failure.** We hash a dummy password when the user does not
  exist, so "no such user" and "wrong password" take the same time. Without it,
  a stopwatch enumerates your user table.
* **Refresh-token rotation.** Every refresh issues a new token and revokes the
  old ``jti``. A stolen refresh token is then usable at most once, and the
  legitimate client's next refresh fails loudly instead of silently sharing
  the session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.domain.enums import Rank
from app.game.skills.registry import DEFAULT_UNLOCKED_BUILDINGS, SKILLS
from app.models.progress import SkillProgress
from app.models.user import PlayerProfile, RefreshToken, User
from app.repositories.player import ProfileRepository, RefreshTokenRepository, UserRepository
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, TokenPair, UserPublic

log = get_logger(__name__)

#: A real bcrypt hash of a value nobody can supply. Verifying against it burns
#: the same ~250ms as a genuine check, which is the whole point.
_DUMMY_HASH = hash_password("$aiforge-timing-equaliser$never-a-real-password$")


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.profiles = ProfileRepository(session)
        self.tokens = RefreshTokenRepository(session)

    async def register(self, payload: RegisterRequest) -> AuthResponse:
        email = payload.email.lower().strip()
        if await self.users.get_by_email(email):
            raise ConflictError("An account with that email already exists.")
        if await self.users.get_by_username(payload.username):
            raise ConflictError("That username is taken.")

        user = User(
            email=email,
            username=payload.username,
            hashed_password=hash_password(payload.password),
        )
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            # The check above is an optimisation; the unique index is the truth.
            # Two simultaneous registrations of the same email land here.
            await self.session.rollback()
            raise ConflictError("That email or username is already registered.") from exc

        await self._create_profile(user, payload.display_name or payload.username)
        log.info("auth.registered", user_id=str(user.id), username=user.username)
        tokens = await self._issue_tokens(user)
        return AuthResponse(user=UserPublic.model_validate(user), tokens=tokens)

    async def _create_profile(self, user: User, display_name: str) -> PlayerProfile:
        profile = PlayerProfile(
            user_id=user.id,
            display_name=display_name[:60],
            title="Python Apprentice",
            rank=Rank.PYTHON_APPRENTICE.value,
            unlocked_buildings=list(DEFAULT_UNLOCKED_BUILDINGS),
        )
        self.session.add(profile)
        await self.session.flush()
        # Seed all 16 skill rows up front. The radar chart needs every axis to
        # exist, and creating them lazily would make "which skills do I have?"
        # depend on what the player happened to touch first.
        self.session.add_all(
            [SkillProgress(profile_id=profile.id, skill_slug=s.slug.value) for s in SKILLS]
        )
        await self.session.flush()
        return profile

    async def login(self, payload: LoginRequest, *, user_agent: str | None = None) -> AuthResponse:
        user = await self.users.get_by_identifier(payload.identifier)
        if user is None:
            verify_password(payload.password, _DUMMY_HASH)  # equalise timing
            raise AuthenticationError("Incorrect credentials.")
        if not verify_password(payload.password, user.hashed_password):
            log.warning("auth.login_failed", user_id=str(user.id))
            raise AuthenticationError("Incorrect credentials.")
        if not user.is_active:
            raise AuthenticationError("This account is disabled.")

        # Transparent upgrade when the cost factor policy increases.
        if needs_rehash(user.hashed_password):
            user.hashed_password = hash_password(payload.password)

        if user.profile is None:
            # Self-heal an account created before profiles existed (or by a
            # partially-failed registration) rather than 500ing on the dashboard.
            await self._create_profile(user, user.username)

        await self.users.touch_login(user.id)
        tokens = await self._issue_tokens(user, user_agent=user_agent)
        log.info("auth.login", user_id=str(user.id))
        return AuthResponse(user=UserPublic.model_validate(user), tokens=tokens)

    async def _issue_tokens(self, user: User, *, user_agent: str | None = None) -> TokenPair:
        access = create_token(user.id, "access", extra_claims={"username": user.username})
        refresh = create_token(user.id, "refresh")
        claims = decode_token(refresh, expected_type="refresh")
        self.session.add(
            RefreshToken(
                user_id=user.id,
                jti=claims["jti"],
                expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
                user_agent=(user_agent or "")[:255] or None,
            )
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.access_token_expire_minutes * 60,
        )

    async def refresh(self, refresh_token: str, *, user_agent: str | None = None) -> TokenPair:
        claims = decode_token(refresh_token, expected_type="refresh")
        stored = await self.tokens.get_by_jti(claims["jti"])
        if stored is None:
            # The token is cryptographically valid but we have no record of it:
            # either it was already rotated away or the DB was reset. Refuse.
            raise AuthenticationError("This session is no longer valid. Please sign in again.")
        if stored.revoked:
            # Reuse of a rotated token is the classic stolen-token signature.
            # Nuke every session for that user and make them re-authenticate.
            revoked = await self.tokens.revoke_all_for_user(stored.user_id)
            # COMMIT BEFORE RAISING. The request-scoped unit of work rolls back
            # on exception, which would silently undo the revocation we just
            # performed — the security response would appear to work in the log
            # and do nothing in the database. This is the one place where the
            # side effect must outlive the failed request.
            await self.session.commit()
            log.warning(
                "auth.refresh_reuse_detected", user_id=str(stored.user_id), sessions_revoked=revoked
            )
            raise AuthenticationError("Session reuse detected. All sessions have been signed out.")
        if not stored.is_valid:
            raise AuthenticationError("This session has expired. Please sign in again.")

        user = await self.users.get(stored.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("This account is unavailable.")

        stored.revoked = True  # rotation
        return await self._issue_tokens(user, user_agent=user_agent)

    async def logout(
        self, refresh_token: str | None, user_id: uuid.UUID, *, all_sessions: bool = False
    ) -> int:
        if all_sessions or refresh_token is None:
            return await self.tokens.revoke_all_for_user(user_id)
        try:
            claims = decode_token(refresh_token, expected_type="refresh")
        except AuthenticationError:
            return 0
        stored = await self.tokens.get_by_jti(claims["jti"])
        if stored and stored.user_id == user_id:
            stored.revoked = True
            return 1
        return 0

    async def change_password(self, user_id: uuid.UUID, current: str, new: str) -> None:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        if not verify_password(current, user.hashed_password):
            raise AuthenticationError("Current password is incorrect.")
        user.hashed_password = hash_password(new)
        # Changing a password must end every other session — otherwise the
        # person you changed it because of keeps their access.
        await self.tokens.revoke_all_for_user(user_id)
        log.info("auth.password_changed", user_id=str(user_id))

    async def get_profile_for_user(self, user_id: uuid.UUID) -> PlayerProfile:
        profile = await self.profiles.get_for_user(user_id)
        if profile is None:
            raise NotFoundError("No player profile for this account.")
        return profile

    async def purge_expired_tokens(self) -> int:
        removed = await self.tokens.purge_expired()
        if removed:
            log.info("auth.tokens_purged", count=removed)
        return removed


def token_expiry_hint() -> timedelta:
    return timedelta(minutes=settings.access_token_expire_minutes)
