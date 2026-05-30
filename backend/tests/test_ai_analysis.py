"""
AI Failure Analysis tests.

Structure:
  TestPromptBuilder    — unit tests on _build_prompt() (no I/O)
  TestAiAnalyzeEndpoint — POST /results/{id}/analyze with mocked OpenAI
  TestAiGetEndpoint    — GET /results/{id}/analysis
  TestAiEdgeCases      — passed results rejected, no API key, idempotency, force
  TestAiAuth           — endpoints require bearer token
  TestAiOwnership      — cross-user isolation

OpenAI is mocked via unittest.mock.patch so no real API calls are made.
The mock returns a deterministic structured response that matches the expected
JSON schema.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio

# ── Shared fake OpenAI response ───────────────────────────────────────────────

FAKE_ANALYSIS = {
    "summary": "The API returned 404 because the user ID does not exist in the database.",
    "root_causes": [
        {
            "title": "Resource not found",
            "description": "The user with the given ID was deleted or never created.",
            "confidence": "high",
        },
        {
            "title": "Wrong endpoint path",
            "description": "The URL may contain a typo in the resource path.",
            "confidence": "low",
        },
    ],
    "debugging_steps": [
        {
            "step": 1,
            "action": "Verify the user ID exists",
            "detail": "Run a GET /users query and confirm the ID is present.",
        },
        {
            "step": 2,
            "action": "Check server logs",
            "detail": "Look for the 404 handler in the API server logs for the exact path.",
        },
    ],
    "likely_fixes": [
        {
            "title": "Use a valid user ID",
            "description": "Create the user first, then reference its ID in this request.",
            "code": 'user = client.post("/users", json={"name": "test"}).json()\nuser_id = user["id"]',
        },
    ],
}


def _make_openai_mock(content: dict | None = None):
    """Build a mock that mimics the openai AsyncOpenAI client."""
    import json

    payload = content if content is not None else FAKE_ANALYSIS

    mock_message  = MagicMock()
    mock_message.content = json.dumps(payload)

    mock_choice   = MagicMock()
    mock_choice.message = mock_message

    mock_usage    = MagicMock()
    mock_usage.prompt_tokens     = 350
    mock_usage.completion_tokens = 220

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage   = mock_usage

    mock_completions = MagicMock()
    mock_completions.create = AsyncMock(return_value=mock_response)

    mock_chat = MagicMock()
    mock_chat.completions = mock_completions

    mock_client = MagicMock()
    mock_client.chat  = mock_chat
    mock_client.close = AsyncMock()

    return mock_client


# ── Helpers ───────────────────────────────────────────────────────────────────

# Patch target for OpenAI API key presence check
_SETTINGS_PATH = "app.services.ai_service.settings"
_CLIENT_PATH   = "app.services.ai_service.create_openai_client"


class _ai_mock:
    """
    Context manager that patches both the settings (to fake a valid API key)
    and the OpenAI client factory (to return a deterministic mock response).
    Avoids repeating two `with patch(...)` blocks in every test.
    """
    def __init__(self, response: dict | None = None):
        self._response = response
        self._patches  = []

    def __enter__(self):
        import unittest.mock as m

        mock_settings = m.MagicMock()
        mock_settings.OPENAI_API_KEY       = "sk-test-key"
        mock_settings.OPENAI_MODEL         = "gpt-4o-mini"
        mock_settings.OPENAI_REQUEST_TIMEOUT = 60.0

        p1 = patch(_SETTINGS_PATH, mock_settings)
        p2 = patch(_CLIENT_PATH, return_value=_make_openai_mock(self._response))
        self._patches = [p1, p2]
        [p.__enter__() for p in self._patches]
        return self

    def __exit__(self, *args):
        [p.__exit__(*args) for p in self._patches]


async def _register(client, email: str) -> str:
    r = await client.post(
        "/auth/register",
        json={"name": "T", "email": email, "password": "Password1"},
    )
    return r.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_failed_result(client, token: str) -> tuple[str, str]:
    """
    Register, workspace, collection, request, add an assertion, run it (mocked
    to fail), and return (run_id, result_id).
    """
    h = _h(token)
    ws_id  = (await client.post("/workspaces", json={"name": "W"}, headers=h)).json()["id"]
    col_id = (await client.post(f"/workspaces/{ws_id}/collections",
                                json={"name": "C"}, headers=h)).json()["id"]
    req_id = (await client.post(f"/collections/{col_id}/requests",
                                json={"name": "R", "method": "GET",
                                      "url": "https://api.example.com/users/999"},
                                headers=h)).json()["id"]
    # assertion that will fail (expects 200, mock returns 404)
    await client.post(f"/requests/{req_id}/assertions",
                      json={"type": "status_code", "operator": "eq",
                            "expected_value": "200"}, headers=h)

    from app.services.runner_service import HttpResult
    mock_result = HttpResult(
        status_code=404,
        headers={"content-type": "application/json"},
        body='{"error": "User not found"}',
        response_time_ms=87,
        error=None,
    )
    with patch("app.services.runner_service.execute_http", return_value=mock_result):
        run_r = await client.post(f"/requests/{req_id}/run", json={}, headers=h)

    result_id = run_r.json()["id"]
    run_id    = run_r.json()["test_run_id"]
    return run_id, result_id


async def _create_passed_result(client, token: str) -> str:
    """Run a request that passes all assertions."""
    h = _h(token)
    ws_id  = (await client.post("/workspaces", json={"name": "WP"}, headers=h)).json()["id"]
    col_id = (await client.post(f"/workspaces/{ws_id}/collections",
                                json={"name": "C"}, headers=h)).json()["id"]
    req_id = (await client.post(f"/collections/{col_id}/requests",
                                json={"name": "R", "method": "GET",
                                      "url": "https://api.example.com/health"},
                                headers=h)).json()["id"]
    await client.post(f"/requests/{req_id}/assertions",
                      json={"type": "status_code", "operator": "eq",
                            "expected_value": "200"}, headers=h)

    from app.services.runner_service import HttpResult
    mock_ok = HttpResult(
        status_code=200, headers={}, body='{"status": "ok"}',
        response_time_ms=20, error=None,
    )
    with patch("app.services.runner_service.execute_http", return_value=mock_ok):
        run_r = await client.post(f"/requests/{req_id}/run", json={}, headers=h)
    return run_r.json()["id"]  # result_id


# ══════════════════════════════════════════════════════════════════════════════
# 1. Prompt builder — pure unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPromptBuilder:

    def _make_result(self, **kwargs):
        result = MagicMock()
        result.request_snapshot = {
            "method": "GET",
            "url": "https://api.example.com/users/999",
            "headers": {"Authorization": "Bearer token"},
            "body": None,
            "body_type": "none",
            "auth_type": "bearer",
        }
        result.response_status  = kwargs.get("status", 404)
        result.response_headers = {"content-type": "application/json"}
        result.response_body    = kwargs.get("body", '{"error": "not found"}')
        result.response_time_ms = kwargs.get("ms", 87)
        result.error_message    = kwargs.get("error")
        result.status           = kwargs.get("result_status", "failed")

        # Assertion results
        ar = MagicMock()
        ar.passed = False
        ar.assertion_snapshot = {
            "type": "status_code", "operator": "eq",
            "expected_value": "200", "path": None,
        }
        ar.actual_value  = "404"
        ar.error_message = None
        result.assertion_results = [ar]
        return result

    def test_prompt_contains_method(self):
        from app.services.ai_service import _build_prompt
        p = _build_prompt(self._make_result())
        assert "GET" in p

    def test_prompt_contains_url(self):
        from app.services.ai_service import _build_prompt
        p = _build_prompt(self._make_result())
        assert "api.example.com/users/999" in p

    def test_prompt_contains_status_code(self):
        from app.services.ai_service import _build_prompt
        p = _build_prompt(self._make_result(status=404))
        assert "404" in p

    def test_prompt_contains_response_body(self):
        from app.services.ai_service import _build_prompt
        p = _build_prompt(self._make_result(body='{"error": "not found"}'))
        assert "not found" in p

    def test_prompt_shows_assertion_failure(self):
        from app.services.ai_service import _build_prompt
        p = _build_prompt(self._make_result())
        assert "status_code" in p
        assert "eq" in p
        assert "200" in p  # expected
        assert "404" in p  # actual

    def test_prompt_shows_error_section_when_connection_failed(self):
        from app.services.ai_service import _build_prompt
        p = _build_prompt(self._make_result(error="Connection refused"))
        assert "Connection refused" in p

    def test_long_body_truncated(self):
        from app.services.ai_service import _build_prompt, _MAX_BODY
        big_body = "x" * (_MAX_BODY * 3)
        p = _build_prompt(self._make_result(body=big_body))
        assert "truncated" in p

    def test_json_schema_in_prompt(self):
        from app.services.ai_service import _build_prompt
        p = _build_prompt(self._make_result())
        assert "root_causes" in p
        assert "debugging_steps" in p
        assert "likely_fixes" in p
        assert "summary" in p


# ══════════════════════════════════════════════════════════════════════════════
# 2. POST /results/{id}/analyze
# ══════════════════════════════════════════════════════════════════════════════

class TestAiAnalyzeEndpoint:

    async def test_returns_201_with_structured_output(self, client):
        token = await _register(client, "ai1@test.com")
        _, result_id = await _create_failed_result(client, token)

        with _ai_mock():
            r = await client.post(f"/results/{result_id}/analyze",
                                  headers=_h(token))

        assert r.status_code == 201
        body = r.json()
        assert body["summary"] == FAKE_ANALYSIS["summary"]
        assert len(body["root_causes"]) == 2
        assert len(body["debugging_steps"]) == 2
        assert len(body["likely_fixes"]) == 1
        assert body["test_result_id"] == result_id

    async def test_root_cause_has_confidence(self, client):
        token = await _register(client, "ai2@test.com")
        _, result_id = await _create_failed_result(client, token)

        with _ai_mock():
            r = await client.post(f"/results/{result_id}/analyze",
                                  headers=_h(token))

        rc = r.json()["root_causes"][0]
        assert rc["confidence"] in ("high", "medium", "low")
        assert "title" in rc
        assert "description" in rc

    async def test_debugging_steps_are_numbered(self, client):
        token = await _register(client, "ai3@test.com")
        _, result_id = await _create_failed_result(client, token)

        with _ai_mock():
            r = await client.post(f"/results/{result_id}/analyze",
                                  headers=_h(token))

        steps = r.json()["debugging_steps"]
        assert all("step" in s and "action" in s and "detail" in s for s in steps)

    async def test_likely_fix_has_code_snippet(self, client):
        token = await _register(client, "ai4@test.com")
        _, result_id = await _create_failed_result(client, token)

        with _ai_mock():
            r = await client.post(f"/results/{result_id}/analyze",
                                  headers=_h(token))

        fix = r.json()["likely_fixes"][0]
        assert "title" in fix and "description" in fix
        # code may be a string or null
        assert "code" in fix

    async def test_token_counts_stored(self, client):
        token = await _register(client, "ai5@test.com")
        _, result_id = await _create_failed_result(client, token)

        with _ai_mock():
            r = await client.post(f"/results/{result_id}/analyze",
                                  headers=_h(token))

        body = r.json()
        assert body["prompt_tokens"]     == 350
        assert body["completion_tokens"] == 220

    async def test_model_field_present(self, client):
        token = await _register(client, "ai6@test.com")
        _, result_id = await _create_failed_result(client, token)

        with _ai_mock():
            r = await client.post(f"/results/{result_id}/analyze",
                                  headers=_h(token))

        assert "model" in r.json()
        assert r.json()["model"] != ""


# ══════════════════════════════════════════════════════════════════════════════
# 3. GET /results/{id}/analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestAiGetEndpoint:

    async def test_returns_404_before_analysis_run(self, client):
        token = await _register(client, "ag1@test.com")
        _, result_id = await _create_failed_result(client, token)

        r = await client.get(f"/results/{result_id}/analysis", headers=_h(token))
        assert r.status_code == 404

    async def test_returns_analysis_after_post(self, client):
        token = await _register(client, "ag2@test.com")
        _, result_id = await _create_failed_result(client, token)

        with _ai_mock():
            await client.post(f"/results/{result_id}/analyze", headers=_h(token))

        r = await client.get(f"/results/{result_id}/analysis", headers=_h(token))
        assert r.status_code == 200
        assert r.json()["summary"] == FAKE_ANALYSIS["summary"]

    async def test_get_returns_same_data_as_post(self, client):
        token = await _register(client, "ag3@test.com")
        _, result_id = await _create_failed_result(client, token)

        with _ai_mock():
            post_body = (await client.post(f"/results/{result_id}/analyze",
                                           headers=_h(token))).json()

        get_body = (await client.get(f"/results/{result_id}/analysis",
                                     headers=_h(token))).json()

        assert post_body["summary"] == get_body["summary"]
        assert post_body["id"] == get_body["id"]


# ══════════════════════════════════════════════════════════════════════════════
# 4. Edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestAiEdgeCases:

    async def test_passed_result_rejected_with_422(self, client):
        token = await _register(client, "ae1@test.com")
        result_id = await _create_passed_result(client, token)

        r = await client.post(f"/results/{result_id}/analyze", headers=_h(token))
        assert r.status_code == 422
        assert "failed" in r.json()["detail"].lower() or "passed" in r.json()["detail"].lower()

    async def test_missing_api_key_returns_503(self, client):
        token = await _register(client, "ae2@test.com")
        _, result_id = await _create_failed_result(client, token)

        with patch("app.services.ai_service.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_MODEL   = "gpt-4o-mini"
            mock_settings.OPENAI_REQUEST_TIMEOUT = 60.0
            r = await client.post(f"/results/{result_id}/analyze", headers=_h(token))

        assert r.status_code == 503

    async def test_idempotent_second_call_returns_cached(self, client):
        """Second POST should return the cached analysis without calling OpenAI again."""
        token = await _register(client, "ae3@test.com")
        _, result_id = await _create_failed_result(client, token)

        call_count = 0
        original_mock = _make_openai_mock()
        original_create = original_mock.chat.completions.create

        async def counting_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return await original_create(*args, **kwargs)

        original_mock.chat.completions.create = counting_create

        import unittest.mock as m
        mock_settings = m.MagicMock()
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.OPENAI_MODEL   = "gpt-4o-mini"
        mock_settings.OPENAI_REQUEST_TIMEOUT = 60.0

        with patch(_SETTINGS_PATH, mock_settings), \
             patch(_CLIENT_PATH, return_value=original_mock):
            r1 = await client.post(f"/results/{result_id}/analyze", headers=_h(token))
            r2 = await client.post(f"/results/{result_id}/analyze", headers=_h(token))

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert call_count == 1   # OpenAI called only once; second returns cache
        assert r1.json()["id"] == r2.json()["id"]

    async def test_force_reruns_analysis(self, client):
        """force=true should call OpenAI even if analysis exists."""
        token = await _register(client, "ae4@test.com")
        _, result_id = await _create_failed_result(client, token)

        call_count = 0

        def counting_mock():
            nonlocal call_count
            m = _make_openai_mock()
            original = m.chat.completions.create

            async def _counted(*a, **kw):
                nonlocal call_count
                call_count += 1
                return await original(*a, **kw)

            m.chat.completions.create = _counted
            return m

        import unittest.mock as m
        mock_settings = m.MagicMock()
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.OPENAI_MODEL   = "gpt-4o-mini"
        mock_settings.OPENAI_REQUEST_TIMEOUT = 60.0

        with patch(_SETTINGS_PATH, mock_settings), \
             patch(_CLIENT_PATH, side_effect=counting_mock):
            await client.post(f"/results/{result_id}/analyze", headers=_h(token))
            await client.post(f"/results/{result_id}/analyze?force=true", headers=_h(token))

        assert call_count == 2  # both calls hit OpenAI

    async def test_unknown_result_returns_404(self, client):
        token = await _register(client, "ae5@test.com")
        r = await client.post("/results/nonexistent-id/analyze", headers=_h(token))
        assert r.status_code == 404

    async def test_openai_failure_returns_502(self, client):
        token = await _register(client, "ae6@test.com")
        _, result_id = await _create_failed_result(client, token)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Connection error")
        )
        mock_client.close = AsyncMock()

        import unittest.mock as m
        mock_settings = m.MagicMock()
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.OPENAI_MODEL   = "gpt-4o-mini"
        mock_settings.OPENAI_REQUEST_TIMEOUT = 60.0

        with patch(_SETTINGS_PATH, mock_settings), \
             patch(_CLIENT_PATH, return_value=mock_client):
            r = await client.post(f"/results/{result_id}/analyze", headers=_h(token))

        assert r.status_code == 502


# ══════════════════════════════════════════════════════════════════════════════
# 5. Auth enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestAiAuth:

    async def test_analyze_requires_bearer(self, client):
        r = await client.post("/results/any-id/analyze")
        assert r.status_code == 403

    async def test_get_analysis_requires_bearer(self, client):
        r = await client.get("/results/any-id/analysis")
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 6. Cross-user ownership
# ══════════════════════════════════════════════════════════════════════════════

class TestAiOwnership:

    async def test_other_user_cannot_analyze_result(self, client):
        owner = await _register(client, "own_ai1@test.com")
        other = await _register(client, "oth_ai1@test.com")
        _, result_id = await _create_failed_result(client, owner)

        with _ai_mock():
            r = await client.post(f"/results/{result_id}/analyze", headers=_h(other))

        assert r.status_code == 404

    async def test_other_user_cannot_get_analysis(self, client):
        owner = await _register(client, "own_ai2@test.com")
        other = await _register(client, "oth_ai2@test.com")
        _, result_id = await _create_failed_result(client, owner)

        with _ai_mock():
            await client.post(f"/results/{result_id}/analyze", headers=_h(owner))

        r = await client.get(f"/results/{result_id}/analysis", headers=_h(other))
        assert r.status_code == 404
