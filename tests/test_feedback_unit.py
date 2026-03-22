"""Unit tests -- run without an API key using mocked LLM responses."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.feedback import _clear_cache_for_tests, get_feedback
from app.models import FeedbackRequest


def _mock_completion(response_data: dict) -> MagicMock:
    """Build a mock ChatCompletion response."""
    choice = MagicMock()
    choice.message.content = json.dumps(response_data)
    completion = MagicMock()
    completion.choices = [choice]
    return completion


@pytest.fixture(autouse=True)
def _reset_feedback_cache():
    _clear_cache_for_tests()


@pytest.mark.asyncio
async def test_feedback_with_errors():
    mock_response = {
        "corrected_sentence": "Yo fui al mercado ayer.",
        "is_correct": False,
        "errors": [
            {
                "original": "soy fue",
                "correction": "fui",
                "error_type": "conjugation",
                "explanation": "You mixed two verb forms.",
            }
        ],
        "difficulty": "A2",
    }

    with patch("app.feedback.AsyncOpenAI") as MockClient:
        instance = MockClient.return_value
        instance.chat.completions.create = AsyncMock(
            return_value=_mock_completion(mock_response)
        )

        request = FeedbackRequest(
            sentence="Yo soy fue al mercado ayer.",
            target_language="Spanish",
            native_language="English",
        )
        result = await get_feedback(request)

    assert result.is_correct is False
    assert result.corrected_sentence == "Yo fui al mercado ayer."
    assert len(result.errors) == 1
    assert result.errors[0].error_type == "conjugation"
    assert result.difficulty == "A2"


@pytest.mark.asyncio
async def test_feedback_correct_sentence():
    mock_response = {
        "corrected_sentence": "Ich habe gestern einen interessanten Film gesehen.",
        "is_correct": True,
        "errors": [],
        "difficulty": "B1",
    }

    with patch("app.feedback.AsyncOpenAI") as MockClient:
        instance = MockClient.return_value
        instance.chat.completions.create = AsyncMock(
            return_value=_mock_completion(mock_response)
        )

        request = FeedbackRequest(
            sentence="Ich habe gestern einen interessanten Film gesehen.",
            target_language="German",
            native_language="English",
        )
        result = await get_feedback(request)

    assert result.is_correct is True
    assert result.errors == []
    assert result.corrected_sentence == request.sentence


@pytest.mark.asyncio
async def test_feedback_multiple_errors():
    mock_response = {
        "corrected_sentence": "Le chat noir est sur la table.",
        "is_correct": False,
        "errors": [
            {
                "original": "La chat",
                "correction": "Le chat",
                "error_type": "gender_agreement",
                "explanation": "'Chat' is masculine.",
            },
            {
                "original": "le table",
                "correction": "la table",
                "error_type": "gender_agreement",
                "explanation": "'Table' is feminine.",
            },
        ],
        "difficulty": "A1",
    }

    with patch("app.feedback.AsyncOpenAI") as MockClient:
        instance = MockClient.return_value
        instance.chat.completions.create = AsyncMock(
            return_value=_mock_completion(mock_response)
        )

        request = FeedbackRequest(
            sentence="La chat noir est sur le table.",
            target_language="French",
            native_language="English",
        )
        result = await get_feedback(request)

    assert result.is_correct is False
    assert len(result.errors) == 2
    assert all(e.error_type == "gender_agreement" for e in result.errors)


@pytest.mark.asyncio
async def test_feedback_non_latin_script():
    mock_response = {
        "corrected_sentence": "私は東京に住んでいます。",
        "is_correct": False,
        "errors": [
            {
                "original": "を",
                "correction": "に",
                "error_type": "grammar",
                "explanation": "「住む」は場所に「に」を使います。",
            }
        ],
        "difficulty": "A2",
    }

    with patch("app.feedback.AsyncOpenAI") as mock_client:
        instance = mock_client.return_value
        instance.chat.completions.create = AsyncMock(
            return_value=_mock_completion(mock_response)
        )

        request = FeedbackRequest(
            sentence="私は東京を住んでいます。",
            target_language="Japanese",
            native_language="English",
        )
        result = await get_feedback(request)

    assert result.is_correct is False
    assert len(result.errors) == 1
    assert result.errors[0].correction == "に"


@pytest.mark.asyncio
async def test_feedback_normalizes_empty_errors_to_correct_sentence():
    mock_response = {
        "corrected_sentence": "Ich habe gestern einen interessanten Film gesehen.",
        "is_correct": False,
        "errors": [],
        "difficulty": "B1",
    }

    with patch("app.feedback.AsyncOpenAI") as mock_client:
        instance = mock_client.return_value
        instance.chat.completions.create = AsyncMock(
            return_value=_mock_completion(mock_response)
        )

        request = FeedbackRequest(
            sentence="Ich habe gestern einen interessanten Film gesehen.",
            target_language="German",
            native_language="English",
        )
        result = await get_feedback(request)

    assert result.is_correct is True
    assert result.errors == []
    assert result.corrected_sentence == request.sentence


@pytest.mark.asyncio
async def test_feedback_retries_after_transient_timeout():
    mock_response = {
        "corrected_sentence": "Yo fui al mercado ayer.",
        "is_correct": False,
        "errors": [
            {
                "original": "soy fue",
                "correction": "fui",
                "error_type": "conjugation",
                "explanation": "Mezclaste dos formas verbales.",
            }
        ],
        "difficulty": "A2",
    }

    with patch("app.feedback.AsyncOpenAI") as mock_client:
        instance = mock_client.return_value
        instance.chat.completions.create = AsyncMock(
            side_effect=[TimeoutError("temporary timeout"), _mock_completion(mock_response)]
        )

        request = FeedbackRequest(
            sentence="Yo soy fue al mercado ayer.",
            target_language="Spanish",
            native_language="English",
        )
        result = await get_feedback(request)

    assert result.is_correct is False
    assert instance.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_feedback_raises_http_502_when_json_invalid():
    with patch("app.feedback.AsyncOpenAI") as mock_client:
        instance = mock_client.return_value
        invalid_choice = MagicMock()
        invalid_choice.message.content = "not-json"
        invalid_completion = MagicMock()
        invalid_completion.choices = [invalid_choice]
        instance.chat.completions.create = AsyncMock(return_value=invalid_completion)

        request = FeedbackRequest(
            sentence="Hola mundo",
            target_language="Spanish",
            native_language="English",
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_feedback(request)

    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_feedback_cache_prevents_duplicate_llm_calls():
    mock_response = {
        "corrected_sentence": "Le chat noir est sur la table.",
        "is_correct": False,
        "errors": [
            {
                "original": "La chat",
                "correction": "Le chat",
                "error_type": "gender_agreement",
                "explanation": "'Chat' est masculin.",
            }
        ],
        "difficulty": "A1",
    }

    with patch("app.feedback.AsyncOpenAI") as mock_client:
        instance = mock_client.return_value
        instance.chat.completions.create = AsyncMock(
            return_value=_mock_completion(mock_response)
        )

        request = FeedbackRequest(
            sentence="La chat noir est sur la table.",
            target_language="French",
            native_language="English",
        )

        first = await get_feedback(request)
        second = await get_feedback(request)

    assert first == second
    assert instance.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_feedback_recovers_from_missing_and_extra_llm_fields():
    # Simulates a common real-model drift:
    # - missing top-level corrected_sentence and difficulty
    # - nested extra key in error object
    mock_response = {
        "is_correct": False,
        "errors": [
            {
                "original": "を",
                "correction": "に",
                "error_type": "grammar",
                "explanation": "Use に with 住む.",
                "difficulty": "A2",
            }
        ],
    }

    with patch("app.feedback.AsyncOpenAI") as mock_client:
        instance = mock_client.return_value
        instance.chat.completions.create = AsyncMock(
            return_value=_mock_completion(mock_response)
        )

        request = FeedbackRequest(
            sentence="私は東京を住んでいます。",
            target_language="Japanese",
            native_language="English",
        )
        result = await get_feedback(request)

    assert result.is_correct is False
    assert result.difficulty == "A2"
    assert result.corrected_sentence
    assert len(result.errors) == 1
    assert result.errors[0].correction == "に"
