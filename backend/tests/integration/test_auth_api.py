"""Authentication over HTTP, including the attacks it is designed to resist."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def register(client, api, **overrides):
    payload = {
        "email": "new@test.dev",
        "username": "newplayer",
        "password": "Str0ng-Passphrase!",
        **overrides,
    }
    return await client.post(f"{api}/auth/register", json=payload)


class TestRegistration:
    async def test_creates_account_profile_and_all_skill_rows(self, seeded_client, api):
        response = await register(seeded_client, api)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["user"]["email"] == "new@test.dev"
        assert body["tokens"]["access_token"]
        assert body["tokens"]["token_type"] == "bearer"

        headers = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
        skills = await seeded_client.get(f"{api}/player/skills", headers=headers)
        assert len(skills.json()) == 16, "every radar axis must exist from day one"

    async def test_password_hash_is_never_returned(self, seeded_client, api):
        response = await register(seeded_client, api)
        assert "password" not in response.text.lower().replace("password_", "")
        assert "hashed" not in response.text

    @pytest.mark.parametrize(
        "password",
        ["short", "password", "12345678", "alllowercase"],
    )
    async def test_rejects_weak_passwords(self, seeded_client, api, password):
        response = await register(seeded_client, api, password=password)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_failed"

    async def test_accepts_a_long_passphrase_without_symbol_gymnastics(self, seeded_client, api):
        """Length is the dominant strength factor; a 16+ char passphrase passes."""
        response = await register(seeded_client, api, password="correct horse battery staple")
        assert response.status_code == 201

    @pytest.mark.parametrize("username", ["ab", ".leading", "-leading", "has space", "x" * 31])
    async def test_rejects_bad_usernames(self, seeded_client, api, username):
        response = await register(seeded_client, api, username=username)
        assert response.status_code == 422

    async def test_duplicate_email_is_a_conflict(self, seeded_client, api):
        await register(seeded_client, api)
        response = await register(seeded_client, api, username="different")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "conflict"

    async def test_duplicate_username_is_a_conflict(self, seeded_client, api):
        await register(seeded_client, api)
        response = await register(seeded_client, api, email="other@test.dev")
        assert response.status_code == 409

    async def test_email_is_normalised_to_lowercase(self, seeded_client, api):
        await register(seeded_client, api, email="MiXeD@Test.DEV", username="mixed")
        response = await seeded_client.post(
            f"{api}/auth/login",
            json={"identifier": "mixed@test.dev", "password": "Str0ng-Passphrase!"},
        )
        assert response.status_code == 200


class TestLogin:
    async def test_by_email_or_username(self, seeded_client, api):
        await register(seeded_client, api)
        for identifier in ("new@test.dev", "newplayer"):
            response = await seeded_client.post(
                f"{api}/auth/login",
                json={"identifier": identifier, "password": "Str0ng-Passphrase!"},
            )
            assert response.status_code == 200, identifier

    async def test_wrong_password_and_unknown_user_are_indistinguishable(self, seeded_client, api):
        """Different messages here are a user-enumeration oracle."""
        await register(seeded_client, api)
        wrong = await seeded_client.post(
            f"{api}/auth/login", json={"identifier": "new@test.dev", "password": "nope"}
        )
        missing = await seeded_client.post(
            f"{api}/auth/login", json={"identifier": "ghost@test.dev", "password": "nope"}
        )
        assert wrong.status_code == missing.status_code == 401
        assert wrong.json()["error"] == missing.json()["error"]


class TestTokens:
    async def test_protected_route_requires_a_token(self, seeded_client, api):
        response = await seeded_client.get(f"{api}/player/dashboard")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"

    async def test_garbage_token_is_rejected_cleanly(self, seeded_client, api):
        response = await seeded_client.get(
            f"{api}/player/dashboard", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code == 401

    async def test_refresh_token_cannot_be_used_as_an_access_token(self, seeded_client, api):
        """Token-type confusion: a refresh token must not open protected routes."""
        body = (await register(seeded_client, api)).json()
        response = await seeded_client.get(
            f"{api}/player/dashboard",
            headers={"Authorization": f"Bearer {body['tokens']['refresh_token']}"},
        )
        assert response.status_code == 401

    async def test_refresh_rotates_and_invalidates_the_old_token(self, seeded_client, api):
        body = (await register(seeded_client, api)).json()
        old = body["tokens"]["refresh_token"]

        first = await seeded_client.post(f"{api}/auth/refresh", json={"refresh_token": old})
        assert first.status_code == 200
        assert first.json()["refresh_token"] != old

        reuse = await seeded_client.post(f"{api}/auth/refresh", json={"refresh_token": old})
        assert reuse.status_code == 401, "a rotated refresh token must not work twice"

    async def test_reuse_revokes_every_session(self, seeded_client, api):
        """Reuse of a rotated token is the stolen-token signature: burn it all."""
        body = (await register(seeded_client, api)).json()
        old = body["tokens"]["refresh_token"]
        new = (await seeded_client.post(f"{api}/auth/refresh", json={"refresh_token": old})).json()[
            "refresh_token"
        ]

        await seeded_client.post(f"{api}/auth/refresh", json={"refresh_token": old})
        after = await seeded_client.post(f"{api}/auth/refresh", json={"refresh_token": new})
        assert after.status_code == 401, "the legitimate session should also be revoked"

    async def test_logout_revokes(self, seeded_client, api):
        body = (await register(seeded_client, api)).json()
        headers = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
        response = await seeded_client.post(f"{api}/auth/logout?all_sessions=true", headers=headers)
        assert response.status_code == 200
        reuse = await seeded_client.post(
            f"{api}/auth/refresh", json={"refresh_token": body["tokens"]["refresh_token"]}
        )
        assert reuse.status_code == 401


class TestPasswordChange:
    async def test_requires_the_current_password(self, seeded_client, api):
        body = (await register(seeded_client, api)).json()
        headers = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
        response = await seeded_client.post(
            f"{api}/auth/change-password",
            headers=headers,
            json={"current_password": "wrong", "new_password": "An0ther-Passphrase!"},
        )
        assert response.status_code == 401

    async def test_changing_password_revokes_other_sessions(self, seeded_client, api):
        body = (await register(seeded_client, api)).json()
        headers = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
        response = await seeded_client.post(
            f"{api}/auth/change-password",
            headers=headers,
            json={
                "current_password": "Str0ng-Passphrase!",
                "new_password": "An0ther-Passphrase!",
            },
        )
        assert response.status_code == 200
        reuse = await seeded_client.post(
            f"{api}/auth/refresh", json={"refresh_token": body["tokens"]["refresh_token"]}
        )
        assert reuse.status_code == 401
