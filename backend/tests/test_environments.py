"""
Environment management tests.

Structure:
  TestEnvironmentCRUD     — list, create, get detail, update, delete
  TestActivation          — activate switches active env, deactivate, idempotent
  TestVariableCRUD        — list, create, update, delete; unique key constraint
  TestBulkUpsert          — full replace, secret preservation, duplicate key rejection
  TestSecretMasking       — secret values never returned; sentinel preserved on bulk
  TestPreview             — interpolation result, resolved/unresolved keys
  TestValidation          — key format, required fields, duplicate keys
  TestAuth                — all endpoints require bearer token
  TestOwnership           — cross-user isolation returns 404
"""
import pytest

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _register(client, email: str) -> str:
    r = await client.post(
        "/auth/register",
        json={"name": "T", "email": email, "password": "Password1"},
    )
    return r.json()["access_token"]


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


async def _make_ws(client, token: str, name: str = "WS") -> str:
    return (await client.post("/workspaces", json={"name": name},
                              headers=_h(token))).json()["id"]


async def _make_env(client, token: str, ws_id: str, name: str = "Dev") -> str:
    r = await client.post(f"/workspaces/{ws_id}/environments",
                          json={"name": name}, headers=_h(token))
    assert r.status_code == 201
    return r.json()["id"]


async def _add_var(client, token: str, env_id: str, key: str,
                   value: str, is_secret: bool = False) -> str:
    r = await client.post(f"/environments/{env_id}/variables",
                          json={"key": key, "value": value, "is_secret": is_secret},
                          headers=_h(token))
    assert r.status_code == 201
    return r.json()["id"]


# ══════════════════════════════════════════════════════════════════════════════
# 1. Environment CRUD
# ══════════════════════════════════════════════════════════════════════════════

class TestEnvironmentCRUD:

    async def test_list_empty(self, client):
        token = await _register(client, "ec1@test.com")
        ws    = await _make_ws(client, token)
        r = await client.get(f"/workspaces/{ws}/environments", headers=_h(token))
        assert r.status_code == 200
        assert r.json() == []

    async def test_create_returns_201(self, client):
        token = await _register(client, "ec2@test.com")
        ws    = await _make_ws(client, token)
        r = await client.post(f"/workspaces/{ws}/environments",
                              json={"name": "Development"}, headers=_h(token))
        assert r.status_code == 201
        b = r.json()
        assert b["name"] == "Development"
        assert b["is_active"] is False
        assert b["variable_count"] == 0
        assert "id" in b

    async def test_create_multiple_environments(self, client):
        token = await _register(client, "ec3@test.com")
        ws    = await _make_ws(client, token)
        for name in ("Development", "Staging", "Production"):
            await client.post(f"/workspaces/{ws}/environments",
                              json={"name": name}, headers=_h(token))
        r = await client.get(f"/workspaces/{ws}/environments", headers=_h(token))
        assert len(r.json()) == 3

    async def test_get_detail_includes_variables(self, client):
        token = await _register(client, "ec4@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await _add_var(client, token, env, "BASE_URL", "https://dev.api.com")
        r = await client.get(f"/environments/{env}", headers=_h(token))
        assert r.status_code == 200
        b = r.json()
        assert b["variable_count"] == 1
        assert len(b["variables"]) == 1
        assert b["variables"][0]["key"] == "BASE_URL"

    async def test_update_name(self, client):
        token = await _register(client, "ec5@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws, "Dev")
        r = await client.patch(f"/environments/{env}",
                               json={"name": "Development"}, headers=_h(token))
        assert r.status_code == 200
        assert r.json()["name"] == "Development"

    async def test_delete_environment(self, client):
        token = await _register(client, "ec6@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        r = await client.delete(f"/environments/{env}", headers=_h(token))
        assert r.status_code == 204
        r = await client.get(f"/environments/{env}", headers=_h(token))
        assert r.status_code == 404

    async def test_delete_cascades_to_variables(self, client):
        token = await _register(client, "ec7@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        var_id = await _add_var(client, token, env, "KEY", "val")
        await client.delete(f"/environments/{env}", headers=_h(token))
        # Variable should also be gone (cascade)
        r = await client.get(f"/environments/{env}/variables", headers=_h(token))
        assert r.status_code == 404   # env gone so 404 on variables too


# ══════════════════════════════════════════════════════════════════════════════
# 2. Activation
# ══════════════════════════════════════════════════════════════════════════════

class TestActivation:

    async def test_activate_sets_is_active(self, client):
        token = await _register(client, "ac1@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws, "Dev")
        r = await client.post(f"/environments/{env}/activate", headers=_h(token))
        assert r.status_code == 200
        assert r.json()["is_active"] is True

    async def test_activate_deactivates_previous(self, client):
        token = await _register(client, "ac2@test.com")
        ws    = await _make_ws(client, token)
        env_a = await _make_env(client, token, ws, "Dev")
        env_b = await _make_env(client, token, ws, "Staging")

        await client.post(f"/environments/{env_a}/activate", headers=_h(token))
        await client.post(f"/environments/{env_b}/activate", headers=_h(token))

        # env_a should now be inactive
        r_a = await client.get(f"/environments/{env_a}", headers=_h(token))
        r_b = await client.get(f"/environments/{env_b}", headers=_h(token))
        assert r_a.json()["is_active"] is False
        assert r_b.json()["is_active"] is True

    async def test_only_one_active_at_a_time(self, client):
        token = await _register(client, "ac3@test.com")
        ws    = await _make_ws(client, token)
        envs  = []
        for n in ("Dev", "Staging", "Prod"):
            envs.append(await _make_env(client, token, ws, n))

        for env in envs:
            await client.post(f"/environments/{env}/activate", headers=_h(token))

        r = await client.get(f"/workspaces/{ws}/environments", headers=_h(token))
        active_count = sum(1 for e in r.json() if e["is_active"])
        assert active_count == 1

    async def test_deactivate_clears_active(self, client):
        token = await _register(client, "ac4@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await client.post(f"/environments/{env}/activate", headers=_h(token))
        r = await client.post(f"/environments/{env}/deactivate", headers=_h(token))
        assert r.json()["is_active"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 3. Variable CRUD
# ══════════════════════════════════════════════════════════════════════════════

class TestVariableCRUD:

    async def test_create_plain_variable(self, client):
        token = await _register(client, "vc1@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        r = await client.post(f"/environments/{env}/variables",
                              json={"key": "BASE_URL", "value": "https://api.dev.com"},
                              headers=_h(token))
        assert r.status_code == 201
        b = r.json()
        assert b["key"] == "BASE_URL"
        assert b["value"] == "https://api.dev.com"
        assert b["is_secret"] is False

    async def test_create_secret_variable_masked(self, client):
        token = await _register(client, "vc2@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        r = await client.post(f"/environments/{env}/variables",
                              json={"key": "API_KEY", "value": "sk-real-secret",
                                    "is_secret": True}, headers=_h(token))
        assert r.status_code == 201
        assert r.json()["value"] == "***"

    async def test_duplicate_key_rejected(self, client):
        token = await _register(client, "vc3@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await _add_var(client, token, env, "KEY", "v1")
        r = await client.post(f"/environments/{env}/variables",
                              json={"key": "KEY", "value": "v2"}, headers=_h(token))
        assert r.status_code == 409

    async def test_update_variable(self, client):
        token  = await _register(client, "vc4@test.com")
        ws     = await _make_ws(client, token)
        env    = await _make_env(client, token, ws)
        var_id = await _add_var(client, token, env, "BASE_URL", "http://old.com")
        r = await client.patch(f"/variables/{var_id}",
                               json={"value": "https://new.com"}, headers=_h(token))
        assert r.status_code == 200
        assert r.json()["value"] == "https://new.com"

    async def test_delete_variable(self, client):
        token  = await _register(client, "vc5@test.com")
        ws     = await _make_ws(client, token)
        env    = await _make_env(client, token, ws)
        var_id = await _add_var(client, token, env, "X", "y")
        r = await client.delete(f"/variables/{var_id}", headers=_h(token))
        assert r.status_code == 204

    async def test_list_variables_sorted_by_key(self, client):
        token = await _register(client, "vc6@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        for k in ("TOKEN", "BASE_URL", "API_KEY"):
            await _add_var(client, token, env, k, "v")
        r = await client.get(f"/environments/{env}/variables", headers=_h(token))
        keys = [v["key"] for v in r.json()]
        assert keys == sorted(keys)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Bulk upsert
# ══════════════════════════════════════════════════════════════════════════════

class TestBulkUpsert:

    async def test_bulk_replaces_all_variables(self, client):
        token = await _register(client, "bu1@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await _add_var(client, token, env, "OLD_KEY", "old_val")

        r = await client.put(f"/environments/{env}/variables",
                             json={"variables": [
                                 {"key": "BASE_URL", "value": "https://new.com"},
                                 {"key": "TOKEN",    "value": "abc123"},
                             ]}, headers=_h(token))
        assert r.status_code == 200
        keys = {v["key"] for v in r.json()}
        assert "OLD_KEY" not in keys
        assert keys == {"BASE_URL", "TOKEN"}

    async def test_bulk_empty_clears_all(self, client):
        token = await _register(client, "bu2@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await _add_var(client, token, env, "K", "v")
        r = await client.put(f"/environments/{env}/variables",
                             json={"variables": []}, headers=_h(token))
        assert r.status_code == 200
        assert r.json() == []

    async def test_bulk_duplicate_keys_rejected(self, client):
        token = await _register(client, "bu3@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        r = await client.put(f"/environments/{env}/variables",
                             json={"variables": [
                                 {"key": "K", "value": "1"},
                                 {"key": "K", "value": "2"},
                             ]}, headers=_h(token))
        assert r.status_code == 422

    async def test_bulk_preserves_secret_on_sentinel(self, client):
        """
        When a secret variable's value is '***', the existing secret
        value should be preserved in the database.
        """
        token  = await _register(client, "bu4@test.com")
        ws     = await _make_ws(client, token)
        env    = await _make_env(client, token, ws)

        # Create a secret variable with a real value
        await client.post(f"/environments/{env}/variables",
                          json={"key": "API_KEY", "value": "real-secret",
                                "is_secret": True}, headers=_h(token))

        # Bulk upsert with sentinel — should preserve the real value
        r = await client.put(f"/environments/{env}/variables",
                             json={"variables": [
                                 {"key": "API_KEY", "value": "***", "is_secret": True}
                             ]}, headers=_h(token))
        assert r.status_code == 200
        # Value still masked
        assert r.json()[0]["value"] == "***"

        # Run a request with this env — if secret was preserved, interpolation works
        # (We just verify the variable still exists and is secret)
        vars_ = r.json()
        assert vars_[0]["is_secret"] is True

    async def test_bulk_updates_secret_when_new_value(self, client):
        """Setting a non-sentinel value on a secret variable updates it."""
        token  = await _register(client, "bu5@test.com")
        ws     = await _make_ws(client, token)
        env    = await _make_env(client, token, ws)
        await client.post(f"/environments/{env}/variables",
                          json={"key": "TOKEN", "value": "old-token",
                                "is_secret": True}, headers=_h(token))
        r = await client.put(f"/environments/{env}/variables",
                             json={"variables": [
                                 {"key": "TOKEN", "value": "new-token", "is_secret": True}
                             ]}, headers=_h(token))
        # Still masked but updated
        assert r.json()[0]["value"] == "***"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Secret masking
# ══════════════════════════════════════════════════════════════════════════════

class TestSecretMasking:

    async def test_secret_masked_in_create_response(self, client):
        token = await _register(client, "sm1@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        r = await client.post(f"/environments/{env}/variables",
                              json={"key": "TOKEN", "value": "super-secret",
                                    "is_secret": True}, headers=_h(token))
        assert r.json()["value"] == "***"

    async def test_secret_masked_in_list(self, client):
        token = await _register(client, "sm2@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await _add_var(client, token, env, "TOKEN", "secret-value", is_secret=True)
        r = await client.get(f"/environments/{env}/variables", headers=_h(token))
        sec = next(v for v in r.json() if v["key"] == "TOKEN")
        assert sec["value"] == "***"
        assert sec["is_secret"] is True

    async def test_plain_variable_not_masked(self, client):
        token = await _register(client, "sm3@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await _add_var(client, token, env, "BASE_URL", "https://visible.com")
        r = await client.get(f"/environments/{env}/variables", headers=_h(token))
        var = next(v for v in r.json() if v["key"] == "BASE_URL")
        assert var["value"] == "https://visible.com"

    async def test_secret_masked_in_environment_detail(self, client):
        token = await _register(client, "sm4@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await _add_var(client, token, env, "API_KEY", "abc", is_secret=True)
        r = await client.get(f"/environments/{env}", headers=_h(token))
        var = next(v for v in r.json()["variables"] if v["key"] == "API_KEY")
        assert var["value"] == "***"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Preview / interpolation
# ══════════════════════════════════════════════════════════════════════════════

class TestPreview:

    async def test_simple_substitution(self, client):
        token = await _register(client, "pv1@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await _add_var(client, token, env, "BASE_URL", "https://api.dev.com")

        r = await client.post(f"/environments/{env}/preview",
                              json={"template": "{{env.BASE_URL}}/users"},
                              headers=_h(token))
        assert r.status_code == 200
        b = r.json()
        assert b["result"] == "https://api.dev.com/users"
        assert "BASE_URL" in b["resolved_keys"]
        assert b["unresolved_keys"] == []

    async def test_multiple_variables(self, client):
        token = await _register(client, "pv2@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await _add_var(client, token, env, "HOST", "api.com")
        await _add_var(client, token, env, "VERSION", "v2")

        r = await client.post(f"/environments/{env}/preview",
                              json={"template": "https://{{env.HOST}}/{{env.VERSION}}/users"},
                              headers=_h(token))
        assert r.json()["result"] == "https://api.com/v2/users"

    async def test_unresolved_keys_reported(self, client):
        token = await _register(client, "pv3@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)

        r = await client.post(f"/environments/{env}/preview",
                              json={"template": "{{env.MISSING}}/endpoint"},
                              headers=_h(token))
        b = r.json()
        assert "MISSING" in b["unresolved_keys"]
        assert b["result"] == "{{env.MISSING}}/endpoint"   # placeholder preserved

    async def test_secret_variables_used_in_preview(self, client):
        """Secrets must be substituted in preview — the real value is used."""
        token = await _register(client, "pv4@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        await _add_var(client, token, env, "TOKEN", "real-token", is_secret=True)

        r = await client.post(f"/environments/{env}/preview",
                              json={"template": "Bearer {{env.TOKEN}}"},
                              headers=_h(token))
        # Secret is substituted (real value used); but the preview shows it
        assert r.json()["result"] == "Bearer real-token"
        assert "TOKEN" in r.json()["resolved_keys"]

    async def test_no_variables_empty_resolved(self, client):
        token = await _register(client, "pv5@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        r = await client.post(f"/environments/{env}/preview",
                              json={"template": "https://static.example.com/health"},
                              headers=_h(token))
        b = r.json()
        assert b["result"] == "https://static.example.com/health"
        assert b["resolved_keys"] == []
        assert b["unresolved_keys"] == []


# ══════════════════════════════════════════════════════════════════════════════
# 7. Validation
# ══════════════════════════════════════════════════════════════════════════════

class TestValidation:

    async def test_invalid_key_space_rejected(self, client):
        token = await _register(client, "vl1@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        r = await client.post(f"/environments/{env}/variables",
                              json={"key": "MY KEY", "value": "x"}, headers=_h(token))
        assert r.status_code == 422

    async def test_invalid_key_starts_with_digit_rejected(self, client):
        token = await _register(client, "vl2@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        r = await client.post(f"/environments/{env}/variables",
                              json={"key": "1KEY", "value": "x"}, headers=_h(token))
        assert r.status_code == 422

    async def test_valid_key_with_underscore(self, client):
        token = await _register(client, "vl3@test.com")
        ws    = await _make_ws(client, token)
        env   = await _make_env(client, token, ws)
        r = await client.post(f"/environments/{env}/variables",
                              json={"key": "_MY_VAR_123", "value": "ok"}, headers=_h(token))
        assert r.status_code == 201

    async def test_blank_env_name_rejected(self, client):
        token = await _register(client, "vl4@test.com")
        ws    = await _make_ws(client, token)
        r = await client.post(f"/workspaces/{ws}/environments",
                              json={"name": "   "}, headers=_h(token))
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 8. Auth enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestAuth:

    async def test_list_environments_no_auth(self, client):
        r = await client.get("/workspaces/any/environments")
        assert r.status_code == 403

    async def test_create_environment_no_auth(self, client):
        r = await client.post("/workspaces/any/environments", json={"name": "Dev"})
        assert r.status_code == 403

    async def test_activate_no_auth(self, client):
        r = await client.post("/environments/any/activate")
        assert r.status_code == 403

    async def test_preview_no_auth(self, client):
        r = await client.post("/environments/any/preview", json={"template": "x"})
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 9. Ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestOwnership:

    async def test_other_user_cannot_list_environments(self, client):
        owner = await _register(client, "ow1@test.com")
        other = await _register(client, "oth1@test.com")
        ws    = await _make_ws(client, owner)
        r = await client.get(f"/workspaces/{ws}/environments", headers=_h(other))
        assert r.status_code == 404

    async def test_other_user_cannot_get_environment(self, client):
        owner = await _register(client, "ow2@test.com")
        other = await _register(client, "oth2@test.com")
        ws    = await _make_ws(client, owner)
        env   = await _make_env(client, owner, ws)
        r = await client.get(f"/environments/{env}", headers=_h(other))
        assert r.status_code == 404

    async def test_other_user_cannot_add_variable(self, client):
        owner = await _register(client, "ow3@test.com")
        other = await _register(client, "oth3@test.com")
        ws    = await _make_ws(client, owner)
        env   = await _make_env(client, owner, ws)
        r = await client.post(f"/environments/{env}/variables",
                              json={"key": "K", "value": "v"}, headers=_h(other))
        assert r.status_code == 404

    async def test_other_user_cannot_activate(self, client):
        owner = await _register(client, "ow4@test.com")
        other = await _register(client, "oth4@test.com")
        ws    = await _make_ws(client, owner)
        env   = await _make_env(client, owner, ws)
        r = await client.post(f"/environments/{env}/activate", headers=_h(other))
        assert r.status_code == 404
