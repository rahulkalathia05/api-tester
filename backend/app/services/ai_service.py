"""
AI Failure Analysis service.

Architecture
────────────
  AiService.analyze()          ← router calls this
      │
      ├─ _load_result()         ownership check + eager-load assertion_results
      ├─ _build_prompt()        structures all failure data for the model
      ├─ _call_openai()         JSON-mode completion, returns raw dict
      ├─ _parse_response()      validates + fills in missing keys
      └─ _persist()             upsert AiAnalysis row, return schema

Prompt design
─────────────
The user prompt sends every piece of failure evidence in labelled sections so
the model can reason about specific patterns (auth error, schema mismatch,
slow upstream, DNS failure, etc.) rather than giving generic advice.

Large fields are truncated at ingest so the prompt stays within a predictable
token budget (≈ 1 200 tokens input, ≈ 600 tokens output → ~$0.0003 per call
with gpt-4o-mini at current pricing).

Output schema (JSON mode enforced)
────────────────────────────────────
{
  "summary": str,                       one-sentence diagnosis
  "root_causes": [                      ordered most-likely first
    {"title": str, "description": str, "confidence": "high"|"medium"|"low"}
  ],
  "debugging_steps": [                  concrete, numbered, prioritised
    {"step": int, "action": str, "detail": str}
  ],
  "likely_fixes": [
    {"title": str, "description": str, "code": str | null}
  ]
}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.openai_client import create_openai_client
from app.models.ai_analysis import AiAnalysis
from app.models.assertion_result import AssertionResult
from app.models.test_result import TestResult
from app.models.test_run import TestRun
from app.models.workspace import Workspace
from app.schemas.runner import AiAnalysisOut

logger = logging.getLogger(__name__)

# ── Truncation limits to keep prompt inside a predictable token budget ────────
_MAX_BODY    = 2_000
_MAX_HEADERS = 800
_MAX_URL     = 300


# ── Prompt builder ────────────────────────────────────────────────────────────

_SYSTEM = """You are an expert API debugging assistant embedded in an API testing platform.

Your job is to analyse a failed API test and give the developer precise, actionable guidance.

Rules:
- Be specific. Reference the actual status codes, values, and paths from the data.
- Do not repeat the same point across sections.
- Order root_causes from most likely to least likely.
- Keep debugging_steps sequential and concrete — each one should move the developer closer to a fix.
- Include a code snippet in likely_fixes only when it materially helps; set "code" to null otherwise.
- Respond with valid JSON only — no prose, no markdown fences.
"""


def _truncate(s: str | None, limit: int) -> str:
    if not s:
        return "(empty)"
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n… [truncated — {len(s) - limit} chars omitted]"


def _fmt_headers(headers: dict) -> str:
    if not headers:
        return "(none)"
    lines = [f"  {k}: {v}" for k, v in list(headers.items())[:15]]
    if len(headers) > 15:
        lines.append(f"  … and {len(headers) - 15} more")
    return "\n".join(lines)


def _fmt_assertion_failures(assertion_results: list) -> str:
    failures = [ar for ar in assertion_results if not ar.passed]
    if not failures:
        return "(no assertion failures — the request itself errored)"

    lines = []
    for ar in failures:
        snap = ar.assertion_snapshot
        line = (
            f"  • [{snap['type']}] "
            f"expected {snap['operator']} {snap['expected_value']!r}"
        )
        if snap.get("path"):
            line += f"  at path {snap['path']!r}"
        if ar.actual_value is not None:
            line += f"  →  actual: {ar.actual_value!r}"
        if ar.error_message:
            line += f"  →  error: {ar.error_message}"
        lines.append(line)
    return "\n".join(lines)


def _build_prompt(result: TestResult) -> str:
    snap = result.request_snapshot or {}
    req_headers = snap.get("headers", {})
    req_body    = snap.get("body")

    resp_headers = result.response_headers or {}
    resp_body    = result.response_body

    failure_section = _fmt_assertion_failures(result.assertion_results)

    # Determine what the failing assertions expected (for context)
    expected_status = "—"
    for ar in result.assertion_results:
        s = ar.assertion_snapshot
        if s.get("type") == "status_code" and not ar.passed:
            expected_status = f"{s['operator']} {s['expected_value']}"
            break

    prompt = f"""## Failed API Test — Analysis Request

### Request
- Method : {snap.get('method', '?')}
- URL    : {_truncate(snap.get('url', '?'), _MAX_URL)}
- Auth   : {snap.get('auth_type', 'none')}
- Headers:
{_fmt_headers(req_headers)}
- Body ({snap.get('body_type', 'none')}):
{_truncate(req_body, _MAX_BODY // 2)}

### Response
- Status code  : {result.response_status} (assertion expected: {expected_status})
- Response time: {result.response_time_ms}ms
- Headers:
{_fmt_headers(resp_headers)}
- Body:
{_truncate(resp_body, _MAX_BODY)}

### Assertion Failures
{failure_section}
"""

    if result.error_message:
        prompt += f"\n### Connection / Execution Error\n{result.error_message}\n"

    prompt += f"""
### Your Task
Analyse the failure above and respond with JSON matching this exact schema:

{{
  "summary": "<one sentence: what went wrong and the single most likely reason>",
  "root_causes": [
    {{"title": "...", "description": "...", "confidence": "high"|"medium"|"low"}}
  ],
  "debugging_steps": [
    {{"step": 1, "action": "...", "detail": "..."}}
  ],
  "likely_fixes": [
    {{"title": "...", "description": "...", "code": "..." | null}}
  ]
}}

Constraints:
- root_causes: 1–4 items, ordered by likelihood
- debugging_steps: 2–5 items, in execution order
- likely_fixes: 1–3 items, most impactful first
- All fields required. code may be null.
"""
    return prompt


# ── OpenAI call ───────────────────────────────────────────────────────────────

async def _call_openai(prompt: str) -> tuple[dict, int, int]:
    """
    Call the model in JSON mode.
    Returns (parsed_dict, prompt_tokens, completion_tokens).
    """
    client = create_openai_client()
    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.2,   # low temp → reproducible, focused answers
            max_tokens=800,
        )
        content = response.choices[0].message.content or "{}"
        usage   = response.usage
        return (
            json.loads(content),
            usage.prompt_tokens     if usage else 0,
            usage.completion_tokens if usage else 0,
        )
    finally:
        await client.close()


# ── Response validation ───────────────────────────────────────────────────────

def _parse_response(raw: dict) -> dict:
    """
    Normalise the model output so the DB row always has every key.
    Fills in empty placeholders if the model omits a field.
    """
    def _ensure_list(val, key: str) -> list:
        if isinstance(val, list):
            return val
        logger.warning("AI response missing or invalid field %r", key)
        return []

    return {
        "summary":          raw.get("summary", "Analysis could not be completed."),
        "root_causes":      _ensure_list(raw.get("root_causes"), "root_causes"),
        "debugging_steps":  _ensure_list(raw.get("debugging_steps"), "debugging_steps"),
        "likely_fixes":     _ensure_list(raw.get("likely_fixes"), "likely_fixes"),
    }


# ── Service ───────────────────────────────────────────────────────────────────

class AiService:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _load_result(self, result_id: str, user_id: str) -> TestResult:
        """Load TestResult with assertion_results; verify workspace ownership."""
        row = await self._db.execute(
            select(TestResult)
            .join(TestRun,   TestRun.id   == TestResult.test_run_id)
            .join(Workspace, Workspace.id == TestRun.workspace_id)
            .where(TestResult.id == result_id, Workspace.user_id == user_id)
            .options(selectinload(TestResult.assertion_results))
        )
        result = row.scalar_one_or_none()
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Test result not found")
        return result

    async def _load_existing(self, result_id: str) -> AiAnalysis | None:
        row = await self._db.execute(
            select(AiAnalysis).where(AiAnalysis.test_result_id == result_id)
        )
        return row.scalar_one_or_none()

    async def analyze(
        self,
        result_id: str,
        user_id: str,
        force: bool = False,
    ) -> AiAnalysisOut:
        """
        Generate (or return cached) AI analysis for a failed test result.

        Only available for status=failed|error results. Passed results are
        excluded — there is no failure to analyse.

        If an analysis already exists and force=False (default), the cached
        analysis is returned immediately without calling OpenAI.
        """
        # Ownership + status checks run first so they return the correct HTTP
        # status regardless of whether an API key is configured.
        result = await self._load_result(result_id, user_id)

        if result.status == "passed":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="AI analysis is only available for failed or errored results.",
            )

        # Return cached analysis unless force=True (no API call needed).
        existing = await self._load_existing(result_id)
        if existing and not force:
            return AiAnalysisOut.model_validate(existing)

        # API key check deferred to here — after ownership/status, before the
        # actual OpenAI call — so unknown result → 404 and passed → 422 still
        # work without a key configured.
        if not settings.OPENAI_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI analysis is not available — OPENAI_API_KEY is not configured.",
            )

        # ── Build prompt and call the model ───────────────────────────────────
        prompt = _build_prompt(result)

        logger.info(
            "Requesting AI analysis for result %s (force=%s)",
            result_id, force,
            extra={"result_id": result_id},
        )

        try:
            raw, prompt_tokens, completion_tokens = await _call_openai(prompt)
        except Exception as exc:
            logger.exception("OpenAI call failed for result %s", result_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI analysis request failed: {exc}",
            )

        parsed = _parse_response(raw)

        logger.info(
            "AI analysis complete for result %s — %d prompt + %d completion tokens",
            result_id, prompt_tokens, completion_tokens,
            extra={"result_id": result_id,
                   "prompt_tokens": prompt_tokens,
                   "completion_tokens": completion_tokens},
        )

        # ── Persist (upsert) ──────────────────────────────────────────────────
        if existing:
            existing.model            = settings.OPENAI_MODEL
            existing.analysis         = parsed["summary"]
            existing.suggestions      = _to_suggestions(parsed)
            existing.prompt_tokens    = prompt_tokens
            existing.completion_tokens = completion_tokens
            existing.created_at       = datetime.now(timezone.utc)
            analysis = existing
        else:
            analysis = AiAnalysis(
                test_result_id=result_id,
                model=settings.OPENAI_MODEL,
                analysis=parsed["summary"],
                suggestions=_to_suggestions(parsed),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            self._db.add(analysis)

        await self._db.flush()

        # Return the full structured response (not just the summary stored in DB)
        return AiAnalysisOut(
            id=analysis.id,
            test_result_id=result_id,
            model=analysis.model,
            summary=parsed["summary"],
            root_causes=parsed["root_causes"],
            debugging_steps=parsed["debugging_steps"],
            likely_fixes=parsed["likely_fixes"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            created_at=analysis.created_at,
        )

    async def get_analysis(self, result_id: str, user_id: str) -> AiAnalysisOut:
        """Return a previously generated analysis, or 404 if not yet run."""
        # Verify the result exists and belongs to the user
        await self._load_result(result_id, user_id)

        existing = await self._load_existing(result_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No analysis found for this result. "
                       "POST /results/{id}/analyze to generate one.",
            )
        return AiAnalysisOut.model_validate(existing)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_suggestions(parsed: dict) -> list[dict]:
    """
    Flatten the structured output into the `suggestions` JSON column.

    The AiAnalysis model stores a flat `suggestions` list for backward compat.
    The full structured output (root_causes, debugging_steps, likely_fixes)
    is returned live from the service and does not need to fit the DB schema.
    """
    items: list[dict] = []
    for rc in parsed.get("root_causes", []):
        items.append({"section": "root_cause",      **rc})
    for ds in parsed.get("debugging_steps", []):
        items.append({"section": "debugging_step",  **ds})
    for fix in parsed.get("likely_fixes", []):
        items.append({"section": "likely_fix",      **fix})
    return items
