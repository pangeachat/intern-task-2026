"""System prompt and LLM interaction for language feedback."""

import asyncio
import json
import os
import time
from typing import Any

from fastapi import HTTPException
from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.models import FeedbackRequest, FeedbackResponse

SYSTEM_PROMPT = """\
You are an expert multilingual writing tutor.
Return feedback for ONE learner sentence in strict JSON only.

GOAL:
- Minimize edits and preserve learner voice.
- Identify real linguistic errors only.
- Explain each error in the learner's native language.

OUTPUT RULES (must follow exactly):
1) If the sentence is already correct:
   - "is_correct": true
   - "errors": []
   - "corrected_sentence": EXACTLY the original sentence (same script/punctuation).
2) If there are errors:
   - "is_correct": false
   - "errors": one item per meaningful issue.
3) "error_type" must be one of:
   grammar, spelling, word_choice, punctuation, word_order, missing_word,
   extra_word, conjugation, gender_agreement, number_agreement, tone_register, other
4) "difficulty" must be one of: A1, A2, B1, B2, C1, C2
   and reflects sentence complexity, not correctness.
5) "original" and "correction" should be short spans, not full-sentence rewrites.
6) "explanation" must be concise, friendly, and in the native language.
7) Never include markdown fences, prose outside JSON, or extra keys.
"""

MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "700"))
MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "1"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "12"))
ENDPOINT_TIMEOUT_SECONDS = float(os.getenv("FEEDBACK_TOTAL_TIMEOUT_SECONDS", "28"))
CACHE_TTL_SECONDS = int(os.getenv("FEEDBACK_CACHE_TTL_SECONDS", "300"))

_response_cache: dict[tuple[str, str, str], tuple[float, FeedbackResponse]] = {}


def _cache_key(request: FeedbackRequest) -> tuple[str, str, str]:
    return (
        request.sentence.strip(),
        request.target_language.strip().lower(),
        request.native_language.strip().lower(),
    )


def _normalize_feedback(
    request: FeedbackRequest, llm_payload: dict[str, Any]
) -> FeedbackResponse:
    normalized_payload = dict(llm_payload)
    errors = normalized_payload.get("errors")
    has_errors = isinstance(errors, list) and len(errors) > 0

    if has_errors:
        normalized_payload["is_correct"] = False
    else:
        normalized_payload["errors"] = []
        normalized_payload["is_correct"] = True
        normalized_payload["corrected_sentence"] = request.sentence

    return FeedbackResponse(**normalized_payload)


def _extract_json(response_content: Any) -> dict[str, Any]:
    if response_content is None:
        raise ValueError("Model returned empty response")
    if not isinstance(response_content, str):
        raise ValueError("Model response content was not a JSON string")
    return json.loads(response_content)


async def _request_feedback_from_llm(
    client: AsyncOpenAI, request: FeedbackRequest
) -> FeedbackResponse:
    user_message = (
        f"Target language: {request.target_language}\n"
        f"Native language: {request.native_language}\n"
        f"Sentence: {request.sentence}"
    )

    attempts = MAX_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            content = response.choices[0].message.content
            payload = _extract_json(content)
            return _normalize_feedback(request, payload)
        except (
            APITimeoutError,
            APIConnectionError,
            RateLimitError,
            APIError,
            TimeoutError,
            asyncio.TimeoutError,
        ) as exc:
            if attempt == attempts:
                raise HTTPException(
                    status_code=502,
                    detail=f"LLM provider request failed after retries: {exc}",
                ) from exc
            await asyncio.sleep(0.4 * attempt)
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"LLM returned invalid JSON payload: {exc}",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Unexpected LLM provider error: {exc}",
            ) from exc

    raise HTTPException(status_code=502, detail="LLM request failed")


async def _get_feedback_uncached(request: FeedbackRequest) -> FeedbackResponse:
    client = AsyncOpenAI()
    return await _request_feedback_from_llm(client, request)


async def _get_feedback_cached(request: FeedbackRequest) -> FeedbackResponse:
    key = _cache_key(request)
    now = time.time()
    cached = _response_cache.get(key)
    if cached and now - cached[0] <= CACHE_TTL_SECONDS:
        return cached[1]

    feedback = await _get_feedback_uncached(request)
    _response_cache[key] = (now, feedback)
    return feedback


async def get_feedback(request: FeedbackRequest) -> FeedbackResponse:
    try:
        return await asyncio.wait_for(
            _get_feedback_cached(request), timeout=ENDPOINT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="Feedback generation exceeded timeout budget",
        ) from exc


def _clear_cache_for_tests() -> None:
    """Reset in-memory cache for deterministic unit tests."""
    _response_cache.clear()
