"""
Full JWT authentication test suite.

Coverage:
  Registration   — success, duplicate email, validation (name/email/password)
  Login          — success, wrong password, unknown email (timing safe)
  Token          — structure, iss/sub/jti/type claims, type confusion, tampered sig
  Protected      — bearer required, valid/invalid/blacklisted/expired tokens
  Refresh        — rotation (old token invalidated), reuse rejected
  Logout         — access token blacklisted, refresh token revoked
  Profile        — PATCH /auth/me updates name
  Password       — change success, wrong current password, new password rules
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.config import settings

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _register(client, *, name="Test User", email="user@example.com", password="Password1"):
    res = await client.post("/auth/register", json={"name": name, "email": email, "password": password})
    return res


async def _login(client, *, email="user@example.com", password="Password1"):
    return await client.post("/auth/login", json={"email": email, "password": password})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Registration
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistration:

    async def test_success_returns_tokens_and_user(self, client):
        res = await _register(client, email="a@test.com")
        assert res.status_code == 201
        body = res.json()
        assert body["token_type"] == "bearer"
        assert len(body["access_token"]) > 20
        assert len(body["refresh_token"]) > 20
        user = body["user"]
        assert user["email"] == "a@test.com"
        assert user["name"] == "Test User"
        assert "id" in user
        assert "created_at" in user
        assert "password_hash" not in user     # never leak hashes

    async def test_email_normalised_to_lowercase(self, client):
        await _register(client, email="Upper@Test.COM")
        res = await client.get("/auth/me", headers=_auth(
            (await _login(client, email="Upper@Test.COM")).json()["access_token"]
        ))
        assert res.json()["email"] == "upper@test.com"

    async def test_duplicate_email_returns_409(self, client):
        await _register(client, email="dup@test.com")
        res = await _register(client, email="dup@test.com")
        assert res.status_code == 409
        assert res.json()["code"] == "CONFLICT"

    async def test_duplicate_email_case_insensitive(self, client):
        await _register(client, email="case@test.com")
        res = await _register(client, email="CASE@test.com")
        assert res.status_code == 409

    # ── Input validation ──────────────────────────────────────────────────────

    async def test_blank_name_rejected(self, client):
        res = await _register(client, name="   ", email="b@test.com")
        assert res.status_code == 422
        assert "name" in res.json()["detail"].lower()

    async def test_missing_name_rejected(self, client):
        res = await client.post("/auth/register", json={"email": "c@test.com", "password": "Password1"})
        assert res.status_code == 422

    async def test_invalid_email_rejected(self, client):
        res = await _register(client, email="not-an-email")
        assert res.status_code == 422

    async def test_password_too_short_rejected(self, client):
        res = await _register(client, email="d@test.com", password="Abc1")
        assert res.status_code == 422

    async def test_password_no_letter_rejected(self, client):
        res = await _register(client, email="e@test.com", password="12345678")
        assert res.status_code == 422
        assert "letter" in res.json()["detail"].lower()

    async def test_password_no_number_rejected(self, client):
        res = await _register(client, email="f@test.com", password="NoNumbers!")
        assert res.status_code == 422
        assert "number" in res.json()["detail"].lower()

    async def test_password_too_long_rejected(self, client):
        res = await _register(client, email="g@test.com", password="Aa1" + "x" * 130)
        assert res.status_code == 422

    async def test_name_trimmed_in_storage(self, client):
        res = await _register(client, name="  Alice  ", email="trim@test.com")
        assert res.json()["user"]["name"] == "Alice"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Login
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogin:

    async def test_success(self, client):
        await _register(client, email="login@test.com")
        res = await _login(client, email="login@test.com")
        assert res.status_code == 200
        assert "access_token" in res.json()
        assert "refresh_token" in res.json()

    async def test_wrong_password_returns_401(self, client):
        await _register(client, email="wp@test.com")
        res = await _login(client, email="wp@test.com", password="WrongPass1")
        assert res.status_code == 401
        # Must not reveal whether the email exists
        assert "email or password" in res.json()["detail"].lower()

    async def test_unknown_email_returns_401(self, client):
        res = await _login(client, email="nobody@test.com")
        assert res.status_code == 401
        # Same error as wrong-password — no email enumeration
        assert "email or password" in res.json()["detail"].lower()

    async def test_login_is_case_insensitive_on_email(self, client):
        await _register(client, email="mixcase@test.com")
        res = await _login(client, email="MIXCASE@test.com")
        assert res.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Token structure and claims
# ═══════════════════════════════════════════════════════════════════════════════

class TestTokenClaims:

    async def test_access_token_has_required_claims(self, client):
        res = await _register(client, email="claims@test.com")
        token = res.json()["access_token"]
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
        )
        assert payload["type"] == "access"
        assert payload["iss"] == settings.JWT_ISSUER
        assert "sub" in payload
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload
        # Token must not be immediately expired
        assert payload["exp"] > datetime.now(timezone.utc).timestamp()

    async def test_access_token_expires_correctly(self, client):
        res = await _register(client, email="exp@test.com")
        token = res.json()["access_token"]
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
        )
        expected_exp = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
        # Allow ±5s clock skew in the test environment
        assert abs(payload["exp"] - expected_exp.timestamp()) < 5

    async def test_each_token_has_unique_jti(self, client):
        r1 = await _register(client, email="jti1@test.com")
        r2 = await _register(client, email="jti2@test.com")
        p1 = jwt.decode(r1.json()["access_token"], settings.JWT_SECRET,
                        algorithms=[settings.JWT_ALGORITHM], issuer=settings.JWT_ISSUER)
        p2 = jwt.decode(r2.json()["access_token"], settings.JWT_SECRET,
                        algorithms=[settings.JWT_ALGORITHM], issuer=settings.JWT_ISSUER)
        assert p1["jti"] != p2["jti"]

    async def test_refresh_token_has_type_refresh(self, client):
        res = await _register(client, email="rt@test.com")
        token = res.json()["refresh_token"]
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
        )
        assert payload["type"] == "refresh"

    async def test_tampered_token_rejected(self, client):
        res = await _register(client, email="tamper@test.com")
        token = res.json()["access_token"]
        # Flip last char to tamper with the signature
        bad_token = token[:-1] + ("A" if token[-1] != "A" else "B")
        res = await client.get("/auth/me", headers=_auth(bad_token))
        assert res.status_code == 401

    async def test_wrong_issuer_rejected(self, client):
        """Forge a token signed with the correct secret but wrong issuer."""
        res = await _register(client, email="issuer@test.com")
        original = jwt.decode(
            res.json()["access_token"], settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM], issuer=settings.JWT_ISSUER,
        )
        forged = jwt.encode(
            {**original, "iss": "evil-service"},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        res = await client.get("/auth/me", headers=_auth(forged))
        assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Protected routes
# ═══════════════════════════════════════════════════════════════════════════════

class TestProtectedRoutes:

    async def test_no_token_returns_403(self, client):
        res = await client.get("/auth/me")
        assert res.status_code == 403

    async def test_malformed_bearer_rejected(self, client):
        res = await client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
        assert res.status_code == 401

    async def test_valid_token_grants_access(self, client):
        res = await _register(client, email="protected@test.com")
        token = res.json()["access_token"]
        res = await client.get("/auth/me", headers=_auth(token))
        assert res.status_code == 200

    async def test_refresh_token_cannot_access_protected_route(self, client):
        """Type confusion: refresh token must be rejected as an access token."""
        res = await _register(client, email="typeconf@test.com")
        refresh_token = res.json()["refresh_token"]
        res = await client.get("/auth/me", headers=_auth(refresh_token))
        assert res.status_code == 401

    async def test_expired_token_rejected(self, client):
        """Craft a token with exp in the past."""
        res = await _register(client, email="expired@test.com")
        payload = jwt.decode(
            res.json()["access_token"], settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM], issuer=settings.JWT_ISSUER,
        )
        expired_token = jwt.encode(
            {**payload, "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        res = await client.get("/auth/me", headers=_auth(expired_token))
        assert res.status_code == 401

    async def test_workspace_route_requires_auth(self, client):
        res = await client.get("/workspaces")
        assert res.status_code == 403

    async def test_workspace_route_accepts_valid_token(self, client):
        res = await _register(client, email="wsauth@test.com")
        token = res.json()["access_token"]
        res = await client.get("/workspaces", headers=_auth(token))
        assert res.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Token refresh
# ═══════════════════════════════════════════════════════════════════════════════

class TestRefresh:

    async def test_valid_refresh_returns_new_token_pair(self, client):
        reg = await _register(client, email="refresh@test.com")
        old_access = reg.json()["access_token"]
        old_refresh = reg.json()["refresh_token"]

        res = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert res.status_code == 200
        new_access = res.json()["access_token"]
        new_refresh = res.json()["refresh_token"]
        # Both tokens must be brand-new values
        assert new_access != old_access
        assert new_refresh != old_refresh

    async def test_new_access_token_works(self, client):
        reg = await _register(client, email="newaccess@test.com")
        res = await client.post("/auth/refresh", json={"refresh_token": reg.json()["refresh_token"]})
        new_access = res.json()["access_token"]
        res = await client.get("/auth/me", headers=_auth(new_access))
        assert res.status_code == 200

    async def test_old_refresh_token_revoked_after_rotation(self, client):
        """Refresh token rotation: using the old refresh token again must fail."""
        reg = await _register(client, email="rotate@test.com")
        old_refresh = reg.json()["refresh_token"]

        # First refresh — rotates token
        await client.post("/auth/refresh", json={"refresh_token": old_refresh})

        # Second attempt with the SAME refresh token must be rejected
        res = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert res.status_code == 401

    async def test_access_token_rejected_as_refresh_token(self, client):
        """Type confusion: access token must be rejected by the refresh endpoint."""
        reg = await _register(client, email="accasref@test.com")
        access_token = reg.json()["access_token"]
        res = await client.post("/auth/refresh", json={"refresh_token": access_token})
        assert res.status_code == 401

    async def test_invalid_refresh_token_rejected(self, client):
        res = await client.post("/auth/refresh", json={"refresh_token": "not.a.real.token"})
        assert res.status_code == 401

    async def test_refresh_user_field_matches_registered_user(self, client):
        reg = await _register(client, email="rfuser@test.com")
        res = await client.post("/auth/refresh", json={"refresh_token": reg.json()["refresh_token"]})
        assert res.json()["user"]["email"] == "rfuser@test.com"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Logout and blacklisting
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogout:

    async def test_logout_returns_204(self, client):
        reg = await _register(client, email="logout@test.com")
        token = reg.json()["access_token"]
        res = await client.post("/auth/logout", json={}, headers=_auth(token))
        assert res.status_code == 204

    async def test_blacklisted_access_token_rejected(self, client):
        reg = await _register(client, email="bl@test.com")
        token = reg.json()["access_token"]

        await client.post("/auth/logout", json={}, headers=_auth(token))

        # Same token must now be rejected
        res = await client.get("/auth/me", headers=_auth(token))
        assert res.status_code == 401

    async def test_logout_revokes_refresh_token(self, client):
        reg = await _register(client, email="revokerf@test.com")
        access = reg.json()["access_token"]
        refresh = reg.json()["refresh_token"]

        await client.post(
            "/auth/logout",
            json={"refresh_token": refresh},
            headers=_auth(access),
        )

        # Refresh token must also be dead
        res = await client.post("/auth/refresh", json={"refresh_token": refresh})
        assert res.status_code == 401

    async def test_logout_without_refresh_token_only_blacklists_access(self, client):
        reg = await _register(client, email="norf@test.com")
        access = reg.json()["access_token"]
        refresh = reg.json()["refresh_token"]

        # Logout without sending the refresh token
        await client.post("/auth/logout", json={}, headers=_auth(access))

        # Access token is blacklisted
        res = await client.get("/auth/me", headers=_auth(access))
        assert res.status_code == 401

        # But refresh token is still alive — client can get a fresh access token
        res = await client.post("/auth/refresh", json={"refresh_token": refresh})
        assert res.status_code == 200

    async def test_logout_requires_valid_bearer(self, client):
        res = await client.post("/auth/logout", json={})
        assert res.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Profile management
# ═══════════════════════════════════════════════════════════════════════════════

class TestProfile:

    async def test_me_returns_correct_fields(self, client):
        await _register(client, name="Alice", email="alice2@test.com")
        token = (await _login(client, email="alice2@test.com")).json()["access_token"]
        body = (await client.get("/auth/me", headers=_auth(token))).json()
        assert body["name"] == "Alice"
        assert body["email"] == "alice2@test.com"
        assert "id" in body
        assert "created_at" in body
        assert "password_hash" not in body

    async def test_update_name(self, client):
        reg = await _register(client, name="Old Name", email="rename@test.com")
        token = reg.json()["access_token"]
        res = await client.patch("/auth/me", json={"name": "New Name"}, headers=_auth(token))
        assert res.status_code == 200
        assert res.json()["name"] == "New Name"

    async def test_update_name_reflected_in_me(self, client):
        reg = await _register(client, name="Before", email="reflect@test.com")
        token = reg.json()["access_token"]
        await client.patch("/auth/me", json={"name": "After"}, headers=_auth(token))
        res = await client.get("/auth/me", headers=_auth(token))
        assert res.json()["name"] == "After"

    async def test_update_blank_name_rejected(self, client):
        reg = await _register(client, email="blankpatch@test.com")
        token = reg.json()["access_token"]
        res = await client.patch("/auth/me", json={"name": "   "}, headers=_auth(token))
        assert res.status_code == 422

    async def test_update_name_trimmed(self, client):
        reg = await _register(client, email="trim2@test.com")
        token = reg.json()["access_token"]
        res = await client.patch("/auth/me", json={"name": "  Trimmed  "}, headers=_auth(token))
        assert res.json()["name"] == "Trimmed"

    async def test_update_requires_auth(self, client):
        res = await client.patch("/auth/me", json={"name": "Hacker"})
        assert res.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Password management
# ═══════════════════════════════════════════════════════════════════════════════

class TestPassword:

    async def test_change_password_success(self, client):
        reg = await _register(client, email="chpw@test.com", password="OldPass1")
        token = reg.json()["access_token"]
        res = await client.post(
            "/auth/change-password",
            json={"current_password": "OldPass1", "new_password": "NewPass2"},
            headers=_auth(token),
        )
        assert res.status_code == 204

    async def test_new_password_works_on_login(self, client):
        reg = await _register(client, email="newpw@test.com", password="OldPass1")
        token = reg.json()["access_token"]
        await client.post(
            "/auth/change-password",
            json={"current_password": "OldPass1", "new_password": "NewPass2"},
            headers=_auth(token),
        )
        res = await _login(client, email="newpw@test.com", password="NewPass2")
        assert res.status_code == 200

    async def test_old_password_rejected_after_change(self, client):
        reg = await _register(client, email="oldpw@test.com", password="OldPass1")
        token = reg.json()["access_token"]
        await client.post(
            "/auth/change-password",
            json={"current_password": "OldPass1", "new_password": "NewPass2"},
            headers=_auth(token),
        )
        res = await _login(client, email="oldpw@test.com", password="OldPass1")
        assert res.status_code == 401

    async def test_wrong_current_password_returns_400(self, client):
        reg = await _register(client, email="wrongcp@test.com", password="Correct1")
        token = reg.json()["access_token"]
        res = await client.post(
            "/auth/change-password",
            json={"current_password": "WrongPass1", "new_password": "NewPass2"},
            headers=_auth(token),
        )
        assert res.status_code == 400

    async def test_new_password_must_meet_strength_rules(self, client):
        reg = await _register(client, email="weaknew@test.com", password="Strong1!")
        token = reg.json()["access_token"]
        # No digit in new password
        res = await client.post(
            "/auth/change-password",
            json={"current_password": "Strong1!", "new_password": "NoDigitsHere"},
            headers=_auth(token),
        )
        assert res.status_code == 422

    async def test_change_password_requires_auth(self, client):
        res = await client.post("/auth/change-password",
                                json={"current_password": "x", "new_password": "NewPass1"})
        assert res.status_code == 403
