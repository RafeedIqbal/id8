"""Unit tests for the ID8 LLM layer.

All Gemini API calls are mocked — no real network requests.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.client import (
    LlmResponse,
    _handle_api_error,
    generate,
    generate_with_fallback,
)
from app.llm.router import resolve_model, resolve_profile
from app.models.enums import ModelProfile
from app.orchestrator.retry import RateLimitError, RetryableError

# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestResolveModel:
    def test_all_profiles(self) -> None:
        assert resolve_model(ModelProfile.PRIMARY) == "gemini-2.5-pro"
        assert resolve_model(ModelProfile.CUSTOMTOOLS) == "gemini-2.5-pro"
        assert resolve_model(ModelProfile.FALLBACK) == "gemini-2.5-pro"

    def test_unknown_profile_raises(self) -> None:
        with pytest.raises(KeyError):
            resolve_model("nonexistent")  # type: ignore[arg-type]


class TestResolveProfile:
    def test_planning_nodes_use_primary(self) -> None:
        assert resolve_profile("GeneratePRD") == ModelProfile.PRIMARY
        assert resolve_profile("GenerateTechPlan") == ModelProfile.PRIMARY

    def test_tool_nodes_use_customtools(self) -> None:
        assert resolve_profile("WriteCode") == ModelProfile.CUSTOMTOOLS
        assert resolve_profile("GenerateDesign") == ModelProfile.CUSTOMTOOLS

    def test_unknown_node_defaults_to_primary(self) -> None:
        assert resolve_profile("IngestPrompt") == ModelProfile.PRIMARY
        assert resolve_profile("SecurityGate") == ModelProfile.PRIMARY
        assert resolve_profile("UnknownNode") == ModelProfile.PRIMARY


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_response(
    text: str = "Generated text",
    input_tokens: int = 10,
    output_tokens: int = 20,
) -> MagicMock:
    """Build a mock of the Gemini generate_content response."""
    usage_metadata = MagicMock()
    usage_metadata.prompt_token_count = input_tokens
    usage_metadata.candidates_token_count = output_tokens
    # Backward-compat fields for older SDK versions.
    usage_metadata.input_token_count = input_tokens
    usage_metadata.output_token_count = output_tokens

    response = MagicMock()
    response.text = text
    response.usage_metadata = usage_metadata
    return response


def _make_mock_client(response: MagicMock | None = None) -> MagicMock:
    """Build a mock genai.Client with aio.models.generate_content."""
    if response is None:
        response = _make_mock_response()

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=response)
    return mock_client


# ---------------------------------------------------------------------------
# Generate tests
# ---------------------------------------------------------------------------


class TestGenerate:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        mock_response = _make_mock_response("Hello!", 5, 15)
        mock_client = _make_mock_client(mock_response)

        with patch("app.llm.client._get_client", return_value=mock_client):
            result = await generate(
                model_id="gemini-3.1-pro-preview",
                prompt="Say hello",
                system_prompt="You are helpful",
            )

        assert isinstance(result, LlmResponse)
        assert result.content == "Hello!"
        assert result.token_usage.prompt_tokens == 5
        assert result.token_usage.completion_tokens == 15
        assert result.model_id == "gemini-3.1-pro-preview"
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_no_usage_metadata(self) -> None:
        """Response with no usage_metadata should still work with defaults."""
        mock_response = MagicMock()
        mock_response.text = "Output"
        mock_response.usage_metadata = None
        mock_client = _make_mock_client(mock_response)

        with patch("app.llm.client._get_client", return_value=mock_client):
            result = await generate(
                model_id="gemini-3.1-pro-preview",
                prompt="Test",
            )

        assert result.content == "Output"
        assert result.token_usage.prompt_tokens == 0
        assert result.token_usage.completion_tokens == 0


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_rate_limit_raises_rate_limit_error(self) -> None:
        from google.genai import errors as genai_errors

        exc = genai_errors.APIError(429, {"error": "Rate limit exceeded"})

        with pytest.raises(RateLimitError, match="Rate limited"):
            _handle_api_error(exc)

    def test_rate_limit_extracts_retry_after_header(self) -> None:
        from google.genai import errors as genai_errors

        response = MagicMock()
        response.headers = {"Retry-After": "12"}
        exc = genai_errors.APIError(
            429,
            {"error": "Rate limit exceeded"},
            response=response,
        )

        with pytest.raises(RateLimitError) as err:
            _handle_api_error(exc)

        assert err.value.retry_after_seconds == 12.0

    def test_server_error_raises_retryable(self) -> None:
        from google.genai import errors as genai_errors

        exc = genai_errors.APIError(500, {"error": "Internal error"})

        with pytest.raises(RetryableError, match="Transient"):
            _handle_api_error(exc)

    def test_permanent_error_reraises(self) -> None:
        from google.genai import errors as genai_errors

        exc = genai_errors.APIError(400, {"error": "Bad request"})

        with pytest.raises(genai_errors.APIError):
            _handle_api_error(exc)


# ---------------------------------------------------------------------------
# Fallback tests
# ---------------------------------------------------------------------------


class TestGenerateWithFallback:
    @pytest.mark.asyncio
    async def test_success_first_attempt(self) -> None:
        mock_response = _make_mock_response("First try!")
        mock_client = _make_mock_client(mock_response)

        with patch("app.llm.client._get_client", return_value=mock_client):
            result = await generate_with_fallback(
                profile=ModelProfile.PRIMARY,
                node_name="GeneratePRD",
                prompt="Build something",
                system_prompt="You are a PM",
            )

        assert result.content == "First try!"
        assert result.profile_used == ModelProfile.PRIMARY

    @pytest.mark.asyncio
    async def test_fallback_on_retryable_error(self) -> None:
        """First two attempts fail, third succeeds with fallback model."""
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableError("transient failure")
            return _make_mock_response("Fallback worked!")

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=side_effect)

        with patch("app.llm.client._get_client", return_value=mock_client):
            result = await generate_with_fallback(
                profile=ModelProfile.PRIMARY,
                node_name="GeneratePRD",
                prompt="Build something",
            )

        assert result.content == "Fallback worked!"
        assert result.profile_used == ModelProfile.FALLBACK
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_fourth_attempt_uses_reduced_prompt(self) -> None:
        long_prompt = "x" * 12_000
        call_args: list[dict[str, object]] = []

        async def side_effect(**kwargs):
            call_args.append(kwargs)
            if len(call_args) <= 3:
                raise RetryableError("transient failure")
            return _make_mock_response("Recovered with reduced prompt")

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=side_effect)

        with patch("app.llm.client._get_client", return_value=mock_client):
            result = await generate_with_fallback(
                profile=ModelProfile.PRIMARY,
                node_name="WriteCode",
                prompt=long_prompt,
            )

        assert result.content == "Recovered with reduced prompt"
        assert result.profile_used == ModelProfile.FALLBACK
        assert len(call_args) == 4
        assert call_args[0]["model"] == "gemini-2.5-pro"
        assert call_args[1]["model"] == "gemini-2.5-pro"
        assert call_args[2]["model"] == "gemini-2.5-pro"
        assert call_args[3]["model"] == "gemini-2.5-pro"
        assert isinstance(call_args[3]["contents"], str)
        assert len(call_args[3]["contents"]) < len(long_prompt)
        assert "[...prompt truncated for fallback retry...]" in call_args[3]["contents"]

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_raises(self) -> None:
        """When all 4 attempts fail, the last error is raised."""
        mock_client = MagicMock()
        mock_generate = AsyncMock(
            side_effect=RetryableError("always failing")
        )
        mock_client.aio.models.generate_content = mock_generate

        with (
            patch("app.llm.client._get_client", return_value=mock_client),
            pytest.raises(RetryableError, match="always failing"),
        ):
            await generate_with_fallback(
                profile=ModelProfile.PRIMARY,
                node_name="GeneratePRD",
                prompt="Build something",
            )

        assert mock_generate.await_count == 4


# ---------------------------------------------------------------------------
# Prompt template tests
# ---------------------------------------------------------------------------


class TestPromptTemplates:
    def test_prd_prompts(self) -> None:
        from app.llm.prompts.prd_generation import build_prompts

        system, user = build_prompts(initial_prompt="Build a CRM")
        assert len(system) > 0
        assert "CRM" in user
        assert "Product Requirements" in system

    def test_prd_prompts_with_feedback(self) -> None:
        from app.llm.prompts.prd_generation import build_prompts

        system, user = build_prompts(
            initial_prompt="Build a CRM",
            feedback="Needs more detail on personas",
        )
        assert "Needs more detail on personas" in user
        assert "rejected" in user.lower() or "feedback" in user.lower()

    def test_tech_plan_prompts(self) -> None:
        from app.llm.prompts.tech_plan_generation import build_prompts

        system, user = build_prompts(
            previous_artifacts={"prd": {"summary": "CRM system"}},
        )
        assert len(system) > 0
        assert "CRM" in user

    def test_code_generation_prompts(self) -> None:
        from app.llm.prompts.code_generation import build_prompts

        system, user = build_prompts(
            previous_artifacts={
                "tech_plan": {"stack": "Python + FastAPI"},
                "design_spec": {"screens": ["dashboard"]},
            },
        )
        assert len(system) > 0
        assert "FastAPI" in user

    def test_code_generation_with_feedback(self) -> None:
        from app.llm.prompts.code_generation import build_prompts

        system, user = build_prompts(
            previous_artifacts={"tech_plan": {"stack": "Python"}},
            feedback="SQL injection in login handler",
        )
        assert "SQL injection" in user
