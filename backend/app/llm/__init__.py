"""ID8 LLM layer — Gemini integration, model routing, and prompt templates.

Public API
----------
- :func:`generate` — single-shot Gemini ``generate_content`` call.
- :func:`generate_with_fallback` — automatic profile-based fallback retry.
- :class:`LlmResponse` / :class:`TokenUsage` — response dataclasses.
- :func:`resolve_model` — map ``ModelProfile`` → Gemini model ID.
- :func:`resolve_profile` — map orchestrator node → ``ModelProfile``.
"""
from __future__ import annotations

from app.llm.client import LlmResponse, TokenUsage, generate, generate_with_fallback
from app.llm.router import resolve_model, resolve_profile

__all__ = [
    "LlmResponse",
    "TokenUsage",
    "generate",
    "generate_with_fallback",
    "resolve_model",
    "resolve_profile",
]
